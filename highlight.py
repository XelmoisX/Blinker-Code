"""highlight.py - Sistema de resaltado de sintaxis (con re) para Blinker Code.

Este archivo NO depende de tkinter. Contiene:
    THEME_COLORS        colores del tema (un color por tag)
    KEYWORDS            keywords de cada lenguaje, divididas por categoría
    register_language   para agregar un lenguaje nuevo
    EXT_LANG            extensión de archivo -> lenguaje
    LANG_NAMES          lenguaje -> nombre que se muestra en la barra de estado
    resolve_language    normaliza un nombre ("py" -> "python")
    highlight_ranges    convierte un texto en rangos (tag, inicio, fin) para tkinter
"""
import re
from bisect import bisect_right


# ======================================================================
#  TEMA  (cada tag = un color).  Los 7 primeros son los de siempre.
# ======================================================================
THEME_COLORS = {
    # --- colores originales ---
    "Keyword": "#ff79c6",     # keyword sin categoría (Rosa)
    "Name": "#f8f8f2",        # Variables comunes (Blanco/Gris claro)
    "Function": "#50fa7b",    # Nombres de funciones (Verde)
    "String": "#f1fa8c",      # "Texto entre comillas" (Amarillo)
    "Comment": "#6272a4",     # # Comentarios (Gris azulado)
    "Number": "#bd93f9",      # 123, 0.5 (Morado)
    "Operator": "#ff79c6",    # +, -, =, ==
    # --- categorías de keywords ---
    "KwControl": "#ff79c6",   # if, else, for, while, return, try, and, or, not (Rosa)
    "KwFunction": "#8be9fd",  # def, fn, func, function, lambda (Celeste)
    "KwClass": "#ffb86c",     # class, struct, enum, interface, trait (Naranja)
    "KwImport": "#ff6e6e",    # import, from, include, using, use, package (Rojo)
    "KwConstant": "#c792ea",  # True, False, None, null, nil, this, self (Lila)
    "KwType": "#82aaff",      # int, float, str, bool, void, char (Azul)
    "KwModifier": "#1abc9c",  # static, const, public, private, async, await (Turquesa)
    # --- nombres ---
    "ClassName": "#ffd9a0",   # Nombre de una clase: class Perro / Perro() (Naranja claro)
}


# ======================================================================
#  KEYWORDS DE VARIOS LENGUAJES, DIVIDIDAS POR CATEGORÍA
#  (aquí es donde se agregan / editan; cada categoría tiene su color)
# ======================================================================
def _kw(control="", function="", cls="", imp="", const="", type_="", mod="", builtin=""):
    """Convierte textos separados por espacios en el diccionario categoría -> palabras."""
    table = {
        "KwControl": control,     # flujo y operadores en palabras
        "KwFunction": function,   # definir funciones
        "KwClass": cls,           # definir clases / estructuras
        "KwImport": imp,          # importar módulos
        "KwConstant": const,      # valores constantes
        "KwType": type_,          # tipos de datos
        "KwModifier": mod,        # modificadores
        "Function": builtin,      # comandos / funciones integradas (color de función)
    }
    return {tag: words.split() for tag, words in table.items() if words}


