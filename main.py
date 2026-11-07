from tkinter import *
from tkinter import ttk, filedialog, messagebox, simpledialog
import os, re, json, shutil, subprocess, sys, threading, queue, codecs, signal, time, uuid
from bisect import bisect_right
import tkinter.font as tkfont

# Sistema de highlight (archivo aparte: highlight.py)
from highlight import THEME_COLORS, EXT_LANG, LANG_NAMES, resolve_language, highlight_ranges

# Sistemas de build (archivo aparte: build.py)
from build import get_build_command

# Colores y estilo oscuro de ttk (archivo aparte: ui.py)
from ui import UI, apply_dark_style

# Iconos del árbol de carpetas (archivo aparte: icons.py)
from icons import IconSet

# Gestor de paquetes desde GitHub (archivo aparte: packages.py)
from packages import PackageManager, PackageAPI, PackageError, parse_source

# Cliente LSP: autocompletado y errores (archivo aparte: lsp.py)
from lsp import LSPManager, same_path

# Recuperación de archivos y sesión (archivo aparte: recovery.py)
from recovery import RecoveryManager

# Sugerencias de keywords, builtins, snippets y palabras (archivo aparte: suggest.py)
from suggest import Suggester, context as suggest_context, expand_snippet
from suggest_ui import SuggestPopup

# Temas de color (archivo aparte: themes.py)
from themes import ThemeManager, ThemeError

# Librerías de autocompletado por paquete (archivo aparte: libs.py)
from libs import LibraryManager, LibraryError, is_library_source, install_library

# ======================================================================
#  CONSTANTES
# ======================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "blinker_config.json")
PACKAGES_DIR = os.path.join(BASE_DIR, "Packages")      # aquí se instalan los paquetes de GitHub
RECOVERY_DIR = os.path.join(BASE_DIR, "Recovery")      # respaldos y sesión
THEMES_DIR = os.path.join(BASE_DIR, "Themes")          # temas .json del usuario
LIBS_DIR = os.path.join(BASE_DIR, "Libraries")         # librerías de autocompletado .json

IGNORED = {".git", "__pycache__", "node_modules", ".idea", ".vscode", ".venv", "venv"}
INDENT = "\t"                      # cambia a "    " si prefieres espacios

COMMENT = {"python": "#", "bash": "#", "cpp": "//", "javascript": "//", "typescript": "//",
           "java": "//", "csharp": "//", "rust": "//", "go": "//", "lua": "--", "sql": "--"}

PAIRS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}
CLOSERS = ")]}"
MAX_MATCHES = 3000

SEV_NAMES = {1: "error", 2: "warning", 3: "info", 4: "hint"}          # severidad LSP
SEV_COLORS = {1: UI["error"], 2: "#f1c40f", 3: UI["accent"], 4: UI["muted"]}

# Paquetes que aparecen SIEMPRE arriba en  Packages > Install Package...  (y View > Install Theme...)
# Formato: ("usuario/repo", "descripcion corta").  Tambien vale "usuario/repo@rama".
DEFAULT_PACKAGES = [
    ("XelmoisX/Midnight", "Tema Midnight"),
    # ("usuario/otro-paquete", "Lo que hace"),
]

# Librerías de autocompletado que aparecen SIEMPRE en  Tools > Install Library...
# Formato: ("usuario/repo/ruta/libreria.json", "descripcion corta")   (o ...json@rama)
DEFAULT_LIBRARIES = [
    # ("usuario/repo/libs/rcbasic.json", "Autocompletado de RCBasic"),
]

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

# Opciones de color de los widgets tk (para recolorear al cambiar de tema)
COLOR_OPTS = ("bg", "background", "fg", "foreground", "insertbackground", "selectbackground",
              "selectforeground", "highlightbackground", "highlightcolor", "activebackground",
              "activeforeground", "selectcolor", "disabledforeground", "inactiveselectbackground")


def sync_sev_colors():
    """SEV_COLORS se calculó al importar: vuelve a leerlo de UI tras cambiar de tema."""
    SEV_COLORS[1], SEV_COLORS[3], SEV_COLORS[4] = UI["error"], UI["accent"], UI["muted"]


def walk_widgets(w):
    yield w
    for child in w.winfo_children():
        yield from walk_widgets(child)


