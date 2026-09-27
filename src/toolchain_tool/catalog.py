"""Load and check the JSON option catalogs (catalog/*.json)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

OPTION_TYPES = ("bool", "choice", "multi", "string")
ARG_KINDS = ("value", "list", "words")
LEVELS = ("error", "warn", "info")


class CatalogError(Exception):
    pass


# --------------------------------------------------------------------------
# Versions
# --------------------------------------------------------------------------


def parse_version(text: str) -> tuple[int, ...]:
    """'16.2.0' -> (16, 2, 0). Non-numeric parts count as 0."""
    return tuple(int(p) if p.isdigit() else 0 for p in text.strip().split("."))


def version_at_least(version: str, bound: str) -> bool:
    """Compare only as many parts as the bound has, so '16.2.0' >= '16'."""
    b = parse_version(bound)
    return parse_version(version)[: len(b)] >= b


def version_at_most(version: str, bound: str) -> bool:
    """Inclusive, compared to the bound's precision, so '15.2.0' <= '15'."""
    b = parse_version(bound)
    return parse_version(version)[: len(b)] <= b


def version_key(text: str) -> tuple[int, ...]:
    return parse_version(text)


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------


def _words(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


@dataclass
class Choice:
    value: str
    label: str
    description: str = ""
    requires: list[str] = field(default_factory=list)
    exclusive: bool = False
    required: bool = False
    emit: dict[str, list[str]] | None = None
    since: str | None = None
    until: str | None = None
    when: list[dict] = field(default_factory=list)


@dataclass
class Option:
    id: str
    label: str
    type: str
    arg: str | None
    default: Any
    description: str = ""
    choices: list[Choice] = field(default_factory=list)
    on: list[str] = field(default_factory=list)
    off: list[str] = field(default_factory=list)
    template: str = "{value}"
    raw: bool = False
    sep: str = ";"
    since: str | None = None
    until: str | None = None
    since_companion: str | None = None
    until_companion: str | None = None
    when: list[dict] = field(default_factory=list)
    section: "Section | None" = None

    def choice(self, value: str) -> Choice | None:
        return next((c for c in self.choices if c.value == value), None)


@dataclass
class Section:
    id: str
    title: str
    description: str = ""
    when: list[dict] = field(default_factory=list)
    options: list[Option] = field(default_factory=list)


@dataclass
class ArgSpec:
    name: str
    stage: str
    kind: str = "value"
    sep: str = " "


@dataclass
class Stage:
    id: str
    title: str
    description: str = ""


@dataclass
class Rule:
    conditions: list[dict]
    level: str
    message: str


@dataclass
class VersionLine:
    """One major release series, e.g. GCC 16 with 16.2.0 and 16.1.0."""

    major: str
    released: str = ""
    releases: list[str] = field(default_factory=list)
    companion: dict[str, str] = field(default_factory=dict)  # recommended/min/max


@dataclass
class Companion:
    """A second component whose version must match the first (binutils for GCC)."""

    id: str
    title: str
    arg: str
    releases: list[str] = field(default_factory=list)


@dataclass
class Catalog:
    id: str
    title: str
    description: str
    dockerfile: str
    image: str
    prefix: str
    version_arg: str
    versions: list[VersionLine]
    companion: Companion | None
    stages: list[Stage]
    args: list[ArgSpec]
    sections: list[Section]
    rules: list[Rule]
    path: Path | None = None

    def options(self) -> list[Option]:
        return [o for s in self.sections for o in s.options]

    def option(self, option_id: str) -> Option:
        for o in self.options():
            if o.id == option_id:
                return o
        raise KeyError(option_id)

    def arg(self, name: str) -> ArgSpec:
        for a in self.args:
            if a.name == name:
                return a
        raise KeyError(name)

    def stage(self, stage_id: str) -> Stage:
        for s in self.stages:
            if s.id == stage_id:
                return s
        raise KeyError(stage_id)

    def releases(self) -> list[str]:
        return [r for line in self.versions for r in line.releases]

    def version_line(self, version: str) -> VersionLine | None:
        for line in self.versions:
            if version in line.releases or version_at_least(version, line.major) and version_at_most(version, line.major):
                return line
        return None


@dataclass
class UbuntuVersion:
    version: str
    label: str
    released: str = ""
    host: dict[str, str] = field(default_factory=dict)


@dataclass
class UbuntuCatalog:
    default: str
    versions: list[UbuntuVersion]

    def get(self, version: str) -> UbuntuVersion | None:
        return next((u for u in self.versions if u.version == version), None)


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def _load_json(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise CatalogError(f"{path}: not found") from None
    except json.JSONDecodeError as e:
        raise CatalogError(f"{path}:{e.lineno}:{e.colno}: {e.msg}") from None


def _choice(data: dict) -> Choice:
    emit = data.get("emit")
    return Choice(
        value=str(data["value"]),
        label=data.get("label", str(data["value"])) or "(none)",
        description=data.get("description", ""),
        requires=list(data.get("requires", [])),
        exclusive=bool(data.get("exclusive", False)),
        required=bool(data.get("required", False)),
        emit={k: _words(v) for k, v in emit.items()} if emit is not None else None,
        since=data.get("since"),
        until=data.get("until"),
        when=list(data.get("when", [])),
    )


def _option(data: dict, section: Section) -> Option:
    return Option(
        id=data["id"],
        label=data.get("label", data["id"]),
        type=data["type"],
        arg=data.get("arg"),
        default=data.get("default"),
        description=data.get("description", ""),
        choices=[_choice(c) for c in data.get("choices", [])],
        on=_words(data.get("on")),
        off=_words(data.get("off")),
        template=data.get("template", "{value}"),
        raw=bool(data.get("raw", False)),
        sep=data.get("sep", ";"),
        since=data.get("since"),
        until=data.get("until"),
        since_companion=data.get("since_companion"),
        until_companion=data.get("until_companion"),
        when=list(data.get("when", [])),
        section=section,
    )


def load_catalog(path: Path) -> Catalog:
    """Load catalog/<id>.json plus its catalog/<id>.versions.json."""
    data = _load_json(path)
    versions_path = path.with_name(path.stem + ".versions.json")
    vdata = _load_json(versions_path)
    try:
        comp = data.get("companion")
        companion = (
            Companion(comp["id"], comp.get("title", comp["id"]), comp["arg"], list(vdata.get("companion_releases", [])))
            if comp
            else None
        )
        sections = []
        for s in data["sections"]:
            section = Section(s["id"], s.get("title", s["id"]), s.get("description", ""), list(s.get("when", [])))
            section.options = [_option(o, section) for o in s["options"]]
            sections.append(section)
        catalog = Catalog(
            id=data["id"],
            title=data.get("title", data["id"]),
            description=data.get("description", ""),
            dockerfile=data["dockerfile"],
            image=data.get("image", f"toolchain-{data['id']}"),
            prefix=data.get("prefix", f"/opt/{data['id']}"),
            version_arg=data["version_arg"],
            versions=[
                VersionLine(str(v["major"]), v.get("released", ""), list(v["releases"]), dict(v.get(comp["id"], {})) if comp else {})
                for v in vdata["versions"]
            ],
            companion=companion,
            stages=[Stage(s["id"], s.get("title", s["id"]), s.get("description", "")) for s in data["stages"]],
            args=[ArgSpec(a["name"], a["stage"], a.get("kind", "value"), a.get("sep", " ")) for a in data["args"]],
            sections=sections,
            rules=[Rule(list(r["if"]), r.get("level", "warn"), r["message"]) for r in data.get("rules", [])],
            path=path,
        )
    except KeyError as e:
        raise CatalogError(f"{path}: missing key {e}") from None
    problems = check_catalog(catalog)
    if problems:
        raise CatalogError(f"{path}:\n  " + "\n  ".join(problems))
    return catalog


def load_ubuntu(path: Path) -> UbuntuCatalog:
    data = _load_json(path)
    versions = [
        UbuntuVersion(str(v["version"]), v.get("label", v["version"]), v.get("released", ""), dict(v.get("host", {})))
        for v in data["versions"]
    ]
    default = data.get("default", versions[-1].version if versions else "")
    return UbuntuCatalog(default, versions)


def check_catalog(c: Catalog) -> list[str]:
    """Consistency checks, so a typo in the JSON is reported at startup."""
    problems: list[str] = []
    stage_ids = {s.id for s in c.stages}
    arg_names = {a.name for a in c.args}
    option_ids: set[str] = set()

    for a in c.args:
        if a.stage not in stage_ids:
            problems.append(f"arg {a.name}: unknown stage '{a.stage}'")
        if a.kind not in ARG_KINDS:
            problems.append(f"arg {a.name}: kind must be one of {ARG_KINDS}")
    for required in ("UBUNTU_VERSION", "PREFIX", c.version_arg) + ((c.companion.arg,) if c.companion else ()):
        if required not in arg_names:
            problems.append(f"args: '{required}' must be declared")
    if not c.versions or not all(v.releases for v in c.versions):
        problems.append("versions: every major needs at least one release")

    all_options = c.options()
    for o in all_options:
        where = f"option {o.id}"
        if o.id in option_ids:
            problems.append(f"{where}: duplicate id")
        option_ids.add(o.id)
        if o.type not in OPTION_TYPES:
            problems.append(f"{where}: type must be one of {OPTION_TYPES}")
            continue
        if o.arg is not None and o.arg not in arg_names:
            problems.append(f"{where}: unknown arg '{o.arg}'")
        values = [ch.value for ch in o.choices]
        if len(values) != len(set(values)):
            problems.append(f"{where}: duplicate choice values")
        for ch in o.choices:
            for name in (ch.emit or {}):
                if name not in arg_names:
                    problems.append(f"{where}: choice '{ch.value}' emits unknown arg '{name}'")
            for req in ch.requires:
                if req not in values:
                    problems.append(f"{where}: choice '{ch.value}' requires unknown choice '{req}'")
            if ch.emit is None and o.type in ("choice", "multi") and o.arg is None:
                problems.append(f"{where}: choice '{ch.value}' has no emit and the option has no arg")
        if o.type == "bool":
            if not isinstance(o.default, bool):
                problems.append(f"{where}: bool default must be true or false")
            if o.arg is None:
                problems.append(f"{where}: bool options need an arg")
        elif o.type == "choice":
            if o.default not in values:
                problems.append(f"{where}: default '{o.default}' is not a choice")
        elif o.type == "multi":
            if not isinstance(o.default, list) or any(v not in values for v in o.default):
                problems.append(f"{where}: default must be a list of choice values")
        elif o.type == "string":
            if not isinstance(o.default, str):
                problems.append(f"{where}: string default must be a string")
            if o.arg is None:
                problems.append(f"{where}: string options need an arg")

    def check_conditions(conds: list[dict], where: str) -> None:
        for cond in conds:
            if "option" in cond:
                if cond["option"] not in option_ids:
                    problems.append(f"{where}: condition refers to unknown option '{cond['option']}'")
            elif "version" not in cond:
                problems.append(f"{where}: condition needs 'option' or 'version': {cond}")

    for s in c.sections:
        check_conditions(s.when, f"section {s.id}")
    for o in all_options:
        check_conditions(o.when, f"option {o.id}")
        for ch in o.choices:
            check_conditions(ch.when, f"option {o.id} choice {ch.value}")
    for i, r in enumerate(c.rules):
        check_conditions(r.conditions, f"rule {i + 1}")
        if r.level not in LEVELS:
            problems.append(f"rule {i + 1}: level must be one of {LEVELS}")
    return problems
