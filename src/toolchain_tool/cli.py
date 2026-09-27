"""Command line entry point: the TUI by default, plus non-interactive commands."""

from __future__ import annotations

import argparse
import curses
import json
import locale
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import upstream
from .app import App, Paths, Project, default_data_dir, write_script
from .catalog import CatalogError
from .config import BuildConfig


def resolve_config(project: Project, name: str) -> BuildConfig:
    """A profile path, a profile name in profiles/, or 'gcc'/'llvm' for the defaults."""
    candidates = [Path(name), project.paths.profiles / name, project.paths.profiles / f"{name}.json"]
    for path in candidates:
        if path.is_file():
            cfg, warnings = project.load_profile(path)
            for w in warnings:
                print(f"warning: {path.name}: {w}", file=sys.stderr)
            return cfg
    if name in project.catalogs:
        return project.new_config(name)
    raise ValueError(f"no profile '{name}' (looked in {project.paths.profiles})")


def print_issues(cfg: BuildConfig) -> bool:
    """Print the checks. Returns True if there are errors."""
    issues = cfg.validate()
    for i in issues:
        print(f"{i.level}: {i.message}", file=sys.stderr)
    return any(i.level == "error" for i in issues)


def cmd_show(project: Project, args) -> int:
    cfg = resolve_config(project, args.profile)
    print_issues(cfg)
    if args.json:
        print(json.dumps(cfg.build_args(), indent=2))
        return 0
    for stage, items in cfg.args_by_stage():
        print(f"# {stage.title}")
        for name, value in items:
            print(f"{name}={value}")
    print()
    print(cfg.shell_command(Path("docker"), args.export))
    return 0


def cmd_build(project: Project, args) -> int:
    cfg = resolve_config(project, args.profile)
    if print_issues(cfg):
        return 1
    cmd = cfg.docker_command(Path("docker"), args.export)
    return subprocess.call(cmd, cwd=project.paths.root)


def cmd_script(project: Project, args) -> int:
    cfg = resolve_config(project, args.profile)
    if print_issues(cfg):
        return 1
    path = Path(args.output).resolve()
    write_script(path, cfg, project.paths.root, args.export)
    print(f"wrote {path}")
    return 0


def cmd_refresh(project: Project, args) -> int:
    for line in upstream.refresh(project.paths.catalog):
        print(line)
    return 0


def cmd_init(project: Project, args) -> int:
    """Copy catalog/ and docker/ from a checkout to a user data directory, so
    an installed (pipx) toolchain-tool can find them from any directory."""
    root = project.paths.root
    dest = Path(args.dest).expanduser().resolve() if args.dest else default_data_dir()
    if dest == root:
        print(f"toolchain-tool: {dest} is already the project directory", file=sys.stderr)
        return 1
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in ("catalog", "docker"):
        src = root / name
        if not src.is_dir():
            continue
        target = dest / name
        if target.exists():
            if not args.force:
                print(f"toolchain-tool: {target} already exists; use --force to overwrite", file=sys.stderr)
                return 1
            shutil.rmtree(target)
        shutil.copytree(src, target)
        copied.append(name)
    # profiles/ holds the user's own saved builds: copy it once, but never
    # overwrite or delete it on a later --force refresh of catalog/docker.
    profiles_src, profiles_dst = root / "profiles", dest / "profiles"
    if profiles_src.is_dir() and not profiles_dst.exists():
        shutil.copytree(profiles_src, profiles_dst)
        copied.append("profiles")
    if not copied:
        print(f"toolchain-tool: nothing to copy from {root}", file=sys.stderr)
        return 1
    print(f"Copied {', '.join(copied)} from {root} to {dest}")
    if dest == default_data_dir():
        print("toolchain-tool will now find this automatically, from any directory.")
    else:
        print(f"Run with --root {dest}, or export TOOLCHAINS_ROOT={dest}, to use it.")
    return 0


def cmd_tui(project: Project, args) -> int:
    os.environ.setdefault("ESCDELAY", "25")
    locale.setlocale(locale.LC_ALL, "")
    try:
        curses.wrapper(lambda stdscr: App(stdscr, project).run())
    except KeyboardInterrupt:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="toolchain-tool",
        description="Configure and build GCC and LLVM toolchain Docker images. Runs the menu UI when no command is given.",
    )
    parser.add_argument("--root", help="project directory (default: $TOOLCHAINS_ROOT, the current directory, or the checkout)")
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.add_parser("tui", help="menu UI (default)")

    p = sub.add_parser("show", help="print the build args and docker command for a profile")
    p.add_argument("profile", help="profile name or path, or 'gcc' / 'llvm' for the defaults")
    p.add_argument("--export", metavar="DIR", help="show the export command instead of the image build")
    p.add_argument("--json", action="store_true", help="print the build args as JSON")

    p = sub.add_parser("build", help="run the docker build for a profile")
    p.add_argument("profile")
    p.add_argument("--export", metavar="DIR", help="write the install prefix to DIR instead of building an image")

    p = sub.add_parser("script", help="write a shell script that runs the docker build")
    p.add_argument("profile")
    p.add_argument("output", help="script path")
    p.add_argument("--export", metavar="DIR")

    sub.add_parser("refresh", help="update catalog/*.versions.json from upstream")

    p = sub.add_parser("init", help="copy catalog/ and docker/ to a user data directory "
                                     f"(default: {default_data_dir()}) so an installed toolchain-tool finds them anywhere")
    p.add_argument("dest", nargs="?", help="destination directory (default: $XDG_DATA_HOME/toolchain-tool)")
    p.add_argument("--force", action="store_true", help="overwrite an existing catalog/ or docker/ at the destination")

    args = parser.parse_args(argv)
    try:
        project = Project(Paths.find(args.root))
    except CatalogError as e:
        print(f"toolchain-tool: {e}", file=sys.stderr)
        return 1
    if project.error and args.command not in (None, "tui", "init"):
        print(f"toolchain-tool: {project.error}", file=sys.stderr)
        return 1
    handlers = {None: cmd_tui, "tui": cmd_tui, "show": cmd_show, "build": cmd_build,
                "script": cmd_script, "refresh": cmd_refresh, "init": cmd_init}
    try:
        return handlers[args.command](project, args)
    except (ValueError, OSError, upstream.UpstreamError) as e:
        print(f"toolchain-tool: {e}", file=sys.stderr)
        return 1
