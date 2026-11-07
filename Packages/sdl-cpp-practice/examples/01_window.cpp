// Ejemplo 01 - Ventana y bucle principal
// Conceptos: SDL_Init, ventana, renderer, bucle de eventos, limpieza.
#include <SDL2/SDL.h>
#include <iostream>

int main(int argc, char* argv[]) {
    if (SDL_Init(SDL_INIT_VIDEO) != 0) {
        std::cerr << "SDL_Init fallo: " << SDL_GetError() << "\n";
        return 1;
    }

    SDL_Window* window = SDL_CreateWindow("Ejemplo 01 - Ventana",
                                          SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
                                          800, 600, SDL_WINDOW_SHOWN);
    SDL_Renderer* renderer = SDL_CreateRenderer(window, -1,
                                                SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    if (!renderer) renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_SOFTWARE);  // sin GPU
    if (!window || !renderer) {
        std::cerr << "No se pudo crear la ventana: " << SDL_GetError() << "\n";
        return 1;
    }

    bool running = true;
    SDL_Event e;
    while (running) {
        // 1) Eventos
        while (SDL_PollEvent(&e)) {
            if (e.type == SDL_QUIT) running = false;
            if (e.type == SDL_KEYDOWN && e.key.keysym.sym == SDLK_ESCAPE) running = false;
        }

        // 2) Dibujo
        SDL_SetRenderDrawColor(renderer, 32, 34, 37, 255);   // color de fondo
        SDL_RenderClear(renderer);
        SDL_RenderPresent(renderer);
    }

    SDL_DestroyRenderer(renderer);
    SDL_DestroyWindow(window);
    SDL_Quit();
    return 0;
}
