"""Refresh catalog/*.versions.json from the upstream release lists.

GCC and binutils come from the ftp.gnu.org directory listings, LLVM from the
GitHub releases API. The parse/merge functions are pure so they can be tested
without the network.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from .catalog import version_key

GNU_URL = "https://ftp.gnu.org/gnu"
LLVM_RELEASES_URL = "https://api.github.com/repos/llvm/llvm-project/releases?per_page=100&page={page}"
TIMEOUT = 30


class UpstreamError(Exception):
    pass


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "toolchain-tool"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UpstreamError(f"{url}: {e}") from None


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def parse_gnu_listing(html: str, name: str) -> dict[str, str]:
    """{version: 'YYYY-MM-DD'} from an ftp.gnu.org directory listing.

    Matches release directories (gcc-16.2.0/) and tarballs (binutils-2.47.tar.xz).
    """
    pattern = re.compile(
        rf'href="{re.escape(name)}-(\d+(?:\.\d+)+)(?:/|\.tar\.xz)".*?(\d{{4}}-\d{{2}}-\d{{2}})'
    )
    out: dict[str, str] = {}
    for line in html.splitlines():
        m = pattern.search(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def parse_llvm_releases(payload: str) -> dict[str, str]:
    """{version: 'YYYY-MM-DD'} for final (non-rc) llvmorg-X.Y.Z releases."""
    out: dict[str, str] = {}
    for rel in json.loads(payload):
        m = re.fullmatch(r"llvmorg-(\d+\.\d+\.\d+)", rel.get("tag_name", ""))
        if m and not rel.get("prerelease") and not rel.get("draft"):
            out[m.group(1)] = (rel.get("published_at") or "")[:10]
    return out


# --------------------------------------------------------------------------
# Merging
# --------------------------------------------------------------------------


def _desc(versions) -> list[str]:
    return sorted(set(versions), key=version_key, reverse=True)


def _group_by_major(releases: dict[str, str], min_major: int) -> dict[str, dict[str, str]]:
    groups: dict[str, dict[str, str]] = {}
    for v, date in releases.items():
        major = v.split(".")[0]
        if major.isdigit() and int(major) >= min_major:
            groups.setdefault(major, {})[v] = date
    return groups


def merge_versions(
    data: dict,
    releases: dict[str, str],
    companion: str | None = None,
    companion_releases: dict[str, str] | None = None,
) -> tuple[dict, list[str]]:
    """Merge upstream releases into a versions file. Returns (new data, notes).

    Existing majors keep their curated fields (release month, companion range)
    and gain new point releases. New majors are added; for them the companion
    range is a guess (recommended = newest companion released before the major,
    min = previous major's recommendation) and is reported as such.
    """
    notes: list[str] = []
    lines = {str(v["major"]): dict(v) for v in data.get("versions", [])}
    min_major = min((int(m) for m in lines), default=0)
    comp_all = _desc((companion_releases or {}).keys())

    for major, found in _group_by_major(releases, min_major).items():
        new = _desc(found)
        if major in lines:
            old = lines[major]["releases"]
            added = [r for r in new if r not in old]
            if added:
                lines[major]["releases"] = _desc(old + added)
                notes.append(f"{major}: added {', '.join(added)}")
            continue
        first_date = min(found.values())
        line: dict = {"major": major, "released": first_date[:7], "releases": new}
        if companion:
            prev = lines.get(str(int(major) - 1), {}).get(companion, {})
            before = [v for v in comp_all if (companion_releases or {}).get(v, "9999") <= first_date]
            rec = before[0] if before else (comp_all[0] if comp_all else "")
            line[companion] = {"recommended": rec, "min": prev.get("recommended", rec), "max": comp_all[0] if comp_all else rec}
            notes.append(f"{major}: new major ({', '.join(new)}); {companion} range guessed as "
                         f"{line[companion]['min']}..{line[companion]['max']}, check it")
        else:
            notes.append(f"{major}: new major ({', '.join(new)})")
        lines[major] = line

    out = dict(data)
    out["versions"] = sorted(lines.values(), key=lambda v: int(v["major"]), reverse=True)
    if companion is not None:
        old = data.get("companion_releases", [])
        oldest = min(old, key=version_key) if old else None
        keep = [v for v in comp_all if oldest is None or version_key(v) >= version_key(oldest)]
        added = [v for v in keep if v not in old]
        out["companion_releases"] = _desc(old + added)
        if added:
            notes.append(f"{companion}: added {', '.join(added)}")
    return out, notes


# --------------------------------------------------------------------------
# Refresh
# --------------------------------------------------------------------------


def _write(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def refresh(catalog_dir: Path) -> list[str]:
    """Update gcc.versions.json and llvm.versions.json. Returns a summary."""
    summary: list[str] = []

    gcc_path = catalog_dir / "gcc.versions.json"
    gcc = parse_gnu_listing(fetch(f"{GNU_URL}/gcc/"), "gcc")
    binutils = parse_gnu_listing(fetch(f"{GNU_URL}/binutils/"), "binutils")
    if not gcc or not binutils:
        raise UpstreamError("could not read the GCC/binutils release lists from ftp.gnu.org")
    data, notes = merge_versions(json.loads(gcc_path.read_text()), gcc, "binutils", binutils)
    _write(gcc_path, data)
    summary += [f"GCC {n}" for n in notes] or ["GCC: up to date"]

    llvm_path = catalog_dir / "llvm.versions.json"
    llvm: dict[str, str] = {}
    for page in (1, 2):
        llvm.update(parse_llvm_releases(fetch(LLVM_RELEASES_URL.format(page=page))))
    if not llvm:
        raise UpstreamError("could not read the LLVM release list from GitHub")
    data, notes = merge_versions(json.loads(llvm_path.read_text()), llvm)
    _write(llvm_path, data)
    summary += [f"LLVM {n}" for n in notes] or ["LLVM: up to date"]
    return summary
