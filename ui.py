"""ui.py - Colores de la interfaz y estilo oscuro de ttk (pestañas, árbol, scrollbars)."""
from tkinter import ttk

UI = {
    "bg": "#202225",            # fondo general y separadores
    "panel": "#2f3136",         # paneles laterales, números de línea, barras
    "editor": "#36393f",        # fondo del editor y del output
    "line_hl": "#3d4148",       # línea actual
    "fg": "#dcddde",            # texto normal de la interfaz
    "muted": "#858585",         # texto secundario
    "select": "#44475a",        # selección
    "find": "#4d5566",          # coincidencias de búsqueda
    "find_current": "#a07d2e",  # coincidencia actual
    "bracket": "#5a6178",       # paréntesis que hacen pareja
    "accent": "#66d9ef",        # color de acento (foco de entradas)
    "error": "#ff5555",
}


def apply_dark_style(root):
    """Estilo oscuro para los widgets ttk (Notebook, Treeview, Scrollbar)."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")     # el único tema que respeta todos los colores
    except Exception:
        pass

    # ---- Pestañas -----------------------------------------------------
    # clam dibuja el borde del área del contenido con estos 3 colores (por defecto, claros)
    style.configure("TNotebook", background=UI["bg"], borderwidth=0,
                    tabmargins=(2, 4, 2, 0), highlightthickness=0,
                    bordercolor=UI["bg"], lightcolor=UI["bg"], darkcolor=UI["bg"])
    # Quita el borde interno del Notebook
    style.layout("TNotebook", [("Notebook.client", {"sticky": "nswe"})])

    style.configure("TNotebook.Tab", background=UI["panel"], foreground="#b9bbbe",
                    padding=(12, 5), borderwidth=0, relief="flat",
                    lightcolor=UI["panel"], darkcolor=UI["panel"], bordercolor=UI["bg"],
                    font=("Segoe UI", 10))
    style.map("TNotebook.Tab",
              background=[("selected", UI["editor"]), ("active", UI["select"])],
              foreground=[("selected", "#ffffff"), ("active", "#ffffff")],
              lightcolor=[("selected", UI["editor"])],
              darkcolor=[("selected", UI["editor"])],
              focuscolor=[("selected", UI["editor"])])       # oculta el cuadro de foco

    # ---- Árbol de carpetas ---------------------------------------------
    style.configure("Folders.Treeview", background=UI["panel"], fieldbackground=UI["panel"],
                    foreground=UI["fg"], borderwidth=0, rowheight=22, font=("Segoe UI", 10))
    style.map("Folders.Treeview",
              background=[("selected", UI["select"])],
              foreground=[("selected", "#ffffff")])
    style.layout("Folders.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    # ---- Scrollbars ------------------------------------------------------
    for name in ("Dark.Vertical.TScrollbar", "Dark.Horizontal.TScrollbar"):
        style.configure(name, background=UI["select"], troughcolor=UI["panel"],
                        bordercolor=UI["panel"], arrowcolor=UI["fg"], lightcolor=UI["select"],
                        darkcolor=UI["select"], gripcount=0)
        style.map(name, background=[("active", UI["muted"])])