"""Popup de sugerencias (Canvas): iconos, coincidencias resaltadas, detalle y pie de ayuda.

ICONOS: pon tus PNG (16x16) en  icons/suggest/<nombre>.png  y se usan automáticamente.
Nombres: keyword, builtin, snippet, word, function, method, class, variable, property,
         field, constant, module, interface, enum, struct, text
Si falta alguno se dibuja uno de respaldo, así que puedes reemplazarlos de a uno.

Cada sugerencia elige su icono con  item["icon"]  o, si no lo trae (sugerencias del LSP),
con KIND_TO_ICON[item["kind"]].

El popup escala con el zoom del editor: SuggestPopup(master, on_accept, font_size) y
popup.apply_size(font_size) (tamaño base = 10).
"""
import os
import tkinter as tk
import tkinter.font as tkfont

from ui import UI

ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "suggest")

# Colores del icono de respaldo (si no existe el PNG)
FALLBACK = {"keyword": "#c586c0", "builtin": "#4fa8ff", "snippet": "#e5a93d", "word": "#7f8896",
            "function": "#b180d7", "method": "#b180d7", "class": "#ee9d28", "variable": "#4aa3ff",
            "property": "#9aa5b1", "field": "#4aa3ff", "constant": "#d19a66", "module": "#3fc1a5",
            "interface": "#3fc1a5", "enum": "#ee9d28", "struct": "#ee9d28", "text": "#7f8896"}

# Para sugerencias del LSP: el "kind" (símbolo corto de lsp.py) -> nombre de icono.
# Ajusta esta tabla a los símbolos que use tu lsp.py.
KIND_TO_ICON = {
    "k": "keyword", "b": "builtin", "s": "snippet", "w": "word",
    "f": "function", "ƒ": "function", "F": "function", "m": "method", "M": "module",
    "c": "class", "C": "class", "v": "variable", "V": "variable", "p": "property",
    "P": "property", "i": "interface", "I": "interface", "e": "enum", "E": "enum",
    "S": "struct", "t": "text", "T": "text", "K": "constant", "◆": "keyword",
    "□": "variable", "▢": "class", "≡": "enum", "·": "text",
}

# Medidas base (para fuente tamaño 10); escalan con el zoom
ROW_H = 24
MAX_ROWS = 10
FOOT_H = 20
PAD = 8
ICON = 16
GAP = 8
MIN_W, MAX_W = 320, 580
BASE_SIZE = 10
HELP = "↑↓ navegar    Tab/Enter aceptar    Esc cerrar"


# ----------------------------------------------------------------------
#  Iconos (se cargan una sola vez)
# ----------------------------------------------------------------------
_icons = {}


def get_icon(name):
    img = _icons.get(name)
    if img is not None:
        return img
    path = os.path.join(ICON_DIR, f"{name}.png")
    try:
        img = tk.PhotoImage(file=path)
    except tk.TclError:
        img = _fallback_icon(name)
    _icons[name] = img
    return img


def _fallback_icon(name):
    color = FALLBACK.get(name, FALLBACK["text"])
    img = tk.PhotoImage(width=ICON, height=ICON)
    img.put(color, to=(1, 1, ICON - 1, ICON - 1))
    for x, y in ((1, 1), (ICON - 2, 1), (1, ICON - 2), (ICON - 2, ICON - 2)):   # esquinas redondeadas
        img.transparency_set(x, y, True)
    return img


def icon_for(item):
    return get_icon(item.get("icon") or KIND_TO_ICON.get(item.get("kind"), "text"))


def match_positions(prefix, label):
    """Índices de `label` que coinciden con lo escrito (para resaltarlos)."""
    if not prefix:
        return ()
    p, t = prefix.lower(), label.lower()
    i = t.find(p)
    if i >= 0:
        return tuple(range(i, i + len(p)))
    pos, j = [], 0
    for ch in p:                                        # letras en orden
        j = t.find(ch, j)
        if j < 0:
            return ()
        pos.append(j)
        j += 1
    return tuple(pos)


# ----------------------------------------------------------------------
#  Fuentes y medidas (una juego de fuentes por tamaño; medir texto es lo más caro)
# ----------------------------------------------------------------------
_fonts = {}
_measured = {}


def get_fonts(size=BASE_SIZE):
    size = max(6, int(size))
    f = _fonts.get(size)
    if f is None:
        label = tkfont.Font(family="Consolas", size=size)
        detail = tkfont.Font(family="Segoe UI", size=max(6, size - 2))
        f = _fonts[size] = {"label": label, "detail": detail, "cw": label.measure("0")}
    return f


def text_width(font, text):
    key = (id(font), text)
    w = _measured.get(key)
    if w is None:
        if len(_measured) > 4000:
            _measured.clear()
        w = _measured[key] = font.measure(text)
    return w


