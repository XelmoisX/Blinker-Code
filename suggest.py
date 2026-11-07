"""Sugerencias de código (keywords, funciones integradas, snippets y palabras del archivo).

Funciona con o sin LSP. Es sensible al contexto: no sugiere dentro de comentarios ni
cadenas, ni después de '.', '->' o '::', ni cuando estás nombrando algo (def, class, fn...).

Cada sugerencia es un dict con el mismo formato que usa el popup del editor:
    filter, sort, label, insert, detail, kind   (+ "snippet": True en los snippets)
"""
import re, time

# ----------------------------------------------------------------------
#  Tablas por lenguaje
# ----------------------------------------------------------------------
ALIAS = {"c++": "cpp", "cc": "cpp", "cxx": "cpp", "js": "javascript", "ts": "typescript",
         "py": "python", "sh": "bash", "shell": "bash", "cs": "csharp", "golang": "go",
         "rs": "rust"}


def _w(text):
    return tuple(text.split())


KEYWORDS = {
    "python": _w("False None True and as assert async await break class continue def del elif "
                 "else except finally for from global if import in is lambda nonlocal not or "
                 "pass raise return try while with yield match case"),
    "c": _w("auto break case char const continue default do double else enum extern float for "
            "goto if inline int long register restrict return short signed sizeof static "
            "struct switch typedef union unsigned void volatile while bool true false NULL"),
    "cpp": _w("alignas alignof and asm auto bool break case catch char class const constexpr "
              "const_cast continue decltype default delete do double dynamic_cast else enum "
              "explicit export extern false final float for friend goto if inline int long "
              "mutable namespace new noexcept nullptr operator override private protected "
              "public register reinterpret_cast return short signed sizeof static "
              "static_assert static_cast struct switch template this thread_local throw true "
              "try typedef typeid typename union unsigned using virtual void volatile while"),
    "javascript": _w("async await break case catch class const continue debugger default delete "
                     "do else export extends false finally for function if import in instanceof "
                     "let new null of return static super switch this throw true try typeof "
                     "undefined var void while with yield"),
    "java": _w("abstract assert boolean break byte case catch char class const continue default "
               "do double else enum extends final finally float for goto if implements import "
               "instanceof int interface long native new null package private protected public "
               "return short static strictfp super switch synchronized this throw throws "
               "transient true false try var void volatile while record sealed permits"),
    "csharp": _w("abstract as base bool break byte case catch char checked class const continue "
                 "decimal default delegate do double else enum event explicit extern false "
                 "finally fixed float for foreach goto if implicit in int interface internal is "
                 "lock long namespace new null object operator out override params private "
                 "protected public readonly ref return sbyte sealed short sizeof stackalloc "
                 "static string struct switch this throw true try typeof uint ulong unchecked "
                 "unsafe ushort using virtual void volatile while var async await record get "
                 "set yield"),
    "rust": _w("as async await break const continue crate dyn else enum extern false fn for if "
               "impl in let loop match mod move mut pub ref return self Self static struct "
               "super trait true type unsafe use where while"),
    "go": _w("break case chan const continue default defer else fallthrough for func go goto if "
             "import interface map package range return select struct switch type var true "
             "false nil iota"),
    "lua": _w("and break do else elseif end false for function goto if in local nil not or "
              "repeat return then true until while"),
    "sql": _w("SELECT FROM WHERE INSERT INTO VALUES UPDATE SET DELETE CREATE TABLE ALTER DROP "
              "INDEX VIEW JOIN INNER LEFT RIGHT FULL OUTER CROSS ON AS AND OR NOT NULL IN "
              "BETWEEN LIKE ORDER BY GROUP HAVING LIMIT OFFSET DISTINCT UNION ALL EXISTS CASE "
              "WHEN THEN ELSE END PRIMARY KEY FOREIGN REFERENCES DEFAULT UNIQUE CHECK "
              "CONSTRAINT ASC DESC BEGIN COMMIT ROLLBACK TRANSACTION IS TRUE FALSE"),
    "bash": _w("if then else elif fi for while until do done case esac in function select time "
               "return exit break continue local export readonly declare unset shift source "
               "alias"),
}
KEYWORDS["typescript"] = KEYWORDS["javascript"] + _w(
    "abstract any as boolean declare enum implements interface keyof namespace never number "
    "private protected public readonly string symbol type unknown get set")

