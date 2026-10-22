# layerguard

[![CI](https://github.com/justiceandmercy/layerguard/actions/workflows/ci.yml/badge.svg)](https://github.com/justiceandmercy/layerguard/actions/workflows/ci.yml)


> A CLI that enforces configured architectural import boundaries between layers in a Python codebase, with baselines and CI-friendly reports.

[![CI](https://github.com/justiceandmercy/layerguard/actions/workflows/ci.yml/badge.svg)](https://github.com/justiceandmercy/layerguard/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Topics:** architecture, linting, import-boundaries, python, cli, static-analysis, developer-tools

## Features

- Define named layers, their source roots, and allowed dependency directions in a TOML configuration file.
- Parse absolute and relative Python imports from ASTs while preserving source locations and module resolution context.
- Build an internal module dependency graph that can be queried by layer, package, or individual module.
- Detect forbidden cross-layer imports, reverse dependencies, and configured cyclic dependencies between layers.
- Support path aliases, src-layout roots, package prefixes, and configurable exclusion globs.
- Generate a baseline file that records existing violations so only new regressions fail CI.
- Report violations in human-readable, JSON, and SARIF-compatible formats with file, line, imported module, and rule details.
- Provide init, check, baseline, and explain subcommands with deterministic exit codes for automation.
- Calculate per-layer dependency metrics such as fan-in, fan-out, and boundary crossing counts.
- Validate configuration structure and provide actionable errors for unknown layers, roots, and rules.

## Install

git clone https://github.com/justiceandmercy/layerguard.git
cd layerguard
pip install .

## Quick start

layerguard --help

Entry point: `src/main.py`.

## Architecture

- `pyproject.toml` — Package metadata, console script entry point, dependencies, and tool configuration.
- `src/main.py` — Thin process entry point that invokes the layerguard CLI and returns its exit code.
- `src/layerguard/__init__.py` — Package version and public API exports for library usage.
- `src/layerguard/cli.py` — Argparse-based subcommands for init, check, baseline, and explain, including output format and exit-code handling.
- `src/layerguard/config.py` — Load, validate, and normalize TOML layer definitions, roots, aliases, rules, and exclusions.
- `src/layerguard/parser.py` — Walk Python files and extract import statements with AST positions and resolved module names.
- `src/layerguard/paths.py` — Normalize filesystem paths, apply aliases, map files to layers, and handle src-layout package roots.
- `src/layerguard/graph.py` — Construct and query the module dependency graph, including reverse edges and layer-level aggregates.
- `src/layerguard/rules.py` — Evaluate configured boundary rules against graph edges and produce structured violation records.
- `src/layerguard/baseline.py` — Read, write, fingerprint, and filter baseline violations for incremental CI adoption.
- `src/layerguard/reporters.py` — Render violations and summaries as text, JSON, or SARIF output.
- `tests/test_parser.py` — Tests import extraction for absolute, relative, aliased, and multi-name imports.
- `tests/test_rules.py` — Tests allowed and forbidden layer dependencies, reverse rules, cycles, and baseline filtering.
- `tests/test_cli.py` — Tests command behavior, config validation errors, exit codes, and output formats using temporary projects.
- `docs/usage.md` — Configuration reference, rule examples, baseline workflow, and CI integration guidance.
- `README.md` — Project overview, installation, quick start, and links to detailed documentation.

For the full module map and design decisions, read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Testing

pytest -q

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). PRs welcome!

## License

MIT — see [LICENSE](LICENSE).
