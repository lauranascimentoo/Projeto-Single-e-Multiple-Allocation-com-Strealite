"""Utilidades compartilhadas para instancias AP, logs e visualizacao."""

import json
import math
import os
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.cm import ScalarMappable
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.lines import Line2D


def _haversine_km(first, second):
    """Distancia geodesica em km entre coordenadas (latitude, longitude)."""
    lat1, lon1 = map(math.radians, first)
    lat2, lon2 = map(math.radians, second)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def load_sp_instance(file_path, n_limit=None, override_p=None, c_hub=1.0, alpha=0.75):
    """Le a instancia SP: coordenadas, demanda, custos CA e parametros nomeados."""
    with open(file_path, "r", encoding="utf-8") as file:
        lines = [line.strip() for line in file if line.strip()]

    original_n = int(lines[0])
    cursor = 1
    original_nodes = list(range(1, original_n + 1))
    original_coords = {}

    for node in original_nodes:
        lat, lon = map(float, lines[cursor].split())
        original_coords[node] = (lat, lon)
        cursor += 1

    def read_matrix():
        nonlocal cursor
        matrix = {}
        for i in original_nodes:
            values = [float(value) for value in lines[cursor].split()]
            if len(values) != original_n:
                raise ValueError(f"Matriz invalida na linha {cursor + 1}: esperados {original_n} valores.")
            cursor += 1
            for j, value in zip(original_nodes, values):
                matrix[(i, j)] = value
        return matrix

    original_flow_matrix = read_matrix()
    original_c_col = read_matrix()
    original_c_ent = read_matrix()

    params = {}
    for line in lines[cursor:]:
        parts = line.split()
        if len(parts) != 2:
            raise ValueError(f"Parametro invalido: {line}")
        params[parts[0]] = float(parts[1])

    required = {
        "gamma", "T", "rho_col", "Q_col", "beta_col", "c_col",
        "rho_ent", "Q_ent", "beta_ent", "c_ent",
    }
    missing = sorted(required - params.keys())
    if missing:
        raise ValueError("Parametros ausentes na instancia: " + ", ".join(missing))

    n = original_n if n_limit is None else min(int(n_limit), original_n)
    nodes = list(range(1, n + 1))
    coords = {i: original_coords[i] for i in nodes}
    flow = {
        (i, j): original_flow_matrix[(i, j)]
        for i in nodes for j in nodes
        if i != j and original_flow_matrix[(i, j)] > 0
    }
    c_col_matrix = {(i, k): original_c_col[(i, k)] for i in nodes for k in nodes}
    c_ent_matrix = {(k, j): original_c_ent[(k, j)] for k in nodes for j in nodes}
    distance = {(i, j): _haversine_km(coords[i], coords[j]) for i in nodes for j in nodes}
    c_hub_matrix = {
        (k, m): (0.0 if k == m else float(alpha) * float(c_hub) * distance[(k, m)])
        for k in nodes for m in nodes
    }

    p = min(int(override_p) if override_p is not None else 5, n)
    return {
        "nodes": nodes,
        "coords": coords,
        "flow": flow,
        "distance": distance,
        "p": p,
        "c_col": c_col_matrix,
        "c_ent": c_ent_matrix,
        "c_hub": c_hub_matrix,
        "params": params,
        "c_hub_per_km": float(c_hub),
        "alpha": float(alpha),
        "original_n": original_n,
    }


def write_execution_log(log_path, instance_path, nodes, flow, p, event, elapsed=None, detail=None):
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)

    fields = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        f"evento={event}",
        f"instancia={instance_path}",
        f"nos={len(nodes)}",
        f"hubs={p}",
        f"fluxos={len(flow)}",
    ]

    if elapsed is not None:
        fields.append(f"tempo_total_s={elapsed:.3f}")

    if detail is not None:
        fields.append(detail)

    with open(log_path, "a", encoding="utf-8") as log_file:
        log_file.write(" | ".join(fields) + "\n")


class ExecutionTimeLimitReached(Exception):
    pass


def _plot_geojson_background(ax, geojson_path, facecolor="#eef3e8", edgecolor="#66745f"):
    """Desenha poligonos GeoJSON usando longitude no eixo X e latitude no Y."""
    if not geojson_path.exists():
        return False

    with open(geojson_path, "r", encoding="utf-8") as geojson_file:
        features = json.load(geojson_file).get("features", [])

    plotted = False
    for feature in features:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates", [])
        geometry_type = geometry.get("type")
        polygons = coordinates if geometry_type == "MultiPolygon" else [coordinates]

        for polygon in polygons:
            if not polygon:
                continue
            exterior = polygon[0]
            longitudes = [point[0] for point in exterior]
            latitudes = [point[1] for point in exterior]
            ax.fill(
                longitudes,
                latitudes,
                facecolor=facecolor,
                edgecolor=edgecolor,
                linewidth=1.2,
                alpha=0.95,
                zorder=0,
            )
            plotted = True

    return plotted


