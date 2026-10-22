"""Module dependency graph helpers for layerguard."""

from __future__ import annotations

import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .config import Config


@dataclass
class ModuleNode:
    name: str
    layer: str | None = None
    path: Path | None = None
    package: str | None = None


@dataclass(frozen=True)
class DependencyEdge:
    source: str
    target: str
    file: Path | None = None
    line: int | None = None
    source_layer: str | None = None
    target_layer: str | None = None
    kind: str = 'import'


@dataclass
class Violation:
    rule: str
    message: str = ''
    file: Path | None = None
    line: int | None = None
    source_module: str = ''
    target_module: str = ''
    source_layer: str | None = None
    target_layer: str | None = None


@dataclass
class DependencyGraph:
    nodes: dict[str, ModuleNode] = field(default_factory=dict)
    edges: list[DependencyEdge] = field(default_factory=list)
    _adj: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    _radj: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    _edge_index: dict[tuple[str, str], list[int]] = field(default_factory=lambda: defaultdict(list))

    def add_module(self, name: str, *, layer: str | None = None, path: Path | None = None, package: str | None = None) -> ModuleNode:
        if name in self.nodes:
            node = self.nodes[name]
            if layer is not None:
                node.layer = layer
            if path is not None:
                node.path = path
            if package is not None:
                node.package = package
        else:
            self.nodes[name] = ModuleNode(name=name, layer=layer, path=path, package=package)
        self._adj.setdefault(name, set())
        self._radj.setdefault(name, set())
        return self.nodes[name]

    def add_dependency(self, source: str, target: str, *, file: Path | None = None, line: int | None = None, source_layer: str | None = None, target_layer: str | None = None, kind: str = 'import') -> DependencyEdge:
        self.add_module(source, layer=source_layer, path=file)
        self.add_module(target, layer=target_layer)
        if source_layer is not None:
            self.nodes[source].layer = source_layer
        if target_layer is not None:
            self.nodes[target].layer = target_layer
        resolved_source_layer = source_layer if source_layer is not None else self.nodes[source].layer
        resolved_target_layer = target_layer if target_layer is not None else self.nodes[target].layer
        for index in self._edge_index.get((source, target), []):
            existing = self.edges[index]
            if existing.file == file and existing.line == line:
                return existing
        edge = DependencyEdge(source=source, target=target, file=file, line=line, source_layer=resolved_source_layer, target_layer=resolved_target_layer, kind=kind)
        index = len(self.edges)
        self.edges.append(edge)
        self._adj[source].add(target)
        self._radj[target].add(source)
        self._edge_index[(source, target)].append(index)
        return edge

    def add_edge(self, *args, **kwargs) -> DependencyEdge:
        return self.add_dependency(*args, **kwargs)

    def modules(self, *, layer: str | None = None, package: str | None = None) -> list[str]:
        result = []
        for name, node in self.nodes.items():
            if layer is not None and node.layer != layer:
                continue
            if package is not None and node.package != package and not name.startswith(package + '.'):
                continue
            result.append(name)
        return sorted(result)

    def dependencies(self, module: str, *, transitive: bool = False) -> set[str]:
        if module not in self.nodes:
            return set()
        if not transitive:
            return set(self._adj.get(module, ()))
        seen: set[str] = set()
        queue: deque[str] = deque([module])
        while queue:
            current = queue.popleft()
            for target in self._adj.get(current, ()):
                if target not in seen:
                    seen.add(target)
                    queue.append(target)
        seen.discard(module)
        return seen

    def dependents(self, module: str, *, transitive: bool = False) -> set[str]:
        if module not in self.nodes:
            return set()
        if not transitive:
            return set(self._radj.get(module, ()))
        seen: set[str] = set()
        queue: deque[str] = deque([module])
        while queue:
            current = queue.popleft()
            for source in self._radj.get(current, ()):
                if source not in seen:
                    seen.add(source)
                    queue.append(source)
        seen.discard(module)
        return seen

    def edges_from(self, module: str | None = None) -> list[DependencyEdge]:
        if module is None:
            return list(self.edges)
        return [edge for edge in self.edges if edge.source == module]

    def edges_to(self, module: str | None = None) -> list[DependencyEdge]:
        if module is None:
            return list(self.edges)
        return [edge for edge in self.edges if edge.target == module]

    def layer_dependencies(self) -> dict[tuple[str, str], int]:
        counts: dict[tuple[str, str], int] = defaultdict(int)
        for edge in self.edges:
            source_layer = edge.source_layer if edge.source_layer is not None else self.nodes[edge.source].layer
            target_layer = edge.target_layer if edge.target_layer is not None else self.nodes[edge.target].layer
            if source_layer is None or target_layer is None:
                continue
            counts[(source_layer, target_layer)] += 1
        return dict(counts)

    def cross_layer_edges(self) -> list[DependencyEdge]:
        result = []
        for edge in self.edges:
            source_layer = edge.source_layer if edge.source_layer is not None else self.nodes[edge.source].layer
            target_layer = edge.target_layer if edge.target_layer is not None else self.nodes[edge.target].layer
            if source_layer is not None and target_layer is not None and source_layer != target_layer:
                result.append(edge)
        return result

    def _tarjan_scc(self, nodes: Iterable[str], adjacency: Mapping[str, Iterable[str]]) -> list[list[str]]:
        node_list = list(nodes)
        sys.setrecursionlimit(max(1000, len(node_list) + 100))
        index_counter = [0]
        stack: list[str] = []
        indices: dict[str, int] = {}
        lowlinks: dict[str, int] = {}
        on_stack: dict[str, bool] = {}
        result: list[list[str]] = []

        def strongconnect(vertex: str) -> None:
            indices[vertex] = index_counter[0]
            lowlinks[vertex] = index_counter[0]
            index_counter[0] += 1
            stack.append(vertex)
            on_stack[vertex] = True
            for successor in adjacency.get(vertex, ()):
                if successor not in indices:
                    strongconnect(successor)
                    lowlinks[vertex] = min(lowlinks[vertex], lowlinks[successor])
                elif on_stack.get(successor):
                    lowlinks[vertex] = min(lowlinks[vertex], indices[successor])
            if lowlinks[vertex] == indices[vertex]:
                component: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack[member] = False
                    component.append(member)
                    if member == vertex:
                        break
                result.append(component)

        for vertex in node_list:
            if vertex not in indices:
                strongconnect(vertex)
        return result

    def module_cycles(self) -> list[list[str]]:
        components = self._tarjan_scc(list(self.nodes), self._adj)
        cycles = []
        for component in components:
            if len(component) > 1:
                cycles.append(sorted(component))
            elif len(component) == 1:
                vertex = component[0]
                if vertex in self._adj.get(vertex, ()):
                    cycles.append([vertex])
        return sorted(cycles)

    def layer_cycles(self) -> list[list[str]]:
        layers = sorted({node.layer for node in self.nodes.values() if node.layer is not None})
        adjacency: dict[str, set[str]] = {layer: set() for layer in layers}
        for edge in self.cross_layer_edges():
            source_layer = edge.source_layer if edge.source_layer is not None else self.nodes[edge.source].layer
            target_layer = edge.target_layer if edge.target_layer is not None else self.nodes[edge.target].layer
            if source_layer is not None and target_layer is not None and source_layer != target_layer:
                adjacency.setdefault(source_layer, set()).add(target_layer)
        components = self._tarjan_scc(layers, adjacency)
        cycles = []
        for component in components:
            if len(component) > 1:
                cycles.append(sorted(component))
            elif len(component) == 1:
                layer = component[0]
                if layer in adjacency.get(layer, ()):
                    cycles.append([layer])
        return sorted(cycles)

    def metrics(self) -> dict[str, Any]:
        module_metrics = {
            name: {'fan_in': len(self._radj.get(name, ())), 'fan_out': len(self._adj.get(name, ()))}
            for name in self.nodes
        }
        layers = sorted({node.layer for node in self.nodes.values() if node.layer is not None})
        layer_metrics: dict[str, dict[str, int]] = {}
        for layer in layers:
            incoming = [edge for edge in self.edges if (edge.target_layer if edge.target_layer is not None else self.nodes[edge.target].layer) == layer and ((edge.source_layer if edge.source_layer is not None else self.nodes[edge.source].layer) != layer)]
            outgoing = [edge for edge in self.edges if (edge.source_layer if edge.source_layer is not None else self.nodes[edge.source].layer) == layer and ((edge.target_layer if edge.target_layer is not None else self.nodes[edge.target].layer) != layer)]
            internal = [edge for edge in self.edges if (edge.source_layer if edge.source_layer is not None else self.nodes[edge.source].layer) == layer and (edge.target_layer if edge.target_layer is not None else self.nodes[edge.target].layer) == layer]
            layer_metrics[layer] = {
                'fan_in': len(incoming),
                'fan_out': len(outgoing),
                'boundary_crossings': len(outgoing),
                'internal_edges': len(internal),
                'modules': len(self.modules(layer=layer)),
            }
        return {'modules': module_metrics, 'layers': layer_metrics}

    def layer_metrics(self) -> dict[str, dict[str, int]]:
        return self.metrics()['layers']

    def to_dict(self) -> dict[str, Any]:
        return {
            'nodes': {name: {'layer': node.layer, 'path': str(node.path) if node.path is not None else None, 'package': node.package} for name, node in self.nodes.items()},
            'edges': [{'source': edge.source, 'target': edge.target, 'file': str(edge.file) if edge.file is not None else None, 'line': edge.line, 'source_layer': edge.source_layer, 'target_layer': edge.target_layer, 'kind': edge.kind} for edge in self.edges],
            'cycles': self.module_cycles(),
            'layer_cycles': self.layer_cycles(),
            'metrics': self.metrics(),
        }

    def detect_violations(self, config: Config) -> list[Violation]:
        violations: list[Violation] = []
        for edge in self.edges:
            source_layer = edge.source_layer if edge.source_layer is not None else self.nodes[edge.source].layer
            target_layer = edge.target_layer if edge.target_layer is not None else self.nodes[edge.target].layer
            if source_layer is None or target_layer is None or source_layer == target_layer:
                continue
            if not config.is_allowed(source_layer, target_layer):
                violations.append(Violation(
                    rule='forbidden-cross-layer',
                    message=f'{source_layer} is not allowed to depend on {target_layer}',
                    file=edge.file,
                    line=edge.line,
                    source_module=edge.source,
                    target_module=edge.target,
                    source_layer=source_layer,
                    target_layer=target_layer,
                ))
        for cycle in self.layer_cycles():
            violations.append(Violation(
                rule='layer-cycle',
                message=' -> '.join(cycle + [cycle[0]]),
                source_layer=cycle[0],
                target_layer=cycle[-1],
            ))
        return violations


