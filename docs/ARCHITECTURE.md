# Architecture

layerguard — A CLI that enforces configured architectural import boundaries between layers in a Python codebase, with baselines and CI-friendly reports.

## Overview

The codebase is organized around a small set of focused modules. Each module owns a
single responsibility and the public surface is kept deliberately small so the tool
stays easy to hack on.

## Module map

| Path | Responsibility |
| ---- | -------------- |
| `pyproject.toml` | Package metadata, console script entry point, dependencies, and tool configuration. |
| `src/main.py` | Thin process entry point that invokes the layerguard CLI and returns its exit code. |
| `src/layerguard/__init__.py` | Package version and public API exports for library usage. |
| `src/layerguard/cli.py` | Argparse-based subcommands for init, check, baseline, and explain, including output format and exit-code handling. |
| `src/layerguard/config.py` | Load, validate, and normalize TOML layer definitions, roots, aliases, rules, and exclusions. |
| `src/layerguard/parser.py` | Walk Python files and extract import statements with AST positions and resolved module names. |
| `src/layerguard/paths.py` | Normalize filesystem paths, apply aliases, map files to layers, and handle src-layout package roots. |
| `src/layerguard/graph.py` | Construct and query the module dependency graph, including reverse edges and layer-level aggregates. |
| `src/layerguard/rules.py` | Evaluate configured boundary rules against graph edges and produce structured violation records. |
| `src/layerguard/baseline.py` | Read, write, fingerprint, and filter baseline violations for incremental CI adoption. |
| `src/layerguard/reporters.py` | Render violations and summaries as text, JSON, or SARIF output. |
| `tests/test_parser.py` | Tests import extraction for absolute, relative, aliased, and multi-name imports. |
| `tests/test_rules.py` | Tests allowed and forbidden layer dependencies, reverse rules, cycles, and baseline filtering. |
| `tests/test_cli.py` | Tests command behavior, config validation errors, exit codes, and output formats using temporary projects. |
| `docs/usage.md` | Configuration reference, rule examples, baseline workflow, and CI integration guidance. |
| `README.md` | Project overview, installation, quick start, and links to detailed documentation. |

## Key design decisions

- **Zero/low runtime dependencies**: the core works from the standard library so
  installs stay fast and supply-chain risk stays low.
- **Configuration before convention**: behavior is tunable through config files and
  documented CLI flags instead of magic environment variables.
- **Structured output modes**: human-readable text by default, machine-readable JSON
  for automation, and DOT/Mermaid exports where a graph applies.
- **Everything is guarded by tests**: the CI matrix runs the suite on every push.

## Data flow

`CLI entrypoint -> config loading -> per-item scanning/processing -> aggregation ->
reporting (text | JSON | graph)`.

## Testing

Unit tests cover AST import extraction, path and layer resolution, rule evaluation, graph aggregation, baseline fingerprinting, and config validation. CLI tests create temporary Python projects with layerguard.toml files and assert violations, allowed dependencies, baseline grandfathering, JSON/SARIF output, and non-zero exit codes for regressions.

Run them locally with `pytest -q`. CI (`.github/workflows/ci.yml`) executes the
same suite on a version matrix for every push and pull request.
