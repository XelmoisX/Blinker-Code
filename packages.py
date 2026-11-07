"""packages.py - Gestor de paquetes de Blinker Code (algo parecido a "Package Control").

Este archivo NO depende de tkinter. Instala repositorios de GitHub dentro de la
carpeta  Packages/  (junto a main.py) y lleva el registro en  Packages/packages.json.

    pm = PackageManager("Packages")
    pm.install("usuario/repo")            # o "usuario/repo@rama", o la URL de GitHub
    pm.installed()                        # {nombre: {source, ref, version, ...}}
    pm.remove("nombre")
    pm.search()                           # repos de GitHub con el topic "blinker-package"

----------------------------------------------------------------------
 CÓMO ES UN PAQUETE
----------------------------------------------------------------------
Un repositorio de GitHub con un archivo  blinker-package.json  en la raíz:

    {
        "name": "mi-paquete",
        "version": "1.0.0",
        "description": "Lo que hace",
        "author": "tu nombre",
        "main": "main.py"
    }

y (opcional) el archivo "main" con una función register(api):

    def register(api):
        api.add_command("Mi paquete: Saludar", lambda: api.message("Hola!"))
        api.add_shortcut("<Control-Shift-H>", lambda: api.message("Hola!"))

    def unregister(api):          # opcional, al desinstalar/actualizar
        pass

El objeto  api  (ver PackageAPI) permite agregar comandos a la paleta, atajos de
teclado, lenguajes de highlight (api.highlight) y sistemas de build (api.build).
Para que aparezca en "Install Package", ponle al repo el topic  blinker-package.
Un repositorio SIN manifest también se instala (sirve para guardar archivos), pero
no se ejecuta nada.
"""
import io
import importlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import types
import urllib.error
import urllib.parse
import urllib.request
import zipfile

MANIFEST = "blinker-package.json"
REGISTRY = "packages.json"
TOPIC = "blinker-package"
MAX_ZIP = 100 * 1024 * 1024            # tamaño máximo del .zip descargado
MAX_UNZIPPED = 300 * 1024 * 1024       # tamaño máximo descomprimido
USER_AGENT = "BlinkerCode-Packages"


class PackageError(Exception):
    """Error 'esperado' (sin conexión, repo inexistente, zip inseguro...)."""


# ======================================================================
#  UTILIDADES
# ======================================================================
def parse_source(text):
    """Acepta 'usuario/repo', 'usuario/repo@rama', 'https://github.com/usuario/repo',
    '.../tree/rama'. Devuelve (owner, repo, ref o None)."""
    s = (text or "").strip()
    if not s:
        raise PackageError("Escribe usuario/repositorio o una URL de GitHub.")
    s = re.sub(r"^(?:https?://)?(?:www\.)?github\.com/", "", s)
    ref = None
    m = re.search(r"/tree/(.+)$", s)
    if m:
        ref = m.group(1).strip("/") or None
        s = s[:m.start()]
    if "@" in s:
        s, _, r = s.partition("@")
        ref = r.strip() or ref
    s = s.strip("/")
    if s.endswith(".git"):
        s = s[:-4]
    parts = s.split("/")
    if len(parts) != 2 or not all(re.fullmatch(r"[\w.-]+", p) for p in parts):
        raise PackageError(f"'{text}' no parece un repositorio de GitHub (usuario/repo).")
    return parts[0], parts[1], ref


def _safe_name(name):
    name = re.sub(r"[^\w.-]", "_", str(name)).strip("._")
    if not name:
        raise PackageError("Nombre de paquete inválido.")
    return name


def _http_get(url, limit, accept=None, api=False):
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    token = os.environ.get("GITHUB_TOKEN")
    if api and token:                       # solo para la API: sube el límite de peticiones
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read(limit + 1)
    except urllib.error.HTTPError as ex:
        if ex.code == 404:
            raise PackageError("No se encontró (404).")
        if ex.code in (403, 429):
            raise PackageError("GitHub limitó las peticiones; prueba más tarde "
                               "(o define la variable de entorno GITHUB_TOKEN).")
        raise PackageError(f"GitHub respondió con el error {ex.code}.")
    except OSError:
        raise PackageError("No se pudo conectar (¿hay internet?).")
    if len(data) > limit:
        raise PackageError("El archivo es demasiado grande.")
    return data


