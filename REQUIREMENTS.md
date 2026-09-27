# Requirements

Status: done, partial, or planned.

## Functional

| ID | Requirement | Status |
|---|---|---|
| R1 | Build GCC with a compatible binutils in Docker | done |
| R2 | Build LLVM/Clang (any sub-projects and runtimes) in Docker | done |
| R3 | Ubuntu version is selectable (22.04, 24.04, 26.04, 26.10) | done |
| R4 | GCC / LLVM version is selectable; binutils defaults to the release matching the GCC series and is limited to a compatible range | done |
| R5 | GCC languages selectable (c, c++, fortran, ada, d, go, objc, obj-c++, m2, rust, cobol, algol68, jit), limited by GCC version | done |
| R6 | GCC configure and build options (bootstrap mode, checking, LTO, multilib, PIE, -march, ...) and binutils options | done |
| R7 | LLVM projects, targets, build options, clang defaults and runtime options | done |
| R8 | Compilation flags configurable (GCC build/target CFLAGS, LLVM C/C++ flags, raw extra configure/CMake args) | done |
| R9 | Options, their flags, version limits, dependencies and checks are defined in JSON, not code | done |
| R10 | Curses menu UI with box drawing, in the style of ../tools | done |
| R11 | Two Dockerfiles; all prerequisite packages in a cached first layer | done |
| R12 | Build args placed as late as possible so a library option does not rebuild the compiler (LLVM: always; GCC: when bootstrap is off, as far as GCC's build allows) | done |
| R13 | Save/load configurations as profiles | done |
| R14 | Build from the menu, export the install tree, write a build script; the same from the command line | done |
| R15 | Refresh release lists from upstream | done |
| R16 | Installed (pipx) use: `toolchain-tool init` copies catalog/docker to a user data directory that is found automatically | done |

## Non-functional

| ID | Requirement | Status |
|---|---|---|
| N1 | Python standard library only | done |
| N2 | Catalog errors are reported at startup with file and option id | done |
| N3 | Pure logic is unit tested without Docker or a terminal | done |
| N4 | Works in ASCII terminals (glyph fallback) and needs 60x16 minimum | done |

## Ideas

- Verify GNU and LLVM source signatures.
- Cross compilers (a target triple for GCC, sysroots).
- Generate option lists from `configure --help` / `cmake -LAH` to spot new options.
- Offload targets (nvptx/amdgcn) for GCC and LLVM.