BUILTINS = {
    "python": _w("abs all any ascii bin bool breakpoint bytearray bytes callable chr classmethod "
                 "compile complex delattr dict dir divmod enumerate eval exec filter float "
                 "format frozenset getattr globals hasattr hash help hex id input int "
                 "isinstance issubclass iter len list locals map max memoryview min next "
                 "object oct open ord pow print property range repr reversed round set "
                 "setattr slice sorted staticmethod str sum super tuple type vars zip "
                 "self cls __init__ __name__ __main__ __file__ Exception ValueError TypeError "
                 "KeyError IndexError OSError RuntimeError StopIteration NotImplementedError"),
    "cpp": _w("std string vector map unordered_map set unordered_set array pair tuple cout cin "
              "cerr endl size_t int8_t int16_t int32_t int64_t uint8_t uint32_t uint64_t "
              "unique_ptr shared_ptr make_unique make_shared nullptr_t optional variant "
              "function printf scanf malloc free main"),
    "c": _w("printf scanf malloc calloc realloc free memcpy memset strlen strcpy strcmp "
            "size_t FILE fopen fclose fgets fprintf main stdin stdout stderr"),
    "javascript": _w("console log Math JSON Promise Array Object String Number Boolean Date Map "
                     "Set WeakMap Symbol RegExp Error parseInt parseFloat isNaN setTimeout "
                     "setInterval clearTimeout fetch document window require module exports "
                     "process globalThis"),
    "java": _w("System String Integer Double Boolean Long Character Math Object List ArrayList "
               "Map HashMap Set HashSet Optional Arrays Collections Scanner Thread Exception "
               "RuntimeException StringBuilder Override main println"),
    "csharp": _w("Console String Int32 Math List Dictionary HashSet Task Exception Array Linq "
                 "StringBuilder DateTime Guid File Path Environment WriteLine ReadLine"),
    "rust": _w("println! print! format! vec! panic! assert! Vec String Option Result Some None "
               "Ok Err Box Rc Arc HashMap HashSet BTreeMap main unwrap expect clone"),
    "go": _w("fmt Println Printf Sprintf Errorf make len cap append copy delete panic recover "
             "new string int int64 float64 bool byte rune error any main"),
    "lua": _w("print pairs ipairs table string math os io require tostring tonumber type pcall "
              "error assert select setmetatable getmetatable unpack insert remove concat sort"),
    "sql": _w("COUNT SUM AVG MIN MAX COALESCE CAST NOW LOWER UPPER TRIM LENGTH SUBSTRING "
              "CONCAT ROUND INT VARCHAR TEXT DATE TIMESTAMP BOOLEAN DECIMAL"),
    "bash": _w("echo cd ls pwd cat grep sed awk find mkdir rm cp mv chmod chown curl wget "
               "read printf test true false"),
}
BUILTINS["typescript"] = BUILTINS["javascript"]

