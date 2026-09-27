# toolchains

A menu-driven terminal tool for building GCC + binutils and LLVM/Clang
toolchains as Docker images. You pick the Ubuntu version, the compiler version
and the build options, and the tool runs `docker buildx build` with the
matching build args.

- **Two Dockerfiles** ([docker/gcc.Dockerfile](docker/gcc.Dockerfile),
  [docker/llvm.Dockerfile](docker/llvm.Dockerfile)). Each installs all of its
  prerequisite packages in a first layer that depends only on the Ubuntu
  version, so that layer stays cached however the options change.
- **Late build args.** Each arg is declared just before the layer that uses
  it, in order of how often it is likely to change. For example, changing the
  libc++ hardening mode rebuilds only the LLVM runtimes, not clang.
- **JSON catalogs** ([catalog/](catalog/README.md)) describe every option, the
  flag it produces, the layer it affects, and the version and option
  conditions it depends on. Adding an option means editing JSON, not code.
- **Matching binutils.** Each GCC series lists the binutils releases that work
  with it. The one current when that GCC was released is chosen by default.
- **ccache.** A BuildKit cache mount speeds up rebuilds after an option change.

## Requirements

- Docker with BuildKit (`docker buildx`)
- Python 3.10 or newer (standard library only)

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/toolchain-tool          # the menu
.venv/bin/pytest                  # tests
```

## Install to `~/.local/bin` (run from any directory)

The tool always needs this project's `catalog/` and `docker/` directories at
run time. When it starts, it looks for them in `--root <dir>`, then
`$TOOLCHAINS_ROOT`, then the current directory, then the directory
`toolchain-tool init` installs them to (below), then the checkout it was
installed from (for a dev install). Make sure `~/.local/bin` is on your
`PATH` (most distros add it automatically once the directory exists;
otherwise add `export PATH="$HOME/.local/bin:$PATH"` to `~/.bashrc`).

**Option A: symlink the venv launcher (recommended while developing).**
The venv install is editable, so edits to the source take effect immediately,
and the launcher finds this checkout on its own:

```sh
mkdir -p ~/.local/bin
ln -sf "$PWD/.venv/bin/toolchain-tool" ~/.local/bin/toolchain-tool
toolchain-tool
```

To uninstall, run `rm ~/.local/bin/toolchain-tool`.

**Option B: standalone install with pipx.**
This makes an isolated copy of the code that doesn't depend on `.venv`, but
it no longer carries `catalog/` and `docker/` with it. Run `toolchain-tool
init` once, from inside this checkout, to copy them to a user data
directory (`$XDG_DATA_HOME/toolchain-tool`, i.e. `~/.local/share/toolchain-tool`
by default — pass a path, e.g. `~/.config/toolchain-tool`, to put them
somewhere else). The tool finds its default location on its own afterwards,
from any directory:

```sh
sudo apt install pipx           # once
pipx install --force .          # installs ~/.local/bin/toolchain-tool
toolchain-tool init             # copies catalog/ and docker/ to ~/.local/share/toolchain-tool
toolchain-tool                  # now works from anywhere
```

After pulling changes to this project, re-run `pipx install --force .` for
the code and `toolchain-tool init --force` (from the checkout) to refresh the
installed catalog and Dockerfiles. `--force` never touches a `profiles/`
directory it already copied over, so saved profiles are never lost. To
uninstall, run `pipx uninstall toolchain-tool` and remove the data directory.

(Plain `pip install --user` is blocked on Ubuntu/Debian by PEP 668, hence
pipx.)

## Using the menu

```
Toolchain Builder
 ├─ GCC + binutils ─┬─ General: Ubuntu, GCC version, binutils version, prefix, image tag
 │                  ├─ Languages
 │                  ├─ Compiler build     (bootstrap, checking, LTO, -march, ...)
 │                  ├─ Runtime libraries  (libstdc++ options, library CFLAGS, ...)
 │                  ├─ binutils
 │                  ├─ Review & build     (b build image · e export · w write script)
 │                  └─ Save profile
 ├─ LLVM / Clang ── General · Projects · LLVM build · Clang defaults · Runtimes · Review & build
 ├─ Load a saved profile
 └─ Refresh versions from upstream
