"""graph_health.py — FASE-3a baseline topologico (plan ratificado S5).

Snapshot determinista de la forma del grafo vivo — el mapa antes del motor
de descubrimiento (3b). Metricas POR CAPA (la densidad global mezcla tipos
incompatibles); capas ratificadas en graph_phase3_plan.vsm:

  estructura    : child_of, extracted_from, derived_from (DAG por diseno)
  consenso      : supersedes (dirigida, aciclica), contradicts (simetrica)
  certificacion : certified_by, answers
  correlacion   : correlates_with (no dirigida)

Metricas por capa:
  nodes, edges        — denominadores explicitos (toda capa reporta los suyos)
  density             — dirigida |E|/(|V|(|V|-1)); no dirigida |E|/(|V|(|V|-1)/2)
  degree_p_k          — distribucion P(k) como pares [k, count] ordenados
  clustering_avg      — transitividad local (para capas dirigidas: sobre la
                        proyeccion no dirigida; para no-dirigidas: directa)
  fiedler             — conectividad algebraica (2do autovalor del Laplaciano
                        no dirigido); null si <2 nodos — honest denominator
  is_dag / cyclic_sccs— solo capas dirigidas: informativo por capa (la capa
                        consenso NO es DAG por diseno — contradict es simetrico)
  acyclic_check        — seccion aparte: child_of/derived_from/supersedes
                         DEBEN ser aciclicos; un ciclo = inconsistencia del KB
                         (gate candidato en 3c); cyclic_sccs = # SCCs size>1
  betweenness_top      — top-N (N=10) por (-centrality, id) — orden estable

Rules:
  NO-NEW-TRUTH — el health es vista derivada del grafo; doble proyeccion,
                 cero verdad nueva; rebuildable from scratch.
  R10          — mismo grafo -> mismo health byte-identico. Orden fijo de
                 capas/kinds, nodos y aristas ordenados en la construccion,
                 eigsh con v0 fijo (sin semilla aleatoria), sin wall-clock
                 en el cuerpo del snapshot (el stamp va en meta aparte).

Usage:
    from epistemic_graph.graph_health import health, write_snapshot
    h = health(build(use_cache=False))
    write_snapshot(h)  # -> state/epistemic/graph_health.json
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import networkx as nx
import numpy as np

# Capas en orden fijo (R10) — ratified graph_phase3_plan.vsm @phases 3a
# (name, edge_kinds, directed)
LAYERS: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    ("estructura", ("child_of", "extracted_from", "derived_from"), True),
    ("consenso", ("supersedes", "contradicts"), True),
    ("certificacion", ("certified_by", "answers"), True),
    ("correlacion", ("correlates_with",), False),
)
BETWEENNESS_TOP_N = 10
SCHEMA = "graph_health-v1"
_FIEDLER_ZERO_TOL = 1e-9


def _layer_graph(graph: dict, kinds: tuple[str, ...],
                 directed: bool) -> nx.Graph:
    """Induced subgraph over edges of `kinds` (endpoints of any node kind).

    Nodos insertados en orden sorted; aristas ordenadas por
    (source, target, kind) — R10: misma construccion siempre.
    """
    edges = [e for e in graph["edges"] if e["kind"] in kinds]
    ids = {e["source"] for e in edges} | {e["target"] for e in edges}
    g: nx.Graph = nx.DiGraph() if directed else nx.Graph()
    for nid in sorted(ids):
        g.add_node(nid)
    for e in sorted(edges, key=lambda e: (e["source"], e["target"], e["kind"])):
        g.add_edge(e["source"], e["target"])
    return g


def _density(g: nx.Graph, directed: bool) -> float:
    n = g.number_of_nodes()
    m = g.number_of_edges()
    if n < 2:
        return 0.0
    if directed:
        return m / (n * (n - 1))
    return m / (n * (n - 1) / 2)


def _degree_p_k(g: nx.Graph) -> list[list[int]]:
    """P(k) como pares [k, count] ordenados por k (JSON-safe, R10)."""
    degs = [d for _, d in g.degree()]
    c = Counter(degs)
    return [[k, c[k]] for k in sorted(c)]


def _clustering_avg(g: nx.Graph, directed: bool) -> float:
    """Transitividad local. Dirigidas: sobre proyeccion no dirigida."""
    target = g.to_undirected() if directed else g
    if target.number_of_nodes() == 0:
        return 0.0
    return nx.average_clustering(target)


def _fiedler(g: nx.Graph) -> float | None:
    """λ₂ del Laplaciano no dirigido (conectividad algebraica / Fiedler).

    El Fiedler es el SEGUNDO autovalor mas chico (λ₂), no el primero no-cero:
    grafo desconectado con c componentes tiene λ₁..λ_c ≈ 0 → λ₂ ≈ 0.
    Denso numpy.linalg.eigvalsh (LAPACK syevd — determinista, sin semilla;
    eigsh iterativo es fragil con which="SM" en Laplacianos). Nodos sorted.
    Escalas ~2k nodos: O(n^3) aceptable para baseline snapshot.
    null si <2 nodos (honest denominator — sin autovalor que reportar).
    """
    und = g.to_undirected() if g.is_directed() else g
    n = und.number_of_nodes()
    if n < 2:
        return None
    nodes = sorted(und.nodes())
    L = nx.laplacian_matrix(und, nodelist=nodes).toarray().astype(float)
    vals = np.linalg.eigvalsh(L)  # ascending, real symmetric
    # λ₂ = vals[1]; desconectado -> ~0. Normalizar -0.0 a 0.0 (JSON limpio).
    f = round(float(vals[1]), 12)
    return 0.0 if f == 0.0 else f


def _cyclic_sccs(g: nx.DiGraph) -> int:
    """# componentes fuertemente conexas con size>1 (ciclos presentes)."""
    return sum(1 for scc in nx.strongly_connected_components(g)
               if len(scc) > 1)


