# syntax=docker/dockerfile:1
#
# GCC + binutils.
#
# Build args appear as late as possible and in order of how often they are
# expected to change, so a change only rebuilds from the layer that uses it:
#
#   base       UBUNTU_VERSION                    apt packages for every language
#   binutils   PREFIX BINUTILS_VERSION BINUTILS_CONFIGURE_FLAGS
#   source     GCC_VERSION                       download + unpack
#   compiler   GCC_LANGUAGES GCC_BOOTSTRAP GCC_CONFIGURE_FLAGS GCC_BUILD_CFLAGS
#   libraries  GCC_TARGET_CFLAGS GCC_TARGET_CXXFLAGS
#   install    GCC_INSTALL_TARGET
#
# binutils is built first because GCC's configure probes the assembler and
# linker it will be used with.
#
# With GCC_BOOTSTRAP=off the compiler is built with `make all-host` and the
# runtime libraries (libgcc, libstdc++, ...) with `make all-target` in the
# next layer, so the library flags can change without rebuilding the compiler.
# A bootstrap builds libstdc++ and friends as part of the compiler stages, so
# then everything happens in the compiler layer.
#
# *_CONFIGURE_FLAGS are shell words: they are expanded with `eval` so that
# quoted values containing spaces survive.
#
# Targets: `final` (default) is a small runtime image; `export` holds only the
# install prefix, for `docker buildx build --output type=local,dest=DIR`.

ARG UBUNTU_VERSION=24.04

# ---------------------------------------------------------------------------
FROM ubuntu:${UBUNTU_VERSION} AS base
ENV DEBIAN_FRONTEND=noninteractive
# gnat, gdc and cargo are the host compilers GCC needs to build its Ada, D and
# Rust front ends. gnat can lag the default gcc (22.04: 10 vs 11, 26.04: 14 vs
# 15), so the g++ that matches gnat is installed as well.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    set -eux; \
    rm -f /etc/apt/apt.conf.d/docker-clean; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl xz-utils bzip2 file ccache \
        bison flex m4 texinfo gawk python3 \
        libgmp-dev libmpfr-dev libmpc-dev libisl-dev zlib1g-dev libzstd-dev \
        gnat gdc cargo; \
    gnat_major="$(gnatmake --version | sed -n '1s/^[^0-9]*\([0-9]*\).*/\1/p')"; \
    apt-get install -y --no-install-recommends "g++-${gnat_major}"; \
    if [ "$(dpkg --print-architecture)" = amd64 ]; then \
        apt-get install -y --no-install-recommends gcc-multilib g++-multilib; \
    fi
ENV CCACHE_DIR=/ccache CCACHE_MAXSIZE=20G

# ---------------------------------------------------------------------------
FROM base AS binutils
ARG GNU_MIRROR=https://ftp.gnu.org/gnu
ARG PREFIX=/opt/gcc
ARG BINUTILS_VERSION=2.46.1
ARG BINUTILS_CONFIGURE_FLAGS="--enable-plugins --enable-deterministic-archives --with-system-zlib --disable-nls"
ENV PATH=${PREFIX}/bin:${PATH}
RUN --mount=type=cache,target=/ccache \
    set -eux; \
    mkdir -p /src /build/binutils; \
    curl -fsSL "${GNU_MIRROR}/binutils/binutils-${BINUTILS_VERSION}.tar.xz" | tar -xJ -C /src; \
    cd /build/binutils; \
    eval "set -- ${BINUTILS_CONFIGURE_FLAGS}"; \
    CC="ccache gcc" CXX="ccache g++" \
        "/src/binutils-${BINUTILS_VERSION}/configure" --prefix="${PREFIX}" --disable-werror "$@"; \
    make -j"$(nproc)"; \
    make install-strip; \
    cd /; rm -rf /build/binutils "/src/binutils-${BINUTILS_VERSION}"

# ---------------------------------------------------------------------------
FROM binutils AS source
ARG GNU_MIRROR=https://ftp.gnu.org/gnu
ARG GCC_VERSION=16.2.0
RUN set -eux; \
    curl -fsSL "${GNU_MIRROR}/gcc/gcc-${GCC_VERSION}/gcc-${GCC_VERSION}.tar.xz" | tar -xJ -C /src; \
    mv "/src/gcc-${GCC_VERSION}" /src/gcc

