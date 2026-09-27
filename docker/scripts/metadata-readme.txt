This directory was written by the toolchain-tool build, alongside the
compiler it describes, so it travels with these files however they are
copied elsewhere (a `docker buildx build --target export` output, or
`COPY --from=<image>` in another Dockerfile).

runtime-packages.txt
    The Ubuntu packages providing the shared libraries this toolchain links
    against (found with `ldd` over every binary and library here). Install
    them wherever these files are copied to, for example in a devcontainer:

        apt-get install -y $(cat share/toolchain-tool/runtime-packages.txt)

toolchain.conf
    The toolchain's own library directories (its bundled libstdc++, libc++,
    etc.). Drop it into /etc/ld.so.conf.d/ and run `ldconfig`, or add the
    listed directories to $LD_LIBRARY_PATH, so those libraries are found at
    run time.
