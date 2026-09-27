# syntax=docker/dockerfile:1
#
# LLVM / Clang and the LLVM runtimes.
#
# Build args appear as late as possible and in order of how often they are
# expected to change, so a change only rebuilds from the layer that uses it:
#
#   base      UBUNTU_VERSION              apt packages for every project
#   source    LLVM_VERSION                download + unpack llvm-project
#   compiler  PREFIX LLVM_HOST_COMPILER LLVM_BUILD_TYPE LLVM_PROJECTS
#             LLVM_TARGETS LLVM_CMAKE_FLAGS LLVM_INSTALL_TARGET
#   runtimes  LLVM_RUNTIMES LLVM_RUNTIMES_BUILD_TYPE LLVM_RUNTIMES_CMAKE_FLAGS
#
# The runtimes (libc++, libc++abi, libunwind, compiler-rt, ...) are a separate
# standalone CMake build of llvm-project/runtimes using the clang installed by
# the compiler layer, so their options never rebuild the compiler. It uses the
# same per-target layout as an in-tree build (lib/<triple>/libc++.so, ...), which
# is where clang looks for them.
#
# *_CMAKE_FLAGS are shell words: they are expanded with `eval` so that quoted
# values containing spaces survive.
#
# Targets: `final` (default) is a small runtime image; `export` holds only the
# install prefix, for `docker buildx build --output type=local,dest=DIR`.

ARG UBUNTU_VERSION=24.04

# ---------------------------------------------------------------------------
FROM ubuntu:${UBUNTU_VERSION} AS base
ENV DEBIAN_FRONTEND=noninteractive
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    set -eux; \
    rm -f /etc/apt/apt.conf.d/docker-clean; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl xz-utils file ccache \
        cmake ninja-build python3 python3-dev swig pkg-config \
        clang lld mold binutils-dev \
        zlib1g-dev libzstd-dev libxml2-dev libedit-dev libncurses-dev \
        libffi-dev liblzma-dev libelf-dev; \
    if [ "$(dpkg --print-architecture)" = amd64 ]; then \
        apt-get install -y --no-install-recommends gcc-multilib g++-multilib; \
    fi
ENV CCACHE_DIR=/ccache CCACHE_MAXSIZE=30G

# ---------------------------------------------------------------------------
FROM base AS source
ARG LLVM_VERSION=23.1.2
RUN set -eux; \
    mkdir -p /src; \
    curl -fsSL "https://github.com/llvm/llvm-project/releases/download/llvmorg-${LLVM_VERSION}/llvm-project-${LLVM_VERSION}.src.tar.xz" \
        | tar -xJ -C /src; \
    mv "/src/llvm-project-${LLVM_VERSION}.src" /src/llvm-project

# ---------------------------------------------------------------------------
FROM source AS compiler
ARG PREFIX=/opt/llvm
ARG LLVM_HOST_COMPILER=gcc
ARG LLVM_BUILD_TYPE=Release
ARG LLVM_PROJECTS="clang;lld"
ARG LLVM_TARGETS=host
ARG LLVM_CMAKE_FLAGS="-DLLVM_USE_LINKER=lld"
ARG LLVM_INSTALL_TARGET=install/strip
RUN --mount=type=cache,target=/ccache \
    set -eux; \
    case "${LLVM_HOST_COMPILER}" in \
        clang) cc=clang; cxx=clang++ ;; \
        *)     cc=gcc;   cxx=g++ ;; \
    esac; \
    eval "set -- ${LLVM_CMAKE_FLAGS}"; \
    cmake -G Ninja -S /src/llvm-project/llvm -B /build/llvm \
        -DCMAKE_BUILD_TYPE="${LLVM_BUILD_TYPE}" \
        -DCMAKE_INSTALL_PREFIX="${PREFIX}" \
        -DCMAKE_C_COMPILER="$cc" -DCMAKE_CXX_COMPILER="$cxx" \
        -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
        -DLLVM_ENABLE_PROJECTS="${LLVM_PROJECTS}" \
        -DLLVM_TARGETS_TO_BUILD="${LLVM_TARGETS}" \
        -DLLVM_INCLUDE_TESTS=OFF -DLLVM_INCLUDE_EXAMPLES=OFF -DLLVM_INCLUDE_BENCHMARKS=OFF \
        "$@"; \
    ninja -C /build/llvm "${LLVM_INSTALL_TARGET}"; \
    rm -rf /build/llvm