# Snippets: (disparador, plantilla, solo_al_inicio_de_línea)
#   \t = un nivel de sangría   $0 = dónde queda el cursor
SNIPPETS = {
    "python": [
        ("ifmain", 'if __name__ == "__main__":\n\t$0', True),
        ("defn", "def $0():\n\t", True),
        ("cls", "class $0:\n\tdef __init__(self):\n\t\t", True),
        ("forin", "for $0 in :\n\t", True),
        ("tryexc", "try:\n\t$0\nexcept Exception as e:\n\t", True),
        ("wopen", 'with open("$0", "r", encoding="utf-8") as f:\n\t', True),
    ],
    "cpp": [
        ("main", "int main() {\n\t$0\n\treturn 0;\n}", True),
        ("fori", "for (int i = 0; i < $0; i++) {\n\t\n}", True),
        ("cls", "class $0 {\npublic:\n\t\nprivate:\n\t\n};", True),
        ("inc", "#include <$0>", True),
    ],
    "c": [
        ("main", "int main(void) {\n\t$0\n\treturn 0;\n}", True),
        ("fori", "for (int i = 0; i < $0; i++) {\n\t\n}", True),
        ("inc", "#include <$0>", True),
    ],
    "javascript": [
        ("clg", "console.log($0);", False),
        ("fori", "for (let i = 0; i < $0; i++) {\n\t\n}", True),
        ("forof", "for (const $0 of ) {\n\t\n}", True),
        ("afn", "const $0 = () => {\n\t\n};", True),
        ("tryc", "try {\n\t$0\n} catch (err) {\n\tconsole.error(err);\n}", True),
    ],
    "java": [
        ("main", "public static void main(String[] args) {\n\t$0\n}", True),
        ("sout", "System.out.println($0);", False),
        ("fori", "for (int i = 0; i < $0; i++) {\n\t\n}", True),
    ],
    "csharp": [
        ("cw", "Console.WriteLine($0);", False),
        ("fori", "for (int i = 0; i < $0; i++)\n{\n\t\n}", True),
        ("tryc", "try\n{\n\t$0\n}\ncatch (Exception ex)\n{\n\t\n}", True),
    ],
    "rust": [
        ("main", "fn main() {\n\t$0\n}", True),
        ("pl", 'println!("{}", $0);', False),
        ("impl", "impl $0 {\n\t\n}", True),
    ],
    "go": [
        ("main", "func main() {\n\t$0\n}", True),
        ("ife", "if err != nil {\n\treturn $0err\n}", True),
        ("forr", "for _, $0 := range  {\n\t\n}", True),
    ],
    "lua": [
        ("func", "function $0()\n\t\nend", True),
        ("fori", "for i = 1, $0 do\n\t\nend", True),
    ],
    "bash": [
        ("shebang", "#!/usr/bin/env bash\nset -euo pipefail\n$0", True),
    ],
}
SNIPPETS["typescript"] = SNIPPETS["javascript"]

# ----------------------------------------------------------------------
#  Contexto (¿dónde está el cursor?)
# ----------------------------------------------------------------------
LINE_COMMENT = {"python": "#", "bash": "#", "cpp": "//", "c": "//", "javascript": "//",
                "typescript": "//", "java": "//", "csharp": "//", "rust": "//", "go": "//",
                "lua": "--", "sql": "--"}
BLOCK_COMMENT = {"cpp", "c", "javascript", "typescript", "java", "csharp", "rust", "go", "sql"}
QUOTES = {"rust": '"', "javascript": "\"'`", "typescript": "\"'`", "go": "\"'`"}

DECL_RE = re.compile(r"\b(def|class|fn|func|function|struct|enum|namespace|interface|trait|"
                     r"let|var)\s+$")
WORD_RE = re.compile(r"[^\W\d]\w{2,39}")
MAX_DOC = 600_000


