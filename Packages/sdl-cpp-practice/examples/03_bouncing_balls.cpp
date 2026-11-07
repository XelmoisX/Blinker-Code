// Ejemplo 03 - Pelotas que rebotan
// Conceptos: structs + vector, fisica simple (gravedad y rebote), eventos del mouse,
//            dibujar un circulo con lineas horizontales (SDL no trae circulos).
// Controles: clic izquierdo = nueva pelota, tecla C = borrar todas, ESC = salir.
#include <SDL.h>
#include <cmath>
#include <cstdlib>
#include <vector>

struct Ball {
    float x, y;       // posicion
    float vx, vy;     // velocidad (px/s)
    int radius;
    Uint8 r, g, b;
};

void fillCircle(SDL_Renderer* renderer, int cx, int cy, int radius) {
    for (int dy = -radius; dy <= radius; ++dy) {
        int dx = (int)std::sqrt((float)(radius * radius - dy * dy));
        SDL_RenderDrawLine(renderer, cx - dx, cy + dy, cx + dx, cy + dy);
    }
}

int main(int argc, char* argv[]) {
    SDL_Init(SDL_INIT_VIDEO);
    const int W = 800, H = 600;
    SDL_Window* window = SDL_CreateWindow("Ejemplo 03 - Pelotas",
                                          SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, W, H, 0);
    SDL_Renderer* renderer = SDL_CreateRenderer(window, -1,
                                                SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    if (!renderer) renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_SOFTWARE);  // sin GPU

    std::vector<Ball> balls;
    const float gravity = 900;       // px/s^2
    const float bounce = 0.85f;      // energia que se conserva al rebotar

    bool running = true;
    Uint64 last = SDL_GetPerformanceCounter();

    while (running) {
        Uint64 now = SDL_GetPerformanceCounter();
        float dt = (now - last) / (float)SDL_GetPerformanceFrequency();
        last = now;

        SDL_Event e;
        while (SDL_PollEvent(&e)) {
            if (e.type == SDL_QUIT) running = false;
            if (e.type == SDL_KEYDOWN) {
                if (e.key.keysym.sym == SDLK_ESCAPE) running = false;
                if (e.key.keysym.sym == SDLK_c) balls.clear();
            }
            if (e.type == SDL_MOUSEBUTTONDOWN && e.button.button == SDL_BUTTON_LEFT) {
                Ball b;
                b.x = (float)e.button.x;
                b.y = (float)e.button.y;
                b.vx = (float)(std::rand() % 600 - 300);
                b.vy = (float)(std::rand() % 400 - 400);
                b.radius = 10 + std::rand() % 25;
                b.r = 80 + std::rand() % 176;
                b.g = 80 + std::rand() % 176;
                b.b = 80 + std::rand() % 176;
                balls.push_back(b);
            }
        }

        // fisica
        for (Ball& b : balls) {
            b.vy += gravity * dt;
            b.x += b.vx * dt;
            b.y += b.vy * dt;

            if (b.x - b.radius < 0)  { b.x = (float)b.radius;      b.vx = -b.vx * bounce; }
            if (b.x + b.radius > W)  { b.x = (float)(W - b.radius); b.vx = -b.vx * bounce; }
            if (b.y + b.radius > H)  { b.y = (float)(H - b.radius); b.vy = -b.vy * bounce; }
            if (b.y - b.radius < 0)  { b.y = (float)b.radius;      b.vy = -b.vy * bounce; }
        }

        // dibujo
        SDL_SetRenderDrawColor(renderer, 32, 34, 37, 255);
        SDL_RenderClear(renderer);
        for (const Ball& b : balls) {
            SDL_SetRenderDrawColor(renderer, b.r, b.g, b.b, 255);
            fillCircle(renderer, (int)b.x, (int)b.y, b.radius);
        }
        SDL_RenderPresent(renderer);
    }

    SDL_DestroyRenderer(renderer);
    SDL_DestroyWindow(window);
    SDL_Quit();
    return 0;
}