# ---------------------------------------------------------------------------
FROM compiler AS runtimes
ARG PREFIX=/opt/llvm
ARG LLVM_INSTALL_TARGET=install/strip
ARG LLVM_RUNTIMES="compiler-rt;libunwind;libcxxabi;libcxx"
ARG LLVM_RUNTIMES_BUILD_TYPE=Release
ARG LLVM_RUNTIMES_CMAKE_FLAGS=""
RUN --mount=type=cache,target=/ccache \
    set -eux; \
    if [ -z "${LLVM_RUNTIMES}" ] || [ ! -x "${PREFIX}/bin/clang" ]; then \
        echo "No runtimes to build (LLVM_RUNTIMES empty or clang not built)"; exit 0; \
    fi; \
    eval "set -- ${LLVM_RUNTIMES_CMAKE_FLAGS}"; \
    case ";${LLVM_RUNTIMES};" in \
        *";flang-rt;"*) set -- -DCMAKE_Fortran_COMPILER="${PREFIX}/bin/flang" -DCMAKE_Fortran_COMPILER_WORKS=ON "$@" ;; \
    esac; \
    triple="$("${PREFIX}/bin/clang" -print-target-triple)"; \
    cmake -G Ninja -S /src/llvm-project/runtimes -B /build/runtimes \
        -DCMAKE_BUILD_TYPE="${LLVM_RUNTIMES_BUILD_TYPE}" \
        -DCMAKE_INSTALL_PREFIX="${PREFIX}" \
        -DCMAKE_C_COMPILER="${PREFIX}/bin/clang" -DCMAKE_CXX_COMPILER="${PREFIX}/bin/clang++" \
        -DCMAKE_C_COMPILER_TARGET="$triple" -DCMAKE_CXX_COMPILER_TARGET="$triple" -DCMAKE_ASM_COMPILER_TARGET="$triple" \
        -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
        -DLLVM_ENABLE_RUNTIMES="${LLVM_RUNTIMES}" \
        -DLLVM_ENABLE_PER_TARGET_RUNTIME_DIR=ON \
        -DCOMPILER_RT_INSTALL_PATH="$("${PREFIX}/bin/clang" -print-resource-dir)" \
        -DLLVM_INCLUDE_TESTS=OFF -DLIBCXX_INCLUDE_TESTS=OFF -DLIBCXX_INCLUDE_BENCHMARKS=OFF \
        -DLIBCXXABI_INCLUDE_TESTS=OFF -DLIBUNWIND_INCLUDE_TESTS=OFF -DCOMPILER_RT_INCLUDE_TESTS=OFF \
        "$@"; \
    ninja -C /build/runtimes "${LLVM_INSTALL_TARGET}"; \
    rm -rf /build/runtimes

# ---------------------------------------------------------------------------
FROM runtimes AS install
ARG PREFIX=/opt/llvm
COPY scripts/runtime-deps.sh /usr/local/bin/runtime-deps
COPY scripts/metadata-readme.txt /tmp/metadata-readme.txt
RUN set -eux; \
    meta="${PREFIX}/share/toolchain-tool"; \
    mkdir -p "$meta"; \
    cp /tmp/metadata-readme.txt "$meta/README"; \
    runtime-deps "${PREFIX}" > "$meta/runtime-packages.txt"; \
    : > "$meta/toolchain.conf"; \
    if [ -x "${PREFIX}/bin/clang" ]; then \
        d="${PREFIX}/lib/$("${PREFIX}/bin/clang" -print-target-triple)"; \
        if [ -d "$d" ]; then echo "$d" > "$meta/toolchain.conf"; fi; \
    fi; \
    cat "$meta/runtime-packages.txt"

# ---------------------------------------------------------------------------
# The export target and the layer below both copy the whole prefix, so
# share/toolchain-tool/ (runtime-packages.txt, toolchain.conf, README) travels
# with the toolchain however it's consumed: an export, or `COPY --from=` this
# image's tag in another Dockerfile.
FROM scratch AS export
ARG PREFIX=/opt/llvm
COPY --from=install ${PREFIX} ${PREFIX}

# ---------------------------------------------------------------------------
FROM ubuntu:${UBUNTU_VERSION} AS final
ARG PREFIX=/opt/llvm
ARG LLVM_VERSION
ENV DEBIAN_FRONTEND=noninteractive
COPY --from=install ${PREFIX} ${PREFIX}
# g++ supplies libstdc++, libgcc and the crt files clang uses by default;
# binutils supplies ld for when lld is not the default linker.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends g++ binutils make $(cat "${PREFIX}/share/toolchain-tool/runtime-packages.txt"); \
    rm -rf /var/lib/apt/lists/*; \
    cp "${PREFIX}/share/toolchain-tool/toolchain.conf" /etc/ld.so.conf.d/toolchain.conf; \
    ldconfig
ENV PATH=${PREFIX}/bin:${PATH}
LABEL org.opencontainers.image.title="llvm ${LLVM_VERSION}"
