"""themes.py - Temas de Blinker Code.

Este archivo NO depende de tkinter. Los temas son archivos .json y pueden venir de:

    1. Integrado:   "Default" (los colores con los que arranca el editor).
    2. Usuario:     Themes/*.json   (junto a main.py)
    3. Paquetes:    cualquier paquete de Packages/ cuyo blinker-package.json tenga
                    "themes": ["themes/midnight.json", ...]

Formato de un tema:

    {
        "name": "Midnight",
        "author": "tu nombre",
        "ui":     {"bg": "#0b0f1a", "panel": "#111726", "editor": "#0f1422", ...},
        "syntax": {"Comment": "#6b7694", "Keyword": "#c792ea", ...}
    }

  - "ui" son las claves del diccionario UI (ui.py).
  - "syntax" son las claves de THEME_COLORS (highlight.py).
  - Todo lo que el tema no defina se toma del tema Default.
  - Los colores deben ser hexadecimales de 6 dígitos (#rrggbb).
  - Tip: View > Export Current Theme crea un .json con TODAS las claves reales.
"""
import json
import os
import re

MANIFEST = "blinker-package.json"
HEX = re.compile(r"#[0-9a-fA-F]{6}")
MAX_THEME_SIZE = 64 * 1024


class ThemeError(Exception):
    """Error 'esperado' (archivo inválido, tema inexistente...)."""


class ThemeManager:
    def __init__(self, ui, syntax, user_dir, packages_dir):
        # ui y syntax son los diccionarios VIVOS (UI y THEME_COLORS): se modifican en el lugar,
        # así todos los módulos que ya los importaron ven los colores nuevos.
        self.ui, self.syntax = ui, syntax
        self.base_ui, self.base_syntax = dict(ui), dict(syntax)
        self.user_dir, self.packages_dir = user_dir, packages_dir
        self.current = "Default"

    # ------------------------------------------------------------ archivos
    @staticmethod
    def load_file(path):
        try:
            if os.path.getsize(path) > MAX_THEME_SIZE:
                raise ThemeError("El tema es demasiado grande.")
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            raise ThemeError(f"No se pudo leer el tema: {os.path.basename(path)}")
        if not isinstance(data, dict):
            raise ThemeError("El tema debe ser un objeto JSON.")
        for section in ("ui", "syntax"):
            block = data.get(section, {})
            if not isinstance(block, dict):
                raise ThemeError(f"'{section}' debe ser un objeto.")
            for key, value in block.items():
                if not (isinstance(value, str) and HEX.fullmatch(value)):
                    raise ThemeError(f"Color inválido en {section}.{key}: {value!r} (usa #rrggbb)")
        return data

    # --------------------------------------------------------- descubrimiento
    def package_themes(self, package_name):
        """Rutas de los temas que declara un paquete (solo dentro de su carpeta)."""
        pkg = os.path.join(self.packages_dir, package_name)
        try:
            with open(os.path.join(pkg, MANIFEST), "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, ValueError):
            return []
        files = manifest.get("themes") if isinstance(manifest, dict) else None
        out, root = [], os.path.realpath(pkg)
        for rel in files if isinstance(files, list) else []:
            if not isinstance(rel, str) or not rel.lower().endswith(".json"):
                continue
            path = os.path.realpath(os.path.join(pkg, rel))
            if path.startswith(root + os.sep) and os.path.isfile(path):
                out.append(path)
        return out

    def available(self):
        """{nombre: {"path": ruta|None, "source": "integrado"|"usuario"|"paquete: x"}}"""
        found = {"Default": {"path": None, "source": "integrado"}}

        def add(path, source):
            try:
                data = self.load_file(path)
            except ThemeError:
                return
            name = str(data.get("name") or os.path.splitext(os.path.basename(path))[0])
            if name in found:
                name = f"{name} [{source}]"
            found[name] = {"path": path, "source": source}

        if os.path.isdir(self.user_dir):
            for fn in sorted(os.listdir(self.user_dir), key=str.lower):
                if fn.lower().endswith(".json"):
                    add(os.path.join(self.user_dir, fn), "usuario")
        if os.path.isdir(self.packages_dir):
            for pkg in sorted(os.listdir(self.packages_dir), key=str.lower):
                if pkg.startswith(".") or not os.path.isdir(os.path.join(self.packages_dir, pkg)):
                    continue
                for path in self.package_themes(pkg):
                    add(path, f"paquete: {pkg}")
        return found

    # -------------------------------------------------------------- aplicar
    def apply(self, name):
        """Cambia los colores de UI y THEME_COLORS en el lugar.
        Devuelve {color_viejo: color_nuevo} para recolorear widgets ya creados."""
        info = self.available().get(name)
        if info is None:
            raise ThemeError(f"El tema «{name}» no existe.")
        data = self.load_file(info["path"]) if info["path"] else {}

        new_ui = dict(self.base_ui)
        new_ui.update({k: v for k, v in (data.get("ui") or {}).items() if k in self.base_ui})
        new_syntax = dict(self.base_syntax)
        new_syntax.update({k: v for k, v in (data.get("syntax") or {}).items()
                           if k in self.base_syntax})

        cmap = {}
        for table, new in ((self.ui, new_ui), (self.syntax, new_syntax)):
            for key, value in new.items():
                old = str(table.get(key, "")).lower()
                if old and old != value.lower():
                    cmap.setdefault(old, value)
            table.update(new)
        self.current = name
        return cmap

    # ------------------------------------------------------------- exportar
    def export_current(self, name):
        """Guarda los colores actuales en Themes/<name>.json (punto de partida para tu tema)."""
        safe = re.sub(r"[^\w.-]", "_", name).strip("._") or "mi-tema"
        os.makedirs(self.user_dir, exist_ok=True)
        path = os.path.join(self.user_dir, safe + ".json")
        hexed = lambda d: {k: v for k, v in d.items() if isinstance(v, str) and HEX.fullmatch(v)}
        data = {"name": name, "author": "", "ui": hexed(self.ui), "syntax": hexed(self.syntax)}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return path