# ======================================================================
#  TERMINAL
# ======================================================================
class Terminal(Text):
    """Panel de SALIDA (output) interactivo: muestra lo que imprime el programa y lo que
    escribas (después de lo ya impreso) se le envía al programa con Enter (input(), cin...).
    Ctrl+C = detener, Ctrl+D = fin de entrada, flechas arriba/abajo = historial.

        terminal.write("texto")          agrega texto
        terminal.clear()                 limpia el panel
        terminal.run('python "a.py"')    ejecuta un comando y muestra su salida
        terminal.kill()                  detiene el comando en ejecución
        terminal.set_cwd("C:/carpeta")   carpeta donde se ejecutan los comandos
    """

    def __init__(self, master=None, **kwargs):
        # Frame propio (como hacía ScrolledText): se agrega al PanedWindow con terminal.frame
        self.frame = Frame(master, bg=UI["editor"])
        self.frame.grid_rowconfigure(0, weight=1)
        self.frame.grid_columnconfigure(0, weight=1)
        super().__init__(self.frame, height=8, wrap="word", bg=UI["editor"], fg="#f8f8f2",
                         relief="flat", font=("Consolas", 10), insertbackground="white",
                         selectbackground=UI["select"],
                         borderwidth=0, highlightthickness=0, padx=6, pady=4, **kwargs)
        # Scrollbar oscuro (ui.py) que solo aparece cuando la salida pasa del tamaño del panel
        self.vbar = AutoScrollbar(self.frame, orient="vertical",
                                  style="Dark.Vertical.TScrollbar", command=self.yview)
        self.config(yscrollcommand=self.vbar.set)
        Text.grid(self, row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")

        self.tag_configure("error", foreground=UI["error"])
        self.tag_configure("info", foreground=THEME_COLORS["Comment"])

        self.cwd = os.getcwd()
        self.running = False
        self.stopped = False
        self.started = 0.0
        self.proc = None
        self.queue = queue.Queue()
        self.encoding = self._detect_encoding()
        self.on_finish = None                    # callback() cuando termina el proceso
        self.history, self.hist_pos = [], 0      # historial de lo que escribes (flechas arriba/abajo)

        # Lo que está ANTES de "in_start" es salida (no se puede editar); lo que está
        # después es lo que el usuario está escribiendo para el programa (stdin).
        self.mark_set("in_start", "1.0")
        self.mark_gravity("in_start", "left")

        self.bind("<Button-1>", lambda e: self.focus_set())
        self.bind("<KeyPress>", self._on_key)
        self.bind("<<Paste>>", self._on_paste)
        self.bind("<<Cut>>", lambda e: "break")
        self.bind("<Button-2>", lambda e: "break")

    @staticmethod
    def _detect_encoding():
        if os.name == "nt":
            try:
                import ctypes
                return f"cp{ctypes.windll.kernel32.GetOEMCP()}"   # codificación de cmd
            except Exception:
                return "cp437"
        return "utf-8"

    def set_cwd(self, path):
        if os.path.isdir(path):
            self.cwd = os.path.abspath(path)

    # ------------------------------------------------------------- salida
    def write(self, text, tag=None):
        text = ANSI_RE.sub("", text).replace("\r\n", "\n").replace("\r", "")
        if not text:
            return
        self.insert("in_start", text, tag)                    # antes de lo que se está escribiendo
        self.mark_set("in_start", f"in_start+{len(text)}c")
        self.see("end")

    def clear(self):
        self.delete("1.0", "end")
        self.mark_set("in_start", "1.0")

    # ----------------------------------------------------------- entrada (stdin)
    def _ensure_cursor(self):
        """Si el cursor/selección está en la zona de salida, lo manda al final."""
        in_output = self.compare("insert", "<", "in_start")
        if not in_output and self.tag_ranges("sel"):
            in_output = self.compare("sel.first", "<", "in_start")
        if in_output:
            self.tag_remove("sel", "1.0", "end")
            self.mark_set("insert", "end-1c")

    def _on_paste(self, event):
        if not self.running:
            return "break"
        self._ensure_cursor()
        return None

    def _on_key(self, e):
        ks = e.keysym
        if e.state & 0x4:                                    # Ctrl+...
            k = ks.lower()
            if k == "c":
                if self.tag_ranges("sel"):
                    return None                              # copiar
                self.kill()                                  # sin selección: detener (como en una consola)
                return "break"
            if k == "d":                                     # fin de entrada (EOF)
                self.close_stdin()
                return "break"
            if k == "x":
                return "break"
            return None
        if ks in ("Return", "KP_Enter"):
            if self.running:
                self._submit()
            return "break"
        if ks in ("Up", "Down"):
            if self.running:
                self._history(-1 if ks == "Up" else 1)
                return "break"
            return None
        if ks == "Home":
            self.mark_set("insert", "in_start")
            self.tag_remove("sel", "1.0", "end")
            self.see("insert")
            return "break"
        if ks in ("BackSpace", "Delete"):
            if not self.running:
                return "break"
            if self.tag_ranges("sel"):
                return "break" if self.compare("sel.first", "<", "in_start") else None
            op = "<=" if ks == "BackSpace" else "<"
            return "break" if self.compare("insert", op, "in_start") else None
        if ks == "Left":
            return "break" if self.compare("insert", "==", "in_start") else None
        if ks in ("Escape", "Tab"):
            return "break"
        if e.char and ord(e.char[0]) >= 32:                  # carácter imprimible
            if not self.running:
                return "break"
            self._ensure_cursor()
        return None

    def _submit(self):
        """Enter: manda lo escrito al programa (con salto de línea)."""
        self._ensure_cursor()
        text = self.get("in_start", "end-1c")
        self.insert("end-1c", "\n")
        self.mark_set("in_start", "end-1c")
        self.mark_set("insert", "end-1c")
        self.see("end")
        if text.strip():
            self.history.append(text)
        self.hist_pos = len(self.history)
        self._send(text + "\n")

    def _send(self, data):
        try:
            if self.proc and self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.write(data.encode(self.encoding, errors="replace"))
                self.proc.stdin.flush()
        except (OSError, ValueError):
            pass

    def _history(self, d):
        if not self.history:
            return
        self.hist_pos = max(0, min(len(self.history), self.hist_pos + d))
        text = self.history[self.hist_pos] if self.hist_pos < len(self.history) else ""
        self.delete("in_start", "end-1c")
        self.insert("end-1c", text)
        self.mark_set("insert", "end-1c")

    def close_stdin(self):
        """Ctrl+D: cierra la entrada del programa (EOF)."""
        try:
            self.proc.stdin.close()
        except Exception:
            pass

    # ---------------------------------------------------------- ejecución
    def run(self, cmd):
        if self.running:
            self.write("Ya hay un comando en ejecución.\n", "info")
            return

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"        # que print() salga al instante
        env["PYTHONIOENCODING"] = self.encoding   # Python: misma codificación al leer/escribir
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True

        try:
            self.proc = subprocess.Popen(
                cmd, shell=True, cwd=self.cwd, env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
        except Exception as ex:
            self.write(f"{ex}\n", "error")
            return

        self.delete("in_start", "end-1c")                    # descarta texto viejo sin enviar
        self.running = True
        self.stopped = False
        self.started = time.time()
        self.queue = queue.Queue()
        threading.Thread(target=self._reader, args=(self.proc, self.queue), daemon=True).start()
        self.after(40, self._poll)
        self.focus_set()                     # para poder escribir en el programa (input, cin...)

    def _reader(self, proc, q):
        """Hilo que lee la salida del proceso sin congelar la interfaz."""
        decoder = codecs.getincrementaldecoder(self.encoding)(errors="replace")
        try:
            while True:
                chunk = proc.stdout.read1(4096)
                if not chunk:
                    break
                text = decoder.decode(chunk)
                if text:
                    q.put(("out", text))
        except Exception:
            pass
        q.put(("done", proc.wait()))

    def _poll(self):
        finished = None
        try:
            while True:
                kind, data = self.queue.get_nowait()
                if kind == "out":
                    self.write(data)
                else:
                    finished = data
        except queue.Empty:
            pass

        if finished is None:
            self.after(40, self._poll)
        else:
            self.close_stdin()
            self.running = False
            self.proc = None
            self.delete("in_start", "end-1c")                # texto escrito que nadie leyó
            elapsed = time.time() - self.started
            if self.stopped:
                self.write(f"\n[Stopped after {elapsed:.1f}s]\n", "info")
            elif finished != 0:
                self.write(f"\n[exit code {finished} in {elapsed:.1f}s]\n", "error")
            else:
                self.write(f"\n[Finished in {elapsed:.1f}s]\n", "info")
            if self.on_finish:
                self.on_finish()

    def kill(self):
        if not (self.proc and self.running):
            return
        self.stopped = True
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


# ======================================================================
#  WIDGETS BÁSICOS
# ======================================================================
class AutoScrollbar(ttk.Scrollbar):
    """Un Scrollbar (ttk) que se oculta automáticamente si no es necesario."""
    def set(self, lo, hi):
        if float(lo) <= 0.0 and float(hi) >= 1.0:
            self.grid_remove()
        else:
            self.grid()
        ttk.Scrollbar.set(self, lo, hi)


class LineNumbers(Canvas):
    WIDTH = 50

    def __init__(self, master, text_widget, *args, **kwargs):
        super().__init__(master, *args, **kwargs)
        self.text_widget = text_widget
        self.font_size = 10
        self.marks = {}                      # línea -> severidad LSP (1=error, 2=aviso...)
        self.config(width=self.WIDTH, highlightthickness=0, bg=UI["panel"])

    def redraw(self):
        if self.text_widget is None:
            return
        self.delete("all")
        try:
            current_line = self.text_widget.index("insert").split(".")[0]
        except Exception:
            current_line = "1"

        i = self.text_widget.index("@0,0")
        last_drawn = None
        while True:
            dline = self.text_widget.dlineinfo(i)
            if dline is None:
                break
            y, height = dline[1], dline[3]
            line_num = i.split(".")[0]
            if line_num == last_drawn:          # llegamos al final del documento
                break
            last_drawn = line_num

            sev = self.marks.get(int(line_num))
            if sev:                                  # franjita de color si hay un problema
                self.create_rectangle(0, y, 3, y + height, fill=SEV_COLORS.get(sev, UI["accent"]),
                                      outline="")

            is_focused = (line_num == current_line)
            if is_focused:
                self.create_rectangle(0, y, self.WIDTH, y + height, fill=UI["select"], outline="")
            self.create_text(self.WIDTH - 10, y + height / 2, anchor="e", text=line_num,
                             fill="#ffffff" if is_focused else UI["muted"],
                             font=("Consolas", self.font_size, "bold" if is_focused else "normal"))
            i = self.text_widget.index(f"{i}+1line")


# ======================================================================
#  BARRA DE BÚSQUEDA / REEMPLAZO  (Ctrl+F / Ctrl+H)
# ======================================================================
class FindBar(Frame):
    def __init__(self, editor):
        super().__init__(editor, bg=UI["panel"])
        self.editor = editor
        self.ta = editor.text_area
        self.visible = False
        self.matches = []            # [(inicio, fin, match)]
        self.current = -1

        self.case = BooleanVar(value=False)
        self.regex = BooleanVar(value=False)
        self.word = BooleanVar(value=False)
        self.find_var = StringVar()
        self.repl_var = StringVar()
        self.info = StringVar()

        def entry(parent, var):
            return Entry(parent, textvariable=var, bg=UI["editor"], fg="#ffffff",
                         insertbackground="white", relief="flat", highlightthickness=1,
                         highlightbackground=UI["bg"], highlightcolor=UI["accent"],
                         font=("Segoe UI", 10))

        def button(parent, text, command, toggle_var=None):
            opts = dict(text=text, command=command, bg=UI["editor"], fg=UI["fg"], relief="flat",
                        bd=0, padx=8, pady=2, activebackground=UI["select"],
                        activeforeground="#ffffff", font=("Segoe UI", 9))
            if toggle_var is not None:
                return Checkbutton(parent, variable=toggle_var, indicatoron=False,
                                   selectcolor=UI["select"], **opts)
            return Button(parent, **opts)

        self.row1 = Frame(self, bg=UI["panel"])
        self.row1.pack(fill="x", padx=6, pady=(6, 3))
        self.find_entry = entry(self.row1, self.find_var)
        self.find_entry.pack(side="left", fill="x", expand=True, ipady=2)
        Label(self.row1, textvariable=self.info, bg=UI["panel"], fg=UI["muted"], width=12,
              font=("Segoe UI", 9)).pack(side="left", padx=4)
        button(self.row1, "Aa", self.refresh, self.case).pack(side="left", padx=1)
        button(self.row1, ".*", self.refresh, self.regex).pack(side="left", padx=1)
        button(self.row1, "\\b", self.refresh, self.word).pack(side="left", padx=1)
        button(self.row1, "▲", lambda: self.step(-1)).pack(side="left", padx=(6, 1))
        button(self.row1, "▼", lambda: self.step(1)).pack(side="left", padx=1)
        button(self.row1, "✕", self.hide).pack(side="left", padx=(6, 0))

        self.row2 = Frame(self, bg=UI["panel"])
        self.repl_entry = entry(self.row2, self.repl_var)
        self.repl_entry.pack(side="left", fill="x", expand=True, ipady=2)
        button(self.row2, "Replace", self.replace_current).pack(side="left", padx=(6, 1))
        button(self.row2, "Replace All", self.replace_all).pack(side="left", padx=1)

        self.find_var.trace_add("write", lambda *a: self.refresh())
        for e in (self.find_entry, self.repl_entry):
            e.bind("<Escape>", lambda ev: (self.hide(), "break")[1])
        self.find_entry.bind("<Return>", lambda ev: (self.step(1), "break")[1])
        self.find_entry.bind("<Shift-Return>", lambda ev: (self.step(-1), "break")[1])
        self.repl_entry.bind("<Return>", lambda ev: (self.replace_current(), "break")[1])

    # -------------------------------------------------------- mostrar
    def show(self, replace=False):
        self.visible = True
        self.grid(row=2, column=0, columnspan=3, sticky="ew")
        if replace:
            self.row2.pack(fill="x", padx=6, pady=(0, 6), after=self.row1)
        else:
            self.row2.pack_forget()
        if self.ta.tag_ranges("sel"):
            sel = self.ta.get("sel.first", "sel.last")
            if sel and "\n" not in sel:
                self.find_var.set(sel)
        self.find_entry.focus_set()
        self.find_entry.select_range(0, "end")
        self.find_entry.icursor("end")
        self.refresh()

    def hide(self):
        self.visible = False
        self.grid_remove()
        self.ta.tag_remove("find", "1.0", "end")
        self.ta.tag_remove("find_current", "1.0", "end")
        self.ta.focus_set()

    # ------------------------------------------------------- búsqueda
    def compile(self):
        q = self.find_var.get()
        if not q:
            return None
        try:
            pat = q if self.regex.get() else re.escape(q)
            if self.word.get():
                pat = rf"\b(?:{pat})\b"
            return re.compile(pat, re.M | (0 if self.case.get() else re.I))
        except re.error:
            self.info.set("Regex inválida")
            return None

    def refresh(self, jump=True):
        ta = self.ta
        ta.tag_remove("find", "1.0", "end")
        ta.tag_remove("find_current", "1.0", "end")
        self.matches, self.current = [], -1
        self.info.set("")
        pat = self.compile()
        if pat is None:
            return

        code = ta.get("1.0", "end-1c")
        starts = [0] + [m.end() for m in re.finditer("\n", code)]

        def idx(p):
            line = bisect_right(starts, p) - 1
            return f"{line + 1}.{p - starts[line]}"

        for m in pat.finditer(code):
            if m.end() == m.start():
                continue
            self.matches.append((idx(m.start()), idx(m.end()), m))
            if len(self.matches) >= MAX_MATCHES:
                break
        for s, e, _ in self.matches:
            ta.tag_add("find", s, e)

        if self.matches and jump:
            self._goto_from(self._pos())
        else:
            self._update_info()

    def _pos(self):
        return self.ta.index("sel.first") if self.ta.tag_ranges("sel") else self.ta.index("insert")

    def _goto_from(self, pos, move=False):
        idx = 0                                      # si no hay más adelante, vuelve al inicio
        for i, (s, e, m) in enumerate(self.matches):
            if self.ta.compare(s, ">=", pos):
                idx = i
                break
        self._select(idx, move)

    def _select(self, i, move):
        ta = self.ta
        s, e, _ = self.matches[i]
        self.current = i
        ta.tag_remove("find_current", "1.0", "end")
        ta.tag_add("find_current", s, e)
        if move:
            ta.tag_remove("sel", "1.0", "end")
            ta.tag_add("sel", s, e)
            ta.mark_set("insert", e)
            self.editor.cursor_moved()
        ta.see(s)
        self._update_info()

    def _update_info(self):
        if self.matches:
            more = "+" if len(self.matches) >= MAX_MATCHES else ""
            self.info.set(f"{self.current + 1}/{len(self.matches)}{more}")
        elif self.find_var.get() and self.compile() is not None:
            self.info.set("Sin resultados")

    def step(self, direction):
        if not self.visible:
            self.show()
            return
        if not self.matches:
            return
        if self.current < 0:
            self._goto_from(self._pos(), move=True)
        else:
            self._select((self.current + direction) % len(self.matches), move=True)

    # ------------------------------------------------------ reemplazar
    def _replacement(self, m):
        r = self.repl_var.get()
        return m.expand(r) if self.regex.get() else r

    def replace_current(self):
        if self.current < 0 or not self.matches:
            self.step(1)
            return
        s, e, m = self.matches[self.current]
        try:
            text = self._replacement(m)
        except (re.error, IndexError):
            self.info.set("Reemplazo inválido")
            return

        def do():
            self.ta.delete(s, e)
            self.ta.insert(s, text)
        self.editor.group(do)
        after = self.ta.index(f"{s}+{len(text)}c")
        self.refresh(jump=False)
        if self.matches:
            self._goto_from(after, move=True)

    def replace_all(self):
        if not self.matches:
            return
        try:
            reps = [self._replacement(m) for _, _, m in self.matches]
        except (re.error, IndexError):
            self.info.set("Reemplazo inválido")
            return

        def do():
            for (s, e, _), r in reversed(list(zip(self.matches, reps))):
                self.ta.delete(s, e)
                self.ta.insert(s, r)
        self.editor.group(do)
        self.refresh(jump=False)


# ======================================================================
#  EDITOR DE CÓDIGO
# ======================================================================
class CodeEditor(Frame):
    def __init__(self, master=None, language="python", file_path=None, font_size=11, **kwargs):
        super().__init__(master, bg=UI["bg"], **kwargs)
        self.language = language
        self.file_path = file_path      # None = archivo sin guardar (Untitled)
        self.dirty = False              # ¿tiene cambios sin guardar?
        self.font_size = font_size         # tamaño actual (también lo usa el popup de sugerencias)
        self.rid = uuid.uuid4().hex[:12]   # id del respaldo de este editor
        self.rev = 0                       # sube con cada cambio
        self.backed_rev = 0                # revisión que ya está respaldada
        self.disk_mtime = None             # fecha del archivo en disco al abrir/guardar
        self.on_dirty = None            # callback(editor): se llamó al primer cambio
        self.on_cursor = None           # callback(editor): el cursor se movió
        self._hl_job = None

        # --- LSP (autocompletado y errores) ---
        self.lsp = None                 # LSPManager (lo asigna la ventana principal)
        self.lsp_opened = False         # ¿el servidor tiene abierto este archivo?
        self.lsp_path = None
        self._sync_job, self._sync_pending = None, False
        self._synced_text = None        # último texto enviado al servidor
        self.on_diag = None             # callback(editor) cuando cambian los diagnósticos
        self.diag_tags, self.diag_info, self.diag_items = [], {}, []
        self.diag_counts = (0, 0)       # (errores, avisos)
        self.comp_box, self._comp_rows, self._comp_all, self._comp_anchor = None, [], [], None
        self._comp_token, self._comp_job = 0, None
        self._tip, self._tip_job = None, None
        self.suggester = Suggester()    # keywords / builtins / snippets / palabras del archivo
        self.suggest_on = True          # lo controla la ventana principal
        self.libs = None                # LibraryManager (lo asigna la ventana principal)

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self.line_numbers = LineNumbers(self, None)
        self.line_numbers.grid(row=0, column=0, sticky="ns")

        self.vbar = AutoScrollbar(self, orient="vertical", style="Dark.Vertical.TScrollbar")
        self.vbar.grid(row=0, column=2, sticky="ns")
        self.hbar = AutoScrollbar(self, orient="horizontal", style="Dark.Horizontal.TScrollbar")
        self.hbar.grid(row=1, column=1, sticky="ew")

        self.font = tkfont.Font(family="Consolas", size=font_size)
        self.text_area = Text(self, font=self.font, wrap="none", bg=UI["editor"], fg="#ffffff",
                              insertbackground="white", relief="flat", borderwidth=0,
                              highlightthickness=0, padx=6,
                              selectbackground=UI["select"], selectforeground="#ffffff",
                              inactiveselectbackground=UI["select"],
                              undo=True, autoseparators=True, maxundo=-1)   # <- deshacer/rehacer
        self.text_area.grid(row=0, column=1, sticky="nsew")
        self.line_numbers.text_widget = self.text_area

        self.vbar.config(command=self.text_area.yview)
        self.hbar.config(command=self.text_area.xview)
        self.text_area.config(yscrollcommand=self._yscroll, xscrollcommand=self.hbar.set)

        self.find_bar = FindBar(self)          # se muestra con Ctrl+F / Ctrl+H

        self.set_font_size(font_size)
        self.setup_tags()

        ta = self.text_area
        ta.bind("<<Modified>>", self.on_content_changed)
        ta.bind("<KeyRelease>", self.on_key_release)
        ta.bind("<ButtonRelease-1>", lambda e: self.cursor_moved())
        ta.bind("<Return>", self.on_return)
        ta.bind("<Tab>", self.on_tab)
        ta.bind("<Shift-Tab>", lambda e: self.on_shift_tab())
        try:
            ta.bind("<ISO_Left_Tab>", lambda e: self.on_shift_tab())      # Linux
        except TclError:
            pass
        ta.bind("<BackSpace>", self.on_backspace)
        ta.bind("<KeyPress>", self.on_keypress)
        ta.bind("<Up>", self.on_up)
        ta.bind("<Down>", self.on_down)
        ta.bind("<Escape>", self.on_escape)
        ta.bind("<Control-space>", lambda e: (self.request_completion(manual=True), "break")[1])
        ta.bind("<Button-1>", lambda e: self.comp_close(), add="+")
        ta.bind("<FocusOut>", lambda e: self.comp_close(), add="+")
        ta.bind("<Motion>", self._on_motion)
        ta.bind("<Leave>", lambda e: self._hide_tip())

        self.line_numbers.redraw()

    # ----------------------------------------------------------- base
    def _yscroll(self, *args):
        self.vbar.set(*args)
        self.line_numbers.redraw()

    def setup_tags(self):
        ta = self.text_area
        ta.tag_configure("current_line", background=UI["line_hl"])
        ta.tag_configure("bracket", background=UI["bracket"])
        ta.tag_configure("find", background=UI["find"])
        ta.tag_configure("find_current", background=UI["find_current"])
        for tag_name, color in THEME_COLORS.items():
            ta.tag_configure(tag_name, foreground=color)
        ta.tag_raise("sel")                    # la selección siempre por encima

    def set_font_size(self, size):
        self.font_size = size                              # el popup de sugerencias usa este valor
        self.font.configure(size=size)
        self.text_area.config(tabs=self.font.measure(" " * 4))
        self.line_numbers.font_size = max(7, size - 1)
        self.line_numbers.redraw()
        if self.comp_box is not None:                      # popup abierto: reescalarlo al instante
            self.comp_box.apply_size(size)
            self._comp_show()

    def set_wrap(self, flag):
        self.text_area.config(wrap="word" if flag else "none")

    def set_language(self, language):
        """Cambia el lenguaje y vuelve a colorear."""
        self.language = language
        self.highlight()
        if self.lsp is not None and self.file_path:
            self.lsp_open()                  # otro lenguaje = otro servidor

    def lang(self):
        if self.libs is not None and self.file_path:          # una librería/servidor puede reclamar la extensión
            declared = self.libs.language_for_path(self.file_path)
            if declared:
                return declared
        return resolve_language(self.language)

    # ------------------------------------------------- carga / guardado
    def load_text(self, text):
        ta = self.text_area
        ta.insert("1.0", text)
        ta.edit_reset()                  # no se puede deshacer la carga del archivo
        ta.edit_modified(False)
        self.dirty = False
        self.highlight()
        ta.mark_set("insert", "1.0")

    def mark_saved(self):
        self.dirty = False
        self.text_area.edit_modified(False)

    # -------------------------------------------------------- highlight
    def highlight(self):
        code = self.text_area.get("1.0", "end-1c")
        for tag_name in THEME_COLORS.keys():
            self.text_area.tag_remove(tag_name, "1.0", "end")
        for tag, start, end in highlight_ranges(code, self.language):
            self.text_area.tag_add(tag, start, end)

    def schedule_highlight(self):
        if self._hl_job:
            self.after_cancel(self._hl_job)
        self._hl_job = self.after(30, self._run_highlight)

    def _run_highlight(self):
        self._hl_job = None
        if not self.winfo_exists():
            return
        self.highlight()
        if self.find_bar.visible:
            self.find_bar.refresh(jump=False)

    def on_content_changed(self, event=None):
        ta = self.text_area
        if not ta.edit_modified():
            return
        ta.edit_modified(False)
        self.rev += 1
        if not self.dirty:
            self.dirty = True
            if self.on_dirty:
                self.on_dirty(self)
        self.schedule_highlight()
        self.lsp_schedule_sync()
        self.cursor_moved()

    # ----------------------------------------------- cursor / paréntesis
    def cursor_moved(self):
        ta = self.text_area
        ta.tag_remove("current_line", "1.0", "end")
        if not ta.tag_ranges("sel"):
            ta.tag_add("current_line", "insert linestart", "insert lineend+1c")
        self.match_brackets()
        self.line_numbers.redraw()
        if self.on_cursor:
            self.on_cursor(self)

    def match_brackets(self):
        ta = self.text_area
        ta.tag_remove("bracket", "1.0", "end")
        opens, closes = "([{", ")]}"
        for off in ("insert", "insert-1c"):
            ch = ta.get(off, f"{off}+1c")
            if ch and ch in opens:
                target, depth = closes[opens.index(ch)], 1
                text = ta.get(f"{off}+1c", f"{off}+20001c")
                for i, c in enumerate(text):
                    if c == ch:
                        depth += 1
                    elif c == target:
                        depth -= 1
                        if depth == 0:
                            ta.tag_add("bracket", off, f"{off}+1c")
                            ta.tag_add("bracket", f"{off}+{i + 1}c", f"{off}+{i + 2}c")
                            return
            elif ch and ch in closes:
                target, depth = opens[closes.index(ch)], 1
                text = ta.get(f"{off}-20000c", off)
                for i, c in enumerate(reversed(text)):
                    if c == ch:
                        depth += 1
                    elif c == target:
                        depth -= 1
                        if depth == 0:
                            ta.tag_add("bracket", off, f"{off}+1c")
                            ta.tag_add("bracket", f"{off}-{i + 1}c", f"{off}-{i}c")
                            return

    # -------------------------------------------------- deshacer / rehacer
    def _history(self, action):
        """Deshacer / rehacer. action = "edit_undo" o "edit_redo"."""
        try:
            getattr(self.text_area, action)()
        except TclError:
            return                       # nada que deshacer / rehacer
        self.text_area.see("insert")
        self.schedule_highlight()
        self.cursor_moved()

    def undo(self):
        self._history("edit_undo")

    def redo(self):
        self._history("edit_redo")

    def group(self, fn):
        """Ejecuta fn() como UN solo paso de deshacer (aunque borre e inserte)."""
        ta = self.text_area
        ta.edit_separator()
        ta.config(autoseparators=False)
        try:
            fn()
        finally:
            ta.config(autoseparators=True)
            ta.edit_separator()

    # ---------------------------------------------------------- edición
    def select_all(self):
        self.text_area.tag_add("sel", "1.0", "end")
        self.cursor_moved()

    def _select_range(self, s, e):
        ta = self.text_area
        ta.tag_remove("sel", "1.0", "end")
        ta.tag_add("sel", s, e)
        ta.mark_set("insert", e)
        ta.see(s)
        self.cursor_moved()

    def sel_lines(self):
        """(primera, última) línea afectada por la selección o por el cursor."""
        ta = self.text_area
        if ta.tag_ranges("sel"):
            a = int(ta.index("sel.first").split(".")[0])
            end = ta.index("sel.last")
            b = int(end.split(".")[0])
            if end.endswith(".0") and b > a:
                b -= 1
            return a, b
        line = int(ta.index("insert").split(".")[0])
        return line, line

    def last_line(self):
        return int(self.text_area.index("end-1c").split(".")[0])

    def goto_line(self, n):
        n = max(1, min(int(n), self.last_line()))
        ta = self.text_area
        ta.tag_remove("sel", "1.0", "end")
        ta.mark_set("insert", f"{n}.0")
        ta.see(f"{n}.0")
        self.cursor_moved()

    # --- auto-indentación, tabs y pares ---------------------------------
    def on_return(self, event):
        ta = self.text_area
        if self.comp_box is not None:                 # aceptar la sugerencia
            self.comp_accept()
            return "break"

        def do():
            if ta.tag_ranges("sel"):
                ta.delete("sel.first", "sel.last")
            line = ta.get("insert linestart", "insert")
            indent = re.match(r"[ \t]*", line).group(0)
            stripped = line.rstrip()
            after = ta.get("insert", "insert lineend")
            opener = stripped.endswith(("{", "(", "["))
            extra = INDENT if (opener or (self.lang() == "python" and stripped.endswith(":"))) else ""
            if opener and after[:1] in ("}", ")", "]"):
                ta.insert("insert", "\n" + indent + extra + "\n" + indent)
                ta.mark_set("insert", "insert-1l lineend")
            else:
                ta.insert("insert", "\n" + indent + extra)
            ta.see("insert")
        self.group(do)
        return "break"

    def on_tab(self, event):
        if self.comp_box is not None:
            self.comp_accept()
            return "break"
        if self.text_area.tag_ranges("sel"):
            a, b = self.sel_lines()
            if a != b:
                self.indent_lines(a, b)
                return "break"
        return None

    def on_shift_tab(self):
        self.unindent()
        return "break"

    def indent_lines(self, a, b):
        ta = self.text_area

        def do():
            for l in range(a, b + 1):
                if ta.get(f"{l}.0", f"{l}.end").strip():
                    ta.insert(f"{l}.0", INDENT)
        self.group(do)
        ta.tag_remove("sel", "1.0", "end")
        ta.tag_add("sel", f"{a}.0", f"{b}.end")

    def indent(self):
        a, b = self.sel_lines()
        self.indent_lines(a, b)

    def unindent(self):
        ta = self.text_area
        a, b = self.sel_lines()
        had_sel = bool(ta.tag_ranges("sel"))

        def do():
            for l in range(a, b + 1):
                text = ta.get(f"{l}.0", f"{l}.end")
                if text.startswith("\t"):
                    ta.delete(f"{l}.0", f"{l}.1")
                else:
                    n = min(4, len(text) - len(text.lstrip(" ")))
                    if n:
                        ta.delete(f"{l}.0", f"{l}.{n}")
        self.group(do)
        if had_sel:
            ta.tag_remove("sel", "1.0", "end")
            ta.tag_add("sel", f"{a}.0", f"{b}.end")
        self.cursor_moved()
        return "break"

    def on_keypress(self, event):
        self.after_idle(self.cursor_moved)          # flechas, etc.
        ch = event.char
        if not ch or (ch not in PAIRS and ch not in CLOSERS):
            return None
        ta = self.text_area
        nxt = ta.get("insert", "insert+1c")
        prev = ta.get("insert-1c", "insert")

        if ch in PAIRS:
            close = PAIRS[ch]
            if ta.tag_ranges("sel"):                # envuelve la selección
                text = ta.get("sel.first", "sel.last")
                start = ta.index("sel.first")

                def do():
                    ta.delete("sel.first", "sel.last")
                    ta.insert(start, ch + text + close)
                self.group(do)
                self._select_range(f"{start}+1c", f"{start}+{len(text) + 1}c")
                return "break"
            if ch in "\"'":
                if nxt == ch:                       # saltar la comilla que ya está
                    ta.mark_set("insert", "insert+1c")
                    return "break"
                if prev.isalnum() or prev == "\\" or nxt.isalnum():
                    return None                     # apóstrofe dentro de una palabra
            elif nxt and not (nxt.isspace() or nxt in ")]}\"',;:"):
                return None
            ta.insert("insert", ch + close)
            ta.mark_set("insert", "insert-1c")
            return "break"

        if ch in CLOSERS and nxt == ch:             # saltar el cierre que ya está
            ta.mark_set("insert", "insert+1c")
            return "break"
        return None

    def on_backspace(self, event):
        ta = self.text_area
        if ta.tag_ranges("sel"):
            return None
        prev = ta.get("insert-1c", "insert")
        nxt = ta.get("insert", "insert+1c")
        if prev in PAIRS and PAIRS[prev] == nxt:    # borra ambos: ( | )
            ta.delete("insert-1c", "insert+1c")
            return "break"
        return None

    # --- operaciones de línea (estilo Sublime) --------------------------
    def duplicate_line(self):
        ta = self.text_area
        if ta.tag_ranges("sel"):
            text = ta.get("sel.first", "sel.last")
            end = ta.index("sel.last")
            self.group(lambda: ta.insert(end, text))
            self._select_range(end, f"{end}+{len(text)}c")
            return
        line = int(ta.index("insert").split(".")[0])
        col = ta.index("insert").split(".")[1]
        text = ta.get(f"{line}.0", f"{line}.end")
        self.group(lambda: ta.insert(f"{line}.end", "\n" + text))
        ta.mark_set("insert", f"{line + 1}.{col}")
        ta.see("insert")
        self.cursor_moved()

    def delete_line(self):
        ta = self.text_area
        a, b = self.sel_lines()
        last = self.last_line()

        def do():
            if b < last:
                ta.delete(f"{a}.0", f"{b + 1}.0")
            elif a > 1:
                ta.delete(f"{a - 1}.end", f"{b}.end")
            else:
                ta.delete(f"{a}.0", f"{b}.end")
        self.group(do)
        self.cursor_moved()

    def move_lines(self, delta):
        ta = self.text_area
        a, b = self.sel_lines()
        if (delta < 0 and a == 1) or (delta > 0 and b >= self.last_line()):
            return
        had_sel = bool(ta.tag_ranges("sel"))
        line, col = ta.index("insert").split(".")
        block = ta.get(f"{a}.0", f"{b}.end")

        def do():
            if delta < 0:
                other = ta.get(f"{a - 1}.0", f"{a - 1}.end")
                ta.delete(f"{a - 1}.0", f"{b}.end")
                ta.insert(f"{a - 1}.0", block + "\n" + other)
            else:
                other = ta.get(f"{b + 1}.0", f"{b + 1}.end")
                ta.delete(f"{a}.0", f"{b + 1}.end")
                ta.insert(f"{a}.0", other + "\n" + block)
        self.group(do)
        ta.mark_set("insert", f"{int(line) + delta}.{col}")
        if had_sel:
            ta.tag_remove("sel", "1.0", "end")
            ta.tag_add("sel", f"{a + delta}.0", f"{b + delta}.end")
        ta.see("insert")
        self.cursor_moved()

    def move_line_up(self):
        self.move_lines(-1)

    def move_line_down(self):
        self.move_lines(1)

    def toggle_comment(self):
        prefix = COMMENT.get(self.lang()) or (
            self.libs.comment_for(self.lang(), self.file_path) if self.libs is not None else None)
        if not prefix:
            return
        ta = self.text_area
        a, b = self.sel_lines()
        rows = list(range(a, b + 1))
        lines = [ta.get(f"{l}.0", f"{l}.end") for l in rows]
        nonblank = [x for x in lines if x.strip()]
        if not nonblank:
            return
        uncomment = all(x.lstrip().startswith(prefix) for x in nonblank)

        def do():
            if uncomment:
                for l, text in zip(rows, lines):
                    s = text.lstrip()
                    if not s.startswith(prefix):
                        continue
                    col = len(text) - len(s)
                    n = len(prefix) + (1 if s[len(prefix):len(prefix) + 1] == " " else 0)
                    ta.delete(f"{l}.{col}", f"{l}.{col + n}")
            else:
                col = min(len(x) - len(x.lstrip()) for x in nonblank)
                for l, text in zip(rows, lines):
                    if text.strip():
                        ta.insert(f"{l}.{col}", prefix + " ")
        self.group(do)
        self.cursor_moved()

    def select_next(self):
        """Ctrl+D: selecciona la palabra; otra vez Ctrl+D salta a la siguiente coincidencia."""
        ta = self.text_area
        if not ta.tag_ranges("sel"):
            s, e = ta.index("insert wordstart"), ta.index("insert wordend")
            if s != e:
                self._select_range(s, e)
            return
        text = ta.get("sel.first", "sel.last")
        start = ta.index("sel.last")
        pos = ta.search(text, start, "end", exact=True) or ta.search(text, "1.0", start, exact=True)
        if pos:
            self._select_range(pos, f"{pos}+{len(text)}c")

    # =====================================================================
    #  LSP: sincronización, errores (diagnósticos) y autocompletado
    # =====================================================================
    def lsp_open(self):
        """Avisa al servidor que este archivo está abierto. True si hay servidor para él."""
        self.lsp_close()
        if self.lsp is None or not self.file_path:
            return False
        text = self.text_area.get("1.0", "end-1c")
        if self.lsp.open(self.file_path, self.lang(), text):
            self.lsp_opened, self.lsp_path = True, self.file_path
            self._synced_text = text
        return self.lsp_opened

    def lsp_close(self):
        if self._sync_job:
            self.after_cancel(self._sync_job)
            self._sync_job = None
        if self.lsp_opened and self.lsp is not None and self.lsp_path:
            self.lsp.close(self.lsp_path)
        self.lsp_opened, self.lsp_path, self._sync_pending = False, None, False
        self.comp_close()
        self.set_diagnostics([])

    def lsp_schedule_sync(self):
        if not self.lsp_opened:
            return
        self._sync_pending = True
        if self._sync_job:
            self.after_cancel(self._sync_job)
        self._sync_job = self.after(300, self.lsp_sync)

    def lsp_sync(self):
        """Manda el texto actual al servidor (solo si cambió desde la última vez)."""
        if self._sync_job:
            self.after_cancel(self._sync_job)
            self._sync_job = None
        self._sync_pending = False
        if not self.lsp_opened or self.lsp is None:
            return
        text = self.text_area.get("1.0", "end-1c")
        if text != self._synced_text:
            self._synced_text = text
            self.lsp.change(self.lsp_path, text)

    # --- diagnósticos -------------------------------------------------------
    def set_diagnostics(self, diags):
        ta = self.text_area
        for t in self.diag_tags:
            ta.tag_delete(t)
        self.diag_tags, self.diag_info, self.diag_items = [], {}, []
        marks, errors, warnings = {}, 0, 0
        last = self.last_line()
        for i, d in enumerate(diags[:300]):
            r = d.get("range") or {}
            s, e = r.get("start") or {}, r.get("end") or {}
            sl, sc = s.get("line", 0) + 1, s.get("character", 0)
            el, ec = e.get("line", s.get("line", 0)) + 1, e.get("character", sc)
            if sl > last:
                continue
            start = f"{sl}.{sc}"
            if (el, ec) == (sl, sc):
                end = f"{start}+1c"
            else:
                end = "end-1c" if el > last else f"{el}.{ec}"
            sev = d.get("severity", 1)
            name = f"diag_{i}"
            try:
                ta.tag_configure(name, underline=True, underlinefg=SEV_COLORS.get(sev, UI["muted"]))
            except TclError:
                ta.tag_configure(name, underline=True)
            ta.tag_add(name, start, end)
            msg = (d.get("message") or "").strip()
            source = d.get("source")
            self.diag_tags.append(name)
            self.diag_info[name] = f"[{SEV_NAMES.get(sev, '?')}] {msg}" + (f"   ({source})" if source else "")
            self.diag_items.append((sl, sc, sev, msg.split("\n")[0]))
            if sev < marks.get(sl, 9):
                marks[sl] = sev
            errors += sev == 1
            warnings += sev == 2
        self.diag_counts = (errors, warnings)
        self.line_numbers.marks = marks
        self.line_numbers.redraw()
        if self.on_diag:
            self.on_diag(self)

    def _on_motion(self, e):
        self._hide_tip()
        if self.diag_tags:
            self._tip_job = self.after(450, lambda x=e.x, y=e.y: self._show_tip(x, y))

    def _hide_tip(self):
        if self._tip_job:
            self.after_cancel(self._tip_job)
            self._tip_job = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None

    def _show_tip(self, x, y):
        """Muestra el mensaje del error cuando el mouse se queda sobre el subrayado."""
        self._tip_job = None
        ta = self.text_area
        bbox = ta.bbox(f"@{x},{y}")
        if not bbox or not (bbox[0] <= x < bbox[0] + bbox[2] and bbox[1] <= y < bbox[1] + bbox[3]):
            return
        index = ta.index(f"@{x},{y}")
        msgs = [self.diag_info[t] for t in ta.tag_names(index) if t in self.diag_info]
        if not msgs:
            return
        tip = Label(self, text="\n".join(msgs[:4]), justify="left", anchor="w", bg=UI["bg"],
                    fg=UI["fg"], bd=1, relief="solid", padx=6, pady=3, wraplength=520,
                    font=("Segoe UI", 9))
        tip.place(in_=ta, x=0, y=0)
        tip.update_idletasks()
        px = max(0, min(x + 12, ta.winfo_width() - tip.winfo_reqwidth() - 4))
        py = y + 20
        if py + tip.winfo_reqheight() > ta.winfo_height():
            py = max(0, y - tip.winfo_reqheight() - 6)
        tip.place(in_=ta, x=px, y=py)
        tip.lift()
        self._tip = tip

    # --- autocompletado -----------------------------------------------------
    def _has_libs(self):
        return self.libs is not None and self.libs.has(self.lang(), self.file_path)

    def _word_before(self):
        line = self.text_area.get("insert linestart", "insert")
        return re.search(r"\w*$", line).group(0)

    def on_key_release(self, e):
        self.cursor_moved()
        if not (self.lsp_opened or self.suggest_on or self._has_libs()):
            return
        ks = e.keysym
        if ks in ("Up", "Down", "Return", "KP_Enter", "Tab", "Escape"):
            return
        before = self.text_area.get("insert linestart", "insert")
        ch = e.char or ({"period": ".", "underscore": "_", "colon": ":", "greater": ">"}.get(ks)
                        or (before[-1:] if len(ks) == 1 else ""))
        ident = bool(ch) and (ch.isalnum() or ch == "_")
        if self.comp_box is not None:
            if ident or ks == "BackSpace":
                self._comp_filter_show()                      # seguir filtrando sin pedir de nuevo
                return
            self.comp_close()
        if ident:
            self._schedule_completion(None)
        elif ch == "." and before.endswith("."):
            self._schedule_completion(".")
        elif ch == ">" and before.endswith("->"):
            self._schedule_completion(">")
        elif ch == ":" and before.endswith("::"):
            self._schedule_completion(":")

    def _schedule_completion(self, trigger):
        if self._comp_job:
            self.after_cancel(self._comp_job)
        delay = 80 if self.lsp_opened else 25
        self._comp_job = self.after(delay, lambda: self.request_completion(trigger))

    def request_completion(self, trigger=None, manual=False):
        """Pide sugerencias (Ctrl+Space o automático al escribir): LSP + keywords/snippets/palabras."""
        self._comp_job = None
        ta = self.text_area
        if ta.tag_ranges("sel"):
            return
        use_lsp = self.lsp_opened and self.lsp is not None
        has_lib = self._has_libs()
        if not use_lsp and not self.suggest_on and not has_lib:
            return
        line, col = (int(v) for v in ta.index("insert").split("."))
        prefix = self._word_before()
        anchor = (line, col - len(prefix))
        before = ta.get(f"{line}.0", f"{line}.{anchor[1]}")

        # No sugerir dentro de comentarios ni cadenas
        ctx = suggest_context(self.lang(), before)
        if ctx in ("string", "comment"):
            self.comp_close()
            return

        local = []
        if self.suggest_on:
            local = self.suggester.suggest(self.lang(), before, prefix,
                                           lambda: ta.get("1.0", "end-1c"), self.rev, manual)
        if has_lib and ctx == "code" and not prefix[:1].isdigit() and (manual or len(prefix) >= 2):
            lib = self.libs.items_for(self.lang(), self.file_path)       # funciones/keywords de la librería
            names = {i["label"].lower() for i in lib}
            local = lib + [i for i in local if i["label"].lower() not in names]
        self._comp_token += 1
        token = self._comp_token
        if not use_lsp:
            self._on_completion(local, token, anchor)
            return
        self.lsp_sync()                                        # el servidor debe tener el texto actual
        self.lsp.completion(self.lsp_path, line - 1, col, trigger,
                            lambda items: self._on_completion(self._merge(items, local), token, anchor))

    @staticmethod
    def _merge(lsp_items, local):
        """Primero lo del LSP; lo local solo agrega lo que el servidor no trajo."""
        labels = {i["label"] for i in lsp_items}
        return list(lsp_items) + [i for i in local if i.get("snippet") or i["label"] not in labels]

    def _on_completion(self, items, token, anchor):
        if token != self._comp_token:
            return                                             # respuesta vieja
        self._comp_all, self._comp_anchor = items, anchor
        self._comp_filter_show()

    @staticmethod
    def _rank(prefix, items):
        p = prefix.lower()
        scored = []
        for it in items:
            f = it.get("_f") or it["filter"].lower()
            if not p:
                score = 3
            elif f.startswith(p):
                score = 0 if it["filter"].startswith(prefix) else 1
            elif p in f:
                score = 2
            else:
                # coincidencia difusa (letras en orden): solo con 3+ letras y misma inicial
                if len(p) < 3 or f[:1] != p[:1]:
                    continue
                it_f = iter(f)
                if not all(c in it_f for c in p):
                    continue
                score = 3
            scored.append((score, it["sort"], it["label"], it))
        scored.sort(key=lambda t: t[:3])
        return [t[3] for t in scored]

    def _comp_filter_show(self):
        ta = self.text_area
        if self._comp_anchor is None:
            return
        line, start = self._comp_anchor
        cur_line, cur_col = (int(v) for v in ta.index("insert").split("."))
        if cur_line != line or cur_col < start:
            self.comp_close()
            return
        prefix = ta.get(f"{line}.{start}", "insert")
        if prefix and not re.fullmatch(r"\w+", prefix):
            self.comp_close()
            return
        rows = self._rank(prefix, self._comp_all)[:60]
        if not rows or (len(rows) == 1 and rows[0]["insert"] == prefix):
            self.comp_close()
            return
        self._comp_rows = rows
        self._comp_prefix = prefix
        self._comp_show()

    def _comp_show(self):
        ta = self.text_area
        if self._comp_anchor is None:
            return
        line, start = self._comp_anchor
        bbox = ta.bbox(f"{line}.{start}") or ta.bbox("insert")
        if not bbox:
            self.comp_close()
            return
        if self.comp_box is None:
            self.comp_box = SuggestPopup(self, self.comp_accept, self.font_size)
        box = self.comp_box
        box.set_rows(self._comp_rows, getattr(self, "_comp_prefix", ""))
        w, h = box.size()
        x, y, _, bh = bbox
        px = max(0, min(x, ta.winfo_width() - w - 4))           # que no se salga por la derecha
        py = y + bh + 2
        if py + h > ta.winfo_height() and y - h > 0:
            py = y - h - 4                                      # si no cabe abajo, va arriba
        box.place(in_=ta, x=px, y=py)
        box.lift()

    def _comp_move(self, d):
        self.comp_box.move(d)

    def comp_close(self):
        self._comp_token += 1                                   # ignora respuestas que lleguen tarde
        if self.comp_box is not None:
            self.comp_box.destroy()
            self.comp_box = None

    def comp_accept(self, index=None):
        if self.comp_box is None:
            return
        if index is None:
            index = self.comp_box.selected()
        if index is None or index >= len(self._comp_rows):
            self.comp_close()
            return
        item = self._comp_rows[index]
        line, start = self._comp_anchor
        ta = self.text_area

        def do():
            ta.delete(f"{line}.{start}", "insert")
            if item.get("snippet"):
                indent = re.match(r"[ \t]*", ta.get("insert linestart", "insert")).group(0)
                body, offset = expand_snippet(item["insert"], indent, INDENT)
                at = ta.index("insert")
                ta.insert("insert", body)
                ta.mark_set("insert", f"{at}+{offset}c")
            else:
                ta.insert("insert", item["insert"])
        self.group(do)
        self.comp_close()
        self.cursor_moved()

    def on_up(self, event):
        if self.comp_box is not None:
            self._comp_move(-1)
            return "break"
        self.after_idle(self.cursor_moved)
        return None

    def on_down(self, event):
        if self.comp_box is not None:
            self._comp_move(1)
            return "break"
        self.after_idle(self.cursor_moved)
        return None

    def on_escape(self, event):
        if self.comp_box is not None:
            self.comp_close()
            return "break"
        return None

    # --- búsqueda ---------------------------------------------------------
    def find(self):
        self.find_bar.show(replace=False)

    def replace(self):
        self.find_bar.show(replace=True)

    def find_next(self):
        self.find_bar.step(1)

    def find_prev(self):
        self.find_bar.step(-1)


# ======================================================================
#  ÁRBOL DE CARPETAS (con iconos)
# ======================================================================
DUMMY = "|dummy"          # hijo falso para que las carpetas muestren la flechita


class FileTree(Frame):
    """Panel lateral con las carpetas/archivos. Carga cada carpeta al abrirla."""

    def __init__(self, master, icons, on_open, on_renamed=None):
        super().__init__(master, bg=UI["panel"])
        self.icons = icons
        self.on_open = on_open              # callback(path) al abrir un archivo
        self.on_renamed = on_renamed        # callback(old, new)
        self.root_path = None
        self.expanded = set()

        Label(self, text="FOLDERS", anchor="w", bg=UI["panel"], fg=UI["muted"],
              font=("Segoe UI", 8, "bold"), padx=10, pady=6).pack(fill="x")

        body = Frame(self, bg=UI["panel"])
        body.pack(fill="both", expand=True)
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(body, style="Folders.Treeview", show="tree", selectmode="browse")
        self.vbar = AutoScrollbar(body, orient="vertical", style="Dark.Vertical.TScrollbar",
                                  command=self.tree.yview)
        self._rename_entry = None                       # Entry flotante del rename inline
        self.tree.configure(yscrollcommand=self._on_yscroll)   # <- antes: self.vbar.set
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")

        self.tree.bind("<<TreeviewOpen>>", self._on_open_node)
        self.tree.bind("<<TreeviewClose>>", self._on_close_node)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Return>", self._on_return)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<F2>", lambda e: (self.rename(), "break")[1])
        self.tree.bind("<MouseWheel>", lambda e: self._cancel_rename(), add="+")

        self.menu = Menu(self, tearoff=0)
        self.menu.add_command(label="New File...", command=self.new_file)
        self.menu.add_command(label="New Folder...", command=self.new_folder)
        self.menu.add_separator()
        self.menu.add_command(label="Rename...", accelerator="F2", command=self.rename)
        self.menu.add_command(label="Delete", command=self.delete)
        self.menu.add_separator()
        self.menu.add_command(label="Show in Explorer", command=self.show_in_explorer)
        self.menu.add_command(label="Refresh", command=self.refresh)

    # ------------------------------------------------------------ carga
    def set_root(self, path):
        self._cancel_rename()
        self.root_path = os.path.abspath(path)
        self.expanded = {self.root_path}
        self.refresh()

    def refresh(self):
        if not self.root_path:
            return
        self._cancel_rename()
        self.tree.delete(*self.tree.get_children())
        self._insert_node("", self.root_path, True)
        self.tree.item(self.root_path, open=True, image=self.icons.get("folder_open"))
        self._fill(self.root_path)

    def _insert_node(self, parent, path, is_dir):
        name = os.path.basename(path) or path
        image = self.icons.for_path(path, is_dir)
        self.tree.insert(parent, "end", iid=path, text=" " + name, image=image, open=False)
        if is_dir:
            self.tree.insert(path, "end", iid=path + DUMMY)

    @staticmethod
    def _list(path):
        try:
            names = os.listdir(path)
        except OSError:
            return [], []
        dirs, files = [], []
        for n in names:
            if n in IGNORED:
                continue
            (dirs if os.path.isdir(os.path.join(path, n)) else files).append(n)
        return sorted(dirs, key=str.lower), sorted(files, key=str.lower)

    def _fill(self, iid):
        for c in self.tree.get_children(iid):
            self.tree.delete(c)
        dirs, files = self._list(iid)
        for n in dirs:
            self._insert_node(iid, os.path.join(iid, n), True)
        for n in files:
            self._insert_node(iid, os.path.join(iid, n), False)
        for n in dirs:                                   # reabrir las que estaban abiertas
            p = os.path.join(iid, n)
            if p in self.expanded:
                self.tree.item(p, open=True, image=self.icons.get("folder_open"))
                self._fill(p)

    # ----------------------------------------------------------- eventos
    def _on_open_node(self, event=None):
        self._cancel_rename()
        iid = self.tree.focus()
        if not iid or not os.path.isdir(iid):
            return
        self.expanded.add(iid)
        if any(c.endswith(DUMMY) for c in self.tree.get_children(iid)):
            self._fill(iid)
        self.tree.item(iid, image=self.icons.get("folder_open"))

    def _on_close_node(self, event=None):
        self._cancel_rename()
        iid = self.tree.focus()
        if iid:
            self.expanded.discard(iid)
            self.tree.item(iid, image=self.icons.get("folder"))

    def _open_item(self, iid):
        if iid and os.path.isfile(iid):
            self.on_open(iid)
            return "break"

    def _on_double_click(self, event):
        return self._open_item(self.tree.identify_row(event.y))

    def _on_return(self, event):
        return self._open_item(self.tree.focus())

    def _on_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
            self.tree.focus(iid)
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def reveal(self, path):
        path = os.path.abspath(path)
        if self.tree.exists(path):
            self.tree.selection_set(path)
            self.tree.see(path)

    # ---------------------------------------------------------- acciones
    def _selected(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _target_dir(self):
        sel = self._selected()
        if sel is None:
            return self.root_path
        return sel if os.path.isdir(sel) else os.path.dirname(sel)

    def new_file(self):
        folder = self._target_dir()
        name = simpledialog.askstring("New File", "Nombre del archivo:", parent=self)
        if not name:
            return
        path = os.path.join(folder, name)
        try:
            with open(path, "x", encoding="utf-8"):
                pass
        except OSError as ex:
            messagebox.showerror("Blinker Code", f"No se pudo crear el archivo:\n{ex}", parent=self)
            return
        self.expanded.add(folder)
        self.refresh()
        self.on_open(path)

    def new_folder(self):
        folder = self._target_dir()
        name = simpledialog.askstring("New Folder", "Nombre de la carpeta:", parent=self)
        if not name:
            return
        try:
            os.makedirs(os.path.join(folder, name))
        except OSError as ex:
            messagebox.showerror("Blinker Code", f"No se pudo crear la carpeta:\n{ex}", parent=self)
            return
        self.expanded.add(folder)
        self.refresh()

    # ------------------------------------------------- rename inline
    def _on_yscroll(self, *args):
        self._cancel_rename()                    # el entry flotante no sigue al scroll
        self.vbar.set(*args)

    def rename(self):
        """Renombra editando el nombre directamente en el árbol (como la barra de Find)."""
        old = self._selected()
        if not old or old == self.root_path:
            return
        self._cancel_rename()
        self.tree.see(old)
        self.tree.update_idletasks()
        self.after_idle(lambda: self._start_rename(old))

    def _start_rename(self, old):
        if not self.tree.exists(old):
            return
        bbox = self.tree.bbox(old, "#0")
        if not bbox:
            return
        x, y, w, h = bbox

        # el entry empieza después del icono para que se vea como editar el texto
        try:
            img = self.tree.item(old, "image")
            icon_w = int(self.tk.call("image", "width", img[0] if isinstance(img, tuple) else img))
        except (TclError, ValueError, IndexError):
            icon_w = 16
        x += icon_w + 6

        name = os.path.basename(old)
        entry = Entry(self.tree, bg=UI["editor"], fg="#ffffff", insertbackground="white",
                      relief="flat", highlightthickness=1, highlightbackground=UI["bg"],
                      highlightcolor=UI["accent"], font=("Segoe UI", 10))
        entry.insert(0, name)
        entry.place(x=x, y=y, width=max(80, self.tree.winfo_width() - x - 2), height=h)
        self._rename_entry = entry

        # selecciona solo el nombre sin la extensión (en archivos)
        stem = os.path.splitext(name)[0] if os.path.isfile(old) and os.path.splitext(name)[0] else name
        entry.select_range(0, len(stem))
        entry.icursor(len(stem))
        entry.focus_force()

        entry.bind("<Return>", lambda e: self._commit_rename(old, entry))
        entry.bind("<KP_Enter>", lambda e: self._commit_rename(old, entry))
        entry.bind("<Escape>", lambda e: (self._cancel_rename(), "break")[1])
        entry.bind("<FocusOut>", lambda e: self._cancel_rename())
        entry.bind("<Key>", lambda e: entry.config(highlightcolor=UI["accent"],
                                                   highlightbackground=UI["bg"]), add="+")

    def _cancel_rename(self):
        entry, self._rename_entry = self._rename_entry, None
        if entry is not None:
            try:
                entry.destroy()
            except TclError:
                pass
            try:
                self.tree.focus_set()
            except TclError:
                pass

    @staticmethod
    def _rename_error(entry):
        entry.config(highlightcolor=UI["error"], highlightbackground=UI["error"])

    def _commit_rename(self, old, entry):
        name = entry.get().strip()
        if not name or name == os.path.basename(old):
            self._cancel_rename()
            return "break"
        if "/" in name or "\\" in name or name in (".", ".."):
            self._rename_error(entry)
            return "break"
        new = os.path.join(os.path.dirname(old), name)
        # permitir cambiar solo mayúsculas/minúsculas en Windows
        if os.path.exists(new) and os.path.normcase(new) != os.path.normcase(old):
            self._rename_error(entry)                     # ya existe uno con ese nombre
            return "break"
        try:
            os.rename(old, new)
        except OSError:
            self._rename_error(entry)
            return "break"

        self._cancel_rename()
        self.expanded = {new + p[len(old):] if p == old or p.startswith(old + os.sep) else p
                         for p in self.expanded}
        self.refresh()
        self.reveal(new)
        if self.on_renamed:
            self.on_renamed(old, new)
        return "break"

    def delete(self):
        path = self._selected()
        if not path or path == self.root_path:
            return
        kind = "la carpeta" if os.path.isdir(path) else "el archivo"
        if not messagebox.askyesno("Delete", f"¿Eliminar {kind} «{os.path.basename(path)}»?\n"
                                             "Se borra de forma permanente.", parent=self):
            return
        try:
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
        except OSError as ex:
            messagebox.showerror("Blinker Code", f"No se pudo eliminar:\n{ex}", parent=self)
            return
        self.refresh()

    def show_in_explorer(self):
        path = self._selected() or self.root_path
        if not path:
            return
        try:
            if os.name == "nt":
                if os.path.isfile(path):
                    subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
                else:
                    os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path if os.path.isdir(path) else os.path.dirname(path)])
            else:
                subprocess.Popen(["xdg-open", path if os.path.isdir(path) else os.path.dirname(path)])
        except Exception:
            pass


