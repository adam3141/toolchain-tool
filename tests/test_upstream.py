import json

from toolchain_tool.upstream import merge_versions, parse_gnu_listing, parse_llvm_releases

GNU_HTML = """
<tr><td><a href="gcc-15.2.0/">gcc-15.2.0/</a></td><td align="right">2025-08-08 06:00  </td></tr>
<tr><td><a href="gcc-16.1.0/">gcc-16.1.0/</a></td><td align="right">2026-04-30 05:30  </td></tr>
<tr><td><a href="gcc-17.1.0/">gcc-17.1.0/</a></td><td align="right">2027-04-29 05:30  </td></tr>
<a href="binutils-2.46.1.tar.xz">binutils-2.46.1.tar.xz</a> 2026-05-01 10:00 30M
<a href="binutils-2.48.tar.xz">binutils-2.48.tar.xz</a> 2027-02-01 10:00 30M
<a href="binutils-2.48.tar.xz.sig">binutils-2.48.tar.xz.sig</a> 2027-02-01 10:00 1K
"""


def test_parse_gnu_listing():
    assert parse_gnu_listing(GNU_HTML, "gcc") == {"15.2.0": "2025-08-08", "16.1.0": "2026-04-30", "17.1.0": "2027-04-29"}
    assert parse_gnu_listing(GNU_HTML, "binutils") == {"2.46.1": "2026-05-01", "2.48": "2027-02-01"}


def test_parse_llvm_releases():
    payload = json.dumps([
        {"tag_name": "llvmorg-23.1.2", "published_at": "2026-09-20T00:00:00Z", "prerelease": False},
        {"tag_name": "llvmorg-24.1.0-rc1", "published_at": "2027-01-01T00:00:00Z", "prerelease": True},
        {"tag_name": "llvmorg-23.1.3", "published_at": "2026-10-01T00:00:00Z", "prerelease": False},
    ])
    assert parse_llvm_releases(payload) == {"23.1.2": "2026-09-20", "23.1.3": "2026-10-01"}


def test_merge_adds_point_release_and_new_major():
    data = {
        "versions": [
            {"major": "16", "released": "2026-04", "releases": ["16.1.0"],
             "binutils": {"recommended": "2.46.1", "min": "2.44", "max": "2.47"}},
            {"major": "15", "released": "2025-04", "releases": ["15.2.0"],
             "binutils": {"recommended": "2.44", "min": "2.42", "max": "2.46.1"}},
        ],
        "companion_releases": ["2.47", "2.46.1", "2.44"],
    }
    upstream = {"15.2.0": "2025-08-08", "16.1.0": "2026-04-30", "16.2.0": "2026-08-01", "17.1.0": "2027-04-29",
                "9.5.0": "2022-05-27"}
    binutils = {"2.44": "2025-02-02", "2.46.1": "2026-05-01", "2.47": "2026-08-01", "2.48": "2027-02-01",
                "2.20": "2009-10-16"}
    out, notes = merge_versions(data, upstream, "binutils", binutils)
    majors = [v["major"] for v in out["versions"]]
    assert majors == ["17", "16", "15"]  # GCC 9 is older than anything tracked
    v16 = out["versions"][1]
    assert v16["releases"] == ["16.2.0", "16.1.0"]
    assert v16["binutils"]["max"] == "2.47"  # curated range untouched
    v17 = out["versions"][0]
    assert v17["released"] == "2027-04"
    assert v17["binutils"] == {"recommended": "2.48", "min": "2.46.1", "max": "2.48"}
    assert out["companion_releases"] == ["2.48", "2.47", "2.46.1", "2.44"]
    assert any("guessed" in n for n in notes)


def test_merge_is_idempotent():
    data = {"versions": [{"major": "23", "released": "2026-08", "releases": ["23.1.0"]}]}
    out, notes = merge_versions(data, {"23.1.0": "2026-08-25"})
    assert out == data and notes == []
