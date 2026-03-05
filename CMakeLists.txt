cmake_minimum_required(VERSION 3.21)
project(Fastest)

message(STATUS "C Compiler: ${CMAKE_C_COMPILER}")
message(STATUS "C++ Compiler: ${CMAKE_CXX_COMPILER}")

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=c++20 -Ofast")
# 添加调试符号并保持优化
#set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=c++20 -Ofast -ggdb3 -funwind-tables -fno-omit-frame-pointer")  # 关键修改1：添加-ggdb3

find_package(OpenMP REQUIRED)
find_package(Boost REQUIRED COMPONENTS system filesystem)
find_package(GSL REQUIRED)
find_package(TBB REQUIRED)

# ===== Target 1: CLI executable =====
file(GLOB_RECURSE SOURCES
    "driver/*.cc"
)

add_executable(Fastest ${SOURCES})

target_include_directories(Fastest PRIVATE
    ${Boost_INCLUDE_DIRS}
    ${GSL_INCLUDE_DIRS}
    ${CMAKE_SOURCE_DIR}/lib
)

target_link_libraries(Fastest
    PRIVATE
    OpenMP::OpenMP_CXX
    ${Boost_LIBRARIES}
    ${GSL_LIBRARIES}
    pthread
    TBB::tbb
)

# ===== Target 2: Pybind11 module (fastest_core.so) =====
find_package(pybind11 QUIET)
if(pybind11_FOUND)
    pybind11_add_module(fastest_core pybind/FastestPybind.cc)

    target_include_directories(fastest_core PRIVATE
        ${Boost_INCLUDE_DIRS}
        ${GSL_INCLUDE_DIRS}
        ${CMAKE_SOURCE_DIR}/lib
    )

    target_link_libraries(fastest_core
        PRIVATE
        OpenMP::OpenMP_CXX
        ${Boost_LIBRARIES}
        ${GSL_LIBRARIES}
        pthread
        TBB::tbb
    )

    # Install the .so next to the source for easy import
    set_target_properties(fastest_core PROPERTIES
        LIBRARY_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}"
    )

    message(STATUS "Pybind11 found: fastest_core module will be built")
else()
    message(STATUS "Pybind11 NOT found: fastest_core module will NOT be built. Install with: pip install pybind11")
endif()