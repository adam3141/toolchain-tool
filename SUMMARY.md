# Project summary (running log)

A concise record of what has been built, for future sessions. Newest entries last.

## Layout
- `catalog/ubuntu.json` lists the Ubuntu base images with their release month and host tool versions (gcc, gnat, clang, cmake).
- `catalog/{gcc,llvm}.json` hold the option catalogs: `stages` (Docker layers, in order), `args` (build args with stage and kind), `sections` → `options` → `choices`, and `rules`. `catalog/README.md` documents the schema.
- `catalog/{gcc,llvm}.versions.json` list the releases per major series. For GCC, each series also has its binutils range (`recommended`, `min`, `max`) and the file holds the binutils release list. `toolchain-tool refresh` rewrites these files; the option catalogs are only edited by hand.
- `docker/gcc.Dockerfile`: stages base → binutils → source → compiler → libraries → install → export or final.
- `docker/llvm.Dockerfile`: stages base → source → compiler → runtimes → install → export or final.
- `docker/scripts/runtime-deps.sh` runs `ldd` over the prefix and maps the libraries to apt packages with `dpkg -S`. The final image installs that list.
- `src/toolchain_tool/catalog.py`: dataclasses, JSON loading, `check_catalog` consistency checks, version comparison.
- `src/toolchain_tool/config.py`: `BuildConfig`, which holds the selections and handles conditions and availability reasons, multi toggles (requires, exclusive, required), emissions to build args, validation (`Issue`s), the docker command and profile save/load.
- `src/toolchain_tool/upstream.py`: parses the ftp.gnu.org listings and the GitHub releases API, and merges them into the versions files (pure `merge_versions`).
- `src/toolchain_tool/ui.py`: Theme and glyphs, box drawing, `dialog`, `pick` (radio list), `prompt_text` with `LineEditor`. Adapted from `../tools`.
- `src/toolchain_tool/app.py`: `Paths`/`Project` (files on disk), `App` (screen stack, `run_external` to leave curses for docker), `MenuScreen` + `Row` (a generic list with a status area), and the screens `HomeScreen`, `ToolchainScreen`, `SectionScreen`, `MultiScreen`, `ReviewScreen`.
- `src/toolchain_tool/cli.py`: argparse commands `tui` (default), `show`, `build`, `script`, `refresh`.
- `tests/`: pytest for catalogs (including a check that each catalog arg is declared as an `ARG` in its Dockerfile), config, upstream parsing/merging, and the text helpers.

## Design notes
- Every build arg is passed on every build, even when empty, so Dockerfile defaults never apply without being noticed.
- `words` args are shell-quoted by Python and expanded in the Dockerfile with `eval "set -- $ARG"`. Raw (user-typed) text is added unquoted after the generated flags, so it can override them.
- An unavailable option (version, `when` or section condition) emits nothing and counts as empty/off in other conditions. A `seen` set stops conditions that refer to each other from recursing forever.
- GCC split: with bootstrap off, `make all-host` runs in the compiler layer and `make all-target CFLAGS_FOR_TARGET=...` in the libraries layer. With bootstrap on, libstdc++, libgcc, libgomp, the sanitizers, libatomic and libphobos are bootstrap modules (GCC `Makefile.def`), so everything is built in the compiler layer and the library flag options are disabled with `when: bootstrap in [off]`.
- GCC Ada: Ubuntu's gnat can lag its gcc (22.04: gnat 10 / gcc 11; 26.04: gnat 14 / gcc 15). The base layer installs `g++-<gnat major>`, and the compiler layer uses that gcc when `ada` is selected.
- gccrs (GCC 15+) needs cargo; its crates are vendored in the GCC tarball, so no network access is needed.
- LLVM runtimes: a standalone build of `llvm-project/runtimes` with the installed clang. It needs three settings a standalone build does not choose itself: `COMPILER_RT_INSTALL_PATH=$(clang -print-resource-dir)` (otherwise compiler-rt lands in `$PREFIX/lib`, where clang does not look), `CMAKE_{C,CXX,ASM}_COMPILER_TARGET=$(clang -print-target-triple)` (compiler-rt refuses `COMPILER_RT_DEFAULT_TARGET_ONLY=ON` without it), and `LLVM_ENABLE_PER_TARGET_RUNTIME_DIR=ON` (otherwise libc++/libunwind install flat into `$PREFIX/lib`, where clang does not search).
- LLVM `host` in `LLVM_TARGETS_TO_BUILD` is resolved and de-duplicated by LLVM (`config-ix.cmake`), so `host;X86` is fine.
- ccache runs in a BuildKit cache mount (`/ccache`) for binutils, GCC stage 1 and all of LLVM.
- The TUI leaves curses for docker builds with `def_prog_mode`/`endwin`, then waits for Enter.
- Arrow keys arrive as `ESC O x` in keypad mode. `ESCDELAY` is 25ms.

- `toolchain-tool init [DEST] [--force]` (`cli.py`) copies `catalog/` and `docker/` from the checkout it is run in to a user data directory (default `default_data_dir()` in `app.py`: `$XDG_DATA_HOME/toolchain-tool`, i.e. `~/.local/share/toolchain-tool`), so a `pipx`-installed `toolchain-tool` finds them without `$TOOLCHAINS_ROOT`. `Paths.find` checks that directory as a fallback, after cwd and before the dev/editable-install fallback. `--force` refreshes `catalog/`/`docker/` but never touches an already-migrated `profiles/`, so saved profiles survive a refresh.

- Both Dockerfiles now write `share/toolchain-tool/{runtime-packages.txt,toolchain.conf,README}` inside `$PREFIX` itself (from `docker/scripts/metadata-readme.txt`), instead of a separate `/out/` stage the `final` target consumed and discarded. Since `export` and `final` both copy the whole prefix, the metadata now travels with the toolchain however it's taken out: an `export`, or `COPY --from=<image>` in someone else's Dockerfile. The `final` stage's own apt-install/ldconfig step now just reads these files from the copied prefix instead of a separate `/tmp/toolchain` copy.

## Log
- 2026-09-27: Initial implementation of R1-R15 and N1-N4. Catalog options were taken from the GCC 16.2.0, binutils 2.47 and LLVM 23.1.2 sources, and the Ubuntu package versions were checked in containers for 22.04, 24.04, 26.04 and 26.10. 33 unit tests pass. The TUI was driven in a pty (pyte) through home, toolchain, section, multi-select, picker, review, and profile save/load.
- 2026-09-27: Real builds on Ubuntu 24.04 (32 cores). GCC 16.2.0 + binutils 2.46.1 (C/C++, no bootstrap): C, C++23 `<print>` and `-flto` work; image 606 MB. The first run took about 13 minutes, mostly the apt layer. Changing only `GCC_TARGET_CXXFLAGS` reused base/binutils/source/compiler from cache and rebuilt only the libraries layer (112 s). LLVM 23.1.2 (clang+lld, host target, compiler-rt/libunwind/libc++abi/libc++): clang with libstdc++, libc++ `<print>`, a pure LLVM stack (compiler-rt + libunwind + lld), ThinLTO and ASan all work. The compiler layer takes about 10 minutes and the image is 4.1 GB with the LLVM dev libraries (the new "Toolchain only" option drops them). Runtime-only fixes rebuilt only the runtimes layer (37 s with ccache). Fixed along the way: compiler-rt needs `CMAKE_*_COMPILER_TARGET`, and libc++ needs `LLVM_ENABLE_PER_TARGET_RUNTIME_DIR=ON`. One transient GCC 13 ICE (segfault in `alloc_traits.h`) during the LLVM build went away on a retry.
