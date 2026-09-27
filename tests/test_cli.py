import json

import pytest

from toolchain_tool import cli
from toolchain_tool.app import Paths, Project, default_data_dir
from toolchain_tool.catalog import CatalogError

ROOT_MARKERS = ("catalog/gcc.json", "catalog/llvm.json", "catalog/ubuntu.json", "docker/gcc.Dockerfile")


def make_checkout(tmp_path):
    """A minimal copy of the real catalog/docker, so init/find can be tested without touching the real project."""
    from conftest import ROOT as real_root

    checkout = tmp_path / "checkout"
    for rel in ("catalog", "docker"):
        (checkout / rel).parent.mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copytree(real_root / "catalog", checkout / "catalog")
    shutil.copytree(real_root / "docker", checkout / "docker")
    return checkout


def test_default_data_dir_honours_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert default_data_dir() == tmp_path / "xdg" / "toolchain-tool"


def test_default_data_dir_falls_back_to_local_share(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    assert default_data_dir() == tmp_path / ".local" / "share" / "toolchain-tool"


def test_paths_find_prefers_explicit_root(monkeypatch, tmp_path):
    checkout = make_checkout(tmp_path)
    monkeypatch.delenv("TOOLCHAINS_ROOT", raising=False)
    assert Paths.find(str(checkout)).root == checkout


def test_paths_find_uses_data_dir_when_nothing_else_matches(monkeypatch, tmp_path):
    checkout = make_checkout(tmp_path)
    data_dir = tmp_path / "xdg" / "toolchain-tool"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("TOOLCHAINS_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)  # cwd has no catalog/, so this candidate is skipped
    cli.cmd_init(Project(Paths(checkout)), _Args(dest=None, force=False))
    assert Paths.find().root == data_dir


def test_paths_find_errors_when_nothing_matches(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("TOOLCHAINS_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    # Neutralise the dev/editable-install fallback (Path(__file__).parents[2]), which
    # would otherwise resolve to this real checkout under `pip install -e`.
    monkeypatch.setattr("toolchain_tool.app.__file__", str(tmp_path / "nowhere" / "app.py"))
    with pytest.raises(CatalogError, match="toolchain-tool init"):
        Paths.find()


class _Args:
    def __init__(self, dest=None, force=False):
        self.dest = dest
        self.force = force


def test_init_copies_catalog_and_docker(tmp_path):
    checkout = make_checkout(tmp_path)
    dest = tmp_path / "dest"
    project = Project(Paths(checkout))
    assert cli.cmd_init(project, _Args(dest=str(dest))) == 0
    for marker in ROOT_MARKERS:
        assert (dest / marker).is_file()


def test_init_refuses_to_overwrite_without_force(tmp_path):
    checkout = make_checkout(tmp_path)
    dest = tmp_path / "dest"
    project = Project(Paths(checkout))
    cli.cmd_init(project, _Args(dest=str(dest)))
    assert cli.cmd_init(project, _Args(dest=str(dest))) == 1
    assert cli.cmd_init(project, _Args(dest=str(dest), force=True)) == 0


def test_init_migrates_profiles_once_and_never_deletes_them(tmp_path):
    checkout = make_checkout(tmp_path)
    (checkout / "profiles").mkdir()
    (checkout / "profiles" / "mine.json").write_text('{"toolchain": "gcc"}')
    dest = tmp_path / "dest"
    project = Project(Paths(checkout))
    cli.cmd_init(project, _Args(dest=str(dest)))
    assert (dest / "profiles" / "mine.json").is_file()

    # A saved profile at the destination survives a --force refresh of catalog/docker,
    # even though the checkout's copy has since changed.
    (dest / "profiles" / "new.json").write_text('{"toolchain": "llvm"}')
    (checkout / "profiles" / "mine.json").write_text('{"toolchain": "gcc", "edited": true}')
    cli.cmd_init(project, _Args(dest=str(dest), force=True))
    assert json.loads((dest / "profiles" / "mine.json").read_text()) == {"toolchain": "gcc"}
    assert (dest / "profiles" / "new.json").is_file()


def test_init_refuses_to_copy_onto_itself(tmp_path):
    checkout = make_checkout(tmp_path)
    project = Project(Paths(checkout))
    assert cli.cmd_init(project, _Args(dest=str(checkout))) == 1