# ======================================================================
#  PALETA (Ctrl+P = ir a archivo / Ctrl+Shift+P = comandos / Ctrl+G = línea)
# ======================================================================
def fuzzy(query, text):
    """Puntaje de coincidencia 'difusa' (letras en orden). None = no coincide; menor = mejor."""
    q, t = query.lower(), text.lower()
    pos, score = -1, 0
    for ch in q:
        nxt = t.find(ch, pos + 1)
        if nxt == -1:
            return None
        score += nxt - pos - 1
        pos = nxt
    return score + len(t) * 0.01


class Palette(Toplevel):
    """Ventanita con una caja de texto y una lista filtrada.

    get_items(texto) -> [(etiqueta, dato), ...]      on_pick(dato) al elegir uno
    """

    def __init__(self, app, get_items, on_pick, initial=""):
        super().__init__(app)
        self.app, self.get_items, self.on_pick = app, get_items, on_pick
        self.overrideredirect(True)
        self.configure(bg=UI["accent"])
        w = 580
        x = app.winfo_rootx() + (app.winfo_width() - w) // 2
        y = app.winfo_rooty() + 70
        self.geometry(f"{w}x330+{x}+{y}")

        inner = Frame(self, bg=UI["bg"])
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        self.var = StringVar(value=initial)
        self.entry = Entry(inner, textvariable=self.var, font=("Segoe UI", 12), bg=UI["panel"],
                           fg="#ffffff", insertbackground="white", relief="flat", highlightthickness=0)
        self.entry.pack(fill="x", padx=4, pady=(4, 0), ipady=6)
        self.listbox = Listbox(inner, bg=UI["editor"], fg=UI["fg"], selectbackground=UI["select"],
                               selectforeground="#ffffff", relief="flat", highlightthickness=0,
                               activestyle="none", font=("Segoe UI", 10), borderwidth=0)
        self.listbox.pack(fill="both", expand=True, padx=4, pady=4)

        self.items = []
        self.var.trace_add("write", lambda *a: self.refresh())
        self.entry.bind("<Down>", lambda e: self.move(1))
        self.entry.bind("<Up>", lambda e: self.move(-1))
        self.entry.bind("<Return>", self.pick)
        self.entry.bind("<Escape>", lambda e: self.close())
        self.listbox.bind("<ButtonRelease-1>", self.pick)
        self.bind("<FocusOut>", lambda e: self.after(120, self._check_focus))

        self.refresh()
        self.entry.focus_force()
        self.entry.icursor("end")

    def _check_focus(self):
        try:
            f = self.focus_get()
        except Exception:
            f = None
        if f is None or f.winfo_toplevel() is not self:
            self.close()

    def refresh(self):
        self.items = self.get_items(self.var.get())[:200]
        self.listbox.delete(0, "end")
        for label, _ in self.items:
            self.listbox.insert("end", "  " + label)
        if self.items:
            self.listbox.selection_set(0)

    def move(self, d):
        if not self.items:
            return "break"
        cur = self.listbox.curselection()
        i = max(0, min(len(self.items) - 1, (cur[0] if cur else 0) + d))
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(i)
        self.listbox.see(i)
        return "break"

    def pick(self, event=None):
        cur = self.listbox.curselection()
        if not cur:
            return "break"
        payload = self.items[cur[0]][1]
        self.close()
        if payload is not None:
            self.on_pick(payload)
        return "break"

    def close(self):
        if self.winfo_exists():
            self.destroy()
        self.app.focus_editor()