KEYWORDS = {
    "python": _kw(
        control="and assert break continue del elif else except finally for if in is "
                "not or pass raise return try while with yield",
        function="def lambda",
        cls="class",
        imp="import from as",
        const="True False None self cls",
        type_="int float str bool list dict set tuple bytes complex",
        mod="async await global nonlocal",
    ),
    "cpp": _kw(
        control="alignas alignof and break case catch const_cast continue decltype default "
                "delete do dynamic_cast else for goto if new noexcept not or "
                "reinterpret_cast return sizeof static_assert static_cast switch throw try "
                "typeid while",
        function="operator",
        cls="class enum namespace struct template typedef typename union",
        imp="using",
        const="false nullptr this true",
        type_="auto bool char double float int long short signed unsigned void",
        mod="asm const constexpr explicit export extern final friend inline mutable "
            "override private protected public register static virtual volatile",
    ),
    "javascript": _kw(
        control="break case catch continue debugger default delete do else finally for if in "
                "instanceof new of return switch throw try typeof void while with yield",
        function="function",
        cls="class extends",
        imp="import export",
        const="false null super this true undefined",
        mod="async await const get let set static var",
    ),
    "typescript": _kw(
        control="break case catch continue default delete do else finally for if in instanceof "
                "keyof new of return switch throw try typeof void while yield",
        function="function",
        cls="class enum extends implements interface namespace type",
        imp="as export import",
        const="false null super this true undefined",
        type_="any boolean never number string unknown",
        mod="abstract async await const declare let private protected public readonly "
            "static var",
    ),
    "java": _kw(
        control="assert break case catch continue default do else finally for goto if "
                "instanceof new return switch throw throws try while",
        cls="class enum extends implements interface record",
        imp="import package",
        const="false null super this true",
        type_="boolean byte char double float int long short var void",
        mod="abstract const final native private protected public static strictfp "
            "synchronized transient volatile",
    ),
    "csharp": _kw(
        control="as break case catch checked continue default do else finally fixed for "
                "foreach goto if in is lock new return sizeof switch throw try typeof "
                "unchecked while yield",
        function="delegate operator",
        cls="class enum interface namespace record struct",
        imp="using",
        const="base false null this true",
        type_="bool byte char decimal double float int long object sbyte short string uint "
              "ulong ushort var void",
        mod="abstract async await const event explicit extern get implicit internal out "
            "override params private protected public readonly ref sealed set static "
            "unsafe virtual volatile",
    ),
    "rust": _kw(
        control="break continue else for if in loop match return while",
        function="fn",
        cls="enum impl mod struct trait type",
        imp="as crate extern use",
        const="false self Self super true",
        type_="bool char f32 f64 i8 i16 i32 i64 i128 isize str u8 u16 u32 u64 u128 usize",
        mod="async await const dyn let move mut pub ref static unsafe where",
    ),
    "go": _kw(
        control="break case continue default defer else fallthrough for go goto if range "
                "return select switch",
        function="func",
        cls="interface struct type",
        imp="import package",
        const="false iota nil true",
        type_="any bool byte chan error float32 float64 int int8 int16 int32 int64 map "
              "rune string uint",
        mod="const var",
    ),
    "lua": _kw(
        control="and break do else elseif end for goto if in not or repeat return then "
                "until while",
        function="function",
        const="false nil true",
        mod="local",
    ),
    "sql": _kw(
        control="SELECT FROM WHERE INSERT INTO VALUES UPDATE SET DELETE JOIN INNER LEFT RIGHT "
                "FULL OUTER ON AS AND OR NOT IN IS LIKE BETWEEN ORDER BY GROUP HAVING LIMIT "
                "OFFSET DISTINCT UNION ALL EXISTS CASE WHEN THEN ELSE END BEGIN COMMIT "
                "ROLLBACK ASC DESC",
        cls="CREATE TABLE ALTER DROP INDEX VIEW",
        const="NULL TRUE FALSE",
        type_="INT INTEGER VARCHAR TEXT DATE BOOLEAN",
        mod="PRIMARY KEY FOREIGN REFERENCES DEFAULT UNIQUE CHECK CONSTRAINT",
        builtin="COUNT SUM AVG MIN MAX",
    ),
    "bash": _kw(
        control="break case continue do done elif else esac exit fi for if in return select "
                "then until while",
        function="function",
        imp="source",
        const="false true",
        mod="declare export local readonly",
        builtin="alias cd echo shift unset",
    ),
}


# ======================================================================
#  SISTEMA DE HIGHLIGHT CON re
# ======================================================================
def _words(*words):
    """Crea un patrón que coincide con cualquiera de las palabras completas."""
    return r"\b(?:" + "|".join(words) + r")\b"


