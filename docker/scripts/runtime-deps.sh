#!/bin/sh
# Print the Ubuntu packages that provide the shared libraries used by the ELF
# files under the given prefix, one per line. The final image installs these so
# the toolchain runs without the build dependencies.
set -eu
prefix="$1"

find "$prefix" -type f \( -perm -u+x -o -name '*.so' -o -name '*.so.*' \) |
while read -r f; do
    case "$(file -b "$f")" in
        ELF*) ldd "$f" 2>/dev/null | awk '$2 == "=>" && $3 ~ /^\// { print $3 }' ;;
    esac
done | sort -u |
while read -r lib; do
    case "$lib" in "$prefix"/*) continue ;; esac
    # usrmerge: a library can be registered under /lib or /usr/lib.
    dpkg -S "$lib" 2>/dev/null || dpkg -S "$(readlink -f "$lib")" 2>/dev/null || true
done | cut -d: -f1 | sort -u
