"""build.py - Sistemas de build para Blinker Code (Tools > Build).

Este archivo NO depende de tkinter. Dado el archivo que está abierto,
identifica su lenguaje (por la extensión) y arma el comando a ejecutar.

Variables que se pueden usar dentro de un comando:
    {file}    ruta completa del archivo         C:\\proyecto\\hola.py
    {dir}     carpeta del archivo               C:\\proyecto
    {name}    nombre con extensión              hola.py
    {stem}    nombre sin extensión              hola
    {out}     ruta del ejecutable a generar     C:\\proyecto\\hola(.exe)
    {python}  el intérprete de Python que ejecuta el editor

Para agregar un lenguaje:
    register_build("kotlin", 'kotlinc "{file}" -include-runtime -d "{out}.jar" && java -jar "{out}.jar"')
"""
import os
import sys

# lenguaje (el mismo nombre que usa highlight.py) -> comando
BUILD_SYSTEMS = {
    "python":     '"{python}" "{file}"',
    "javascript": 'node "{file}"',
    "java":       'java "{file}"',                                  # JDK 11+ (archivo único)
    "cpp":        'g++ "{file}" -o "{out}" && "{out}"',
    "rust":       'rustc "{file}" -o "{out}" && "{out}"',
    "go":         'go run "{file}"',
    "lua":        'lua "{file}"',
    "bash":       'bash "{file}"',
}

# La extensión tiene prioridad sobre el lenguaje (.c y .cpp comparten lenguaje "cpp")
BUILD_BY_EXT = {
    ".c": 'gcc "{file}" -o "{out}" && "{out}"',
}


def register_build(language, command, extensions=()):
    """Agrega o reemplaza el build de un lenguaje (y opcionalmente de extensiones)."""
    BUILD_SYSTEMS[language] = command
    for ext in extensions:
        BUILD_BY_EXT[ext.lower()] = command


def get_build_command(file_path, language):
    """Devuelve el comando listo para ejecutar, o None si no hay build para ese archivo."""
    ext = os.path.splitext(file_path)[1].lower()
    template = BUILD_BY_EXT.get(ext) or BUILD_SYSTEMS.get(language)
    if not template:
        return None

    folder, name = os.path.split(os.path.abspath(file_path))
    stem = os.path.splitext(name)[0]
    out = os.path.join(folder, stem + (".exe" if os.name == "nt" else ""))

    return template.format(file=os.path.abspath(file_path), dir=folder, name=name,
                           stem=stem, out=out, python=sys.executable)