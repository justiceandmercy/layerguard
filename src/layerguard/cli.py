"""Argparse-based CLI for layerguard."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import sys
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


EXIT_OK = 0
EXIT_VIOLATIONS = 1
EXIT_ERROR = 2

DEFAULT_CONFIG = "layerguard.toml"
DEFAULT_BASELINE = ".layerguard-baseline.json"

RULE_DESCRIPTIONS = {
    "forbidden-cross-layer": "Import crosses a layer boundary that is not declared as allowed.",
    "reverse-dependency": "A lower layer imports a higher layer, reversing the intended direction.",
    "cyclic-dependency": "Layers form a dependency cycle that is not explicitly allowed.",
}


@dataclass
class Layer:
    name: str
    roots: List[str]
    allow: List[str]


@dataclass
class Config:
    root: Path
    layers: Dict[str, Layer]
    aliases: Dict[str, str]
    src_roots: List[str]
    excludes: List[str]
    allowed_cycles: Set[Tuple[str, str]]
    baseline_path: Optional[Path]


@dataclass
class Violation:
    file: str
    line: int
    module: str
    imported: str
    rule: str
    message: str

    def identity(self) -> str:
        return f"{self.rule}:{self.file}:{self.line}:{self.imported}"


def _fail(message: str) -> int:
    print(f"layerguard: error: {message}", file=sys.stderr)
    return EXIT_ERROR


def _load_toml(path: Path) -> Dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        raise ValueError(f"configuration file not found: {path}")
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid TOML in {path}: {exc}")


def _normalize_root(root: Optional[str]) -> Path:
    return Path(root or ".").resolve()


def load_config(config_path: Optional[str], root: Path) -> Config:
    path = Path(config_path) if config_path else (root / DEFAULT_CONFIG)
    if not path.is_absolute():
        path = (root / path).resolve()
    if not path.exists():
        # Allow pyproject.toml [tool.layerguard].
        alt = root / "pyproject.toml"
        if alt.exists():
            data = _load_toml(alt)
            section = data.get("tool", {}).get("layerguard")
            if section is not None:
                path = alt
                raw = {"layerguard": section}
            else:
                raw = {}
        else:
            raw = {}
    else:
        raw = _load_toml(path)
    section = raw.get("layerguard", raw)
    layers_raw = section.get("layers", {})
    if not isinstance(layers_raw, dict) or not layers_raw:
        raise ValueError("configuration must define at least one layer")
    layers: Dict[str, Layer] = {}
    for name, info in layers_raw.items():
        if not isinstance(info, dict):
            raise ValueError(f"layer '{name}' must be a table")
        roots = info.get("roots", [])
        allow = info.get("allow", [])
        if not isinstance(roots, list) or not all(isinstance(x, str) for x in roots):
            raise ValueError(f"layer '{name}' roots must be a list of strings")
        if not isinstance(allow, list) or not all(isinstance(x, str) for x in allow):
            raise ValueError(f"layer '{name}' allow must be a list of strings")
        layers[name] = Layer(name=name, roots=roots, allow=allow)
    for layer in layers.values():
        for dep in layer.allow:
            if dep not in layers:
                raise ValueError(f"layer '{layer.name}' allows unknown layer '{dep}'")
    paths = section.get("paths", {})
    aliases = paths.get("aliases", {}) if isinstance(paths, dict) else {}
    if not isinstance(aliases, dict):
        raise ValueError("paths.aliases must be a table")
    src_roots = paths.get("src_roots", []) if isinstance(paths, dict) else []
    excludes = paths.get("exclude", []) if isinstance(paths, dict) else []
    if not isinstance(src_roots, list):
        raise ValueError("paths.src_roots must be a list")
    if not isinstance(excludes, list):
        raise ValueError("paths.exclude must be a list")
    cycles_raw = section.get("cycles", [])
    allowed_cycles: Set[Tuple[str, str]] = set()
    if isinstance(cycles_raw, list):
        for item in cycles_raw:
            if isinstance(item, list) and len(item) == 2:
                allowed_cycles.add((str(item[0]), str(item[1])))
    baseline = section.get("baseline")
    baseline_path = Path(baseline).resolve() if isinstance(baseline, str) else None
    return Config(
        root=root,
        layers=layers,
        aliases={str(k): str(v) for k, v in aliases.items()},
        src_roots=[str(x) for x in src_roots],
        excludes=[str(x) for x in excludes],
        allowed_cycles=allowed_cycles,
        baseline_path=baseline_path,
    )


def _apply_alias(name: str, aliases: Dict[str, str]) -> str:
    for alias, target in aliases.items():
        if name == alias:
            return target
        if name.startswith(alias + "."):
            return target + name[len(alias):]
    return name


def _is_excluded(rel: str, excludes: List[str]) -> bool:
    return any(fnmatch.fnmatch(rel, pat) for pat in excludes)


def _module_name(path: Path, base: Path) -> str:
    rel = path.relative_to(base)
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__.py":
        parts = parts[:-1]
    elif parts:
        parts[-1] = parts[-1][:-3]
    return ".".join(p for p in parts if p)


def _layer_for(path: Path, root: Path, config: Config) -> Optional[str]:
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return None
    for layer in config.layers.values():
        for r in layer.roots:
            rnorm = r.rstrip("/")
            if rel == rnorm or rel.startswith(rnorm + "/"):
                return layer.name
    return None


def _collect_files(root: Path, config: Config, base: Path) -> List[Path]:
    files: List[Path] = []
    for p in base.rglob("*.py"):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            rel = p.relative_to(base).as_posix()
        if _is_excluded(rel, config.excludes):
            continue
        files.append(p)
    return files


def _resolve_relative(current: str, is_package: bool, level: int, module: Optional[str]) -> Optional[str]:
    if level <= 0:
        return module
    package = current if is_package else (current.rsplit(".", 1)[0] if "." in current else "")
    parts = package.split(".") if package else []
    if level - 1 > len(parts):
        return None
    base = parts[: len(parts) - (level - 1)]
    if module:
        base = base + module.split(".")
    result = ".".join(p for p in base if p)
    return result or None


def analyze(root: Path, config: Config) -> List[Violation]:
    base = root / "src" if (root / "src").is_dir() else root
    files = _collect_files(root, config, base)
    module_index: Dict[str, Path] = {}
    file_layer: Dict[Path, str] = {}
    file_package: Dict[Path, bool] = {}
    for f in files:
        mod = _module_name(f, base)
        if mod:
            module_index[mod] = f
        layer = _layer_for(f, root, config)
        if layer:
            file_layer[f] = layer
        file_package[f] = f.name == "__init__.py"

    edges: List[Tuple[str, str, Path, int, str]] = []
    for f in files:
        current_mod = _module_name(f, base)
        if not current_mod:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except SyntaxError:
            continue
        is_pkg = f.name == "__init__.py"
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = _apply_alias(alias.name, config.aliases)
                    if name in module_index:
                        edges.append((current_mod, name, f, node.lineno, name))
            elif isinstance(node, ast.ImportFrom):
                resolved = _resolve_relative(current_mod, is_pkg, node.level, node.module)
                if resolved is None:
                    continue
                resolved = _apply_alias(resolved, config.aliases)
                targets: Set[str] = set()
                if node.names and any(a.name == "*" for a in node.names):
                    if resolved in module_index:
                        targets.add(resolved)
                else:
                    if resolved in module_index:
                        targets.add(resolved)
                    for alias in node.names:
                        cand = f"{resolved}.{alias.name}" if resolved else alias.name
                        cand = _apply_alias(cand, config.aliases)
                        if cand in module_index:
                            targets.add(cand)
                for t in targets:
                    edges.append((current_mod, t, f, node.lineno, resolved))

    # Layer graph for cycles.
    layer_edges: Set[Tuple[str, str]] = set()
    for src_mod, dst_mod, *_ in edges:
        sl = file_layer.get(module_index.get(src_mod)) if src_mod in module_index else None
        # map module->layer via file_layer
    # Build module->layer map.
    mod_layer: Dict[str, str] = {}
    for mod, f in module_index.items():
        if f in file_layer:
            mod_layer[mod] = file_layer[f]

    for src_mod, dst_mod, f, line, imported in edges:
        sl = mod_layer.get(src_mod)
        dl = mod_layer.get(dst_mod)
        if sl and dl and sl != dl:
            layer_edges.add((sl, dl))

    # SCCs (simple) for cycles.
    cyclic_pairs: Set[Tuple[str, str]] = set()
    layers_list = list(config.layers)
    # Floyd-warshall reachability.
    reach: Dict[str, Set[str]] = {l: set() for l in layers_list}
    for a, b in layer_edges:
        reach.setdefault(a, set()).add(b)
    changed = True
    while changed:
        changed = False
        for a in layers_list:
            for b in list(reach.get(a, ())):
                for c in list(reach.get(b, ())):
                    if c not in reach[a]:
                        reach[a].add(c)
                        changed = True
    for a, b in layer_edges:
        if a in reach.get(b, set()) or a == b:
            # cycle exists if a reachable from b (back path) or self-loop
            cyclic_pairs.add((a, b))

    violations: List[Violation] = []
    for src_mod, dst_mod, f, line, imported in edges:
        sl = mod_layer.get(src_mod)
        dl = mod_layer.get(dst_mod)
        if not sl or not dl or sl == dl:
            continue
        rel_file = f.relative_to(root).as_posix() if f.is_relative_to(root) else str(f)
        allowed = dl in config.layers[sl].allow
        is_cycle = (sl, dl) in cyclic_pairs and (sl, dl) not in config.allowed_cycles
        if allowed and not is_cycle:
            continue
        if is_cycle:
            rule = "cyclic-dependency"
        elif sl in config.layers[dl].allow:
            rule = "reverse-dependency"
        else:
            rule = "forbidden-cross-layer"
        msg = f"{src_mod} imports {dst_mod} ({sl} -> {dl})"
        violations.append(Violation(file=rel_file, line=line, module=src_mod, imported=imported, rule=rule, message=msg))
    # dedup exact duplicates
    seen: Set[str] = set()
    unique: List[Violation] = []
    for v in violations:
        if v.identity() in seen:
            continue
        seen.add(v.identity())
        unique.append(v)
    unique.sort(key=lambda v: (v.file, v.line, v.rule))
    return unique


def _baseline_ids(path: Optional[Path]) -> Set[str]:
    if path is None or not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    ids = data.get("violations", [])
    return set(str(x) for x in ids) if isinstance(ids, list) else set()


def _write_baseline(path: Path, violations: List[Violation]) -> None:
    path.write_text(json.dumps({"violations": [v.identity() for v in violations]}, indent=2) + "\n", encoding="utf-8")


def _report(violations: List[Violation], fmt: str) -> str:
    if fmt == "json":
        return json.dumps([ {**asdict(v), "id": v.identity()} for v in violations], indent=2)
    if fmt == "sarif":
        runs = [{
            "tool": {"driver": {"name": "layerguard", "version": "0.1.0"}},
            "results": [
                {
                    "ruleId": v.rule,
                    "level": "error",
                    "message": {"text": v.message},
                    "locations": [{
                        "physicalLocation": {
                            "artifactLocation": {"uri": v.file},
                            "region": {"startLine": v.line},
                        }
                    }],
                }
                for v in violations
            ],
        }]
        return json.dumps({"version": "2.1.0", "$schema": "https://json.schemastore.org/sarif-2.1.0.json", "runs": runs}, indent=2)
    lines = [f"{v.file}:{v.line}: {v.rule}: {v.message} (imported module: {v.imported})" for v in violations]
    return "\n".join(lines)


def cmd_init(args: argparse.Namespace) -> int:
    root = _normalize_root(args.root)
    path = root / DEFAULT_CONFIG
    if path.exists() and not args.force:
        return _fail(f"{path} already exists (use --force)")
    template = '''# layerguard configuration
[paths]
src_roots = ["src"]
exclude = ["tests/**", "**/__pycache__/**"]

[layers]
# Define layers, their source roots, and allowed dependency directions.
domain = { roots = ["src/domain"], allow = [] }
application = { roots = ["src/application"], allow = ["domain"] }
infrastructure = { roots = ["src/infrastructure"], allow = ["domain", "application"] }
presentation = { roots = ["src/presentation"], allow = ["application", "domain"] }
'''
    path.write_text(template, encoding="utf-8")
    print(f"created {path}")
    return EXIT_OK


def cmd_check(args: argparse.Namespace) -> int:
    root = _normalize_root(args.root)
    try:
        config = load_config(args.config, root)
    except ValueError as exc:
        return _fail(str(exc))
    violations = analyze(root, config)
    baseline_path = Path(args.baseline) if args.baseline else config.baseline_path
    if baseline_path is not None and not baseline_path.is_absolute():
        baseline_path = (root / baseline_path).resolve()
    baseline = _baseline_ids(baseline_path) if args.baseline or config.baseline_path else set()
    if args.no_baseline:
        baseline = set()
    new_violations = [v for v in violations if v.identity() not in baseline]
    output = _report(new_violations, args.format)
    if output:
        print(output)
    if args.output:
        Path(args.output).write_text(output + ("\n" if output else ""), encoding="utf-8")
    if new_violations:
        return EXIT_VIOLATIONS
    return EXIT_OK


def cmd_baseline(args: argparse.Namespace) -> int:
    root = _normalize_root(args.root)
    try:
        config = load_config(args.config, root)
    except ValueError as exc:
        return _fail(str(exc))
    violations = analyze(root, config)
    out = Path(args.output) if args.output else (root / DEFAULT_BASELINE)
    if not out.is_absolute():
        out = (root / out).resolve()
    _write_baseline(out, violations)
    print(f"wrote baseline with {len(violations)} violation(s) to {out}")
    return EXIT_OK


def cmd_explain(args: argparse.Namespace) -> int:
    target = args.target
    if target in RULE_DESCRIPTIONS:
        print(f"{target}: {RULE_DESCRIPTIONS[target]}")
        return EXIT_OK
    # Allow explaining a violation id prefix.
    print(f"Unknown target '{target}'. Known rules: {', '.join(sorted(RULE_DESCRIPTIONS))}")
    return EXIT_ERROR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="layerguard", description="Enforce architectural import boundaries.")
    parser.add_argument("--root", default=None, help="Project root (default: current directory)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create a starter configuration")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing config")
    p_init.set_defaults(func=cmd_init)

    p_check = sub.add_parser("check", help="Check import boundaries")
    p_check.add_argument("--config", default=None, help="Path to config file")
    p_check.add_argument("--format", choices=["text", "json", "sarif"], default="text")
    p_check.add_argument("--baseline", default=None, help="Baseline file to filter known violations")
    p_check.add_argument("--no-baseline", action="store_true", help="Ignore configured baseline")
    p_check.add_argument("--output", default=None, help="Write report to file")
    p_check.set_defaults(func=cmd_check)

    p_base = sub.add_parser("baseline", help="Generate a baseline file")
    p_base.add_argument("--config", default=None, help="Path to config file")
    p_base.add_argument("--output", default=None, help="Baseline output path")
    p_base.set_defaults(func=cmd_baseline)

    p_exp = sub.add_parser("explain", help="Explain a rule or violation")
    p_exp.add_argument("target", help="Rule name or violation id")
    p_exp.set_defaults(func=cmd_explain)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else EXIT_ERROR
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return EXIT_ERROR
    except Exception as exc:  # pragma: no cover - defensive
        return _fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
