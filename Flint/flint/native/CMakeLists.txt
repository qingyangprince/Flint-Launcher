cmake_minimum_required(VERSION 3.18)

project(flint_native VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

add_library(flint_native SHARED
  src/abort.cpp
  src/fs.cpp
  src/hash.cpp
  src/unzip.cpp
  src/version.cpp
  third_party/miniz/miniz.c
)

target_include_directories(flint_native
  PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_include_directories(flint_native SYSTEM PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/third_party/miniz
)

target_compile_definitions(flint_native
  PRIVATE FLINT_NATIVE_BUILD=1
)

set_target_properties(flint_native PROPERTIES
  OUTPUT_NAME flint_native
  C_VISIBILITY_PRESET hidden
  CXX_VISIBILITY_PRESET hidden
  VISIBILITY_INLINES_HIDDEN ON
)

if(WIN32)
  set_target_properties(flint_native PROPERTIES PREFIX "")
  target_compile_definitions(flint_native PRIVATE _CRT_SECURE_NO_WARNINGS NOMINMAX WIN32_LEAN_AND_MEAN)
endif()

if(MSVC)
  target_compile_options(flint_native PRIVATE /W4 /permissive- /utf-8)
  set_source_files_properties(third_party/miniz/miniz.c PROPERTIES COMPILE_OPTIONS "/w")
else()
  target_compile_options(flint_native PRIVATE -Wall -Wextra -Wpedantic)
  set_source_files_properties(third_party/miniz/miniz.c PROPERTIES COMPILE_OPTIONS "-w")
endif()

# `cmake --build . --target stage` 会把刚构建出的动态库复制到 Python 包旁边，
# 这样无需重新安装即可被 `python -m flint` 加载。
add_custom_target(stage
  COMMAND ${CMAKE_COMMAND} -E make_directory ${CMAKE_CURRENT_SOURCE_DIR}/../lib
  COMMAND ${CMAKE_COMMAND} -E copy_if_different $<TARGET_FILE:flint_native> ${CMAKE_CURRENT_SOURCE_DIR}/../lib/
  DEPENDS flint_native
  COMMENT "正在把 flint_native 复制到 flint/lib"
  VERBATIM
)
