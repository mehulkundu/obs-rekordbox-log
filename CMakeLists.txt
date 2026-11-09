cmake_minimum_required(VERSION 3.28...3.30)

include("${CMAKE_CURRENT_SOURCE_DIR}/cmake/common/bootstrap.cmake" NO_POLICY_SCOPE)

project(${_name} VERSION ${_version})

option(ENABLE_FRONTEND_API "Use obs-frontend-api for UI functionality" OFF)
option(ENABLE_QT "Use Qt functionality" OFF)

include(compilerconfig)
include(defaults)
include(helpers)

add_library(${CMAKE_PROJECT_NAME} MODULE)

find_package(libobs REQUIRED)
target_link_libraries(${CMAKE_PROJECT_NAME} PRIVATE OBS::libobs)

if(ENABLE_FRONTEND_API)
  find_package(obs-frontend-api REQUIRED)
  target_link_libraries(${CMAKE_PROJECT_NAME} PRIVATE OBS::obs-frontend-api)
endif()

if(ENABLE_QT)
  find_package(Qt6 COMPONENTS Widgets Core)
  target_link_libraries(${CMAKE_PROJECT_NAME} PRIVATE Qt6::Core Qt6::Widgets)
  target_compile_options(
    ${CMAKE_PROJECT_NAME}
    PRIVATE $<$<C_COMPILER_ID:Clang,AppleClang>:-Wno-quoted-include-in-framework-header -Wno-comma>
  )
  set_target_properties(
    ${CMAKE_PROJECT_NAME}
    PROPERTIES AUTOMOC ON AUTOUIC ON AUTORCC ON
  )
endif()

# The macOS 27 SDK has no AGL framework, but Qt 6's FindWrapOpenGL still links it
if(APPLE AND TARGET WrapOpenGL::WrapOpenGL)
  get_target_property(_gl_libs WrapOpenGL::WrapOpenGL INTERFACE_LINK_LIBRARIES)
  list(FILTER _gl_libs EXCLUDE REGEX "AGL")
  set_target_properties(WrapOpenGL::WrapOpenGL PROPERTIES INTERFACE_LINK_LIBRARIES "${_gl_libs}")
endif()

target_sources(
  ${CMAKE_PROJECT_NAME}
  PRIVATE src/plugin-main.cpp src/controllers.cpp src/session.cpp src/midi.cpp src/dock.cpp src/history.cpp
)
target_link_libraries(${CMAKE_PROJECT_NAME} PRIVATE "-framework CoreMIDI" "-framework CoreFoundation")

# SQLCipher (vendored, BSD) to read Rekordbox's encrypted library, read-only. Static and hidden, so it
# can't clash with the plain SQLite other plugins load.
add_library(sqlcipher STATIC deps/sqlcipher/sqlite3.c)
target_compile_definitions(
  sqlcipher
  PUBLIC SQLITE_HAS_CODEC
  PRIVATE
    SQLCIPHER_CRYPTO_CC
    SQLITE_TEMP_STORE=2
    SQLITE_THREADSAFE=1
    SQLITE_OMIT_LOAD_EXTENSION
    SQLITE_EXTRA_INIT=sqlcipher_extra_init
    SQLITE_EXTRA_SHUTDOWN=sqlcipher_extra_shutdown
)
target_include_directories(sqlcipher PUBLIC deps/sqlcipher)
target_compile_options(sqlcipher PRIVATE -w)
set_target_properties(sqlcipher PROPERTIES C_VISIBILITY_PRESET hidden COMPILE_WARNING_AS_ERROR OFF)
target_link_libraries(sqlcipher PUBLIC "-framework Security")
target_link_libraries(${CMAKE_PROJECT_NAME} PRIVATE sqlcipher)

set_target_properties_plugin(${CMAKE_PROJECT_NAME} PROPERTIES OUTPUT_NAME ${_name})
