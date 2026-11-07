"""libs.py - Librerías de autocompletado para Blinker Code (un "mini LSP" sin servidor).

Este archivo NO depende de tkinter. Un paquete (o tú, en la carpeta Libraries/) puede traer
archivos .json que describen las funciones, keywords, constantes y snippets de un lenguaje
o de una librería (por ejemplo RCBasic). El editor los usa para autocompletar.

----------------------------------------------------------------------
 DÓNDE SE DECLARAN
----------------------------------------------------------------------
  - En un paquete, en blinker-package.json:
        "libraries": ["libs/rcbasic.json"]
  - Sueltos, en  Libraries/*.json  (junto a main.py)

----------------------------------------------------------------------
 FORMATO DE UNA LIBRERÍA
----------------------------------------------------------------------
    {
        "name": "RCBasic",
        "languages":  ["basic"],          # id de lenguaje del editor (opcional si hay extensions)
        "extensions": [".bas"],           # archivos a los que aplica
        "comment": "'",                   # prefijo de comentario (para Ctrl+/)
        "keywords":  ["If", "Then", "Else", "For", "Next"],
        "constants": ["True", "False"],
        "types":     ["Integer", "String"],
        "functions": [
            "OpenWindow(title, w, h, fullscreen, vsync) = OpenWindow(\\"Hola\\", 640, 480, 0, 0) # Abre una ventana",
            "CloseWindow()",
            "Cls",
            {"name": "Wait", "params": ["ms"], "doc": "Pausa", "insert": "Wait(1000)"}
        ],
        "snippets": [
            {"trigger": "forn", "body": "For i = 1 To $0\\n\\t\\nNext", "detail": "Bucle For"}
        ]
    }

Sintaxis corta de una función (texto):

    Nombre(param1, param2) = texto_a_insertar # documentación

  - "(params)" es opcional. Sin paréntesis => se inserta solo el nombre (p. ej. Cls).
  - "= texto_a_insertar" es opcional: es lo que se escribe al aceptar la sugerencia
    (p. ej. con valores de ejemplo). Sin él se inserta Nombre(  ) con el cursor dentro.
  - "# documentación" es opcional y se muestra junto a la firma en la lista.

----------------------------------------------------------------------
 SERVIDOR LSP REAL (opcional)
----------------------------------------------------------------------
Para errores/diagnósticos reales, el paquete puede traer su propio servidor LSP (un
programa que habla JSON-RPC por stdin/stdout). Se declara en blinker-package.json:

    "lsp": {"language": "basic", "extensions": [".bas"],
            "command": ["{python}", "{pkg}/server.py"]}

  {python} = el Python con el que corre el editor, {pkg} = carpeta del paquete.

----------------------------------------------------------------------
 INSTALAR DESDE GITHUB  (Tools > Install Library...)
----------------------------------------------------------------------
Se acepta el .json de una librería como:
    usuario/repo/ruta/libreria.json            (rama por defecto)
    usuario/repo/ruta/libreria.json@rama
    https://github.com/usuario/repo/blob/rama/ruta/libreria.json
    https://raw.githubusercontent.com/usuario/repo/rama/ruta/libreria.json
Se valida y se guarda en  Libraries/  (reinstalar = actualizar). Un repo completo
("usuario/repo") se instala como PAQUETE si su blinker-package.json trae "libraries".

Uso por línea de comandos:
    python libs.py check  libreria.json
    python libs.py from-text api.txt "RCBasic" basic .bas > rcbasic.json
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

from suggest import _item as _suggestion

MANIFEST = "blinker-package.json"
MAX_FILE = 2 * 1024 * 1024
MAX_ENTRIES = 20000
NAME_RE = re.compile(r"[A-Za-z_][\w$%#.]*")
SORT = "y1"          # antes que keywords/builtins/palabras de suggest.py (z1..z4)


class LibraryError(Exception):
    pass


# ======================================================================
#  CONSTRUCCIÓN DE SUGERENCIAS (mismo formato que suggest.py / el popup)
# ======================================================================
def _item(label, insert, kind, icon, detail, snippet=False):
    return _suggestion(label, insert, kind, icon, detail[:90], SORT + label.lower(),
                       **({"snippet": True} if snippet else {}))


def parse_function(entry):
    """Texto u objeto -> (name, params|None, insert|None, doc). Lanza LibraryError."""
    if isinstance(entry, str):
        head, _, doc = entry.partition(" # ")
        sig, _, insert = head.partition(" = ")
        m = re.fullmatch(r"\s*(" + NAME_RE.pattern + r")\s*(?:\(([^)]*)\))?\s*", sig)
        if not m:
            raise LibraryError(f"Función inválida: {entry!r}")
        name, raw = m.group(1), m.group(2)
        params = None if raw is None else [p.strip() for p in raw.split(",") if p.strip()]
        return name, params, (insert.strip() or None), doc.strip()
    if isinstance(entry, dict) and isinstance(entry.get("name"), str) and NAME_RE.fullmatch(entry["name"]):
        params = entry.get("params")
        if params is not None and not (isinstance(params, list) and all(isinstance(p, str) for p in params)):
            raise LibraryError(f"'params' inválido en {entry['name']}")
        return (entry["name"], params, entry.get("insert") or None,
                str(entry.get("doc") or entry.get("returns") and f"-> {entry['returns']}" or ""))
    raise LibraryError(f"Función inválida: {entry!r}")


def function_item(name, params, insert, doc):
    sig = name if params is None else f"{name}({', '.join(params)})"
    if insert:
        body = insert                                  # el cursor queda al final
    elif params is None:
        body = name
    elif not params:
        body = f"{name}()"
    else:
        body = f"{name}($0)"                           # cursor dentro de los paréntesis
    return _item(name, body, "f", "function", f"{sig}  {doc}".strip(), snippet=True)


class Library:
    def __init__(self, data, source, package=None):
        if not isinstance(data, dict):
            raise LibraryError("La librería debe ser un objeto JSON.")
        self.name = str(data.get("name") or "Librería")
        self.source, self.package = source, package
        langs, exts = data.get("languages") or [], data.get("extensions") or []
        if not (isinstance(langs, list) and isinstance(exts, list)
                and all(isinstance(x, str) for x in langs + exts)):
            raise LibraryError("'languages' y 'extensions' deben ser listas de texto.")
        self.languages = [x.lower() for x in langs]
        self.extensions = [x.lower() if x.startswith(".") else "." + x.lower() for x in exts]
        if not (self.languages or self.extensions):
            raise LibraryError("Indica 'languages' o 'extensions'.")
        self.comment = data.get("comment") if isinstance(data.get("comment"), str) else None

        items, seen = [], set()

        def add(it):
            key = (it["label"].lower(), bool(it.get("snippet")), it["insert"])
            if key not in seen and len(items) < MAX_ENTRIES:
                seen.add(key)
                items.append(it)

        for kind, key, icon, letter in (("keywords", "keywords", "keyword", "k"),
                                        ("constants", "constants", "constant", "K"),
                                        ("types", "types", "class", "c")):
            for w in data.get(key) or []:
                if isinstance(w, str) and w.strip() and " " not in w.strip():
                    add(_item(w.strip(), w.strip(), letter, icon, kind[:-1]))
        for f in data.get("functions") or []:
            add(function_item(*parse_function(f)))
        for s in data.get("snippets") or []:
            if isinstance(s, dict) and isinstance(s.get("trigger"), str) and isinstance(s.get("body"), str):
                preview = s["body"].replace("$0", "").replace("\t", " ").replace("\n", " \u23ce ").strip()
                add(_item(s["trigger"], s["body"], "s", "snippet",
                          str(s.get("detail") or preview), snippet=True))
        self.items = items

    def matches(self, lang, path):
        if lang and lang.lower() in self.languages:
            return True
        return bool(path) and os.path.splitext(path)[1].lower() in self.extensions


# ======================================================================
#  GESTOR
# ======================================================================
class LibraryManager:
    def __init__(self, packages_dir, user_dir):
        self.packages_dir, self.user_dir = packages_dir, user_dir
        self.libraries, self.errors, self._lsp = [], [], []

    # --------------------------------------------------------------- carga
    @staticmethod
    def _read_json(path):
        try:
            if os.path.getsize(path) > MAX_FILE:
                raise LibraryError("archivo demasiado grande")
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError) as ex:
            raise LibraryError(f"no se pudo leer ({ex.__class__.__name__})")

    def _add_file(self, path, source, package=None):
        try:
            self.libraries.append(Library(self._read_json(path), source, package))
        except LibraryError as ex:
            self.errors.append(f"{os.path.basename(path)} ({source}): {ex}")

    def reload(self):
        self.libraries, self.errors, self._lsp = [], [], []
        if os.path.isdir(self.user_dir):
            for fn in sorted(os.listdir(self.user_dir), key=str.lower):
                if fn.lower().endswith(".json"):
                    self._add_file(os.path.join(self.user_dir, fn), "usuario")
        if not os.path.isdir(self.packages_dir):
            return
        for pkg in sorted(os.listdir(self.packages_dir), key=str.lower):
            root = os.path.join(self.packages_dir, pkg)
            mf = os.path.join(root, MANIFEST)
            if pkg.startswith(".") or not os.path.isfile(mf):
                continue
            try:
                manifest = self._read_json(mf)
            except LibraryError:
                continue
            if not isinstance(manifest, dict):
                continue
            real = os.path.realpath(root)
            libs = manifest.get("libraries")
            for rel in libs if isinstance(libs, list) else []:
                path = os.path.realpath(os.path.join(root, rel)) if isinstance(rel, str) else ""
                if path.startswith(real + os.sep) and path.lower().endswith(".json") and os.path.isfile(path):
                    self._add_file(path, f"paquete: {pkg}", pkg)
                else:
                    self.errors.append(f"{pkg}: librería no válida o fuera del paquete: {rel!r}")
            self._read_lsp(manifest.get("lsp"), pkg, root)

    def _read_lsp(self, spec, pkg, root):
        if spec is None:
            return
        cmd = spec.get("command") if isinstance(spec, dict) else None
        lang = spec.get("language") if isinstance(spec, dict) else None
        if not (isinstance(lang, str) and lang and isinstance(cmd, list) and cmd
                and all(isinstance(c, str) for c in cmd)):
            self.errors.append(f"{pkg}: 'lsp' necesita 'language' y 'command' (lista).")
            return
        cmd = [c.replace("{python}", sys.executable).replace("{pkg}", root) for c in cmd]
        exts = [e.lower() if e.startswith(".") else "." + e.lower()
                for e in spec.get("extensions", []) if isinstance(e, str)]
        self._lsp.append({"language": lang.lower(), "command": cmd, "extensions": exts, "package": pkg})

    # ------------------------------------------------------------- consulta
    def _for(self, lang, path):
        return [lib for lib in self.libraries if lib.matches(lang, path)]

    def has(self, lang, path):
        return any(lib.matches(lang, path) for lib in self.libraries)

    def items_for(self, lang, path):
        out = []
        for lib in self._for(lang, path):
            out.extend(lib.items)
        return out

    def comment_for(self, lang, path):
        for lib in self._for(lang, path):
            if lib.comment:
                return lib.comment
        return None

    def language_for_path(self, path):
        """Id de lenguaje que una librería/servidor declara para esa extensión (o None)."""
        ext = os.path.splitext(path or "")[1].lower()
        if not ext:
            return None
        for lib in self.libraries:
            if ext in lib.extensions and lib.languages:
                return lib.languages[0]
        for s in self._lsp:
            if ext in s["extensions"]:
                return s["language"]
        return None

    def lsp_servers(self):
        return list(self._lsp)

    def count_for(self, package):
        return sum(1 for lib in self.libraries if lib.package == package)

    def summary(self):
        rows = [f"{lib.name}    ({lib.source})    {len(lib.items)} elementos    "
                f"{', '.join(lib.extensions or lib.languages)}" for lib in self.libraries]
        rows += [f"Servidor LSP: {s['language']}    (paquete: {s['package']})" for s in self._lsp]
        return rows


# ======================================================================
#  INSTALAR DESDE GITHUB
# ======================================================================
_PART = r"[\w.-]+"
_BLOB = re.compile(rf"https?://(?:www\.)?github\.com/({_PART})/({_PART})/blob/([^/]+)/(.+\.json)$", re.I)
_RAW = re.compile(r"https://raw\.githubusercontent\.com/[\w.-]+/[\w.-]+/.+\.json$", re.I)


def library_url(source):
    """Texto del usuario -> URL 'raw' del .json. Lanza LibraryError si no es un .json de GitHub."""
    s = (source or "").strip()
    if not s:
        raise LibraryError("Escribe usuario/repo/ruta/libreria.json o un link de GitHub.")
    if s.lower().startswith(("http://", "https://")):
        m = _BLOB.match(s)
        if m:
            owner, repo, ref, path = m.groups()
            return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
        if _RAW.match(s):
            return s
        raise LibraryError("El link debe ser el .json de un repositorio de GitHub.")
    s, _, ref = s.partition("@")
    parts = s.strip("/").split("/")
    if (len(parts) >= 3 and s.lower().endswith(".json")
            and all(re.fullmatch(r"[\w.@ -]+", p) for p in parts[2:])
            and all(re.fullmatch(_PART, p) for p in parts[:2])):
        return f"https://raw.githubusercontent.com/{parts[0]}/{parts[1]}/{ref.strip() or 'HEAD'}/" + "/".join(parts[2:])
    raise LibraryError(f"'{source}' no parece un .json de GitHub (usuario/repo/ruta/libreria.json).")


def is_library_source(text):
    try:
        library_url(text)
        return True
    except LibraryError:
        return False


def _download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "BlinkerCode-Libs"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read(MAX_FILE + 1)
    except urllib.error.HTTPError as ex:
        raise LibraryError("No se encontró el archivo (404)." if ex.code == 404
                           else f"GitHub respondió con el error {ex.code}.")
    except OSError:
        raise LibraryError("No se pudo conectar (¿hay internet?).")
    if len(data) > MAX_FILE:
        raise LibraryError("El archivo es demasiado grande.")
    return data


def install_library(source, user_dir, fetch=_download):
    """Descarga el .json, lo valida y lo guarda en user_dir (Libraries/). Bloquea (red):
    llámalo desde un hilo. Devuelve {"name", "items", "path", "source"}."""
    url = library_url(source)
    try:
        data = json.loads(fetch(url).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise LibraryError("El archivo descargado no es un JSON válido.")
    lib = Library(data, "github")                                  # valida el formato
    data["source"] = source.strip()                                # para saber de dónde vino
    fname = re.sub(r"[^\w.-]", "_", os.path.basename(url.split("?")[0])).strip("._") or "libreria.json"
    os.makedirs(user_dir, exist_ok=True)
    path = os.path.join(user_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return {"name": lib.name, "items": len(lib.items), "path": path, "source": source.strip()}


# ======================================================================
#  HERRAMIENTAS (línea de comandos)
# ======================================================================
def from_text(text, name, language, extension):
    """Convierte un texto con una firma por línea en el JSON de una librería.
    Se ignoran las líneas vacías y las que empiezan con ';'."""
    funcs = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith(";")]
    for f in funcs:
        parse_function(f)                                  # valida
    return {"name": name, "languages": [language], "extensions": [extension],
            "keywords": [], "constants": [], "types": [], "functions": funcs, "snippets": []}


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "check":
        lib = Library(LibraryManager._read_json(args[1]), "archivo")
        print(f"OK: {lib.name} - {len(lib.items)} elementos")
    elif len(args) == 5 and args[0] == "from-text":
        with open(args[1], "r", encoding="utf-8") as f:
            print(json.dumps(from_text(f.read(), args[2], args[3], args[4]), indent=2, ensure_ascii=False))
    else:
        print(__doc__)