def _plot_intermediate_regions(ax, regions_dir):
    """Desenha e identifica as 11 Regioes Geograficas Intermediarias de SP."""
    region_names = {
        3501: "São Paulo",
        3502: "Sorocaba",
        3503: "Bauru",
        3504: "Marília",
        3505: "Presidente\nPrudente",
        3506: "Araçatuba",
        3507: "São José do\nRio Preto",
        3508: "Ribeirão Preto",
        3509: "Araraquara",
        3510: "Campinas",
        3511: "São José dos\nCampos",
    }
    colors = [
        "#b8dcc2", "#e7a6ea", "#e6a0a5", "#f4b5d5", "#91b9e6", "#c9e99d",
        "#d8d88d", "#89d4d1", "#8ed9be", "#efbd87", "#aaa6df",
    ]
    plotted = False

    for position, (region_code, region_name) in enumerate(region_names.items()):
        region_path = regions_dir / f"{region_code}.geojson"
        if not region_path.exists():
            continue

        with open(region_path, "r", encoding="utf-8") as region_file:
            features = json.load(region_file).get("features", [])

        points = []
        for feature in features:
            geometry = feature.get("geometry") or {}
            coordinates = geometry.get("coordinates", [])
            polygons = coordinates if geometry.get("type") == "MultiPolygon" else [coordinates]
            for polygon in polygons:
                if not polygon:
                    continue
                exterior = polygon[0]
                points.extend(exterior)
                ax.fill(
                    [point[0] for point in exterior],
                    [point[1] for point in exterior],
                    facecolor=colors[position],
                    edgecolor="#626b62",
                    linewidth=1.0,
                    alpha=0.62,
                    zorder=0,
                )
                plotted = True

        if points:
            min_lon = min(point[0] for point in points)
            max_lon = max(point[0] for point in points)
            min_lat = min(point[1] for point in points)
            max_lat = max(point[1] for point in points)
            ax.text(
                (min_lon + max_lon) / 2,
                (min_lat + max_lat) / 2,
                region_name,
                ha="center",
                va="center",
                fontsize=7,
                color="#3f493f",
                alpha=0.88,
                zorder=0.5,
            )

    return plotted


def plot_solution(coords, flow, selected_hubs, selected_routes, output_path, title=None):
    """Plota a rede com hubs destacados e largura proporcional ao fluxo agregado."""
    fig, ax = plt.subplots(figsize=(13, 8))
    map_dir = Path(__file__).resolve().parent / "data" / "SPdata"
    has_map = _plot_intermediate_regions(ax, map_dir / "regioes_intermediarias")
    if not has_map:
        has_map = _plot_geojson_background(ax, map_dir / "estado_sp.geojson")
    hub_set = set(selected_hubs)
    edge_flows = {}

    for (i, j), (k, m) in selected_routes.items():
        for a, b in [(i, k), (k, m), (m, j)]:
            if a == b:
                continue

            edge = tuple(sorted((a, b)))
            edge_flows[edge] = edge_flows.get(edge, 0) + flow[(i, j)]

    min_flow = min(edge_flows.values(), default=0)
    max_flow = max(edge_flows.values(), default=1)
    flow_norm = Normalize(vmin=min_flow, vmax=max_flow)
    flow_cmap = LinearSegmentedColormap.from_list(
        "fluxo_contraste",
        ["#64748b", "#475569", "#27364a", "#0f172a"],
    )

    for (a, b), edge_flow in edge_flows.items():
        lat_a, lon_a = coords[a]
        lat_b, lon_b = coords[b]
        scaled_flow = math.sqrt(edge_flow / max_flow)
        is_hub_link = a in hub_set and b in hub_set

        ax.plot(
            [lon_a, lon_b],
            [lat_a, lat_b],
            color=flow_cmap(flow_norm(edge_flow)),
            linewidth=1.0 + 5.6 * scaled_flow,
            alpha=0.95 if is_hub_link else 0.84,
            solid_capstyle="round",
            zorder=2 if is_hub_link else 1,
        )

    for node, (latitude, longitude) in coords.items():
        if node in hub_set:
            ax.scatter(
                longitude, latitude, marker="o", s=250, color="#d62728",
                edgecolors="black", linewidths=1.2, zorder=4,
            )
            ax.annotate(
                f"H{node}", (longitude, latitude), xytext=(0, 13),
                textcoords="offset points", ha="center", fontsize=10,
                fontweight="bold", color="#8b0000", zorder=5,
            )
        else:
            ax.scatter(
                longitude, latitude, marker="o", s=75, color="#2166f3",
                edgecolors="white", linewidths=0.8, zorder=3,
            )
            ax.annotate(
                str(node), (longitude, latitude), xytext=(5, 5),
                textcoords="offset points", fontsize=8, color="#222222",
                zorder=5,
            )

    legend_elements = [
        Line2D(
            [0], [0], marker="o", color="none", markerfacecolor="#d62728",
            markeredgecolor="black", markersize=9, label="Hub",
        ),
        Line2D(
            [0], [0], marker="o", color="none", markerfacecolor="#2166f3",
            markeredgecolor="white", markersize=7, label="Spoke",
        ),
    ]

    ax.legend(handles=legend_elements, loc="upper right", framealpha=0.96)
    scalar_mappable = ScalarMappable(norm=flow_norm, cmap=flow_cmap)
    scalar_mappable.set_array([])
    colorbar = fig.colorbar(scalar_mappable, ax=ax, pad=0.02, fraction=0.045)
    colorbar.set_label("Fluxo agregado na conexao")
    ax.set_title(title or "Solucao SP - Rede hub-and-spoke", fontsize=14, pad=12)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    if has_map:
        ax.margins(x=0.02, y=0.03)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, color="#e6e6e6", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()

    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"\nFigura salva em: {output_path}")

    if os.environ.get("SP_SKIP_PLOT_SHOW") != "1":
        plt.show()

    plt.close(fig)
