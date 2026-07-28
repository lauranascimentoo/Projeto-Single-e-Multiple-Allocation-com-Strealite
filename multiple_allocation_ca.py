"""Continuum Approximation (CA) utilities for multiple-allocation instances.

This module estimates CA parameters per service region as described by the
user: area, demand, number of clients, density, number of tours, mean route
length, hub-region distance, total distance/time and cost.

The implementation uses a Voronoi-like assignment to hubs: if `hub_indices`
are provided, nodes are assigned to their nearest hub among those seeds. If
`hub_indices` is None and `p` is provided, the function selects the top-p
nodes by outgoing flow as hub seeds.

This file avoids external spatial dependencies by implementing a simple
2D convex hull (Monotone Chain) and polygon area (shoelace) to compute region
areas.
"""

from math import ceil, sqrt
from collections import defaultdict
from typing import Dict, List, Tuple, Any


def _euclidean(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return (dx * dx + dy * dy) ** 0.5


def _convex_hull(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    # Monotone chain convex hull. Returns points of the hull in CCW order.
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def _polygon_area(points: List[Tuple[float, float]]) -> float:
    if not points:
        return 0.0
    area = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _centroid(points: List[Tuple[float, float]]) -> Tuple[float, float]:
    if not points:
        return (0.0, 0.0)
    x = sum(p[0] for p in points) / len(points)
    y = sum(p[1] for p in points) / len(points)
    return (x, y)


def estimate_ca(
    nodes: List[int],
    coords: Dict[int, Tuple[float, float]],
    flow: Dict[Tuple[int, int], float],
    distance: Dict[Tuple[int, int], float],
    hub_indices: List[int] = None,
    p: int = None,
    Q_col: float = 40.0,
    rho_col: float = 1.0,
    beta_col: float = 0.75,
    Q_ent: float = 40.0,
    rho_ent: float = 1.0,
    beta_ent: float = 0.75,
    area_per_node: float = 1.0,
    cost_per_km_col: float = 1.0,
    cost_per_km_ent: float = 1.0,
    c_hub: float = 1.0,
    alpha: float = 0.75,
    v: float = 40.0,
    **kwargs,
) -> Dict[int, Dict[str, Any]]:
    """Estimate CA parameters per hub region using the PDF formulas.

    Returns a dict keyed by hub index with estimated fields:
    - out_volume, in_volume, n_stops_col, n_stops_ent, m_col, m_ent,
      L_col, L_ent, hub_distance_col, hub_distance_ent, D_col, D_ent,
      C_col, C_ent, C_total, C_unit_col, C_unit_ent, avg_interhub_cost.
    """

    if hub_indices is None:
        if p is None:
            raise ValueError("Either hub_indices or p must be provided")
        sent = {node: 0.0 for node in nodes}
        for (o, d), val in flow.items():
            sent[o] = sent.get(o, 0.0) + val
        sorted_nodes = sorted(nodes, key=lambda n: sent.get(n, 0.0), reverse=True)
        hub_indices = sorted_nodes[:p]

    regions = {h: [] for h in hub_indices}
    for node in nodes:
        best = min(hub_indices, key=lambda h: _euclidean(coords[node], coords[h]))
        regions[best].append(node)

    raw_node_out = {node: 0.0 for node in nodes}
    raw_node_in = {node: 0.0 for node in nodes}
    for (o, d), val in flow.items():
        raw_node_out[o] += val
        raw_node_in[d] += val

    results = {}
    for h, members in regions.items():
        pts = [coords[n] for n in members]
        hull = _convex_hull(pts) if pts else []
        area = _polygon_area(hull)
        area = max(area, area_per_node * max(1, len(members)))

        out_volume = sum(raw_node_out.get(n, 0.0) for n in members)
        in_volume = sum(raw_node_in.get(n, 0.0) for n in members)
        n_stops_col = out_volume / rho_col if rho_col > 0 else 0.0
        n_stops_ent = in_volume / rho_ent if rho_ent > 0 else 0.0
        m_col = ceil(out_volume / Q_col) if Q_col > 0 else 0
        m_ent = ceil(in_volume / Q_ent) if Q_ent > 0 else 0

        weighted_col_distance = 0.0
        weighted_ent_distance = 0.0
        for n in members:
            weighted_col_distance += raw_node_out.get(n, 0.0) * distance.get((h, n), _euclidean(coords[h], coords[n]))
            weighted_ent_distance += raw_node_in.get(n, 0.0) * distance.get((h, n), _euclidean(coords[h], coords[n]))

        centroid = _centroid(pts) if pts else coords[h]

        N_col = out_volume / rho_col if rho_col > 0 else 0.0
        N_ent = in_volume / rho_ent if rho_ent > 0 else 0.0
        R_col = ceil(out_volume / Q_col) if Q_col > 0 else 0
        R_ent = ceil(in_volume / Q_ent) if Q_ent > 0 else 0

        L_col = beta_col * rho_col * sqrt(area * N_col) if area > 0 and N_col > 0 else 0.0
        L_ent = beta_ent * rho_ent * sqrt(area * N_ent) if area > 0 and N_ent > 0 else 0.0

        avg_interhub_cost = 0.0
        if len(hub_indices) > 1:
            other_distances = [distance.get((h, other), _euclidean(coords[h], coords[other])) for other in hub_indices if other != h]
            avg_interhub_cost = c_hub * alpha * (sum(other_distances) / len(other_distances)) if other_distances else 0.0

        results[h] = {
            "area": area,
            "out_volume": out_volume,
            "in_volume": in_volume,
            "n_stops_col": n_stops_col,
            "n_stops_ent": n_stops_ent,
            "m_col": m_col,
            "m_ent": m_ent,
            "R_col": R_col,
            "R_ent": R_ent,
            "N_col": N_col,
            "N_ent": N_ent,
            "L_col": L_col,
            "L_ent": L_ent,
            "C_unit_col": out_volume and cost_per_km_col * (L_col / out_volume) or 0.0,
            "C_unit_ent": in_volume and cost_per_km_ent * (L_ent / in_volume) or 0.0,
            "avg_interhub_cost": avg_interhub_cost,
            "centroid": centroid,
            "members": members,
        }

    # Build full cost matrices between regions and hub candidates.
    C_col = {i: {} for i in results}
    C_ent = {m: {} for m in results}
    C_hub = {k: {} for k in hub_indices}

    for i, region in results.items():
        A_i = region["area"]
        D_i = region["out_volume"]
        N_i = region["N_col"]
        R_i = region["R_col"]

        for k in hub_indices:
            d_ik = distance.get((i, k), _euclidean(region["centroid"], coords[k]))
            if D_i > 0:
                C_col[i][k] = cost_per_km_col * (2 * d_ik * R_i + beta_col * sqrt(A_i * N_i)) / D_i
            else:
                C_col[i][k] = 0.0

    for j, region in results.items():
        A_j = region["area"]
        D_j = region["in_volume"]
        N_j = region["N_ent"]
        R_j = region["R_ent"]

        for m in hub_indices:
            d_mj = distance.get((m, j), _euclidean(coords[m], region["centroid"]))
            if D_j > 0:
                C_ent[m][j] = cost_per_km_ent * (2 * d_mj * R_j + beta_ent * sqrt(A_j * N_j)) / D_j
            else:
                C_ent[m][j] = 0.0

    for k in hub_indices:
        for m in hub_indices:
            if k == m:
                C_hub[k][m] = 0.0
            else:
                d_km = distance.get((k, m), _euclidean(coords[k], coords[m]))
                C_hub[k][m] = alpha * c_hub * d_km

    return {
        "regions": results,
        "C_col": C_col,
        "C_ent": C_ent,
        "C_hub": C_hub,
        "hub_indices": hub_indices,
    }


if __name__ == "__main__":
    print("Module multiple_allocation_ca: helper functions for CA estimation.")