def _keyword_rules(keywords, ignore_case=False):
    """Una regla por categoría: cada una usa el color de su tag."""
    if not isinstance(keywords, dict):          # lista simple -> tag "Keyword"
        keywords = {"Keyword": keywords}
    rules = []
    for tag, words in keywords.items():
        if words:
            pattern = _words(*words)
            rules.append((tag, f"(?i:{pattern})" if ignore_case else pattern))
    return rules


NUMBER = (r"(?<![\w.])(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|"
          r"\d[\d_]*\.?[\d_]*(?:[eE][+-]?\d+)?)(?:[iu]size|[iuf]\d+|[uUlLfFnNdD]*)\b")
OPERATOR = r"[+\-*/%=<>!&|^~]+"
CLASS_CALL = r"\b[A-Z]\w*(?=\s*\()"            # Perro(  ->  nombre de clase
FUNC_CALL = r"\b[A-Za-z_]\w*(?=\s*\()"         # nombre(  ->  función


def make_rules(keywords, line_comment=(), block_comment=(), strings=('"', "'"),
               backtick=False, preproc=False, ignore_case=False,
               names_after=(), extra=(), calls=True, class_calls=False):
    """Genera la lista de reglas (tag, patrón) para un lenguaje estilo C.

    keywords      dict categoría -> palabras (ver KEYWORDS) o una lista simple
    line_comment  "//" o ("//", "#")
    block_comment ("/*", "*/")
    strings       comillas que abren/cierran strings en una línea
    backtick      strings con `...` multilínea (JS, Go)
    preproc       líneas #include / #define (C, C++, C#)
    ignore_case   keywords sin distinguir mayúsculas (SQL)
    names_after   {"class": "ClassName", "fn": "Function"}: palabra -> tag del
                  nombre que viene después (también acepta una lista = Function)
    extra         reglas adicionales [(tag, patrón)]
    class_calls   Perro( se pinta como nombre de clase
    """
    if isinstance(line_comment, str):
        line_comment = (line_comment,)
    if not isinstance(names_after, dict):
        names_after = {w: "Function" for w in names_after}

    rules = []
    if block_comment:                     # antes que el de línea (Lua: --[[ ]])
        start, end = block_comment
        rules.append(("Comment", re.escape(start) + r"[\s\S]*?(?:" + re.escape(end) + r"|\Z)"))
    for lc in line_comment:
        rules.append(("Comment", re.escape(lc) + r"[^\n]*"))
    if preproc:
        rules.append(("KwImport", r"^[ \t]*#[ \t]*(?:include|import)\b"))
        rules.append(("Keyword", r"^[ \t]*#[ \t]*\w+"))
        rules.append(("String", r"(?<=include )<[^>\n]*>"))
    for q in strings:
        rules.append(("String", rf"{q}(?:\\.|[^{q}\\\n])*{q}?"))
    if backtick:
        rules.append(("String", r"`(?:\\.|[^`\\])*`?"))
    rules.extend(extra)
    for word, tag in names_after.items():
        rules.append((tag, rf"(?<=\b{word} )\w+"))

    rules.extend(_keyword_rules(keywords, ignore_case))
    if class_calls:
        rules.append(("ClassName", CLASS_CALL))
    if calls:
        rules.append(("Function", FUNC_CALL))
    rules.append(("Number", NUMBER))
    rules.append(("Operator", OPERATOR))
    return rules


# Python va aparte por los strings """ """, los prefijos f"" y los decoradores
PY_STRING = (
    r'(?<!\w)(?:[rRbBuUfF]{1,2})?(?:'
    r'"""[\s\S]*?(?:"""|\Z)'
    r"|'''[\s\S]*?(?:'''|\Z)"
    r'|"(?:\\.|[^"\\\n])*"?'
    r"|'(?:\\.|[^'\\\n])*'?"
    r')'
)

