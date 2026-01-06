cmake_minimum_required(VERSION 3.16)

project(mpi_bully_sim
        VERSION 0.1.0
        LANGUAGES CXX)

# Require modern C++
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Find MPI
find_package(MPI REQUIRED)

# Fetch nlohmann_json
include(FetchContent)
FetchContent_Declare(
    nlohmann_json
    GIT_REPOSITORY https://github.com/nlohmann/json.git
    GIT_TAG v3.11.3
)
FetchContent_MakeAvailable(nlohmann_json)

add_executable(mpi_bully_sim
    src/main.cpp
)

# Link MPI and nlohmann_json to the target
target_link_libraries(mpi_bully_sim
    MPI::MPI_CXX
    nlohmann_json::nlohmann_json
)
