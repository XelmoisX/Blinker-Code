// Ejemplo 02 - Mover un rectangulo con el teclado
// Conceptos: estado del teclado, delta time (movimiento independiente de los FPS), limites.
// Controles: flechas o WASD. ESC para salir.
#include <SDL.h>
#include <algorithm>

int main(int argc, char* argv[]) {
    SDL_Init(SDL_INIT_VIDEO);
    const int W = 800, H = 600;
    SDL_Window* window = SDL_CreateWindow("Ejemplo 02 - Mover rectangulo",
                                          SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, W, H, 0);
    SDL_Renderer* renderer = SDL_CreateRenderer(window, -1,
                                                SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    if (!renderer) renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_SOFTWARE);  // sin GPU

    float x = 100, y = 100;          // posicion
    const float size = 60;           // lado del cuadrado
    const float speed = 300;         // pixeles por segundo

    bool running = true;
    Uint64 last = SDL_GetPerformanceCounter();

    while (running) {
        // delta time en segundos
        Uint64 now = SDL_GetPerformanceCounter();
        float dt = (now - last) / (float)SDL_GetPerformanceFrequency();
        last = now;

        SDL_Event e;
        while (SDL_PollEvent(&e)) {
            if (e.type == SDL_QUIT) running = false;
            if (e.type == SDL_KEYDOWN && e.key.keysym.sym == SDLK_ESCAPE) running = false;
        }

        const Uint8* keys = SDL_GetKeyboardState(nullptr);
        if (keys[SDL_SCANCODE_LEFT]  || keys[SDL_SCANCODE_A]) x -= speed * dt;
        if (keys[SDL_SCANCODE_RIGHT] || keys[SDL_SCANCODE_D]) x += speed * dt;
        if (keys[SDL_SCANCODE_UP]    || keys[SDL_SCANCODE_W]) y -= speed * dt;
        if (keys[SDL_SCANCODE_DOWN]  || keys[SDL_SCANCODE_S]) y += speed * dt;

        // no salir de la ventana
        x = std::clamp(x, 0.0f, W - size);
        y = std::clamp(y, 0.0f, H - size);

        SDL_SetRenderDrawColor(renderer, 32, 34, 37, 255);
        SDL_RenderClear(renderer);

        SDL_Rect rect = { (int)x, (int)y, (int)size, (int)size };
        SDL_SetRenderDrawColor(renderer, 80, 250, 123, 255);
        SDL_RenderFillRect(renderer, &rect);

        SDL_RenderPresent(renderer);
    }

    SDL_DestroyRenderer(renderer);
    SDL_DestroyWindow(window);
    SDL_Quit();
    return 0;
}