PY_RULES = [
    ("Comment",   r"#[^\n]*"),
    ("String",    PY_STRING),
    ("Function",  r"@[A-Za-z_][\w.]*"),                  # decoradores
    ("Function",  r"(?<=\bdef )\w+"),                    # def nombre
    ("ClassName", r"(?<=\bclass )\w+"),                  # class Nombre
    *_keyword_rules(KEYWORDS["python"]),
    ("ClassName", CLASS_CALL),                           # Perro(
    ("Function",  FUNC_CALL),                            # nombre(
    ("Number",    NUMBER + r"|\d[\d_]*[jJ]\b"),
    ("Operator",  OPERATOR),
]

JSON_RULES = [
    ("Function",   r'"(?:\\.|[^"\\\n])*"(?=\s*:)'),      # claves
    ("String",     r'"(?:\\.|[^"\\\n])*"?'),
    ("KwConstant", _words("true", "false", "null")),
    ("Number",     r"-?\b\d+\.?\d*(?:[eE][+-]?\d+)?\b"),
]

HTML_RULES = [
    ("Comment",  r"<!--[\s\S]*?(?:-->|\Z)"),
    ("String",   r'(?<==)"[^"\n]*"?'),
    ("String",   r"(?<==)'[^'\n]*'?"),
    ("Keyword",  r"</?[A-Za-z][\w:-]*|<![A-Za-z]+"),      # <div  </div  <!DOCTYPE
    ("Function", r"\b[A-Za-z_:@][\w:.-]*(?==)"),          # atributos
    ("Operator", r"/?>|="),
]

CSS_RULES = [
    ("Comment",  r"/\*[\s\S]*?(?:\*/|\Z)"),
    ("String",   r'"(?:\\.|[^"\\\n])*"?'),
    ("String",   r"'(?:\\.|[^'\\\n])*'?"),
    ("KwImport", r"@[\w-]+"),                             # @media @import
    ("Number",   r"#[0-9a-fA-F]{3,8}\b"),
    ("KwClass",  r"[.#][A-Za-z_][\w-]*"),                 # .clase  #id
    ("Function", r"[A-Za-z-]+(?=\s*:(?!:))"),             # propiedades
    ("Number",   r"(?<![\w-])-?\d*\.?\d+(?:px|em|rem|%|vh|vw|ms|s|deg|pt)?"),
    ("Operator", r"[{}:;,>+~*]"),
]

# Se llenan con register_language()
LANGUAGE_RULES = {"text": []}       # texto plano: no se colorea nada
LANG_NAMES = {"text": "Text"}       # nombre que se muestra en la barra de estado
EXT_LANG = {".txt": "text"}         # extensión -> lenguaje

# Alias para aceptar varios nombres de un mismo lenguaje
LANGUAGE_ALIASES = {
    "py": "python", "python3": "python",
    "c": "cpp", "c++": "cpp", "h": "cpp", "hpp": "cpp",
    "js": "javascript", "ts": "typescript", "c#": "csharp", "cs": "csharp",
    "rs": "rust", "sh": "bash", "shell": "bash",
    "txt": "text", "plain": "text", "plaintext": "text",
}

_highlighter_cache = {}


def register_language(name, rules, display=None, extensions=()):
    """Registra un lenguaje: sus reglas, su nombre visible y sus extensiones."""
    LANGUAGE_RULES[name] = rules
    LANG_NAMES[name] = display or name.capitalize()
    for ext in extensions:
        EXT_LANG[ext] = name
    _highlighter_cache.pop(name, None)


C_LIKE = dict(line_comment="//", block_comment=("/*", "*/"))
FN, CL = "Function", "ClassName"      # tags de los nombres que siguen a def / class

register_language("python", PY_RULES, "Python", (".py", ".pyw"))
register_language("cpp", make_rules(KEYWORDS["cpp"], preproc=True,
                                    names_after={"class": CL, "struct": CL, "enum": CL}, **C_LIKE),
                  "C/C++", (".c", ".h", ".cpp", ".hpp", ".cc", ".cxx"))
register_language("javascript", make_rules(KEYWORDS["javascript"], backtick=True, class_calls=True,
                                           names_after={"function": FN, "class": CL}, **C_LIKE),
                  "JavaScript", (".js", ".mjs"))
