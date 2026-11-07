"""lsp.py - Cliente LSP (Language Server Protocol) básico para Blinker Code.

Este archivo NO depende de tkinter. Habla con servidores de lenguaje (pyright, clangd,
typescript-language-server, rust-analyzer, gopls...) por stdin/stdout con JSON-RPC.

    lsp = LSPManager(on_diagnostics, on_status)
    lsp.open(path, "python", texto)             # didOpen (arranca el servidor si hace falta)
    lsp.change(path, texto)                     # didChange (texto completo)
    lsp.completion(path, linea0, col, None, callback)
    lsp.poll()                                  # llamar cada ~50 ms desde el hilo de la interfaz
    lsp.stop_all()

Todo lo que llega del servidor se procesa dentro de poll(), así que los callbacks
siempre corren en el hilo de la interfaz (no hay que usar locks en tkinter).

----------------------------------------------------------------------
 SERVIDORES
----------------------------------------------------------------------
Se usa el primero de cada lista que esté instalado (en el PATH):

    python      pyright-langserver  (npm i -g pyright  /  pip install pyright)
                pylsp (pip install python-lsp-server) / jedi-language-server
    cpp         clangd              (apt install clangd / brew install llvm / LLVM en Windows)
    javascript  typescript-language-server (npm i -g typescript typescript-language-server)
    rust        rust-analyzer       go   gopls

Para usar otro, en blinker_config.json:   "lsp_servers": {"python": ["pylsp"]}
"""
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import urllib.parse
import urllib.request
from pathlib import Path

SERVERS = {
    "python": [["pyright-langserver", "--stdio"], ["pyright-python-langserver", "--stdio"],
               ["basedpyright-langserver", "--stdio"], ["pylsp"], ["jedi-language-server"]],
    "cpp": [["clangd", "--header-insertion=never"]],
    "javascript": [["typescript-language-server", "--stdio"]],
    "typescript": [["typescript-language-server", "--stdio"]],
    "rust": [["rust-analyzer"]],
    "go": [["gopls"]],
}

INSTALL_HINT = {
    "python": "npm i -g pyright   (o: pip install pyright)",
    "cpp": "instala clangd (apt install clangd / LLVM para Windows)",
    "javascript": "npm i -g typescript typescript-language-server",
    "typescript": "npm i -g typescript typescript-language-server",
    "rust": "rustup component add rust-analyzer",
    "go": "go install golang.org/x/tools/gopls@latest",
}

# kind de CompletionItem -> letra corta para la lista
KIND_LETTER = {1: "T", 2: "M", 3: "F", 4: "C", 5: "f", 6: "V", 7: "C", 8: "I", 9: "m", 10: "p",
               11: "u", 12: "v", 13: "E", 14: "K", 15: "S", 16: "c", 17: "F", 18: "r", 19: "d",
               20: "e", 21: "c", 22: "S", 23: "e", 24: "o", 25: "t"}


def path_to_uri(path):
    return Path(os.path.abspath(path)).as_uri()


def uri_to_path(uri):
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme != "file":
        return None
    return os.path.abspath(urllib.request.url2pathname(parsed.path))