def build_dependency_graph(records: Iterable[Any], *, resolver: Any = None, config: Config | None = None) -> DependencyGraph:
    graph = DependencyGraph()
    for record in records:
        if isinstance(record, Mapping):
            get = record.get
        else:
            def get(key: str, default: Any = None) -> Any:
                return getattr(record, key, default)
        source_module = get('module_name') or get('source_module')
        file_value = get('file')
        if source_module is None and resolver is not None and file_value is not None:
            source_module = getattr(resolver, 'module_name_for_path', lambda value: None)(file_value)
        target_module = get('resolved_module') or get('module') or get('target_module')
        if not source_module or not target_module:
            continue
        source_layer = None
        target_layer = None
        if resolver is not None:
            source_layer = getattr(resolver, 'layer_for_module', lambda value: None)(source_module)
            if source_layer is None and file_value is not None:
                source_layer = getattr(resolver, 'layer_for_path', lambda value: None)(file_value)
            target_layer = getattr(resolver, 'layer_for_module', lambda value: None)(target_module)
        graph.add_module(str(source_module), layer=source_layer, path=Path(file_value) if file_value is not None else None)
        graph.add_module(str(target_module), layer=target_layer)
        graph.add_dependency(
            str(source_module),
            str(target_module),
            file=Path(file_value) if file_value is not None else None,
            line=get('line'),
            source_layer=source_layer,
            target_layer=target_layer,
        )
    return graph
