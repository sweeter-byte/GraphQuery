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