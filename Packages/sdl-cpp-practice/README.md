# sdl-cpp-practice

Repositorio de practica de **C++ con SDL2**: tres ejemplos cortos y comentados, y un
paquete para **Blinker Code** que los compila y ejecuta con una tecla.

| Ejemplo | Que aprendes |
|---|---|
| `examples/01_window.cpp` | Ventana, renderer, bucle de eventos, limpieza |
| `examples/02_moving_rect.cpp` | Teclado, delta time, limites de la ventana |
| `examples/03_bouncing_balls.cpp` | `struct` + `vector`, gravedad y rebotes, mouse, circulos |

## 1. Instalar SDL2

- **Ubuntu/Debian:** `sudo apt install g++ pkg-config libsdl2-dev`
- **macOS (brew):** `brew install sdl2 pkg-config`
- **Windows (MSYS2 UCRT64):** `pacman -S mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-SDL2 mingw-w64-ucrt-x86_64-pkg-config`
- **Windows (MinGW "a mano"):** descarga `SDL2-devel-2.x.x-mingw.zip` de
  <https://github.com/libsdl-org/SDL/releases>, descomprimelo y define la variable de entorno
  `SDL2_DIR` con la ruta de la carpeta `x86_64-w64-mingw32` (la que contiene `include`, `lib` y `bin`).

## 2. Compilar a mano

```bash
g++ -std=c++17 examples/01_window.cpp -o 01_window $(pkg-config --cflags --libs sdl2)
./01_window
```

O con CMake:

```bash
cmake -S . -B build && cmake --build build
./build/01_window
```

## 3. Usarlo desde Blinker Code

En Blinker Code: **Packages > Install Package...** y escribe `TU-USUARIO/sdl-cpp-practice`.
Abre un `.cpp` y pulsa **F6** (o `Ctrl+Shift+P` > *SDL: Build & Run current file*).
(Para que aparezca en la lista de busqueda, agrega al repo el topic `blinker-package`.)

### Autocompletado y errores (LSP)

Blinker Code usa **clangd** para sugerir y subrayar errores. Para que conozca `SDL.h`, abre la carpeta
del repo y ejecuta `Ctrl+Shift+P` > **SDL: Create .clangd (autocomplete)**. Crea un archivo `.clangd`
con las rutas de SDL2 de tu equipo (es local; no lo subas a GitHub).

## Ejercicios

1. En el 01, cambia el color de fondo cuando pulses la barra espaciadora.
2. En el 02, haz que el cuadrado no salga de la ventana *rebotando* en vez de detenerse.
3. En el 02, agrega un segundo cuadrado controlado con las flechas y deja el primero con WASD.
4. En el 03, haz que el clic derecho elimine la pelota mas cercana.
5. En el 03, agrega rozamiento: que las pelotas pierdan velocidad horizontal al tocar el suelo.
6. Nuevo (04): dibuja texto con **SDL2_ttf** o carga una imagen con **SDL2_image**.
7. Nuevo (05): un *Pong* de dos jugadores usando todo lo anterior.