def context(language, before):
    """Devuelve 'code', 'string', 'comment', 'member' o 'decl' según lo que hay antes del cursor."""
    lang = ALIAS.get(language, language)
    if lang == "python" and (before.count('"""') % 2 or before.count("'''") % 2):
        return "string"

    prefix = LINE_COMMENT.get(lang)
    quotes = QUOTES.get(lang, "\"'")
    quote, i, n = None, 0, len(before)
    while i < n:
        c = before[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        else:
            if c in quotes:
                quote = c
            elif prefix and before.startswith(prefix, i) and (
                    prefix != "#" or i == 0 or before[i - 1].isspace()):
                return "comment"
            elif lang in BLOCK_COMMENT and before.startswith("/*", i):
                j = before.find("*/", i + 2)
                if j < 0:
                    return "comment"
                i = j + 2
                continue
        i += 1
    if quote:
        return "string"
    if before.endswith((".", "->", "::")):
        return "member"
    if DECL_RE.search(before):
        return "decl"
    return "code"


# ----------------------------------------------------------------------
#  Plantillas
# ----------------------------------------------------------------------
def expand_snippet(template, indent, unit):
    """Devuelve (texto, posición_del_cursor) respetando la sangría de la línea actual."""
    out = []
    for i, line in enumerate(template.split("\n")):
        line = line.replace("\t", unit)
        out.append(line if i == 0 else indent + line)
    body = "\n".join(out)
    pos = body.find("$0")
    if pos < 0:
        return body, len(body)
    return body.replace("$0", "", 1), pos


def _item(label, insert, kind, icon, detail, sort, filt=None, **extra):
    f = filt or label
    d = {"filter": f, "_f": f.lower(), "sort": sort, "label": label, "insert": insert,
         "detail": detail, "kind": kind, "icon": icon}
    d.update(extra)
    return d


# Listas fijas por lenguaje: se construyen UNA sola vez (no en cada tecla)
_STATIC = {}


def _static(lang, at_line_start):
    key = (lang, at_line_start)
    hit = _STATIC.get(key)
    if hit is not None:
        return hit
    upper = lang == "sql"
    items, taken = [], set()
    for kw in KEYWORDS.get(lang, ()):
        taken.add(kw.lower() if upper else kw)
        items.append(_item(kw, kw, "k", "keyword", "keyword", "z1", filt=kw.lower() if upper else kw))
    for b in BUILTINS.get(lang, ()):
        if b not in taken:
            taken.add(b)
            items.append(_item(b, b, "b", "builtin", "integrado", "z2"))
    for trig, tpl, stmt_only in SNIPPETS.get(lang, ()):
        if stmt_only and not at_line_start:
            continue
        preview = tpl.replace("$0", "").replace("\t", " ").replace("\n", " \u23ce ").strip()
        items.append(_item(trig, tpl, "s", "snippet", preview[:48], "z3", snippet=True))
    _STATIC[key] = (items, taken)
    return _STATIC[key]


# ----------------------------------------------------------------------
#  Motor
# ----------------------------------------------------------------------
class Suggester:
    """Uno por editor. Indexa las palabras del archivo de forma incremental (solo reanaliza
    las líneas que cambiaron) y reutiliza el resultado mientras el texto no cambie."""

    MAX_WORD_ITEMS = 40

    def __init__(self):
        self._rev = None
        self._index = []                 # [(palabra, minúscula, veces)] ordenado por frecuencia
        self._line_cache = {}            # texto de línea -> palabras (no se vuelve a analizar)
        self._last_build = 0.0

    def _words(self, get_code, rev):
        if rev == self._rev:
            return self._index
        now = time.monotonic()
        # archivos enormes: no reindexar en cada tecla
        if self._index and len(self._line_cache) > 8000 and now - self._last_build < 0.4:
            return self._index
        code = get_code()
        if len(code) > MAX_DOC:
            code = code[:MAX_DOC]
        cache = self._line_cache
        if len(cache) > 60000:
            cache.clear()
        counts = {}
        for line in code.split("\n"):
            if len(line) < 3:
                continue
            ws = cache.get(line)
            if ws is None:
                ws = cache[line] = tuple(WORD_RE.findall(line))
            for w in ws:
                counts[w] = counts.get(w, 0) + 1
        self._index = [(w, w.lower(), c) for w, c in
                       sorted(counts.items(), key=lambda t: (-t[1], t[0]))]
        self._rev, self._last_build = rev, now
        return self._index

    def suggest(self, language, before, prefix, get_code, rev, manual=False):
        lang = ALIAS.get(language, language)
        if context(lang, before) != "code":
            return []
        if prefix[:1].isdigit() or (not manual and len(prefix) < 2):
            return []

        static, taken = _static(lang, not before.strip())
        items = list(static)

        p = prefix.lower()
        n = 0
        for w, wl, c in self._words(get_code, rev):
            if wl == p or w in taken:
                continue
            if p and not (wl.startswith(p) or p in wl):
                continue
            items.append(_item(w, w, "w", "word", "en este archivo", f"z4{999 - min(c, 999):03d}"))
            n += 1
            if n >= self.MAX_WORD_ITEMS:
                break
        return items