# ---------------------------------------------------------------------------
FROM source AS compiler
ARG PREFIX=/opt/gcc
ARG GCC_LANGUAGES=c,c++
ARG GCC_BOOTSTRAP=off
ARG GCC_CONFIGURE_FLAGS="--enable-lto --enable-plugin --disable-multilib --enable-default-pie --with-isl --with-system-zlib --disable-nls"
ARG GCC_BUILD_CFLAGS="-O2"
RUN --mount=type=cache,target=/ccache \
    set -eux; \
    cc=gcc; cxx=g++; \
    case ",${GCC_LANGUAGES}," in \
        *,ada,*) v="$(gnatmake --version | sed -n '1s/^[^0-9]*\([0-9]*\).*/\1/p')"; cc="gcc-$v"; cxx="g++-$v" ;; \
    esac; \
    eval "set -- ${GCC_CONFIGURE_FLAGS}"; \
    if [ "${GCC_BOOTSTRAP}" = off ]; then set -- --disable-bootstrap "$@"; else set -- --enable-bootstrap "$@"; fi; \
    mkdir -p /build/gcc; cd /build/gcc; \
    CC="ccache $cc" CXX="ccache $cxx" CFLAGS="${GCC_BUILD_CFLAGS}" CXXFLAGS="${GCC_BUILD_CFLAGS}" \
        /src/gcc/configure --prefix="${PREFIX}" --enable-languages="${GCC_LANGUAGES}" --disable-werror "$@"; \
    case "${GCC_BOOTSTRAP}" in \
        off)      make -j"$(nproc)" all-host ;; \
        profiled) make -j"$(nproc)" BOOT_CFLAGS="${GCC_BUILD_CFLAGS}" profiledbootstrap ;; \
        *)        make -j"$(nproc)" BOOT_CFLAGS="${GCC_BUILD_CFLAGS}" ;; \
    esac

# ---------------------------------------------------------------------------
FROM compiler AS libraries
ARG GCC_BOOTSTRAP=off
ARG GCC_TARGET_CFLAGS="-g -O2"
ARG GCC_TARGET_CXXFLAGS="-g -O2"
RUN set -eux; \
    if [ "${GCC_BOOTSTRAP}" = off ]; then \
        cd /build/gcc; \
        make -j"$(nproc)" all-target \
            CFLAGS_FOR_TARGET="${GCC_TARGET_CFLAGS}" CXXFLAGS_FOR_TARGET="${GCC_TARGET_CXXFLAGS}"; \
    fi

# ---------------------------------------------------------------------------
FROM libraries AS install
ARG PREFIX=/opt/gcc
ARG GCC_INSTALL_TARGET=install-strip
COPY scripts/runtime-deps.sh /usr/local/bin/runtime-deps
RUN set -eux; \
    cd /build/gcc; \
    make "${GCC_INSTALL_TARGET}"; \
    mkdir -p /out; \
    runtime-deps "${PREFIX}" > /out/runtime-packages.txt; \
    if [ -d "${PREFIX}/lib32" ]; then echo libc6-dev-i386 >> /out/runtime-packages.txt; fi; \
    for d in lib64 lib lib32; do [ -d "${PREFIX}/$d" ] && echo "${PREFIX}/$d"; done > /out/toolchain.conf; \
    cat /out/runtime-packages.txt

# ---------------------------------------------------------------------------
FROM scratch AS export
ARG PREFIX=/opt/gcc
COPY --from=install ${PREFIX} ${PREFIX}

# ---------------------------------------------------------------------------
FROM ubuntu:${UBUNTU_VERSION} AS final
ARG PREFIX=/opt/gcc
ARG GCC_VERSION
ARG BINUTILS_VERSION
ENV DEBIAN_FRONTEND=noninteractive
COPY --from=install /out/ /tmp/toolchain/
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends libc6-dev make $(cat /tmp/toolchain/runtime-packages.txt); \
    rm -rf /var/lib/apt/lists/*; \
    cp /tmp/toolchain/toolchain.conf /etc/ld.so.conf.d/toolchain.conf; \
    rm -rf /tmp/toolchain
COPY --from=install ${PREFIX} ${PREFIX}
RUN ldconfig
ENV PATH=${PREFIX}/bin:${PATH}
LABEL org.opencontainers.image.title="gcc ${GCC_VERSION} + binutils ${BINUTILS_VERSION}"
