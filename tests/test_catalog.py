import copy
import re

from conftest import ROOT
from toolchain_tool.catalog import check_catalog, version_at_least, version_at_most


def test_version_compare_uses_bound_precision():
    assert version_at_least("16.2.0", "16")
    assert version_at_least("2.46.0", "2.46")
    assert not version_at_least("2.36.1", "2.37")
    assert version_at_most("15.2.0", "15")
    assert version_at_most("2.43.1", "2.43.1")
    assert not version_at_most("2.44", "2.43.1")


def test_shipped_catalogs_are_consistent(gcc_catalog, llvm_catalog):
    assert check_catalog(gcc_catalog) == []
    assert check_catalog(llvm_catalog) == []


def test_every_build_arg_is_declared_in_its_dockerfile(gcc_catalog, llvm_catalog):
    for cat in (gcc_catalog, llvm_catalog):
        text = (ROOT / "docker" / cat.dockerfile).read_text()
        declared = set(re.findall(r"^ARG (\w+)", text, flags=re.M))
        missing = [a.name for a in cat.args if a.name not in declared]
        assert missing == [], f"{cat.dockerfile} lacks ARG {missing}"


def test_version_line_lookup(gcc_catalog):
    assert gcc_catalog.version_line("16.2.0").major == "16"
    assert gcc_catalog.version_line("13.9.0").major == "13"  # unknown point release of a known major
    assert gcc_catalog.version_line("9.1.0") is None


def test_check_catalog_reports_unknown_arg(gcc_catalog):
    broken = copy.deepcopy(gcc_catalog)
    broken.option("lto").arg = "NO_SUCH_ARG"
    assert any("unknown arg 'NO_SUCH_ARG'" in p for p in check_catalog(broken))


def test_check_catalog_reports_bad_condition(llvm_catalog):
    broken = copy.deepcopy(llvm_catalog)
    broken.option("eh").when = [{"option": "nope", "is": True}]
    assert any("unknown option 'nope'" in p for p in check_catalog(broken))
