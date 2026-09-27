# toolchains

Docker images for GCC + binutils and LLVM toolchains, configured through a curses TUI (`toolchain-tool`, Python, stdlib only).

- Read `SUMMARY.md` (architecture and running log) and `REQUIREMENTS.md` before making changes. `catalog/README.md` documents the JSON option schema.
- After any change, append a concise entry to the Log in `SUMMARY.md`, and update `REQUIREMENTS.md` if requirements change.
- Venv: `.venv/`. Install with `.venv/bin/pip install -e '.[dev]'`. Test with `.venv/bin/pytest`. Run with `.venv/bin/toolchain-tool`.
- Options live in `catalog/*.json`, not in Python. When adding a build arg, declare it in the catalog `args` and as an `ARG` in the Dockerfile layer that uses it (a test checks this).

- `toolchain-tool init` (see `cli.py`/`app.py:default_data_dir`) migrates `catalog/`/`docker/` to a user data directory for pipx installs. If you rename or add files under `catalog/` or `docker/`, this still works unchanged since it copies whole directories.
