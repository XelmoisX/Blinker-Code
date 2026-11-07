"""icons.py - Iconos del árbol de carpetas y de las pestañas.

Funciona SIN descargar nada: si no existe el PNG, se dibuja un icono de
relleno (placeholder) de un color según el tipo de archivo.

Para poner tus propios iconos:
    1. Crea la carpeta  icons/  junto a main.py
    2. Guarda PNGs de 16x16 (o 32x32 / 48x48, se reducen solos) con estos nombres:

        folder.png  folder_open.png  file.png
        python.png  javascript.png  typescript.png  java.png  c.png  cpp.png
        header.png  csharp.png  rust.png  go.png  lua.png  sql.png  shell.png
        json.png  html.png  css.png  markdown.png  text.png  log.png
        image.png  config.png  archive.png  pdf.png  exe.png

    3. Reinicia el editor. Los que no existan siguen usando el placeholder.

Para agregar un tipo nuevo: añade la extensión en EXT_ICON y (opcional) un color
en COLORS.
"""
import os
from tkinter import PhotoImage

ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
ICON_SIZE = 16

# extensión -> nombre del icono (icons/<nombre>.png)
EXT_ICON = {
    ".py": "python", ".pyw": "python", ".pyi": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".java": "java",
    ".c": "c", ".h": "header",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "header",
    ".cs": "csharp", ".rs": "rust", ".go": "go", ".lua": "lua", ".sql": "sql",
    ".sh": "shell", ".bash": "shell", ".bat": "shell", ".cmd": "shell", ".ps1": "shell",
    ".json": "json", ".html": "html", ".htm": "html", ".css": "css",
    ".md": "markdown", ".txt": "text", ".log": "log",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
    ".bmp": "image", ".ico": "image", ".svg": "image", ".webp": "image",
    ".ini": "config", ".cfg": "config", ".toml": "config", ".yaml": "config",
    ".yml": "config", ".env": "config", ".conf": "config",
    ".zip": "archive", ".rar": "archive", ".7z": "archive", ".tar": "archive", ".gz": "archive",
    ".pdf": "pdf", ".exe": "exe", ".dll": "exe", ".rubi": "rubi",
}

# nombres de archivo especiales (en minúsculas)
NAME_ICON = {
    ".gitignore": "config", "dockerfile": "config", "makefile": "config",
    "readme": "markdown", "license": "text",
}

# colores de los placeholders
COLORS = {
    "folder": "#e0b050", "folder_open": "#e0b050", "file": "#9aa0a6",
    "python": "#4b8bbe", "javascript": "#f0db4f", "typescript": "#3178c6",
    "java": "#e76f00", "c": "#5c6bc0", "cpp": "#00599c", "header": "#8e6bbf",
    "csharp": "#68217a", "rust": "#dea584", "go": "#00add8", "lua": "#000080",
    "sql": "#e38c00", "shell": "#4eaa25", "json": "#cbcb41", "html": "#e44d26",
    "css": "#264de4", "markdown": "#519aba", "text": "#b0b0b0", "log": "#808080",
    "image": "#a074c4", "config": "#6d8086", "archive": "#c9a227", "pdf": "#e2574c",
    "exe": "#4ec9b0",
}


def icon_key(path, is_dir=False, is_open=False):
    """Devuelve el nombre del icono que corresponde a una ruta."""
    if is_dir:
        return "folder_open" if is_open else "folder"
    name = os.path.basename(path).lower()
    if name in NAME_ICON:
        return NAME_ICON[name]
    return EXT_ICON.get(os.path.splitext(name)[1], "file")


def _shade(color, factor):
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    r, g, b = (max(0, min(255, int(c * factor))) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


class IconSet:
    """Carga (y guarda en caché) los iconos. Hay que conservar la referencia
    a las PhotoImage, por eso viven en self.cache."""

    def __init__(self, master=None):
        self.master = master
        self.cache = {}

    def get(self, key):
        if key not in self.cache:
            self.cache[key] = self._load(key) or self._placeholder(key)
        return self.cache[key]

    def for_path(self, path, is_dir=False, is_open=False):
        return self.get(icon_key(path, is_dir, is_open))

    def _load(self, key):
        path = os.path.join(ICON_DIR, key + ".png")
        if not os.path.isfile(path):
            return None
        try:
            img = PhotoImage(master=self.master, file=path)
        except Exception:
            return None
        if img.width() > ICON_SIZE:                       # 32x32 -> 16x16, etc.
            img = img.subsample(max(1, round(img.width() / ICON_SIZE)))
        return img

    def _placeholder(self, key):
        img = PhotoImage(master=self.master, width=ICON_SIZE, height=ICON_SIZE)
        color = COLORS.get(key, COLORS["file"])
        if key == "folder":
            img.put(_shade(color, 0.75), to=(1, 3, 7, 5))      # pestaña
            img.put(color, to=(1, 5, 15, 14))                  # cuerpo
        elif key == "folder_open":
            img.put(_shade(color, 0.75), to=(1, 3, 7, 5))
            img.put(_shade(color, 0.75), to=(1, 5, 13, 13))    # fondo
            img.put(_shade(color, 1.15), to=(3, 7, 15, 14))    # frente
        else:
            img.put(color, to=(3, 1, 13, 15))                  # hoja
            img.put(_shade(color, 1.4), to=(9, 1, 13, 5))      # esquina doblada
            img.put("#ffffff", to=(5, 8, 11, 9))               # "líneas de texto"
            img.put("#ffffff", to=(5, 11, 11, 12))
        return img