# ======================================================================
#  VENTANA PRINCIPAL
# ======================================================================
def slicing_text(text, max_long=20):
    if len(text) > max_long:
        return text[:max_long] + '...'
    return text


class main(Tk):
    def __init__(self):
        super().__init__()
        self.config_data = self.load_config()
        self.themes = ThemeManager(UI, THEME_COLORS, THEMES_DIR, PACKAGES_DIR)
        self._startup_theme()                   # antes de crear cualquier widget
        self.title("Blinker Code")
        self.geometry("1100x700")
        self.config(bg=UI["bg"])
        try:                                    # primero el tamaño, DESPUÉS maximizar
            self.state("zoomed")
        except TclError:
            try:
                self.attributes("-zoomed", True)
            except TclError:
                pass

        apply_dark_style(self)                  # <- estilo oscuro de ui.py (ttk)
        self.icons = IconSet(self)

        self.idx = None

        self.font_size = 11
        self.word_wrap = False
        self.sidebar_visible = False
        self.terminal_visible = True
        self.code_editor_current = None
        self.palette = None
        self.packages = PackageManager(PACKAGES_DIR)
        self.lsp_enabled = self.config_data.get("lsp_enabled", True)
        self.suggest_enabled = self.config_data.get("suggest_enabled", True)
        self.lsp = LSPManager(self.lsp_diagnostics, self.lsp_status,
                              root_getter=lambda: self.sidebar.root_path,
                              overrides=dict(self.config_data.get("lsp_servers", {})))
        self.package_apis = {}                  # nombre -> PackageAPI de cada paquete cargado
        self.libs = LibraryManager(PACKAGES_DIR, LIBS_DIR)
        self._lib_lsp_langs = set()             # lenguajes con servidor LSP aportado por un paquete

        self.recovery = RecoveryManager(RECOVERY_DIR)
        self.closed_stack = []                  # pestañas cerradas (Ctrl+Shift+T)

        self.frontend()
        self.protocol("WM_DELETE_WINDOW", self.exit_app)
        self.reload_libs()
        self.load_packages()
        if not self.restore_session():
            self.new_file()
        self.after(50, self._lsp_poll)
        self.after(3000, self._recovery_tick)

    # ------------------------------------------------------ configuración
    def load_config(self):
        data = {"recent_files": [], "recent_folders": []}
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data.update(json.load(f))
        except (OSError, ValueError):
            pass
        return data

    def save_config(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, indent=2)
        except OSError:
            pass

    def add_recent(self, path, folder=False):
        key = "recent_folders" if folder else "recent_files"
        items = [p for p in self.config_data.get(key, []) if p != path]
        self.config_data[key] = ([path] + items)[:10]
        self.save_config()

    # ------------------------------------------------------------- UI
    def frontend(self):
        # Barra de estado: se empaqueta primero abajo para que nunca quede tapada
        self.bar_status = Frame(self, bg=UI["panel"])
        self.bar_status.pack(side="bottom", fill="x")

        def status_label(**kw):
            return Label(self.bar_status, font=("Arial", 9), fg=UI["muted"], bg=UI["panel"], **kw)

        self.lin_col_var = StringVar(self, value="Line 1, Column 1")
        self.line_column = status_label(textvariable=self.lin_col_var)
        self.line_column.pack(side="left", padx=15, pady=2)

        self.diag_lb = status_label(text="", cursor="hand2")        # ✖ errores  ⚠ avisos (clic = lista)
        self.diag_lb.pack(side="left", padx=10)
        self.diag_lb.bind("<Button-1>", lambda e: self.show_problems())
        self.lsp_lb = status_label(text="")                         # estado del servidor LSP
        self.lsp_lb.pack(side="left", padx=10)

        self.tab_size_lb = status_label(text="Tab Size: 4")
        self.tab_size_lb.pack(side="right", padx=5)

        self.language_lb = status_label(text="Python", cursor="hand2")
        self.language_lb.pack(side="right", padx=25, before=self.tab_size_lb)
        self.language_lb.bind("<Button-1>", self.show_language_menu)

        # PanedWindow VERTICAL:  arriba (folders + editor)  |  abajo (output)
        self.main_paned = PanedWindow(self, orient="vertical", sashwidth=5, bg=UI["bg"], bd=0)
        self.main_paned.pack(expand=1, fill="both")

        # PanedWindow HORIZONTAL (arriba):  árbol de carpetas  |  editor
        self.win_paned = PanedWindow(self.main_paned, orient="horizontal", sashwidth=5,
                                     bg=UI["bg"], bd=0)
        self.main_paned.add(self.win_paned, minsize=100, stretch="always")

        self.sidebar = FileTree(self.win_paned, self.icons, on_open=self.open_path,
                                on_renamed=self.path_renamed)      # se muestra al abrir una carpeta

        self.notebook = ttk.Notebook(self.win_paned, style="TNotebook")
        self.win_paned.add(self.notebook, stretch="always")
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)
        self.notebook.bind("<Button-2>", self.on_tab_middle_click)   # clic central = cerrar
        self.notebook.bind("<Button-3>", self.show_tab_menu)   # menu click derecho
        self.notebook.bind("<Double-Button-1>", lambda : self.new_file)   # clic central = cerrar


        # Output / terminal (abajo)
        self.terminal = Terminal(self.main_paned)
        self.terminal.on_finish = self._terminal_finished
        self.main_paned.add(self.terminal.frame, height=160, minsize=40, stretch="never")

        self.gestor_menu()
        self.main_paned.forget(self.terminal.frame)
        self.terminal_visible = False

    # ------------------------------------------------------- menús y atajos
    def gestor_menu(self):
        do = lambda name, *a: (lambda: self.editor_do(name, *a))

        self.menu_bar = Menu(self)

        # --- File
        self.menu_file = Menu(self.menu_bar, tearoff=0)
        self.menu_recent = Menu(self.menu_file, tearoff=0, postcommand=self.fill_recent)
        m = self.menu_file
        m.add_command(label="New File", accelerator="Ctrl+N", command=self.new_file)
        m.add_command(label="Open File...", accelerator="Ctrl+O", command=self.open_file)
        m.add_command(label="Open Folder...", accelerator="Ctrl+Shift+O", command=self.open_folder)
        m.add_cascade(label="Open Recent", menu=self.menu_recent)
        m.add_separator()
        m.add_command(label="Save File", accelerator="Ctrl+S", command=self.save_file)
        m.add_command(label="Save As...", accelerator="Ctrl+Shift+S", command=self.save_file_as)
        m.add_command(label="Save All", command=self.save_all)
        m.add_separator()
        m.add_command(label="Close Tab", accelerator="Ctrl+W", command=self.close_tab)
        m.add_command(label="Reopen Closed Tab", accelerator="Ctrl+Shift+T", command=self.reopen_closed)
        m.add_command(label="Exit", command=self.exit_app)

        # --- Edit
        self.menu_edit = Menu(self.menu_bar, tearoff=0)
        m = self.menu_edit
        m.add_command(label="Undo", accelerator="Ctrl+Z", command=self.undo)
        m.add_command(label="Redo", accelerator="Ctrl+Y", command=self.redo)
        m.add_separator()
        m.add_command(label="Cut", accelerator="Ctrl+X", command=lambda: self.clip("Cut"))
        m.add_command(label="Copy", accelerator="Ctrl+C", command=lambda: self.clip("Copy"))
        m.add_command(label="Paste", accelerator="Ctrl+V", command=lambda: self.clip("Paste"))
        m.add_command(label="Select All", accelerator="Ctrl+A", command=self.select_all)
        m.add_separator()
        m.add_command(label="Find...", accelerator="Ctrl+F", command=do("find"))
        m.add_command(label="Replace...", accelerator="Ctrl+H", command=do("replace"))
        m.add_command(label="Find Next", accelerator="F3", command=do("find_next"))
        m.add_command(label="Find Previous", accelerator="Shift+F3", command=do("find_prev"))
        m.add_separator()
        m.add_command(label="Go to Line...", accelerator="Ctrl+G", command=self.goto_line)
        m.add_command(label="Go to Anything...", accelerator="Ctrl+P", command=self.goto_anything)
        m.add_command(label="Command Palette...", accelerator="Ctrl+Shift+P", command=self.command_palette)
        m.add_separator()

        self.menu_lines = Menu(m, tearoff=0)
        l = self.menu_lines
        l.add_command(label="Duplicate Line", accelerator="Ctrl+Shift+D", command=do("duplicate_line"))
        l.add_command(label="Delete Line", accelerator="Ctrl+Shift+K", command=do("delete_line"))
        l.add_command(label="Move Line Up", accelerator="Ctrl+Shift+Up", command=do("move_line_up"))
        l.add_command(label="Move Line Down", accelerator="Ctrl+Shift+Down", command=do("move_line_down"))
        l.add_separator()
        l.add_command(label="Indent", accelerator="Tab", command=do("indent"))
        l.add_command(label="Unindent", accelerator="Shift+Tab", command=do("unindent"))
        l.add_command(label="Toggle Comment", accelerator="Ctrl+/", command=do("toggle_comment"))
        l.add_command(label="Select Next Occurrence", accelerator="Ctrl+D", command=do("select_next"))
        m.add_cascade(label="Lines", menu=self.menu_lines)

        # --- View
        self.menu_view = Menu(self.menu_bar, tearoff=0)
        m = self.menu_view
        m.add_command(label="Toggle Sidebar", accelerator="Ctrl+Shift+E", command=self.toggle_sidebar)
        m.add_command(label="Toggle Output Panel", accelerator="Ctrl+J", command=self.toggle_terminal)
        m.add_command(label="Toggle Word Wrap", accelerator="Alt+Z", command=self.toggle_wrap)
        m.add_separator()
        m.add_command(label="Zoom In", accelerator="Ctrl++", command=lambda: self.zoom(1))
        m.add_command(label="Zoom Out", accelerator="Ctrl+-", command=lambda: self.zoom(-1))
        m.add_command(label="Reset Zoom", accelerator="Ctrl+0", command=lambda: self.zoom(0))
        m.add_separator()
        m.add_command(label="Select Theme...", command=self.select_theme)
        m.add_command(label="Install Theme...", command=self.install_package)
        m.add_command(label="Export Current Theme...", command=self.export_theme)
        m.add_command(label="Open Themes Folder", command=self.open_themes_folder)

        # --- Tools
        self.menu_tools = Menu(self.menu_bar, tearoff=0)
        m = self.menu_tools
        m.add_command(label="Build", accelerator="F5 / Ctrl+B", command=self.build)
        m.add_command(label="Stop Build", accelerator="Shift+F5", command=self.stop_build)
        m.add_separator()
        m.add_command(label="Clear Output", command=self.terminal.clear)
        m.add_separator()
        m.add_command(label="Trigger Completion", accelerator="Ctrl+Space", command=do("request_completion", None, True))
        m.add_command(label="Show Problems", accelerator="Ctrl+Shift+M", command=self.show_problems)
        m.add_command(label="Toggle Keyword Suggestions", command=self.toggle_suggest)
        m.add_command(label="Toggle Language Server (LSP)", command=self.toggle_lsp)
        m.add_command(label="Restart Language Servers", command=self.restart_lsp)
        m.add_command(label="Language Server Status", command=self.lsp_servers)
        m.add_command(label="Install Library...", command=self.install_library)
        m.add_command(label="Reload Libraries", command=self.reload_libs)
        m.add_command(label="Show Loaded Libraries", command=self.show_libs)

        self.menu_bar.add_cascade(label="File", menu=self.menu_file)
        self.menu_bar.add_cascade(label="Edit", menu=self.menu_edit)
        self.menu_bar.add_cascade(label="View", menu=self.menu_view)
        self.menu_packages = Menu(self.menu_bar, tearoff=0)
        m = self.menu_packages
        m.add_command(label="Install Package...", command=self.install_package)
        m.add_command(label="Upgrade Package...", command=self.upgrade_package)
        m.add_command(label="Remove Package...", command=self.remove_package)
        m.add_separator()
        m.add_command(label="List Packages", command=self.list_packages)
        m.add_command(label="Open Packages Folder", command=self.open_packages_folder)

        self.menu_bar.add_cascade(label="Tools", menu=self.menu_tools)
        self.menu_bar.add_cascade(label="Packages", menu=self.menu_packages)
        self.config(menu=self.menu_bar)

        # --- menú contextual del editor
        self.context_menu = Menu(self, tearoff=0)
        c = self.context_menu
        c.add_command(label="Undo", command=self.undo)
        c.add_command(label="Redo", command=self.redo)
        c.add_separator()
        c.add_command(label="Cut", command=lambda: self.clip("Cut"))
        c.add_command(label="Copy", command=lambda: self.clip("Copy"))
        c.add_command(label="Paste", command=lambda: self.clip("Paste"))
        c.add_separator()
        c.add_command(label="Select All", command=self.select_all)
        c.add_command(label="Toggle Comment", command=do("toggle_comment"))

        # --- menú contextual del notebook
        self.tab_menu = Menu(self, tearoff=0)
        c = self.tab_menu
        c.add_command(label="Close Tab", command=self.fast_close_tab)
        c.add_separator()
        c.add_command(label="New File", command=self.new_file)

        # --- atajos de teclado
        self.shortcuts = [
            ("<Control-n>", self.new_file), ("<Control-o>", self.open_file),
            ("<Control-Shift-O>", self.open_folder),
            ("<Control-s>", self.save_file), ("<Control-Shift-S>", self.save_file_as),
            ("<Control-w>", self.close_tab),
            ("<Control-Shift-T>", self.reopen_closed),
            ("<Control-z>", self.undo), ("<Control-y>", self.redo), ("<Control-Shift-Z>", self.redo),
            ("<Control-a>", self.select_all),
            ("<Control-f>", do("find")), ("<Control-h>", do("replace")),
            ("<F3>", do("find_next")), ("<Shift-F3>", do("find_prev")),
            ("<Control-g>", self.goto_line), ("<Control-p>", self.goto_anything),
            ("<Control-Shift-P>", self.command_palette),
            ("<Control-slash>", do("toggle_comment")),
            ("<Control-Shift-D>", do("duplicate_line")), ("<Control-Shift-K>", do("delete_line")),
            ("<Control-Shift-Up>", do("move_line_up")), ("<Control-Shift-Down>", do("move_line_down")),
            ("<Control-d>", do("select_next")),
            ("<Control-Shift-E>", self.toggle_sidebar),
            ("<Control-j>", self.toggle_terminal), ("<Control-grave>", self.toggle_terminal),
            ("<Alt-z>", self.toggle_wrap),
            ("<Control-equal>", lambda: self.zoom(1)), ("<Control-plus>", lambda: self.zoom(1)),
            ("<Control-minus>", lambda: self.zoom(-1)), ("<Control-0>", lambda: self.zoom(0)),
            ("<F5>", self.build), ("<Control-b>", self.build), ("<Shift-F5>", self.stop_build),
            ("<Control-Shift-M>", self.show_problems),
        ]
        # En una caja de texto (Entry) estos atajos los maneja la propia caja
        self.entry_pass = {"<Control-a>", "<Control-z>", "<Control-y>", "<Control-Shift-Z>",
                           "<Control-d>", "<Control-slash>"}
        for seq, func in self.shortcuts:
            self.bind(seq, self._handler(func, seq, root=True))

        self.commands = self.build_commands()

    def add_shortcut(self, seq, func):
        """Registra un atajo nuevo en caliente (lo usan los paquetes)."""
        self.shortcuts.append((seq, func))
        self.bind(seq, self._handler(func, seq, root=True))
        for ed in self.editors():
            ed.text_area.bind(seq, self._handler(func, seq))

    def _handler(self, func, seq, root=False):
        def handler(event=None):
            if root and seq in self.entry_pass and isinstance(self.focused(), (Entry, Terminal)):
                return None
            func()
            return "break"
        return handler

    def attach_shortcuts(self, widget):
        """Los atajos también se enlazan al Text para que ganen a los de Tk (Ctrl+O, Ctrl+N...)."""
        for seq, func in self.shortcuts:
            widget.bind(seq, self._handler(func, seq))
        widget.bind("<Control-MouseWheel>", lambda e: (self.zoom(1 if e.delta > 0 else -1), "break")[1])
        try:
            widget.bind("<Control-Button-4>", lambda e: (self.zoom(1), "break")[1])
            widget.bind("<Control-Button-5>", lambda e: (self.zoom(-1), "break")[1])
        except TclError:
            pass

    def focused(self):
        try:
            return self.focus_get()
        except Exception:
            return None

    def focus_editor(self):
        if self.code_editor_current is not None:
            self.code_editor_current.text_area.focus_set()

    def editors(self):
        return [self.nametowidget(t) for t in self.notebook.tabs()]

    def editor_do(self, method, *args):
        ed = self.code_editor_current
        if ed is not None:
            getattr(ed, method)(*args)

    # --------------------------------------------------- deshacer / rehacer
    def undo(self):
        if isinstance(self.focused(), (Entry, Terminal)):
            return
        self.editor_do("undo")

    def redo(self):
        if isinstance(self.focused(), (Entry, Terminal)):
            return
        self.editor_do("redo")

    def clip(self, name):
        if self.code_editor_current is not None:
            self.code_editor_current.text_area.event_generate(f"<<{name}>>")

    def select_all(self):
        self.editor_do("select_all")

    # ------------------------------------------------------------ pestañas
    def add_editor(self, editor, title="Untitled", icon_name="Untitled"):
        editor.on_dirty = self.update_tab
        editor.on_cursor = self.status
        editor.on_diag = self.update_diag_status
        editor.lsp = self.lsp if self.lsp_enabled else None
        editor.suggest_on = self.suggest_enabled
        editor.libs = self.libs
        editor.set_wrap(self.word_wrap)
        self.attach_shortcuts(editor.text_area)
        editor.text_area.bind("<Button-3>", self.show_context_menu)

        self.notebook.add(editor, text=title, image=self.icons.for_path(icon_name), compound="left")
        self.notebook.select(editor)
        self.code_editor_current = editor
        editor.text_area.focus_set()
        self.update_tab(editor)
        self.status()

    def new_file(self):
        editor = CodeEditor(self.notebook, language="python", font_size=self.font_size)
        self.add_editor(editor)
        editor.highlight()
        return editor

    def update_tab(self, editor):
        name = os.path.basename(editor.file_path) if editor.file_path else "Untitled"
        text = slicing_text(name) + (" ●" if editor.dirty else "")
        try:
            self.notebook.tab(editor, text=text, image=self.icons.for_path(name))
        except TclError:
            return
        if editor is self.code_editor_current:
            self.update_title()

    def update_title(self):
        ed = self.code_editor_current
        if ed is None:
            self.title("Blinker Code")
            return
        name = os.path.basename(ed.file_path) if ed.file_path else "Untitled"
        self.title(f"{'● ' if ed.dirty else ''}{name} - Blinker Code")

    def on_tab_changed(self, event=None):
        try:
            tab_id = self.notebook.select()
            if tab_id:
                ed = self.nametowidget(tab_id)
                self.code_editor_current = ed
                self.language_lb.config(text=LANG_NAMES.get(resolve_language(ed.language), "Text"))
                self.after_idle(ed.line_numbers.redraw)
                ed.text_area.focus_set()
                self.update_title()
                self.status()
                self.update_diag_status()
                if ed.file_path and self.sidebar.root_path:
                    self.sidebar.reveal(ed.file_path)
            else:
                self.code_editor_current = None
                self.language_lb.config(text="Text")
                self.lin_col_var.set("")
                self.update_title()
                self.update_diag_status()
        except TclError:
            pass

    def on_tab_middle_click(self, event):
        try:
            idx = self.notebook.index(f"@{event.x},{event.y}")
        except TclError:
            return
        self.close_tab(self.nametowidget(self.notebook.tabs()[idx]))

    def fast_close_tab(self):
        self.close_tab(self.nametowidget(self.notebook.tabs()[self.idx]))

    def close_tab(self, editor=None):
        """Cierra una pestaña (pregunta si hay cambios). Devuelve False si se canceló."""
        if not isinstance(editor, CodeEditor):
            editor = self.code_editor_current
        if editor is None:
            return True
        if editor.dirty:
            name = os.path.basename(editor.file_path) if editor.file_path else "Untitled"
            ans = messagebox.askyesnocancel("Blinker Code",
                                            f"¿Guardar los cambios en «{name}»?", parent=self)
            if ans is None:
                return False
            if ans and not self.save_editor(editor):
                return False
        if editor.file_path:
            self.closed_stack.append(os.path.abspath(editor.file_path))
        self.recovery.delete_backup(editor.rid)
        editor.lsp_close()
        self.notebook.forget(editor)
        editor.destroy()
        if not self.notebook.tabs():
            self.code_editor_current = None
            self.on_tab_changed()
        return True

    def exit_app(self):
        # Hot exit: no se pregunta nada; lo no guardado queda respaldado y se restaura al abrir
        self.recovery_snapshot()
        self.recovery.cleanup({ed.rid for ed in self.editors() if ed.dirty})
        self.save_config()
        self.terminal.kill()
        self.lsp.stop_all()
        self.destroy()

    # ------------------------------------------------- abrir / guardar
    def open_file(self):
        paths = filedialog.askopenfilenames()
        for p in paths:
            self.open_path(p)

    def open_path(self, path):
        path = os.path.abspath(path)
        for ed in self.editors():
            if ed.file_path and os.path.abspath(ed.file_path) == path:
                self.notebook.select(ed)
                return ed
        if not os.path.isfile(path):
            messagebox.showerror("Blinker Code", f"No existe el archivo:\n{path}", parent=self)
            return None
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as ex:
            messagebox.showerror("Blinker Code", f"No se pudo abrir:\n{ex}", parent=self)
            return None
        if b"\x00" in data[:8192]:
            messagebox.showwarning("Blinker Code", "Parece un archivo binario; no se abrirá.", parent=self)
            return None
        text = data.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")

        ext = os.path.splitext(path)[1].lower()
        lang = EXT_LANG.get(ext, "text")
        editor = CodeEditor(self.notebook, language=lang, file_path=path, font_size=self.font_size)
        editor.load_text(text)
        self._stamp(editor)
        self.add_editor(editor, slicing_text(os.path.basename(path)), os.path.basename(path))
        editor.lsp_open()                                # errores y autocompletado

        self.terminal.set_cwd(os.path.dirname(path))     # el output ejecuta en la carpeta del archivo
        self.add_recent(path)
        self.update_idletasks()
        return editor

    def open_folder(self, path=None):
        if not isinstance(path, str):
            path = filedialog.askdirectory(title="Open Folder")
        if not path:
            return
        self.sidebar.set_root(path)
        self.show_sidebar()
        self.terminal.set_cwd(path)
        self.add_recent(os.path.abspath(path), folder=True)

    def fill_recent(self):
        m = self.menu_recent
        m.delete(0, "end")
        files = self.config_data.get("recent_files", [])
        folders = self.config_data.get("recent_folders", [])
        for p in files:
            m.add_command(label=p, command=lambda p=p: self.open_path(p))
        if files and folders:
            m.add_separator()
        for p in folders:
            m.add_command(label=p + os.sep, command=lambda p=p: self.open_folder(p))
        if files or folders:
            m.add_separator()
            m.add_command(label="Clear Recent", command=self.clear_recent)
        else:
            m.add_command(label="(vacío)", state="disabled")

    def clear_recent(self):
        self.config_data["recent_files"] = []
        self.config_data["recent_folders"] = []
        self.save_config()

    def path_renamed(self, old, new):
        """El árbol renombró un archivo/carpeta: actualiza las pestañas abiertas."""
        for ed in self.editors():
            if not ed.file_path:
                continue
            fp = os.path.abspath(ed.file_path)
            if fp == old or fp.startswith(old + os.sep):
                ed.file_path = new + fp[len(old):]
                lang = EXT_LANG.get(os.path.splitext(ed.file_path)[1].lower())
                if lang:
                    ed.set_language(lang)
                self.update_tab(ed)
        self.on_tab_changed()

    # ------------------------------------------------------------ guardar
    def _write_file(self, editor, path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(editor.text_area.get("1.0", "end-1c"))
        except OSError as ex:
            self.terminal.write(f"No se pudo guardar: {ex}\n", "error")
            return False
        return True

    def save_editor(self, editor, force_as=False):
        """Guarda un editor. Si es Untitled (o force_as) pide el nombre. True si se guardó."""
        path = editor.file_path
        if path is None or force_as:
            self.notebook.select(editor)
            path = filedialog.asksaveasfilename(initialdir=self.terminal.cwd)
            if not path:
                return False
        if not self._write_file(editor, path):
            return False

        editor.file_path = path
        lang = EXT_LANG.get(os.path.splitext(path)[1].lower())
        if lang:                                   # el lenguaje sale de la extensión
            editor.set_language(lang)
        editor.mark_saved()
        self._stamp(editor)
        self.recovery.delete_backup(editor.rid)
        editor.backed_rev = editor.rev
        if editor.lsp is not None:
            if editor.lsp_opened and editor.lsp_path == path:
                editor.lsp_sync()
                editor.lsp.save(path)
            else:
                editor.lsp_open()                        # archivo nuevo / cambió de nombre
        self.update_tab(editor)
        if editor is self.code_editor_current:
            self.language_lb.config(text=LANG_NAMES.get(resolve_language(editor.language), "Text"))
        self.terminal.set_cwd(os.path.dirname(path))
        self.add_recent(path)
        return True

    def save_file(self):
        editor = self.code_editor_current
        return False if editor is None else self.save_editor(editor)

    def save_file_as(self):
        editor = self.code_editor_current
        return False if editor is None else self.save_editor(editor, force_as=True)

    def save_all(self):
        current = self.code_editor_current
        for ed in self.editors():
            if ed.dirty and not self.save_editor(ed):
                return False
        if current is not None:
            self.notebook.select(current)
        return True

    # -------------------------------------------------------- Tools > Build
    def show_terminal(self):
        if not self.terminal_visible:
            self.main_paned.add(self.terminal.frame, height=160, minsize=40, stretch="never")
            self.terminal_visible = True

    def build(self, event=None):
        """Guarda el archivo actual, identifica su lenguaje y lo ejecuta en el output."""
        editor = self.code_editor_current
        self.show_terminal()
        if editor is None:
            self.terminal.write("Build: no hay ningún archivo abierto.\n", "error")
            return "break"
        if self.terminal.running:
            self.terminal.write("Ya hay un build en ejecución (Tools > Stop Build).\n", "info")
            return "break"
        if not self.save_file():                   # guarda los cambios (o pide nombre si es Untitled)
            return "break"

        path = editor.file_path
        ext = os.path.splitext(path)[1].lower()
        lang = EXT_LANG.get(ext) or resolve_language(editor.language)
        lang_name = LANG_NAMES.get(lang, lang)

        command = get_build_command(path, lang)
        self.terminal.clear()
        if command is None:
            self.terminal.write(f"No hay build para {lang_name} ({ext or 'sin extensión'}).\n"
                                "Agrégalo en BUILD_SYSTEMS (build.py).\n", "error")
            return "break"

        self.terminal.set_cwd(os.path.dirname(path))
        self.terminal.write(f"[Build] {os.path.basename(path)}  ({lang_name})\n", "info")
        self.terminal.write(f"> {command}\n\n", "info")
        self.terminal.run(command)
        return "break"

    def stop_build(self, event=None):
        self.terminal.kill()
        return "break"

    # ------------------------------------------------------------- vista
    def show_sidebar(self):
        if not self.sidebar_visible:
            self.win_paned.add(self.sidebar, width=240, minsize=120, before=self.notebook)
            self.sidebar_visible = True

    def toggle_sidebar(self):
        if self.sidebar_visible:
            self.win_paned.forget(self.sidebar)
            self.sidebar_visible = False
        elif self.sidebar.root_path:
            self.show_sidebar()
        else:
            self.open_folder()

    def toggle_terminal(self):
        if self.terminal_visible:
            self.main_paned.forget(self.terminal.frame)
            self.terminal_visible = False
        else:
            self.show_terminal()

    def toggle_wrap(self):
        self.word_wrap = not self.word_wrap
        for ed in self.editors():
            ed.set_wrap(self.word_wrap)

    def zoom(self, delta):
        self.font_size = 11 if delta == 0 else max(6, min(40, self.font_size + delta))
        for ed in self.editors():
            ed.set_font_size(self.font_size)

    def show_context_menu(self, event):
        if self.code_editor_current:
            try:
                self.context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.context_menu.grab_release()
        return "break"

    def show_tab_menu(self, event):
        if self.notebook:
            try:
                self.idx = self.notebook.index(f"@{event.x},{event.y}")
                self.tab_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.tab_menu.grab_release()
        return "break"
        # self.close_tab(self.nametowidget(self.notebook.tabs()[idx]))

    # ------------------------------------------------------------- estado
    def status(self, editor=None):
        ed = self.code_editor_current
        if ed is None or (editor is not None and editor is not ed):
            return
        ta = ed.text_area
        line, col = ta.index("insert").split(".")
        text = f"Line {line}, Column {int(col) + 1}"
        if ta.tag_ranges("sel"):
            n = len(ta.get("sel.first", "sel.last"))
            text += f";  {n} characters selected"
        self.lin_col_var.set(text)

    def show_language_menu(self, event):
        if self.code_editor_current is None:
            return
        menu = Menu(self, tearoff=0)
        for lang, name in sorted(LANG_NAMES.items(), key=lambda kv: kv[1].lower()):
            menu.add_command(label=name, command=lambda l=lang: self.set_language(l))
        try:
            menu.tk_popup(event.x_root, event.y_root - 10)
        finally:
            menu.grab_release()

    def set_language(self, lang):
        ed = self.code_editor_current
        if ed is None:
            return
        ed.set_language(lang)
        self.language_lb.config(text=LANG_NAMES.get(resolve_language(lang), "Text"))

    # ------------------------------------------------------------- temas
    def _startup_theme(self):
        """Aplica el tema guardado antes de crear la interfaz (sin recolorear nada)."""
        name = self.config_data.get("theme", "Default")
        if name != "Default":
            try:
                self.themes.apply(name)
            except ThemeError:
                self.config_data["theme"] = "Default"
        sync_sev_colors()

    def set_theme(self, name, save=True):
        """Cambia de tema en caliente: actualiza UI/THEME_COLORS y recolorea lo ya creado."""
        try:
            cmap = self.themes.apply(name)
        except ThemeError as ex:
            self.pkg_log(f"[Theme] {ex}", "error")
            return
        sync_sev_colors()
        for w in walk_widgets(self):                      # widgets tk: por color antiguo -> nuevo
            for opt in COLOR_OPTS:
                try:
                    new = cmap.get(str(w.cget(opt)).lower())
                except TclError:
                    continue
                if new:
                    try:
                        w.configure(**{opt: new})
                    except TclError:
                        pass
        try:
            apply_dark_style(self)                        # estilos ttk (pestañas, scrollbars, árbol)
        except Exception:
            pass
        self.terminal.tag_configure("error", foreground=UI["error"])
        self.terminal.tag_configure("info", foreground=THEME_COLORS["Comment"])
        for ed in self.editors():
            ed.comp_close()
            ed.setup_tags()
            ed.highlight()
            ed.line_numbers.redraw()
            ed.cursor_moved()
        self.update_diag_status()
        if save:
            self.config_data["theme"] = name
            self.save_config()

    def select_theme(self):
        avail = self.themes.available()

        def items(q):
            rows = []
            for name, info in avail.items():
                label = f"{name}    ({info['source']})" + ("    ✓" if name == self.themes.current else "")
                if not q or fuzzy(q, name) is not None:
                    rows.append((label, name))
            return rows
        self.open_palette(items, self.set_theme)

    def export_theme(self):
        name = simpledialog.askstring("Export Theme", "Nombre del tema nuevo:", parent=self)
        if not name or not name.strip():
            return
        path = self.themes.export_current(name.strip())
        self.pkg_log(f"[Theme] Guardado en {path}. Edita los colores y elígelo en View > Select Theme.")
        self.open_path(path)

    def open_themes_folder(self):
        os.makedirs(THEMES_DIR, exist_ok=True)
        self.open_folder(THEMES_DIR)

    # --------------------------------------------------------- librerías
    def reload_libs(self):
        """Relee las librerías de autocompletado y los servidores LSP que traen los paquetes."""
        self.libs.reload()
        for lang in self._lib_lsp_langs:                  # quita los de paquetes ya desinstalados
            self.lsp.overrides.pop(lang, None)
        self._lib_lsp_langs = set()
        for srv in self.libs.lsp_servers():
            self.lsp.overrides[srv["language"]] = srv["command"]
            self._lib_lsp_langs.add(srv["language"])
        for err in self.libs.errors:
            self.pkg_log(f"[Libs] {err}", "error")
        for ed in self.editors():                         # los editores abiertos usan lo nuevo
            ed.libs = self.libs
            if ed.lsp is not None and ed.file_path and not ed.lsp_opened:
                ed.lsp_open()

    def install_library(self):
        """Paleta: libs predeterminadas, o escribe usuario/repo/ruta/lib.json (o link de GitHub).
        Si escribes solo usuario/repo se instala como paquete (si trae "libraries")."""
        def items(q):
            q = q.strip()
            out = []
            if q and is_library_source(q):
                out.append((f"Instalar librería desde GitHub:  {q}", q))
            else:
                try:
                    owner, repo, ref = parse_source(q) if q else (None, None, None)
                    if owner:
                        src = f"{owner}/{repo}" + (f"@{ref}" if ref else "")
                        out.append((f"Instalar como paquete (si trae libraries):  {src}", src))
                except PackageError:
                    pass
            rows = [(f"{src}    (predeterminada)    {desc}", src) for src, desc in DEFAULT_LIBRARIES]
            if q:
                scored = sorted((s for s in ((fuzzy(q, l), l, src) for l, src in rows) if s[0] is not None),
                                key=lambda s: s[0])
                rows = [(l, src) for _, l, src in scored]
            out.extend(rows)
            return out or [("Escribe usuario/repo/ruta/libreria.json o un link de GitHub", None)]

        def pick(src):
            if is_library_source(src):
                self.do_install_library(src)
            else:
                self.do_install(src)                      # repo completo = paquete
        self.open_palette(items, pick)

    def do_install_library(self, source):
        if not messagebox.askyesno(
                "Install Library",
                f"¿Descargar la librería «{source}» desde GitHub?\n\n"
                "Una librería es solo un .json de autocompletado (no ejecuta código).", parent=self):
            return
        self.pkg_log(f"[Libs] Descargando {source}...")

        def done(ok, value):
            if not ok:
                self.pkg_log(f"[Libs] Error: {value}", "error")
                return
            self.reload_libs()
            self.pkg_log(f"[Libs] Instalada «{value['name']}» ({value['items']} elementos) en "
                         f"{os.path.relpath(value['path'], BASE_DIR)}")
        self.run_task(lambda: install_library(source, LIBS_DIR), done)

    def show_libs(self):
        rows = self.libs.summary() or ["No hay librerías cargadas (Libraries/*.json o paquetes con \"libraries\")"]
        self.open_palette(lambda q: [(r, None) for r in rows if not q or q.lower() in r.lower()], lambda p: None)

    # ------------------------------------------------------------ paletas
    def open_palette(self, get_items, on_pick, initial=""):
        if self.palette is not None and self.palette.winfo_exists():
            self.palette.destroy()
        self.palette = Palette(self, get_items, on_pick, initial)

    def build_commands(self):
        do = lambda name: (lambda: self.editor_do(name))
        cmds = [
            ("File: New File", self.new_file), ("File: Open File", self.open_file),
            ("File: Open Folder", self.open_folder), ("File: Save", self.save_file),
            ("File: Save As", self.save_file_as), ("File: Save All", self.save_all),
            ("File: Close Tab", self.close_tab), ("File: Reopen Closed Tab", self.reopen_closed),
            ("Edit: Undo", self.undo), ("Edit: Redo", self.redo), ("Edit: Select All", self.select_all),
            ("Edit: Find", do("find")), ("Edit: Replace", do("replace")),
            ("Edit: Go to Line", self.goto_line), ("Edit: Go to Anything", self.goto_anything),
            ("Edit: Toggle Comment", do("toggle_comment")),
            ("Edit: Duplicate Line", do("duplicate_line")), ("Edit: Delete Line", do("delete_line")),
            ("Edit: Move Line Up", do("move_line_up")), ("Edit: Move Line Down", do("move_line_down")),
            ("Edit: Indent", do("indent")), ("Edit: Unindent", do("unindent")),
            ("View: Toggle Sidebar", self.toggle_sidebar), ("View: Toggle Output Panel", self.toggle_terminal),
            ("View: Toggle Word Wrap", self.toggle_wrap),
            ("View: Zoom In", lambda: self.zoom(1)), ("View: Zoom Out", lambda: self.zoom(-1)),
            ("View: Reset Zoom", lambda: self.zoom(0)),
            ("Theme: Select Theme", self.select_theme), ("Theme: Install Theme", self.install_package),
            ("Theme: Export Current Theme", self.export_theme),
            ("Theme: Open Themes Folder", self.open_themes_folder),
            ("Tools: Build", self.build), ("Tools: Stop Build", self.stop_build),
            ("Tools: Clear Output", self.terminal.clear),
            ("Package: Install Package", self.install_package),
            ("Package: Upgrade Package", self.upgrade_package),
            ("Package: Remove Package", self.remove_package),
            ("Package: List Packages", self.list_packages),
            ("Package: Open Packages Folder", self.open_packages_folder),
            ("Suggest: Toggle Keyword Suggestions", self.toggle_suggest),
            ("LSP: Show Problems", self.show_problems), ("LSP: Toggle Language Server", self.toggle_lsp),
            ("LSP: Restart Language Servers", self.restart_lsp), ("LSP: Server Status", self.lsp_servers),
            ("LSP: Trigger Completion", lambda: self.editor_do("request_completion", None, True)),
            ("Libraries: Install Library", self.install_library), ("Libraries: Reload", self.reload_libs), ("Libraries: Show Loaded", self.show_libs),
        ]
        for lang, name in sorted(LANG_NAMES.items(), key=lambda kv: kv[1].lower()):
            cmds.append((f"Set Language: {name}", lambda l=lang: self.set_language(l)))
        return cmds

    def command_palette(self):
        def items(q):
            scored = [(fuzzy(q, name), name, fn) for name, fn in self.commands]
            scored = sorted((s for s in scored if s[0] is not None), key=lambda s: s[0])
            return [(name, fn) for _, name, fn in scored]
        self.open_palette(items, lambda fn: fn())

    # ------------------------------------------------------------- LSP
    def _lsp_poll(self):
        try:
            self.lsp.poll()
        except Exception:
            pass
        self.after(50, self._lsp_poll)

    def lsp_diagnostics(self, path, diags):
        for ed in self.editors():
            if ed.lsp_opened and ed.lsp_path and same_path(ed.lsp_path, path):
                ed.set_diagnostics(diags)

    def lsp_status(self, text):
        self.lsp_lb.config(text=text)
        if text.startswith(("No ", "LSP: No")) or "detuvo" in text:
            self.terminal.write(f"[LSP] {text}\n", "info")

    def update_diag_status(self, editor=None):
        ed = self.code_editor_current
        if editor is not None and editor is not ed:
            return
        if ed is None or not ed.lsp_opened:
            self.diag_lb.config(text="", fg=UI["muted"])
            return
        errors, warnings = ed.diag_counts
        color = UI["error"] if errors else ("#f1c40f" if warnings else UI["muted"])
        self.diag_lb.config(text=f"✖ {errors}   ⚠ {warnings}", fg=color)

    def show_problems(self):
        ed = self.code_editor_current
        if ed is None:
            return
        icons = {1: "✖", 2: "⚠", 3: "ℹ", 4: "·"}
        rows = [(f"{icons.get(sev, '·')}  L{line}: {msg}", (None, line))
                for line, col, sev, msg in sorted(ed.diag_items, key=lambda d: (d[0], d[1]))]

        def items(q):
            found = [r for r in rows if not q or fuzzy(q, r[0]) is not None]
            if found:
                return found
            if not ed.lsp_opened:
                return [("Sin servidor LSP para este archivo (guárdalo y revisa Tools > Language Server Status)", None)]
            return [("Sin problemas", None)]
        self.open_palette(items, self.pick_goto)

    def toggle_lsp(self):
        self.lsp_enabled = not self.lsp_enabled
        self.config_data["lsp_enabled"] = self.lsp_enabled
        self.save_config()
        for ed in self.editors():
            if self.lsp_enabled:
                ed.lsp = self.lsp
                ed.lsp_open()
            else:
                ed.lsp_close()
                ed.lsp = None
        if not self.lsp_enabled:
            self.lsp.stop_all()
        self.lsp_lb.config(text="LSP: activado" if self.lsp_enabled else "LSP: desactivado")
        self.update_diag_status()

    def toggle_suggest(self):
        self.suggest_enabled = not self.suggest_enabled
        self.config_data["suggest_enabled"] = self.suggest_enabled
        self.save_config()
        for ed in self.editors():
            ed.suggest_on = self.suggest_enabled
            ed.comp_close()
        self.lsp_lb.config(text="Sugerencias: activadas" if self.suggest_enabled
                           else "Sugerencias: desactivadas")

    def restart_lsp(self):
        self.lsp.stop_all()
        for ed in self.editors():
            if ed.lsp is not None:
                ed.lsp_open()

    def lsp_servers(self):
        rows = self.lsp.status() or ["No hay servidores en ejecución (abre un archivo .py/.cpp guardado)"]
        self.open_palette(lambda q: [(r, None) for r in rows if not q or q.lower() in r.lower()], lambda p: None)

    def _terminal_finished(self):
        """Terminó el programa: si el foco estaba en el output, vuelve al editor."""
        if isinstance(self.focused(), Terminal):
            self.focus_editor()

    # ------------------------------------------------------- recuperación
    @staticmethod
    def _stamp(editor):
        try:
            editor.disk_mtime = os.path.getmtime(editor.file_path)
        except (OSError, TypeError):
            editor.disk_mtime = None

    def recovery_snapshot(self):
        """Respalda lo no guardado y escribe la sesión actual."""
        tabs = []
        for ed in self.editors():
            if ed.dirty and ed.rev != ed.backed_rev:
                if self.recovery.write_backup(ed.rid, ed.text_area.get("1.0", "end-1c")):
                    ed.backed_rev = ed.rev
            if not ed.file_path and not ed.dirty:
                continue                                  # Untitled vacío: no vale la pena
            ta = ed.text_area
            tabs.append({"rid": ed.rid, "path": ed.file_path, "language": ed.language,
                         "dirty": ed.dirty, "mtime": ed.disk_mtime,
                         "cursor": ta.index("insert"), "yview": ta.yview()[0]})
        cur = self.code_editor_current
        self.recovery.save_session({"version": 1, "tabs": tabs,
                                    "active": cur.rid if cur else None,
                                    "folder": self.sidebar.root_path})

    def _recovery_tick(self):
        try:
            self.recovery_snapshot()
        except Exception:
            pass
        self.after(3000, self._recovery_tick)

    def restore_session(self):
        """Reabre las pestañas de la sesión anterior. True si restauró alguna."""
        data = self.recovery.load_session()
        folder = data.get("folder")
        if folder and os.path.isdir(folder):
            self.open_folder(folder)
        restored, active = 0, None
        for t in data.get("tabs") or []:
            try:
                ed = self._restore_tab(t)
            except Exception as ex:
                self.pkg_log(f"[Recovery] No se pudo restaurar una pestaña: {ex}", "error")
                continue
            if ed is not None:
                restored += 1
                if t.get("rid") == data.get("active"):
                    active = ed
        if not restored:
            return False
        if active is not None:
            self.notebook.select(active)
        self.recovery.cleanup({ed.rid for ed in self.editors() if ed.dirty})
        unsaved = sum(1 for ed in self.editors() if ed.dirty)
        if unsaved:
            self.pkg_log(f"[Recovery] Sesión restaurada: {unsaved} archivo(s) con cambios sin guardar.")
        return True

    def _restore_tab(self, t):
        rid, path = t.get("rid"), t.get("path")
        backup = self.recovery.read_backup(rid) if (rid and t.get("dirty")) else None
        on_disk = bool(path) and os.path.isfile(path)
        ed = None

        if backup is not None and on_disk and t.get("mtime") is not None:
            try:
                changed = os.path.getmtime(path) > t["mtime"] + 1
            except OSError:
                changed = False
            if changed and not messagebox.askyesno(
                    "Recovery",
                    f"«{os.path.basename(path)}» cambió en el disco después de tus cambios sin guardar.\n\n"
                    "¿Conservar tu versión recuperada?\n"
                    "Sí = la recuperada   ·   No = la del disco", parent=self):
                self.recovery.delete_backup(rid)
                backup = None

        if backup is None:
            if not on_disk:
                if path:
                    self.pkg_log(f"[Recovery] No se encontró «{path}»", "error")
                return None
            ed = self.open_path(path)
        else:
            ext = os.path.splitext(path)[1].lower() if path else ""
            lang = EXT_LANG.get(ext) or t.get("language") or "python"
            ed = CodeEditor(self.notebook, language=lang, file_path=path, font_size=self.font_size)
            ed.load_text(backup)
            ed.rid, ed.dirty, ed.disk_mtime = rid, True, t.get("mtime")
            name = os.path.basename(path) if path else "Untitled"
            self.add_editor(ed, slicing_text(name), name)
            if path:
                ed.lsp_open()

        if ed is not None:
            ta = ed.text_area
            try:
                ta.mark_set("insert", t.get("cursor", "1.0"))
                ta.see("insert")
                self.after_idle(lambda ed=ed, y=t.get("yview", 0.0):
                                (ed.text_area.yview_moveto(y), ed.cursor_moved()))
            except TclError:
                pass
        return ed

    def reopen_closed(self):
        """Ctrl+Shift+T: reabre la última pestaña cerrada."""
        while self.closed_stack:
            p = self.closed_stack.pop()
            if os.path.isfile(p):
                self.open_path(p)
                return

    # ----------------------------------------------------------- paquetes
    def run_task(self, work, done):
        """Ejecuta work() en un hilo (red) y llama a done(ok, resultado) en el hilo de la interfaz."""
        q = queue.Queue()

        def target():
            try:
                q.put((True, work()))
            except Exception as ex:
                q.put((False, ex))
        threading.Thread(target=target, daemon=True).start()

        def poll():
            try:
                ok, value = q.get_nowait()
            except queue.Empty:
                self.after(100, poll)
                return
            done(ok, value)
        self.after(100, poll)

    def pkg_log(self, text, tag="info"):
        self.show_terminal()
        self.terminal.write(text + "\n", tag)

    def load_package(self, name):
        """Carga un paquete instalado. Devuelve None, o el texto del error."""
        api = PackageAPI(self, name, self.packages.path(name))
        self.package_apis[name] = api
        try:
            self.packages.load(name, api)
        except Exception as ex:
            self.unload_package(name)
            return f"{type(ex).__name__}: {ex}"
        return None

    def unload_package(self, name):
        api = self.package_apis.pop(name, None)
        self.packages.unload(name, api)
        if api is not None:                                  # quita sus comandos de la paleta
            self.commands = [c for c in self.commands if c not in api.commands]

    def load_packages(self):
        for name in self.packages.installed():
            err = self.load_package(name)
            if err:
                self.pkg_log(f"[Package] No se pudo cargar «{name}»: {err}", "error")

    def install_package(self):
        """Paleta: escribe usuario/repo (o URL de GitHub), o elige uno de la lista de GitHub."""
        state = {"results": [], "done": False, "error": None}

        def items(q):
            q = q.strip()
            out = []
            if q:
                try:
                    owner, repo, ref = parse_source(q)
                    src = f"{owner}/{repo}" + (f"@{ref}" if ref else "")
                    out.append((f"Instalar desde GitHub:  {src}", src))
                except PackageError:
                    pass
            found = [(f"{r['full_name']}    ★{r['stars']}    {r['description']}", r["full_name"])
                     for r in state["results"]]
            known = {src for _, src in found}
            found = ([(f"{src}    (predeterminado)    {desc}", src)
                      for src, desc in DEFAULT_PACKAGES if src not in known] + found)
            if q:
                scored = [(fuzzy(q, label), label, src) for label, src in found]
                scored = sorted((s for s in scored if s[0] is not None), key=lambda s: s[0])
                found = [(label, src) for _, label, src in scored]
            out.extend(found)
            if not out:
                if not state["done"]:
                    out.append(("Buscando paquetes en GitHub (topic: blinker-package)...", None))
                else:
                    if state["error"]:
                        out.append((f"No se pudo buscar: {state['error']}", None))
                    out.append(("Escribe usuario/repositorio o una URL de GitHub", None))
            return out

        def searched(ok, value):
            state["done"] = True
            if ok:
                state["results"] = value
            else:
                state["error"] = str(value)
            if self.palette is not None and self.palette.winfo_exists():
                self.palette.refresh()

        self.open_palette(items, lambda src: self.do_install(src))
        self.run_task(self.packages.search, searched)

    def do_install(self, source, ask=True):
        if ask and not messagebox.askyesno(
                "Install Package",
                f"¿Instalar «{source}» desde GitHub?\n\n"
                "Los paquetes pueden ejecutar código Python con los mismos permisos que este "
                "programa. Instala solo paquetes de fuentes en las que confíes.", parent=self):
            return
        self.pkg_log(f"[Package] Descargando {source}...")

        def done(ok, value):
            if not ok:
                self.pkg_log(f"[Package] Error: {value}", "error")
                return
            name = value["name"]
            self.pkg_log(f"[Package] Instalado «{name}» {value['version']}"
                         f"{' - ' + value['description'] if value['description'] else ''}")
            self.unload_package(name)                        # por si era una actualización
            self.reload_libs()
            err = self.load_package(name)
            if err:
                self.pkg_log(f"[Package] No se pudo cargar «{name}»: {err}", "error")
            elif self.libs.count_for(name):
                self.pkg_log(f"[Package] «{name}» trae {self.libs.count_for(name)} librería(s) de autocompletado.")
            elif self.themes.package_themes(name):
                n = len(self.themes.package_themes(name))
                self.pkg_log(f"[Package] «{name}» trae {n} tema(s): View > Select Theme...")
            elif not value["has_code"]:
                self.pkg_log(f"[Package] «{name}» no tiene 'main' en blinker-package.json: "
                             "solo se guardaron sus archivos.")
        self.run_task(lambda: self.packages.install(source), done)

    def _installed_items(self, only_remote=False):
        inst = {n: i for n, i in self.packages.installed().items()
                if i.get("source") or not only_remote}

        def items(q):
            rows = []
            for n, i in inst.items():
                if q and fuzzy(q, n) is None:
                    continue
                label = f"{n}    {i['version']}    {i.get('source') or 'local'}"
                if i["description"]:
                    label += f"    {i['description']}"
                rows.append((label, n))
            return rows or [("No hay paquetes instalados", None)]
        return inst, items

    def upgrade_package(self):
        inst, items = self._installed_items(only_remote=True)
        def pick(name):
            info = inst[name]
            src = info["source"] + (f"@{info['ref']}" if info.get("ref") else "")
            self.do_install(src, ask=False)
        self.open_palette(items, pick)

    def remove_package(self):
        inst, items = self._installed_items()
        def pick(name):
            if not messagebox.askyesno("Remove Package", f"¿Eliminar el paquete «{name}»?\n"
                                       "Se borra su carpeta dentro de Packages/.", parent=self):
                return
            self.unload_package(name)
            try:
                self.packages.remove(name)
            except (PackageError, OSError) as ex:
                self.pkg_log(f"[Package] No se pudo eliminar «{name}»: {ex}", "error")
                return
            self.reload_libs()
            self.pkg_log(f"[Package] Eliminado «{name}». Los atajos y lenguajes que registró "
                         "se quitan por completo al reiniciar el editor.")
        self.open_palette(items, pick)

    def list_packages(self):
        """Lista los paquetes; al elegir uno se abre su carpeta en el panel lateral."""
        inst, items = self._installed_items()
        self.open_palette(items, lambda name: self.open_folder(inst[name]["path"]))

    def open_packages_folder(self):
        os.makedirs(PACKAGES_DIR, exist_ok=True)
        self.open_folder(PACKAGES_DIR)

    def project_files(self):
        root = self.sidebar.root_path
        found = []
        if root:
            for d, dirs, files in os.walk(root):
                dirs[:] = [x for x in dirs if x not in IGNORED]
                found.extend(os.path.join(d, f) for f in files)
                if len(found) >= 8000:
                    break
        known = set(found)
        for ed in self.editors():
            if ed.file_path:
                ap = os.path.abspath(ed.file_path)
                if ap not in known:
                    found.append(ap)
        return found

    def goto_anything(self):
        root = self.sidebar.root_path
        labeled = []
        for p in self.project_files():
            if root and p.startswith(root + os.sep):
                labeled.append((p[len(root) + 1:].replace("\\", "/"), p))
            else:
                labeled.append((p, p))

        def items(q):
            name, sep, ln = q.partition(":")
            line = int(ln) if ln.strip().isdigit() else None
            if sep and not name:                                  # ":42" = ir a la línea
                if line:
                    return [(f"Ir a la línea {line}", (None, line))]
                return [("Escribe un número de línea...", None)]
            scored = [(fuzzy(name, label), label, path) for label, path in labeled]
            scored = sorted((s for s in scored if s[0] is not None), key=lambda s: s[0])
            return [(label, (path, line)) for _, label, path in scored]

        self.open_palette(items, self.pick_goto)

    def goto_line(self):
        if self.code_editor_current is None:
            return
        self.open_palette(lambda q: self._line_items(q), self.pick_goto, initial=":")

    def _line_items(self, q):
        digits = q.lstrip(":").strip()
        if digits.isdigit():
            return [(f"Ir a la línea {int(digits)}", (None, int(digits)))]
        return [("Escribe un número de línea...", None)]

    def pick_goto(self, payload):
        path, line = payload
        editor = self.open_path(path) if path else self.code_editor_current
        if editor is not None and line:
            self.update_idletasks()
            editor.goto_line(line)
            editor.text_area.focus_set()

if __name__ == "__main__":
    app = main()
    app.mainloop()