def _archive_urls(owner, repo, ref):
    base = f"https://github.com/{owner}/{repo}/archive/"
    if not ref:
        return [base + "HEAD.zip"]                       # rama por defecto
    r = urllib.parse.quote(ref, safe="/")
    return [base + f"refs/heads/{r}.zip", base + f"refs/tags/{r}.zip", base + f"{r}.zip"]


# ======================================================================
#  GESTOR
# ======================================================================
class PackageManager:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    # ------------------------------------------------------------ registro
    def _registry_path(self):
        return os.path.join(self.root, REGISTRY)

    def _load_registry(self):
        try:
            with open(self._registry_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_registry(self, reg):
        with open(self._registry_path(), "w", encoding="utf-8") as f:
            json.dump(reg, f, indent=2, ensure_ascii=False)

    @staticmethod
    def _read_manifest(path):
        mf = os.path.join(path, MANIFEST)
        if not os.path.isfile(mf):
            return {}
        try:
            with open(mf, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            raise PackageError(f"{MANIFEST} no es un JSON válido.")
        if not isinstance(data, dict):
            raise PackageError(f"{MANIFEST} debe ser un objeto JSON.")
        return data

    def path(self, name):
        return os.path.join(self.root, name)

    # -------------------------------------------------------------- listar
    def installed(self):
        """{nombre: info}. Incluye los instalados desde GitHub y las carpetas
        locales que tengan un blinker-package.json (útil para desarrollar)."""
        reg = self._load_registry()
        out = {}
        for entry in sorted(os.listdir(self.root), key=str.lower):
            p = os.path.join(self.root, entry)
            if entry.startswith(".") or not os.path.isdir(p):
                continue
            try:
                manifest = self._read_manifest(p)
            except PackageError:
                manifest = {}
            if entry not in reg and not manifest:
                continue                                 # carpeta ajena
            info = dict(reg.get(entry, {}))
            info.setdefault("source", None)
            info.setdefault("ref", None)
            info["version"] = str(manifest.get("version", info.get("version", "?")))
            info["description"] = manifest.get("description", "")
            info["path"] = p
            out[entry] = info
        return out

    # ---------------------------------------------------------------- buscar
    def search(self, query=""):
        """Repos de GitHub con el topic 'blinker-package' (ordenados por estrellas)."""
        q = (query.strip() + " " if query.strip() else "") + f"topic:{TOPIC}"
        url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
            {"q": q, "sort": "stars", "per_page": 50})
        data = json.loads(_http_get(url, 2 * 1024 * 1024,
                                    accept="application/vnd.github+json", api=True))
        return [{"full_name": it["full_name"],
                 "description": it.get("description") or "",
                 "stars": it.get("stargazers_count", 0)} for it in data.get("items", [])]

    # -------------------------------------------------------------- instalar
    def install(self, source):
        """Descarga el repo, lo descomprime en Packages/<nombre> y lo registra.
        Bloquea (red): llámalo desde un hilo. Devuelve un dict con los datos."""
        owner, repo, ref = parse_source(source)

        data, last = None, None
        for url in _archive_urls(owner, repo, ref):
            try:
                data = _http_get(url, MAX_ZIP)
                break
            except PackageError as ex:
                last = ex
        if data is None:
            raise PackageError(f"No se pudo descargar {owner}/{repo}"
                               f"{'@' + ref if ref else ''}: {last}")

        tmp = tempfile.mkdtemp(prefix=".tmp_", dir=self.root)
        try:
            self._extract(data, tmp)
            manifest = self._read_manifest(tmp)
            name = _safe_name(manifest.get("name") or repo)
            dest = os.path.join(self.root, name)
            if os.path.exists(dest):
                shutil.rmtree(dest)
            shutil.move(tmp, dest)
            tmp = None
        finally:
            if tmp and os.path.isdir(tmp):
                shutil.rmtree(tmp, ignore_errors=True)

        version = str(manifest.get("version", "?"))
        reg = self._load_registry()
        reg[name] = {"source": f"{owner}/{repo}", "ref": ref, "version": version,
                     "installed": int(time.time())}
        self._save_registry(reg)
        return {"name": name, "version": version, "source": f"{owner}/{repo}",
                "description": manifest.get("description", ""),
                "has_code": bool(manifest.get("main"))}

    @staticmethod
    def _extract(data, dest):
        dest_abs = os.path.abspath(dest)
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise PackageError("El archivo descargado no es un .zip válido.")
        with zf:
            infos = zf.infolist()
            if sum(i.file_size for i in infos) > MAX_UNZIPPED:
                raise PackageError("El paquete descomprimido es demasiado grande.")
            names = [i.filename for i in infos if i.filename]
            tops = {n.split("/")[0] for n in names}
            strip = len(tops) == 1 and any("/" in n for n in names)   # GitHub: repo-rama/...
            for info in infos:
                name = info.filename
                if strip:
                    name = name.split("/", 1)[1] if "/" in name else ""
                if not name:
                    continue
                target = os.path.abspath(os.path.join(dest_abs, name))
                if target != dest_abs and not target.startswith(dest_abs + os.sep):
                    raise PackageError("El .zip contiene rutas inseguras; se canceló la instalación.")
                if name.endswith("/"):
                    os.makedirs(target, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)

    # ------------------------------------------------------------- eliminar
    def remove(self, name):
        if name not in self.installed():
            raise PackageError(f"'{name}' no está instalado.")
        shutil.rmtree(self.path(name), ignore_errors=False)
        reg = self._load_registry()
        reg.pop(name, None)
        self._save_registry(reg)

    # ----------------------------------------------------- cargar / descargar
    @staticmethod
    def _modname(name):
        return "blinker_pkg_" + re.sub(r"\W", "_", name)

    def load(self, name, api):
        """Importa el 'main' del manifest y llama a register(api)."""
        path = self.path(name)
        main = self._read_manifest(path).get("main")
        if not main:
            return                                        # paquete sin código
        if (not isinstance(main, str) or ".." in main
                or not re.fullmatch(r"\w[\w./-]*\.py", main)):
            raise PackageError("'main' del manifest no es válido.")
        pkgname = self._modname(name)
        pkg = types.ModuleType(pkgname)
        pkg.__path__ = [path]                             # permite 'from . import otro'
        sys.modules[pkgname] = pkg
        importlib.invalidate_caches()
        mod = importlib.import_module(f"{pkgname}.{main[:-3].replace('/', '.')}")
        register = getattr(mod, "register", None)
        if callable(register):
            register(api)

    def unload(self, name, api=None):
        """Llama a unregister(api) (si existe) y olvida los módulos del paquete."""
        pkgname = self._modname(name)
        for key in [k for k in sys.modules if k == pkgname or k.startswith(pkgname + ".")]:
            mod = sys.modules.get(key)
            unregister = getattr(mod, "unregister", None)
            if callable(unregister) and api is not None:
                try:
                    unregister(api)
                except Exception:
                    pass
            sys.modules.pop(key, None)


# ======================================================================
#  API QUE RECIBEN LOS PAQUETES
# ======================================================================
class PackageAPI:
    """Lo que un paquete puede hacer. Se le pasa a register(api)."""

    def __init__(self, app, name, path):
        self.app = app              # la ventana principal (úsala con cuidado)
        self.name = name
        self.path = path            # carpeta del paquete (para leer sus archivos)
        self.commands = []          # lo que registró este paquete (para quitarlo al desinstalar)

    @property
    def highlight(self):
        import highlight            # register_language, make_rules, THEME_COLORS...
        return highlight

    @property
    def build(self):
        import build                # register_build
        return build

    def add_command(self, title, func):
        """Agrega un comando a la paleta (Ctrl+Shift+P)."""
        entry = (title, func)
        self.app.commands.append(entry)
        self.commands.append(entry)

    def add_shortcut(self, sequence, func):
        """Atajo de teclado, p. ej. '<Control-Shift-H>'."""
        self.app.add_shortcut(sequence, func)

    def editor(self):
        """El editor (CodeEditor) de la pestaña activa, o None."""
        return self.app.code_editor_current

    def message(self, text, error=False):
        """Escribe un mensaje en el panel de output."""
        self.app.pkg_log(f"[{self.name}] {text}", "error" if error else "info")