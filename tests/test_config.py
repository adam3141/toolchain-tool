import shlex
from pathlib import Path

from toolchain_tool.config import BuildConfig


def words(cfg, arg):
    return shlex.split(cfg.build_args()[arg])


def test_gcc_defaults(gcc):
    args = gcc.build_args()
    assert args["GCC_VERSION"] == gcc.catalog.versions[0].releases[0]
    assert args["BINUTILS_VERSION"] == gcc.version_line().companion["recommended"]
    assert args["GCC_LANGUAGES"] == "c,c++"
    assert args["GCC_BOOTSTRAP"] == "off"
    assert "--enable-lto" in words(gcc, "GCC_CONFIGURE_FLAGS")
    assert args["GCC_TARGET_CXXFLAGS"] == "-g -O2"
    assert not gcc.has_errors()


def test_every_arg_is_always_passed(gcc, llvm):
    for cfg in (gcc, llvm):
        assert list(cfg.build_args()) == [a.name for a in cfg.catalog.args]


def test_bootstrap_moves_library_flags_out(gcc):
    gcc.set(gcc.catalog.option("bootstrap"), "lto")
    args = gcc.build_args()
    assert args["GCC_BOOTSTRAP"] == "on"
    assert "--with-build-config=bootstrap-lto" in words(gcc, "GCC_CONFIGURE_FLAGS")
    assert args["GCC_TARGET_CFLAGS"] == ""
    assert gcc.option_reason(gcc.catalog.option("target_cflags")) == "only when Bootstrap is Off (single stage)"


def test_changing_major_resets_binutils_and_drops_new_languages(gcc):
    langs = gcc.catalog.option("languages")
    gcc.toggle_choice(langs, "m2")
    assert "m2" in gcc.values["languages"]
    gcc.set_version("12.5.0")
    assert gcc.companion_version == "2.38"
    assert "m2" not in gcc.values["languages"]  # Modula-2 arrived in GCC 13
    assert gcc.choice_reason(langs, langs.choice("m2")) == "needs GCC 13 or newer"


def test_incompatible_binutils_is_an_error(gcc):
    gcc.companion_version = "2.36.1"
    assert any("outside the range" in i.message for i in gcc.validate() if i.level == "error")
    assert "2.36.1" not in gcc.companion_choices()


def test_binutils_version_gates_options(gcc):
    gold = gcc.catalog.option("bu_gold")
    assert gcc.option_reason(gold) == "needs binutils 2.43.1 or older"
    gcc.set_version("14.4.0")
    assert gcc.option_reason(gold) is None


def test_jit_rule(gcc):
    gcc.toggle_choice(gcc.catalog.option("languages"), "jit")
    assert any("Host shared" in i.message for i in gcc.validate() if i.level == "error")
    gcc.set(gcc.catalog.option("host_shared"), True)
    assert not gcc.has_errors()


def test_requires_are_added_and_dependents_removed(llvm):
    projects = llvm.catalog.option("projects")
    notes = llvm.toggle_choice(projects, "flang")
    assert set(llvm.values["projects"]) >= {"clang", "mlir", "flang"}
    assert any("mlir" in n for n in notes)
    llvm.toggle_choice(projects, "clang")
    assert "flang" not in llvm.values["projects"]
    assert "clang" not in llvm.values["projects"]


def test_exclusive_choice(llvm):
    targets = llvm.catalog.option("targets")
    llvm.toggle_choice(targets, "AArch64")
    assert llvm.build_args()["LLVM_TARGETS"] == "host;AArch64"
    llvm.toggle_choice(targets, "all")
    assert llvm.values["targets"] == ["all"]
    llvm.toggle_choice(targets, "X86")
    assert llvm.values["targets"] == ["X86"]


def test_runtimes_need_clang(llvm):
    assert llvm.build_args()["LLVM_RUNTIMES"] == "compiler-rt;libunwind;libcxxabi;libcxx"
    llvm.toggle_choice(llvm.catalog.option("projects"), "clang")
    args = llvm.build_args()
    assert args["LLVM_RUNTIMES"] == ""
    assert args["LLVM_RUNTIMES_CMAKE_FLAGS"] == ""
    assert "-DCLANG_DEFAULT_PIE_ON_LINUX=ON" not in args["LLVM_CMAKE_FLAGS"]


def test_multi_with_template(llvm):
    llvm.toggle_choice(llvm.catalog.option("experimental_targets"), "M68k")
    llvm.toggle_choice(llvm.catalog.option("experimental_targets"), "ARC")
    assert "-DLLVM_EXPERIMENTAL_TARGETS_TO_BUILD=ARC;M68k" in words(llvm, "LLVM_CMAKE_FLAGS")


def test_strings_are_quoted_and_raw_is_verbatim(gcc):
    gcc.set(gcc.catalog.option("pkgversion"), "My GCC (build 7)")
    gcc.set(gcc.catalog.option("extra_configure"), "--with-foo='a b' --enable-bar")
    w = words(gcc, "GCC_CONFIGURE_FLAGS")
    assert "--with-pkgversion=My GCC (build 7)" in w
    assert w[-2:] == ["--with-foo=a b", "--enable-bar"]


def test_empty_choice_emits_nothing(llvm):
    assert not any(w.startswith("-DLLVM_ENABLE_LTO") for w in words(llvm, "LLVM_CMAKE_FLAGS"))
    llvm.set(llvm.catalog.option("lto"), "Thin")
    assert "-DLLVM_ENABLE_LTO=Thin" in words(llvm, "LLVM_CMAKE_FLAGS")
    assert any("host compiler clang" in i.message for i in llvm.validate() if i.level == "error")


def test_stage_of(gcc, llvm):
    assert gcc.stage_of(gcc.catalog.option("target_cflags")).id == "libraries"
    assert gcc.stage_of(gcc.catalog.option("bootstrap")).id == "compiler"
    assert gcc.stage_of(gcc.catalog.option("bu_gold")).id == "binutils"
    assert llvm.stage_of(llvm.catalog.option("hardening")).id == "runtimes"


def test_old_toolchain_on_new_ubuntu_warns(gcc):
    gcc.set_version("11.5.0")
    gcc.ubuntu = "26.04"
    assert any("much older" in i.message for i in gcc.validate() if i.level == "warn")


def test_profile_round_trip(gcc_catalog, ubuntu, gcc):
    gcc.ubuntu = "22.04"
    gcc.set_version("14.4.0")
    gcc.toggle_choice(gcc.catalog.option("languages"), "fortran")
    gcc.set(gcc.catalog.option("bootstrap"), "on")
    gcc.custom_tag = "me/gcc:14"
    data = gcc.to_profile()
    assert set(data["options"]) == {"languages", "bootstrap"}
    other = BuildConfig(gcc_catalog, ubuntu)
    assert other.apply_profile(data) == []
    assert other.build_args() == gcc.build_args()
    assert other.image_tag == "me/gcc:14"


def test_profile_warnings(gcc):
    warnings = gcc.apply_profile({"toolchain": "gcc", "options": {"nope": 1, "lto": "yes"}})
    assert len(warnings) == 2


def test_docker_command(gcc):
    cmd = gcc.docker_command(Path("docker"))
    assert cmd[:5] == ["docker", "buildx", "build", "-f", "docker/gcc.Dockerfile"]
    assert "--build-arg" in cmd and cmd[-1] == "docker"
    exp = gcc.docker_command(Path("docker"), export_dir="out/x")
    assert "type=local,dest=out/x" in exp and "--load" not in exp
    text = gcc.shell_command(Path("docker"))
    assert shlex.split(text.replace("\\\n", " ")) == cmd