register_language("typescript", make_rules(KEYWORDS["typescript"], backtick=True, class_calls=True,
                                           names_after={"function": FN, "class": CL, "interface": CL,
                                                        "type": CL, "enum": CL}, **C_LIKE),
                  "TypeScript", (".ts", ".tsx"))
register_language("java", make_rules(KEYWORDS["java"], class_calls=True,
                                     names_after={"class": CL, "interface": CL, "enum": CL, "record": CL},
                                     **C_LIKE),
                  "Java", (".java",))
register_language("csharp", make_rules(KEYWORDS["csharp"], preproc=True,
                                       names_after={"class": CL, "struct": CL, "interface": CL,
                                                    "enum": CL, "record": CL}, **C_LIKE),
                  "C#", (".cs",))
register_language("rust", make_rules(KEYWORDS["rust"], strings=('"',),
                                     names_after={"fn": FN, "struct": CL, "enum": CL, "trait": CL, "impl": CL},
                                     extra=[("Function", r"\b\w+!(?=[(\[{])")], **C_LIKE),
                  "Rust", (".rs",))
register_language("go", make_rules(KEYWORDS["go"], backtick=True,
                                   names_after={"func": FN, "type": CL}, **C_LIKE),
                  "Go", (".go",))
register_language("lua", make_rules(KEYWORDS["lua"], line_comment="--", block_comment=("--[[", "]]"),
                                    names_after={"function": FN}),
                  "Lua", (".lua",))
register_language("sql", make_rules(KEYWORDS["sql"], line_comment="--", block_comment=("/*", "*/"),
                                    strings=("'",), ignore_case=True),
                  "SQL", (".sql",))
register_language("bash", make_rules(KEYWORDS["bash"], line_comment="#", names_after={"function": FN}),
                  "Bash", (".sh", ".bash"))
register_language("json", JSON_RULES, "JSON", (".json",))
register_language("html", HTML_RULES, "HTML", (".html", ".htm"))
register_language("css", CSS_RULES, "CSS", (".css",))


class Highlighter:
    """Compila las reglas de un lenguaje en UNA sola expresión regular.

    El orden de las reglas es la prioridad: si dos reglas coinciden en la
    misma posición, gana la que esté primero en la lista.
    """

    def __init__(self, rules):
        self.group_tag = {}
        parts = []
        for i, (tag, pattern) in enumerate(rules):
            group = f"t{i}"
            self.group_tag[group] = tag
            parts.append(f"(?P<{group}>{pattern})")
        self.regex = re.compile("|".join(parts), re.MULTILINE) if parts else None

    def tokens(self, code):
        """Devuelve tuplas (tag, inicio, fin) con posiciones en caracteres."""
        if self.regex is None:
            return
        for m in self.regex.finditer(code):
            if m.end() > m.start():
                yield self.group_tag[m.lastgroup], m.start(), m.end()


def resolve_language(language):
    name = (language or "text").lower()
    name = LANGUAGE_ALIASES.get(name, name)
    return name if name in LANGUAGE_RULES else "text"


def get_highlighter(language):
    name = resolve_language(language)
    if name not in _highlighter_cache:
        _highlighter_cache[name] = Highlighter(LANGUAGE_RULES[name])
    return _highlighter_cache[name]


def highlight_ranges(code, language):
    """Devuelve (tag, inicio, fin) con índices de tkinter ("linea.columna").

    Se usa así en el editor:
        for tag, start, end in highlight_ranges(codigo, "python"):
            text_widget.tag_add(tag, start, end)
    """
    highlighter = get_highlighter(language)

    # Posición (en caracteres) donde empieza cada línea, para convertir
    # un offset del string a un índice "linea.columna" de Tk.
    line_starts = [0]
    for m in re.finditer("\n", code):
        line_starts.append(m.end())

    def to_index(pos):
        line = bisect_right(line_starts, pos) - 1
        return f"{line + 1}.{pos - line_starts[line]}"

    for tag, start, end in highlighter.tokens(code):
        yield tag, to_index(start), to_index(end)