# Kinds que DEBEN ser aciclicos (graph_phase3_plan.vsm: supersedes/
# derived_from/child_of — un ciclo aqui = inconsistencia del KB, gate 3c).
# contradict es simetrico por diseno (2-ciclos esperados) — NO entra aqui.
ACYCLIC_KINDS: tuple[str, ...] = ("child_of", "derived_from", "supersedes")


def _acyclic_check(graph: dict) -> dict:
    """Ciclos por kind dirigido que debe ser aciclico — gate candidato 3c."""
    out: dict[str, dict] = {}
    for kind in ACYCLIC_KINDS:
        g = _layer_graph(graph, (kind,), directed=True)
        n, m = g.number_of_nodes(), g.number_of_edges()
        out[kind] = {
            "nodes": n,
            "edges": m,
            "is_dag": nx.is_directed_acyclic_graph(g),
            "cyclic_sccs": _cyclic_sccs(g),
        }
    return out


def _betweenness_top(g: nx.Graph) -> list[list]:
    """Top-N betweenness, orden estable por (-centrality, id) — R10."""
    if g.number_of_nodes() == 0 or g.number_of_edges() == 0:
        return []
    bc = nx.betweenness_centrality(g, normalized=True)
    ranked = sorted(bc.items(), key=lambda kv: (-kv[1], kv[0]))
    return [[nid, round(val, 12)] for nid, val in ranked[:BETWEENNESS_TOP_N]
            if val > 0]


def health(graph: dict) -> dict:
    """Topological baseline snapshot — determinista (R10), solo lectura."""
    layers: dict[str, dict] = {}
    for name, kinds, directed in LAYERS:
        g = _layer_graph(graph, kinds, directed)
        n, m = g.number_of_nodes(), g.number_of_edges()
        entry: dict = {
            "edge_kinds": list(kinds),
            "nodes": n,
            "edges": m,
            "density": round(_density(g, directed), 12),
            "degree_p_k": _degree_p_k(g),
            "clustering_avg": round(_clustering_avg(g, directed), 12),
            "fiedler": _fiedler(g),
            "betweenness_top": _betweenness_top(g),
        }
        if directed:
            entry["is_dag"] = nx.is_directed_acyclic_graph(g)
            entry["cyclic_sccs"] = _cyclic_sccs(g)
        layers[name] = entry

    meta = graph.get("meta", {})
    return {
        "schema": SCHEMA,
        "fingerprint": meta.get("fingerprint"),
        "nodes_total": meta.get("nodes_total"),
        "edges_total": meta.get("edges_total"),
        "edges_by_kind": meta.get("edges_by_kind", {}),
        "layers": layers,
        "acyclic_check": _acyclic_check(graph),
    }


def default_snapshot_path() -> Path:
    import os
    root = Path(os.environ.get(
        "VOSLAB_PATH",
        Path(__file__).resolve().parents[3]))
    return root / "state" / "epistemic" / "graph_health.json"


def write_snapshot(h: dict, path: Path | None = None) -> Path:
    """Escribe el snapshot (JSON indentado, sort_keys — byte-estable)."""
    out = path or default_snapshot_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(h, indent=2, sort_keys=True,
                              ensure_ascii=False) + "\n",
                   encoding="utf-8")
    return out