def same_path(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def language_id(path, language):
    ext = os.path.splitext(path)[1].lower()
    if language == "cpp" and ext in (".c", ".h"):
        return "c"
    if language == "javascript" and ext in (".jsx",):
        return "javascriptreact"
    if language == "typescript" and ext in (".tsx",):
        return "typescriptreact"
    return language


_SNIPPET_1 = re.compile(r"\$\{\d+:([^{}]*)\}")
_SNIPPET_2 = re.compile(r"\$\{\d+\|([^,|}]*)[^}]*\}")
_SNIPPET_3 = re.compile(r"\$\{?\d+\}?")


def strip_snippet(text):
    """Quita marcas de snippet ($1, ${1:valor}) para insertar texto plano."""
    text = _SNIPPET_1.sub(r"\1", text)
    text = _SNIPPET_2.sub(r"\1", text)
    return _SNIPPET_3.sub("", text)


def normalize_completion(result):
    """CompletionList | CompletionItem[] -> [{label, insert, filter, sort, kind, detail}]"""
    if result is None:
        return []
    items = result.get("items", []) if isinstance(result, dict) else result
    out = []
    for it in items:
        if not isinstance(it, dict) or not it.get("label"):
            continue
        edit = it.get("textEdit") or {}
        text = edit.get("newText") or it.get("insertText") or it["label"]
        if it.get("insertTextFormat") == 2:
            text = strip_snippet(text)
        out.append({
            "label": it["label"].strip(),
            "insert": text,
            "filter": it.get("filterText") or it["label"].strip(),
            "sort": it.get("sortText") or it["label"],
            "kind": KIND_LETTER.get(it.get("kind"), "·"),
            "detail": (it.get("detail") or "").split("\n")[0][:60],
        })
    return out


# ======================================================================
#  CLIENTE (un servidor)
# ======================================================================
class LSPClient:
    def __init__(self, cmd, root, name):
        self.cmd = cmd
        self.root = root
        self.name = name
        self.proc = None
        self.inbox = queue.Queue()
        self.pending = {}               # id -> callback(result, error)
        self.outbox = []                # mensajes en espera hasta que termine 'initialize'
        self.next_id = 1
        self.ready = False
        self.dead = False
        self.capabilities = {}
        self.on_notification = None     # f(client, method, params)
        self.on_exit = None             # f(client)
        self._write_lock = threading.Lock()

    # --------------------------------------------------------------- vida
    def start(self):
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        self.proc = subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, cwd=self.root, **kwargs)
        threading.Thread(target=self._reader, daemon=True).start()
        root_uri = path_to_uri(self.root)
        params = {
            "processId": os.getpid(),
            "clientInfo": {"name": "Blinker Code"},
            "rootUri": root_uri,
            "rootPath": self.root,
            "workspaceFolders": [{"uri": root_uri, "name": os.path.basename(self.root) or "root"}],
            "capabilities": {
                "workspace": {"configuration": True, "workspaceFolders": True},
                "textDocument": {
                    "synchronization": {"didSave": True, "dynamicRegistration": False},
                    "completion": {"completionItem": {"snippetSupport": False,
                                                       "documentationFormat": ["plaintext"]}},
                    "publishDiagnostics": {"relatedInformation": False},
                },
            },
        }
        self._send_raw({"jsonrpc": "2.0", "id": self._new_id(callback=self._on_initialized),
                        "method": "initialize", "params": params})

    def _on_initialized(self, result, error):
        if error:
            self.dead = True
            return
        self.capabilities = (result or {}).get("capabilities", {})
        self._send_raw({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        self.ready = True
        queued, self.outbox = self.outbox, []
        for msg in queued:
            self._send_raw(msg)

    def stop(self):
        if self.proc is None:
            return
        try:
            if self.ready and not self.dead:
                self._send_raw({"jsonrpc": "2.0", "id": self._new_id(), "method": "shutdown"})
                self._send_raw({"jsonrpc": "2.0", "method": "exit"})
                self.proc.wait(timeout=1.5)
        except Exception:
            pass
        try:
            self.proc.kill()
        except Exception:
            pass
        self.dead = True

    # ------------------------------------------------------------ mensajes
    def _new_id(self, callback=None):
        i = self.next_id
        self.next_id += 1
        if callback is not None:
            self.pending[i] = callback
        return i

    def request(self, method, params, callback):
        msg = {"jsonrpc": "2.0", "id": self._new_id(callback), "method": method, "params": params}
        self._send(msg)

    def notify(self, method, params):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _send(self, msg):
        if self.dead:
            return
        if not self.ready:
            self.outbox.append(msg)
        else:
            self._send_raw(msg)

    def _send_raw(self, msg):
        body = json.dumps(msg, separators=(",", ":")).encode("utf-8")
        data = b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        try:
            with self._write_lock:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
        except (OSError, ValueError):
            self.dead = True

    def _reader(self):
        """Hilo: lee los mensajes del servidor y los deja en la cola."""
        out = self.proc.stdout
        try:
            while True:
                length = None
                while True:
                    line = out.readline()
                    if not line:
                        raise EOFError
                    line = line.strip()
                    if not line:
                        break
                    if line.lower().startswith(b"content-length:"):
                        length = int(line.split(b":", 1)[1])
                if length is None:
                    continue
                body = b""
                while len(body) < length:
                    chunk = out.read(length - len(body))
                    if not chunk:
                        raise EOFError
                    body += chunk
                self.inbox.put(("msg", json.loads(body.decode("utf-8", errors="replace"))))
        except Exception:
            pass
        self.inbox.put(("exit", None))

    def poll(self):
        """Procesa lo recibido. Llamar desde el hilo de la interfaz."""
        while True:
            try:
                kind, msg = self.inbox.get_nowait()
            except queue.Empty:
                return
            if kind == "exit":
                if not self.dead:
                    self.dead = True
                if self.on_exit:
                    self.on_exit(self)
                continue
            self._handle(msg)

    def _handle(self, msg):
        method, mid = msg.get("method"), msg.get("id")
        if method is None and mid is not None:                       # respuesta
            cb = self.pending.pop(mid, None)
            if cb:
                try:
                    cb(msg.get("result"), msg.get("error"))
                except Exception:
                    pass
        elif method is not None and mid is not None:                 # petición del servidor
            result = None
            if method == "workspace/configuration":
                result = [{} for _ in (msg.get("params") or {}).get("items", [])]
            elif method == "workspace/workspaceFolders":
                result = [{"uri": path_to_uri(self.root), "name": os.path.basename(self.root)}]
            self._send_raw({"jsonrpc": "2.0", "id": mid, "result": result})
        elif method is not None:                                     # notificación
            if self.on_notification:
                try:
                    self.on_notification(self, method, msg.get("params") or {})
                except Exception:
                    pass


# ======================================================================
#  GESTOR (varios servidores, varios documentos)
# ======================================================================
class LSPManager:
    def __init__(self, on_diagnostics, on_status=None, root_getter=None, overrides=None):
        self.on_diagnostics = on_diagnostics      # f(path, [diagnostic])
        self.on_status = on_status or (lambda text: None)
        self.root_getter = root_getter or (lambda: None)
        self.overrides = overrides or {}
        self.clients = {}                         # (tuple(cmd), root) -> LSPClient
        self.docs = {}                            # path_normalizado -> {"client","version","uri"}
        self.warned = set()

    # ---------------------------------------------------------- servidores
    def command_for(self, language):
        custom = self.overrides.get(language)
        candidates = [custom] if custom else SERVERS.get(language, [])
        for cmd in candidates:
            exe = shutil.which(cmd[0])
            if exe:
                return [exe] + list(cmd[1:])
        return None

    def supports(self, language):
        return language in SERVERS or language in self.overrides

    def _root_for(self, path):
        root = self.root_getter()
        folder = os.path.dirname(os.path.abspath(path))
        if root:
            root = os.path.abspath(root)
            if os.path.normcase(folder).startswith(os.path.normcase(root)):
                return root
        return folder

    def client_for(self, language, path):
        cmd = self.command_for(language)
        if cmd is None:
            if language not in self.warned:
                self.warned.add(language)
                hint = INSTALL_HINT.get(language, "")
                self.on_status(f"No hay servidor LSP para {language}. {hint}")
            return None
        root = self._root_for(path)
        key = (tuple(cmd), root)
        client = self.clients.get(key)
        if client is None or client.dead:
            client = LSPClient(cmd, root, os.path.basename(cmd[0]))
            client.on_notification = self._on_notification
            try:
                client.start()
            except OSError as ex:
                self.on_status(f"No se pudo iniciar {cmd[0]}: {ex}")
                return None
            self.clients[key] = client
            self.on_status(f"LSP: iniciando {client.name}...")
        return client

    # ----------------------------------------------------------- documentos
    @staticmethod
    def _key(path):
        return os.path.normcase(os.path.abspath(path))

    def open(self, path, language, text):
        """Devuelve True si algún servidor atiende este archivo."""
        self.close(path)
        if not self.supports(language):
            return False
        client = self.client_for(language, path)
        if client is None:
            return False
        uri = path_to_uri(path)
        self.docs[self._key(path)] = {"client": client, "version": 1, "uri": uri}
        client.notify("textDocument/didOpen", {"textDocument": {
            "uri": uri, "languageId": language_id(path, language), "version": 1, "text": text}})
        return True

    def change(self, path, text):
        doc = self.docs.get(self._key(path))
        if not doc:
            return
        doc["version"] += 1
        doc["client"].notify("textDocument/didChange", {
            "textDocument": {"uri": doc["uri"], "version": doc["version"]},
            "contentChanges": [{"text": text}]})

    def save(self, path, text=None):
        doc = self.docs.get(self._key(path))
        if not doc:
            return
        params = {"textDocument": {"uri": doc["uri"]}}
        if text is not None:
            params["text"] = text
        doc["client"].notify("textDocument/didSave", params)

    def close(self, path):
        doc = self.docs.pop(self._key(path), None)
        if doc:
            doc["client"].notify("textDocument/didClose", {"textDocument": {"uri": doc["uri"]}})

    def completion(self, path, line, col, trigger, callback):
        """Pide sugerencias. callback(items) con items normalizados ([] si falla)."""
        doc = self.docs.get(self._key(path))
        if not doc:
            callback([])
            return
        context = {"triggerKind": 2, "triggerCharacter": trigger} if trigger else {"triggerKind": 1}
        params = {"textDocument": {"uri": doc["uri"]},
                  "position": {"line": line, "character": col}, "context": context}

        def done(result, error):
            callback([] if error else normalize_completion(result))
        doc["client"].request("textDocument/completion", params, done)

    # ----------------------------------------------------------- ciclo
    def _on_notification(self, client, method, params):
        if method == "textDocument/publishDiagnostics":
            path = uri_to_path(params.get("uri", ""))
            if path:
                self.on_diagnostics(path, params.get("diagnostics", []))

    def poll(self):
        for client in list(self.clients.values()):
            was_ready = client.ready
            client.poll()
            if client.ready and not was_ready:
                self.on_status(f"LSP: {client.name} listo")
            if client.dead and client.proc is not None and client.proc.poll() is not None:
                key = next((k for k, v in self.clients.items() if v is client), None)
                if key:
                    self.clients.pop(key, None)
                    for p, d in list(self.docs.items()):
                        if d["client"] is client:
                            self.docs.pop(p, None)
                    self.on_status(f"LSP: {client.name} se detuvo")

    def status(self):
        rows = []
        for (cmd, root), client in self.clients.items():
            state = "listo" if client.ready else ("detenido" if client.dead else "iniciando")
            rows.append(f"{client.name}  [{state}]  {root}")
        return rows

    def stop_all(self):
        for client in list(self.clients.values()):
            client.stop()
        self.clients.clear()
        self.docs.clear()