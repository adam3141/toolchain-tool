# Option catalogs

Everything the menu shows comes from these files. The Python code has no
knowledge of any GCC or LLVM option, so adding an option means editing JSON.
It never means editing code.

| File | Contents | Edited by |
|---|---|---|
| `ubuntu.json` | Ubuntu base images and their host tool versions | hand |
| `gcc.json`, `llvm.json` | build args, Docker layers, sections, options, rules | hand |
| `gcc.versions.json`, `llvm.versions.json` | release lists, binutils compatibility | `toolchain-tool refresh` and hand |

The catalogs are checked at startup. A typo, such as an option that emits to
an undeclared build arg or a condition that names an unknown option, is
reported with the file and the option id. `pytest` also checks that every build
arg is declared as an `ARG` in its Dockerfile.

## How options become build args

Each option emits items into one Docker build arg. The arg's `kind` decides
how the items are joined:

| kind | joined as | example |
|---|---|---|
| `value` | the last item | `GCC_BOOTSTRAP=off` |
| `list` | `sep` between items | `GCC_LANGUAGES=c,c++,fortran` |
| `words` | shell-quoted words, expanded in the Dockerfile with `eval "set -- $ARG"` | `GCC_CONFIGURE_FLAGS=--enable-lto '--with-pkgversion=My GCC'` |

Each arg belongs to a `stage`, which is the Docker layer that uses it. The
review screen groups args by stage, and each option shows its layer, so you can
see what a change will rebuild. Keep the order of `stages` the same as the
order of the layers in the Dockerfile.

Every arg is always passed, even when it is empty, so Dockerfile defaults never
apply without being noticed.

## Option types

```jsonc
// bool: emits `on` or `off` (a string or a list; either may be omitted)
{"id": "lto", "label": "LTO support", "type": "bool", "default": true,
 "arg": "GCC_CONFIGURE_FLAGS", "on": "--enable-lto", "off": "--disable-lto",
 "description": "Shown in the status area."}

// choice: emits template.format(value=...); an empty value emits nothing.
// A choice can instead emit to several args with "emit".
{"id": "checking", "type": "choice", "default": "release", "arg": "GCC_CONFIGURE_FLAGS",
 "template": "--enable-checking={value}",
 "choices": [{"value": "release", "label": "release", "description": "..."},
             {"value": "yes", "label": "yes"}]}
{"value": "lto", "label": "3-stage + LTO",
 "emit": {"GCC_BOOTSTRAP": "on", "GCC_CONFIGURE_FLAGS": "--with-build-config=bootstrap-lto"}}

// multi: a checklist. With a template, the values are joined with "sep" and
// emitted as one item; without one, each value is an item of a list arg.
{"id": "projects", "type": "multi", "arg": "LLVM_PROJECTS", "default": ["clang", "lld"],
 "choices": [{"value": "flang", "label": "flang", "requires": ["clang", "mlir"]},
             {"value": "all", "label": "all", "exclusive": true},
             {"value": "c", "label": "C", "required": true}]}

// string: free text, emitted through the template when not empty.
// "raw": true inserts the text unquoted, after all generated flags.
{"id": "with_arch", "type": "string", "default": "", "arg": "GCC_CONFIGURE_FLAGS",
 "template": "--with-arch={value}"}
```

`requires` selects other choices of the same list automatically. When a choice
is removed, the choices that depend on it are removed too. `exclusive` clears
the other selections. `required` cannot be removed.

## Availability

Options and choices can be limited to versions. Bounds are inclusive and are
compared at the bound's precision, so `"until": "15"` includes 15.2.0.

```jsonc
"since": "13", "until": "15"            // the GCC or LLVM version
"since_companion": "2.39"               // the binutils version (gcc.json only)
```

Options, choices and whole sections can depend on other options with `when`.
Every condition in the list must hold:

```jsonc
"when": [{"option": "bootstrap", "in": ["off"]},
         {"option": "projects", "has": "clang"},
         {"option": "projects", "lacks": "flang"},
         {"option": "dylib", "is": true},
         {"option": "runtimes", "not_empty": true},
         {"version": "binutils", "min": "2.40", "max": "2.45"}]
```

An unavailable option is shown dimmed with the reason and emits nothing. For
other conditions, an unavailable option counts as empty or off.

## Rules

`rules` are checks shown on the review screen. An `error` blocks the build.

```jsonc
{"if": [{"option": "languages", "has": "jit"}, {"option": "host_shared", "is": false}],
 "level": "error", "message": "libgccjit needs 'Host shared' turned on."}
```

## Versions

`*.versions.json` lists each major series with its releases, newest first.
For GCC, each series also names the binutils releases that go with it:

```json
{"major": "16", "released": "2026-04", "releases": ["16.2.0", "16.1.0"],
 "binutils": {"recommended": "2.46.1", "min": "2.44", "max": "2.47"}}
```

`recommended` is the binutils release that was current when that GCC came
out, and it is chosen by default. The menu offers only releases between `min`
and `max`. `toolchain-tool refresh` adds new point releases and new series.
For a new GCC series it has to guess the binutils range, and it says so. Check
the guess.

The review screen warns when a toolchain was released more than three years
before the chosen Ubuntu (using `released` here and in `ubuntu.json`), because
older sources often fail to build with a newer host compiler and glibc.
