from pathlib import Path

import pytest

from toolchain_tool.catalog import load_catalog, load_ubuntu
from toolchain_tool.config import BuildConfig

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def ubuntu():
    return load_ubuntu(ROOT / "catalog" / "ubuntu.json")


@pytest.fixture(scope="session")
def gcc_catalog():
    return load_catalog(ROOT / "catalog" / "gcc.json")


@pytest.fixture(scope="session")
def llvm_catalog():
    return load_catalog(ROOT / "catalog" / "llvm.json")


@pytest.fixture
def gcc(gcc_catalog, ubuntu):
    return BuildConfig(gcc_catalog, ubuntu)


@pytest.fixture
def llvm(llvm_catalog, ubuntu):
    return BuildConfig(llvm_catalog, ubuntu)
