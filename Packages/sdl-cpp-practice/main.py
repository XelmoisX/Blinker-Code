"""Paquete de Blinker Code: compilar y ejecutar archivos C++ que usan SDL2.

Agrega a la paleta (Ctrl+Shift+P):
    SDL: Build & Run current file      (tambien con F6)
    SDL: Open examples folder
    SDL: Create .clangd (autocomplete) -> le dice a clangd donde estan los headers de SDL

Como encuentra SDL2:
    1. pkg-config / sdl2-config  (Linux, macOS con brew, MSYS2)
    2. variable de entorno SDL2_DIR (Windows + MinGW): la carpeta
       "x86_64-w64-mingw32" del zip SDL2-devel-...-mingw, la que tiene include/ lib/ bin/
"""
import json
import os
import shlex
import shutil
import subprocess


def _sdl_flags():
    for cmd in (["pkg-config", "--cflags", "--libs", "sdl2"], ["sdl2-config", "--cflags", "--libs"]):
        if shutil.which(cmd[0]):
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if res.returncode == 0 and res.stdout.strip():
                    return " ".join(res.stdout.split()), None
            except Exception:
                pass
    d = os.environ.get("SDL2_DIR")
    if d:
        d = d.replace("\\", "/").rstrip("/")
        dll = os.path.join(d, "bin", "SDL2.dll")
        flags = f'-I"{d}/include/SDL2" -L"{d}/lib" -lmingw32 -lSDL2main -lSDL2'
        return flags, (dll if os.path.isfile(dll) else None)
    return None, None


def build_and_run(api):
    app, ed = api.app, api.editor()
    if ed is None:
        api.message("No hay ningun archivo abierto.", error=True)
        return
    if app.terminal.running:
        api.message("Ya hay un build en ejecucion (Tools > Stop Build).")
        return
    if not app.save_file():
        return

    path = ed.file_path
    if os.path.splitext(path)[1].lower() not in (".cpp", ".cc", ".cxx"):
        api.message("Este comando es para archivos C++ (.cpp).", error=True)
        return

    flags, dll = _sdl_flags()
    if flags is None:
        api.message("No encontre SDL2. Instala SDL2 (ver README) o define SDL2_DIR.", error=True)
        return

    folder, name = os.path.split(path)
    stem = os.path.splitext(name)[0]
    out = os.path.join(folder, stem + (".exe" if os.name == "nt" else ""))
    if dll and not os.path.isfile(os.path.join(folder, "SDL2.dll")):
        shutil.copy(dll, folder)                       # el .exe necesita SDL2.dll al lado

    command = f'g++ -std=c++17 -Wall "{path}" -o "{out}" {flags} && "{out}"'
    app.show_terminal()
    app.terminal.clear()
    app.terminal.set_cwd(folder)
    app.terminal.write(f"[SDL] {name}\n> {command}\n\n", "info")
    app.terminal.run(command)


def write_clangd(api):
    """Crea .clangd en la carpeta del proyecto para que clangd (autocompletado y errores) encuentre SDL.h."""
    app, ed = api.app, api.editor()
    flags, _ = _sdl_flags()
    if flags is None:
        api.message("No encontre SDL2 (ver README).", error=True)
        return
    keep = [t for t in shlex.split(flags) if t.startswith(("-I", "-D", "-std"))]
    if not any(t.startswith("-std") for t in keep):
        keep.insert(0, "-std=c++17")
    root = app.sidebar.root_path or (os.path.dirname(ed.file_path) if ed and ed.file_path else None)
    if not root:
        api.message("Abre una carpeta (File > Open Folder) o guarda el archivo primero.", error=True)
        return
    target = os.path.join(root, ".clangd")
    with open(target, "w", encoding="utf-8") as f:
        f.write("CompileFlags:\n  Add: [" + ", ".join(json.dumps(t) for t in keep) + "]\n")
    api.message(f"Creado {target}")
    if hasattr(app, "restart_lsp"):
        app.restart_lsp()                                  # clangd relee la configuracion


def register(api):
    api.add_command("SDL: Build & Run current file", lambda: build_and_run(api))
    api.add_command("SDL: Open examples folder",
                    lambda: api.app.open_folder(os.path.join(api.path, "examples")))
    api.add_command("SDL: Create .clangd (autocomplete)", lambda: write_clangd(api))
    api.add_shortcut("<F6>", lambda: build_and_run(api))
