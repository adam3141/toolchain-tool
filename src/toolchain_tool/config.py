"""A toolchain configuration: selected versions and option values.

Turns the selections into Docker build args, checks them against the catalog
rules, and saves/loads them as profile JSON files.
"""

from __future__ import annotations

import copy
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .catalog import (
    Catalog,
    Choice,
    Option,
    Stage,
    UbuntuCatalog,
    version_at_least,
    version_at_most,
    version_key,
)

PROFILE_FORMAT = 1


@dataclass
class Issue:
    level: str  # error | warn | info
    message: str


def _year_month(text: str) -> float | None:
    try:
        year, month = text.split("-")[:2]
        return int(year) + (int(month) - 1) / 12
    except (ValueError, AttributeError):
        return None


class BuildConfig:
    # A toolchain released this many years before the Ubuntu release may not
    # compile with that release's newer host compiler and glibc.
    HOST_AGE_WARN_YEARS = 3

    def __init__(self, catalog: Catalog, ubuntu: UbuntuCatalog) -> None:
        self.catalog = catalog
        self.ubuntu_catalog = ubuntu
        self.ubuntu = ubuntu.default
        self.version = catalog.versions[0].releases[0]
        self.companion_version = self.recommended_companion() or ""
        self.prefix = catalog.prefix
        self.custom_tag: str | None = None  # None means derive from the versions
        self.values: dict[str, Any] = {o.id: copy.deepcopy(o.default) for o in catalog.options()}

    # ---- versions ------------------------------------------------------
    @property
    def image_tag(self) -> str:
        return self.custom_tag or self.default_tag()

    def default_tag(self) -> str:
        return f"{self.catalog.image}:{self.version}-ubuntu{self.ubuntu}"

    def version_line(self):
        return self.catalog.version_line(self.version)

    def recommended_companion(self) -> str | None:
        if not self.catalog.companion:
            return None
        line = self.version_line()
        rec = line.companion.get("recommended") if line else None
        return rec or (self.catalog.companion.releases[0] if self.catalog.companion.releases else None)

    def companion_compatible(self, release: str) -> bool:
        line = self.version_line()
        if not line:
            return True
        lo, hi = line.companion.get("min"), line.companion.get("max")
        return (lo is None or version_at_least(release, lo)) and (hi is None or version_at_most(release, hi))

    def companion_choices(self) -> list[str]:
        if not self.catalog.companion:
            return []
        return [r for r in self.catalog.companion.releases if self.companion_compatible(r)]

    def set_version(self, version: str) -> None:
        old_line = self.version_line()
        self.version = version
        if self.catalog.companion:
            new_line = self.version_line()
            if old_line is not new_line or not self.companion_compatible(self.companion_version):
                self.companion_version = self.recommended_companion() or ""
        self._drop_unavailable_choices()

    def _drop_unavailable_choices(self) -> None:
        """Remove multi selections that the new version does not have (e.g. m2 before GCC 13)."""
        for o in self.catalog.options():
            if o.type == "multi":
                self.values[o.id] = [v for v in self.values[o.id] if (c := o.choice(v)) and not self._version_reason(c)]

    def component_version(self, name: str) -> str | None:
        if name == self.catalog.id:
            return self.version
        if self.catalog.companion and name == self.catalog.companion.id:
            return self.companion_version
        if name == "ubuntu":
            return self.ubuntu
        return None

    # ---- conditions ----------------------------------------------------
    def check(self, cond: dict, seen: frozenset[str] = frozenset()) -> bool:
        """Evaluate one condition. An unavailable option counts as empty/off."""
        if "version" in cond:
            v = self.component_version(cond["version"])
            if v is None:
                return False
            ok = True
            if "min" in cond:
                ok = ok and version_at_least(v, cond["min"])
            if "max" in cond:
                ok = ok and version_at_most(v, cond["max"])
            return ok
        opt = self.catalog.option(cond["option"])
        value = self.effective(opt, seen)
        if "in" in cond:
            return value in cond["in"]
        if "has" in cond:
            return isinstance(value, list) and cond["has"] in value
        if "lacks" in cond:
            return not (isinstance(value, list) and cond["lacks"] in value)
        if "is" in cond:
            return value == cond["is"]
        if "not_empty" in cond:
            return bool(value) == bool(cond["not_empty"])
        return True

    def describe(self, cond: dict) -> str:
        """Human text for a condition, used as the reason an option is unavailable."""
        if "version" in cond:
            name = self._component_title(cond["version"])
            if "min" in cond and "max" in cond:
                return f"needs {name} {cond['min']} to {cond['max']}"
            if "min" in cond:
                return f"needs {name} {cond['min']} or newer"
            return f"needs {name} {cond['max']} or older"
        opt = self.catalog.option(cond["option"])
        if "in" in cond:
            labels = [self._choice_label(opt, v) for v in cond["in"]]
            return f"only when {opt.label} is {' or '.join(labels)}"
        if "has" in cond:
            return f"needs {self._choice_label(opt, cond['has'])} in {opt.label}"
        if "lacks" in cond:
            return f"not with {self._choice_label(opt, cond['lacks'])} in {opt.label}"
        if "is" in cond:
            if isinstance(cond["is"], bool):
                return f"needs {opt.label} turned {'on' if cond['is'] else 'off'}"
            return f"needs {opt.label} = {cond['is']}"
        if "not_empty" in cond:
            return f"needs something selected in {opt.label}"
        return "unavailable"

    def _component_title(self, name: str) -> str:
        if name == self.catalog.id:
            return self.catalog.title.split(" ")[0]
        if self.catalog.companion and name == self.catalog.companion.id:
            return self.catalog.companion.title
        return name.capitalize()

    @staticmethod
    def _choice_label(opt: Option, value: str) -> str:
        c = opt.choice(value)
        return c.label if c else value or "(none)"

    def _version_reason(self, item: Option | Choice) -> str | None:
        main = self._component_title(self.catalog.id)
        if item.since and not version_at_least(self.version, item.since):
            return f"needs {main} {item.since} or newer"
        if item.until and not version_at_most(self.version, item.until):
            return f"needs {main} {item.until} or older"
        if isinstance(item, Option) and self.catalog.companion:
            comp = self.catalog.companion.title
            if item.since_companion and not version_at_least(self.companion_version, item.since_companion):
                return f"needs {comp} {item.since_companion} or newer"
            if item.until_companion and not version_at_most(self.companion_version, item.until_companion):
                return f"needs {comp} {item.until_companion} or older"
        return None

    def _when_reason(self, conds: list[dict], seen: frozenset[str]) -> str | None:
        for cond in conds:
            if cond.get("option") in seen:
                continue  # conditions that refer back to each other are ignored
            if not self.check(cond, seen):
                return self.describe(cond)
        return None

    def _option_reason(self, opt: Option, seen: frozenset[str] = frozenset()) -> str | None:
        seen = seen | {opt.id}
        if opt.section and opt.section.when:
            reason = self._when_reason(opt.section.when, seen)
            if reason:
                return reason
        return self._version_reason(opt) or self._when_reason(opt.when, seen)

    def option_reason(self, opt: Option) -> str | None:
        """Why the option is unavailable, or None if it can be used."""
        return self._option_reason(opt)

    def choice_reason(self, opt: Option, choice: Choice, seen: frozenset[str] = frozenset()) -> str | None:
        return self._version_reason(choice) or self._when_reason(choice.when, seen | {opt.id})

    def section_reason(self, section) -> str | None:
        return self._when_reason(section.when, frozenset())

    # ---- values --------------------------------------------------------
    def effective(self, opt: Option, seen: frozenset[str] = frozenset()) -> Any:
        """The value that takes effect, i.e. None for an unavailable option."""
        if self._option_reason(opt, seen) is not None:
            return None
        value = self.values.get(opt.id)
        if opt.type == "multi":
            return [v for v in value or [] if (c := opt.choice(v)) and self.choice_reason(opt, c, seen) is None]
        return value

    def is_default(self, opt: Option) -> bool:
        return self.values.get(opt.id) == opt.default

    def changed_count(self, options: list[Option]) -> int:
        return sum(1 for o in options if not self.is_default(o))

    def reset(self, opt: Option) -> None:
        self.values[opt.id] = copy.deepcopy(opt.default)

    def set(self, opt: Option, value: Any) -> None:
        self.values[opt.id] = value

    def toggle_choice(self, opt: Option, value: str) -> list[str]:
        """Toggle a value of a multi option. Returns notes about related changes."""
        selected: list[str] = list(self.values.get(opt.id) or [])
        choice = opt.choice(value)
        if choice is None:
            return []
        notes: list[str] = []
        if value in selected:
            if choice.required:
                return [f"{choice.label} is always built"]
            removed = {value}
            # Also drop anything that requires what was removed.
            changed = True
            while changed:
                changed = False
                for c in opt.choices:
                    if c.value in selected and c.value not in removed and removed & set(c.requires):
                        removed.add(c.value)
                        changed = True
            selected = [v for v in selected if v not in removed]
            extra = [self._choice_label(opt, v) for v in removed - {value}]
            if extra:
                notes.append("Also removed " + ", ".join(sorted(extra)) + " (they need it)")
        else:
            if choice.exclusive:
                if selected:
                    notes.append(f"{choice.label} replaces the other selections")
                selected = [value]
            else:
                dropped = [v for v in selected if (c := opt.choice(v)) and c.exclusive]
                if dropped:
                    notes.append("Removed " + ", ".join(self._choice_label(opt, v) for v in dropped))
                selected = [v for v in selected if v not in dropped]
                added = self._with_requirements(opt, value, selected)
                extra = [self._choice_label(opt, v) for v in added if v != value]
                if extra:
                    notes.append("Also selected " + ", ".join(extra))
                selected += added
        # Keep catalog order so the generated argument is stable.
        order = [c.value for c in opt.choices]
        self.values[opt.id] = sorted(set(selected), key=order.index)
        return notes

    def _with_requirements(self, opt: Option, value: str, selected: list[str]) -> list[str]:
        out: list[str] = []
        stack = [value]
        while stack:
            v = stack.pop()
            if v in selected or v in out:
                continue
            out.append(v)
            c = opt.choice(v)
            if c:
                stack.extend(c.requires)
        return out

    # ---- build args ----------------------------------------------------
    def emissions(self, opt: Option) -> dict[str, list[tuple[str, bool]]]:
        """Items this option contributes to each build arg, as (text, raw) pairs."""
        value = self.effective(opt)
        out: dict[str, list[tuple[str, bool]]] = {}
        if value is None:
            return out

        def add(arg: str | None, items: list[str], raw: bool = False) -> None:
            if arg and items:
                out.setdefault(arg, []).extend((i, raw) for i in items)

        if opt.type == "bool":
            add(opt.arg, opt.on if value else opt.off)
        elif opt.type == "string":
            text = value.strip()
            if text:
                add(opt.arg, [text] if opt.raw else [opt.template.format(value=text)], raw=opt.raw)
        elif opt.type == "choice":
            c = opt.choice(value)
            if c and c.emit is not None:
                for arg, items in c.emit.items():
                    add(arg, items)
            elif value != "":
                add(opt.arg, [opt.template.format(value=value)])
        elif opt.type == "multi":
            plain: list[str] = []
            for v in value:
                c = opt.choice(v)
                if c and c.emit is not None:
                    for arg, items in c.emit.items():
                        add(arg, items)
                else:
                    plain.append(v)
            if plain:
                if opt.template != "{value}":
                    add(opt.arg, [opt.template.format(value=opt.sep.join(plain))])
                else:
                    add(opt.arg, plain)
        return out

    def preview(self, opt: Option) -> str:
        """Short text of what the option emits, for the status line."""
        parts = []
        for arg, items in self.emissions(opt).items():
            parts.append(f"{arg}: " + self._render(arg, items))
        return "  ".join(parts)

    def _render(self, arg_name: str, items: list[tuple[str, bool]]) -> str:
        spec = self.catalog.arg(arg_name)
        if spec.kind == "words":
            # Raw (user-typed) text goes last so it can override the generated flags.
            quoted = [shlex.quote(text) for text, raw in items if not raw]
            return " ".join(quoted + [text for text, raw in items if raw])
        if spec.kind == "list":
            return spec.sep.join(text for text, _ in items)
        return items[-1][0] if items else ""

    def build_args(self) -> dict[str, str]:
        """Every build arg, in catalog order. Args with no value are passed as
        empty strings so the Dockerfile defaults never apply silently."""
        collected: dict[str, list[tuple[str, bool]]] = {a.name: [] for a in self.catalog.args}
        fixed = {"UBUNTU_VERSION": self.ubuntu, "PREFIX": self.prefix, self.catalog.version_arg: self.version}
        if self.catalog.companion:
            fixed[self.catalog.companion.arg] = self.companion_version
        for opt in self.catalog.options():
            for arg, items in self.emissions(opt).items():
                collected[arg].extend(items)
        out: dict[str, str] = {}
        for spec in self.catalog.args:
            out[spec.name] = fixed[spec.name] if spec.name in fixed else self._render(spec.name, collected[spec.name])
        return out

    def args_by_stage(self) -> list[tuple[Stage, list[tuple[str, str]]]]:
        args = self.build_args()
        out = []
        for stage in self.catalog.stages:
            items = [(a.name, args[a.name]) for a in self.catalog.args if a.stage == stage.id]
            out.append((stage, items))
        return out

    def stage_of(self, opt: Option) -> Stage | None:
        """The earliest Docker stage the option affects (what a change rebuilds from)."""
        args = set()
        if opt.arg:
            args.add(opt.arg)
        for c in opt.choices:
            args.update((c.emit or {}).keys())
        order = [s.id for s in self.catalog.stages]
        stages = [self.catalog.arg(a).stage for a in args]
        if not stages:
            return None
        return self.catalog.stage(min(stages, key=order.index))

    # ---- validation ----------------------------------------------------
    def validate(self) -> list[Issue]:
        issues: list[Issue] = []
        cat = self.catalog
        if self.ubuntu_catalog.get(self.ubuntu) is None:
            issues.append(Issue("warn", f"Ubuntu {self.ubuntu} is not in catalog/ubuntu.json; it will still be tried."))
        if self.version not in cat.releases():
            issues.append(Issue("warn", f"{cat.title} {self.version} is not a known release."))
        if cat.companion:
            if not self.companion_version:
                issues.append(Issue("error", f"No {cat.companion.title} version selected."))
            elif not self.companion_compatible(self.companion_version):
                line = self.version_line()
                rng = f"{line.companion.get('min', '?')} to {line.companion.get('max', '?')}" if line else "?"
                issues.append(Issue("error", f"{cat.companion.title} {self.companion_version} is outside the range "
                                             f"for {cat.title.split(' ')[0]} {self.version} ({rng})."))
        if not self.prefix.startswith("/"):
            issues.append(Issue("error", "The install prefix must be an absolute path."))

        line, host = self.version_line(), self.ubuntu_catalog.get(self.ubuntu)
        if line and host:
            t, u = _year_month(line.released), _year_month(host.released)
            if t is not None and u is not None and u - t > self.HOST_AGE_WARN_YEARS:
                issues.append(Issue("warn", f"{cat.title.split(' ')[0]} {line.major} ({line.released}) is much older than "
                                            f"Ubuntu {host.version}; its newer host compiler/glibc may not build it. "
                                            f"An older Ubuntu is safer."))

        for opt in cat.options():
            value = self.values.get(opt.id)
            if opt.type == "choice" and opt.choice(value) is None:
                issues.append(Issue("error", f"{opt.label}: '{value}' is not a valid choice."))
            if opt.type == "multi" and self.option_reason(opt) is None:
                eff = self.effective(opt)
                for c in opt.choices:
                    if c.required and c.value not in eff:
                        issues.append(Issue("error", f"{opt.label}: {c.label} is required."))
                    if c.value in eff:
                        missing = [r for r in c.requires if r not in eff]
                        if missing:
                            issues.append(Issue("error", f"{opt.label}: {c.label} needs {', '.join(missing)}."))
                unknown = [v for v in value or [] if opt.choice(v) is None]
                if unknown:
                    issues.append(Issue("warn", f"{opt.label}: ignoring unknown {', '.join(unknown)}."))

        for rule in cat.rules:
            if all(self.check(c) for c in rule.conditions):
                issues.append(Issue(rule.level, rule.message))
        order = {"error": 0, "warn": 1, "info": 2}
        return sorted(issues, key=lambda i: order.get(i.level, 3))

    def has_errors(self) -> bool:
        return any(i.level == "error" for i in self.validate())

    # ---- docker --------------------------------------------------------
    def docker_command(self, docker_dir: Path, export_dir: str | None = None) -> list[str]:
        cmd = ["docker", "buildx", "build", "-f", str(docker_dir / self.catalog.dockerfile)]
        if export_dir:
            cmd += ["--target", "export", "--output", f"type=local,dest={export_dir}"]
        else:
            cmd += ["--target", "final", "--load", "-t", self.image_tag]
        for name, value in self.build_args().items():
            cmd += ["--build-arg", f"{name}={value}"]
        cmd.append(str(docker_dir))
        return cmd

    def shell_command(self, docker_dir: Path, export_dir: str | None = None) -> str:
        """The docker command as a readable multi-line shell command."""
        takes_value = {"-f", "-t", "--target", "--output", "--build-arg"}
        cmd = self.docker_command(docker_dir, export_dir)
        lines, rest, i = [shlex.join(cmd[:3])], cmd[3:-1], 0
        while i < len(rest):
            if rest[i] in takes_value and i + 1 < len(rest):
                lines.append(f"  {rest[i]} {shlex.quote(rest[i + 1])}")
                i += 2
            else:
                lines.append(f"  {shlex.quote(rest[i])}")
                i += 1
        lines.append(f"  {shlex.quote(cmd[-1])}")
        return " \\\n".join(lines)

    # ---- profiles ------------------------------------------------------
    def to_profile(self) -> dict:
        data: dict[str, Any] = {
            "format": PROFILE_FORMAT,
            "toolchain": self.catalog.id,
            "ubuntu": self.ubuntu,
            "version": self.version,
        }
        if self.catalog.companion:
            data[self.catalog.companion.id] = self.companion_version
        data["prefix"] = self.prefix
        if self.custom_tag:
            data["tag"] = self.custom_tag
        # Only changed options, so catalog default changes still apply to old profiles.
        data["options"] = {o.id: self.values[o.id] for o in self.catalog.options() if not self.is_default(o)}
        return data

    def apply_profile(self, data: dict) -> list[str]:
        """Load a profile over the defaults. Returns warnings for things ignored."""
        warnings: list[str] = []
        if data.get("toolchain") != self.catalog.id:
            raise ValueError(f"profile is for '{data.get('toolchain')}', not '{self.catalog.id}'")
        self.ubuntu = str(data.get("ubuntu", self.ubuntu))
        if "version" in data:
            self.set_version(str(data["version"]))
        if self.catalog.companion and self.catalog.companion.id in data:
            self.companion_version = str(data[self.catalog.companion.id])
        self.prefix = str(data.get("prefix", self.prefix))
        self.custom_tag = data.get("tag") or None
        for key, value in (data.get("options") or {}).items():
            try:
                opt = self.catalog.option(key)
            except KeyError:
                warnings.append(f"unknown option '{key}' ignored")
                continue
            if not self._value_type_ok(opt, value):
                warnings.append(f"option '{key}' has the wrong type; default kept")
                continue
            self.values[key] = value
        return warnings

    @staticmethod
    def _value_type_ok(opt: Option, value: Any) -> bool:
        if opt.type == "bool":
            return isinstance(value, bool)
        if opt.type == "multi":
            return isinstance(value, list) and all(isinstance(v, str) for v in value)
        return isinstance(value, str)


def sort_releases(releases: list[str]) -> list[str]:
    return sorted(set(releases), key=version_key, reverse=True)