# ----------------------------------------------------------------------
#  Popup
# ----------------------------------------------------------------------
class SuggestPopup(tk.Frame):
    """on_accept(indice) se llama al hacer clic en una fila."""

    def __init__(self, master, on_accept, font_size=BASE_SIZE):
        super().__init__(master, bg=UI["select"])
        self.on_accept = on_accept
        self.canvas = tk.Canvas(self, bg=UI["panel"], highlightthickness=0, bd=0, takefocus=0)
        self.canvas.pack(padx=1, pady=1)

        self.rows, self.prefix = [], ""
        self.sel, self.top, self.hover = 0, 0, -1
        self.w = MIN_W
        self.shown = 0
        self.apply_size(font_size)

        c = self.canvas
        c.bind("<Button-1>", self._click)
        c.bind("<Motion>", self._motion)
        c.bind("<Leave>", lambda e: self._set_hover(-1))
        c.bind("<MouseWheel>", lambda e: (self.move(-1 if e.delta > 0 else 1), "break")[1])
        c.bind("<Button-4>", lambda e: (self.move(-1), "break")[1])
        c.bind("<Button-5>", lambda e: (self.move(1), "break")[1])

    def apply_size(self, font_size):
        """Escala fuentes, alto de fila, pie y anchos según el tamaño de fuente del editor."""
        fonts = get_fonts(font_size)
        self.f_label, self.f_detail, self.cw = fonts["label"], fonts["detail"], fonts["cw"]
        self.f_help = self.f_detail
        k = max(6, int(font_size)) / BASE_SIZE
        self.row_h = max(18, round(ROW_H * k))
        self.foot_h = max(16, round(FOOT_H * k))
        self.min_w = round(MIN_W * k)
        self.max_w = round(MAX_W * k)
        self.detail_cap = round(220 * k)
        if self.rows:                                    # ya hay datos: recalcula y redibuja
            self.set_rows(self.rows, self.prefix, keep_pos=True)

    # ------------------------------------------------------------- datos
    def set_rows(self, rows, prefix, keep_pos=False):
        sel, top = (self.sel, self.top) if keep_pos else (0, 0)
        self.rows, self.prefix = rows, prefix
        self.sel, self.top = sel, top
        self.hover = -1
        self.shown = min(len(rows), MAX_ROWS)

        label_w = max(len(r["label"]) for r in rows) * self.cw
        detail_w = max((text_width(self.f_detail, r["detail"][:90]) for r in rows if r.get("detail")),
                       default=0)
        want = (PAD + ICON + GAP + label_w
                + (24 + min(detail_w, self.detail_cap) if detail_w else 0) + PAD + 6)
        self.w = max(self.min_w, min(self.max_w, want))
        self.canvas.config(width=self.w, height=self.shown * self.row_h + self.foot_h)
        self.draw()

    def size(self):
        return self.w + 2, self.shown * self.row_h + self.foot_h + 2

    def selected(self):
        return self.sel if self.rows else None

    def move(self, d):
        if not self.rows:
            return
        self.sel = max(0, min(len(self.rows) - 1, self.sel + d))
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + MAX_ROWS:
            self.top = self.sel - MAX_ROWS + 1
        self.draw()

    # ------------------------------------------------------------ ratón
    def _row_at(self, y):
        if y < 0 or y >= self.shown * self.row_h:
            return -1
        i = self.top + y // self.row_h
        return i if i < len(self.rows) else -1

    def _click(self, event):
        i = self._row_at(event.y)
        if i >= 0:
            self.on_accept(i)
        return "break"                                   # sin quitarle el foco al texto

    def _motion(self, event):
        self._set_hover(self._row_at(event.y))

    def _set_hover(self, i):
        if i != self.hover:
            self.hover = i
            self.draw()

    # ------------------------------------------------------------ dibujo
    def _fit(self, text, font, max_w):
        text = text[:90]
        if text_width(font, text) <= max_w:
            return text
        while text and text_width(font, text + "…") > max_w:
            text = text[:-1]
        return text + "…"

    def draw(self):
        c = self.canvas
        c.delete("all")
        w, n = self.w, len(self.rows)
        accent = UI["accent"]
        rh = self.row_h

        for k in range(self.shown):
            i = self.top + k
            it = self.rows[i]
            y = k * rh
            mid = y + rh // 2

            if i == self.sel:
                c.create_rectangle(0, y, w, y + rh, fill=UI["select"], outline="")
                c.create_rectangle(0, y, 2, y + rh, fill=accent, outline="")
            elif i == self.hover:
                c.create_rectangle(0, y, w, y + rh, fill=UI["line_hl"], outline="")

            c.create_image(PAD, mid, image=icon_for(it), anchor="w")

            # etiqueta con las letras coincidentes resaltadas
            label, x = it["label"], PAD + ICON + GAP
            hit = set(match_positions(self.prefix, label))
            j = 0
            while j < len(label):
                k2 = j
                while k2 < len(label) and ((k2 in hit) == (j in hit)):
                    k2 += 1
                seg = label[j:k2]
                c.create_text(x, mid, text=seg, anchor="w", font=self.f_label,
                              fill=accent if j in hit else "#ffffff")
                x += len(seg) * self.cw
                j = k2

            detail = it.get("detail")
            if detail:
                room = w - x - 24 - PAD - (8 if n > MAX_ROWS else 0)
                if room > 40:
                    c.create_text(w - PAD - (8 if n > MAX_ROWS else 0), mid, anchor="e",
                                  text=self._fit(detail, self.f_detail, room),
                                  font=self.f_detail, fill=UI["muted"])

        # barra de desplazamiento (solo indicador)
        if n > MAX_ROWS:
            h = self.shown * rh
            bar = max(16, h * MAX_ROWS // n)
            y0 = (h - bar) * self.top // max(1, n - MAX_ROWS)
            c.create_rectangle(w - 5, y0 + 2, w - 2, y0 + bar - 2, fill=UI["muted"], outline="")

        # pie
        fy = self.shown * rh
        c.create_line(0, fy, w, fy, fill=UI["bg"])
        c.create_text(PAD, fy + self.foot_h // 2 + 1, text=HELP, anchor="w", font=self.f_help,
                      fill=UI["muted"])
        c.create_text(w - PAD, fy + self.foot_h // 2 + 1, text=f"{self.sel + 1}/{n}", anchor="e",
                      font=self.f_help, fill=UI["muted"])