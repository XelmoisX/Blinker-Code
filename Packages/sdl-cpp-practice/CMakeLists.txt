cmake_minimum_required(VERSION 3.10)
project(sdl_cpp_practice CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(SDL2 REQUIRED)

foreach(example 01_window 02_moving_rect 03_bouncing_balls)
    add_executable(${example} examples/${example}.cpp)
    target_include_directories(${example} PRIVATE ${SDL2_INCLUDE_DIRS})
    target_link_libraries(${example} PRIVATE ${SDL2_LIBRARIES})
endforeach()