```

Keys: arrows or `j`/`k` to move, `Enter`/`Space` to change, `d` to reset to the
default, `q`/`Esc` to go back. The status area shows what the highlighted
option does, the exact flag it adds, and which Docker layer it affects. A `●`
marks settings that differ from the default.

**Review & build** lists any problems (errors block the build), the build
args grouped by Docker layer, and the full command. Pressing `b` builds the
image in the terminal and returns to the menu when it finishes. Pressing `e`
exports the install prefix to a local directory instead, and `w` writes a
shell script with the same command.

Profiles are saved as `profiles/<name>.json`. A profile stores only the
options that differ from the defaults.

## Command line

```sh
toolchain-tool show gcc                    # defaults: build args + docker command
toolchain-tool show my-profile [--json]    # a saved profile
toolchain-tool build my-profile            # docker build → image
toolchain-tool build my-profile --export out/gcc   # just the install tree
toolchain-tool script my-profile build.sh  # write a build script
toolchain-tool refresh                     # add new GCC/binutils/LLVM releases
```

## The images

The `final` target is a plain Ubuntu image with the toolchain in the prefix
(`/opt/gcc` or `/opt/llvm` by default). It is on `PATH`, and its runtime
libraries are registered with `ldconfig`. Shared libraries the toolchain needs
are found with `ldd` at build time and installed from apt, so the image does
not carry the build dependencies.

The `export` target contains only the prefix. It is meant for
`--output type=local,dest=DIR`.

### GCC layers

| Layer | Build args |
|---|---|
| base | `UBUNTU_VERSION` (all packages, including gnat/gdc/cargo for the Ada, D and Rust front ends) |
| binutils | `PREFIX`, `BINUTILS_VERSION`, `BINUTILS_CONFIGURE_FLAGS` |
| source | `GCC_VERSION` |
| compiler | `GCC_LANGUAGES`, `GCC_BOOTSTRAP`, `GCC_CONFIGURE_FLAGS`, `GCC_BUILD_CFLAGS` |
| libraries | `GCC_TARGET_CFLAGS`, `GCC_TARGET_CXXFLAGS` |
| install | `GCC_INSTALL_TARGET` |

binutils is built before GCC because GCC's configure checks which features
the assembler and linker support.

GCC's build limits how far the standard library can be separated from the
compiler:

- Library options set through configure (`--enable-libstdcxx-debug`,
  `--disable-libsanitizer`, ...) are compiler-layer args, because configure
  runs once for the whole tree.
- With **bootstrap off** (the default), the compiler is built with
  `make all-host` and the libraries with `make all-target` in the next layer.
  Library CFLAGS/CXXFLAGS (`CFLAGS_FOR_TARGET`) can then change without
  rebuilding the compiler.
- With **bootstrap on**, GCC builds libstdc++, libgcc, libgomp and the
  sanitizers in each stage, together with the compiler (see `bootstrap=true`
  in GCC's `Makefile.def`). The menu then disables the library flag options,
  because they cannot be applied separately.

### LLVM layers

| Layer | Build args |
|---|---|
| base | `UBUNTU_VERSION` (cmake, ninja, gcc, clang, lld, mold, all project deps) |
| source | `LLVM_VERSION` |
| compiler | `PREFIX`, `LLVM_HOST_COMPILER`, `LLVM_BUILD_TYPE`, `LLVM_PROJECTS`, `LLVM_TARGETS`, `LLVM_CMAKE_FLAGS`, `LLVM_INSTALL_TARGET` |
| runtimes | `LLVM_RUNTIMES`, `LLVM_RUNTIMES_BUILD_TYPE`, `LLVM_RUNTIMES_CMAKE_FLAGS` |

The runtimes (libc++, libc++abi, libunwind, compiler-rt, openmp, flang-rt)
are a separate standalone CMake build of `llvm-project/runtimes`. It uses the
clang installed by the compiler layer, so runtime options never rebuild the
compiler.

### Using the Dockerfiles directly

The Dockerfiles work without the tool. The build context is `docker/`:

```sh
docker buildx build -f docker/gcc.Dockerfile -t my-gcc \
  --build-arg GCC_VERSION=15.2.0 --build-arg BINUTILS_VERSION=2.44 \
  --build-arg GCC_LANGUAGES=c,c++,fortran docker
```

## Notes

- Sources are downloaded over HTTPS from ftp.gnu.org and GitHub releases.
  Signatures are not verified yet.
- `GNU_MIRROR` (a Dockerfile arg, not in the menu) can point at a closer GNU
  mirror.
- Building an old GCC or LLVM on a much newer Ubuntu can fail because of the
  newer host compiler and glibc. The review screen warns about this.
