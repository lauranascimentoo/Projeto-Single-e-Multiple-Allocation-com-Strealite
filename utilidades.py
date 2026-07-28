"""Utilidades compartilhadas para instancias AP, logs e visualizacao."""

import math
import os
from datetime import datetime

import matplotlib.pyplot as plt
from matplotlib.cm import ScalarMappable
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.lines import Line2D


def load_ap_instance(file_path, n_limit=None, override_p=None):
    with open(file_path, "r") as file:
        tokens = file.read().split()

    idx = 0
    original_n = int(tokens[idx])
    idx += 1
    original_nodes = list(range(1, original_n + 1))
    original_coords = {}

    for i in original_nodes:
        x_coord = float(tokens[idx])
        y_coord = float(tokens[idx + 1])
        idx += 2
        original_coords[i] = (x_coord, y_coord)

    original_flow_matrix = {}

    for i in original_nodes:
        for j in original_nodes:
            original_flow_matrix[(i, j)] = float(tokens[idx])
            idx += 1

    original_p = int(tokens[idx])
    idx += 1

    params = []
    while idx < len(tokens) and len(params) < 3:
        try:
            params.append(float(tokens[idx]))
        except ValueError:
            break
        idx += 1

    delta = params[0] if len(params) > 0 else 0.75
    alpha = params[1] if len(params) > 1 else delta
    chi = params[2] if len(params) > 2 else delta

    if n_limit is None:
        n = original_n
    else:
        n = min(n_limit, original_n)

    nodes = list(range(1, n + 1))
    coords = {i: original_coords[i] for i in nodes}
    flow = {}

    for i in nodes:
        for j in nodes:
            value = original_flow_matrix[(i, j)]

            if i != j and value > 0:
                flow[(i, j)] = value

    if override_p is not None:
        p = override_p
    else:
        p = min(original_p, n)

    distance = {}

    for i in nodes:
        for j in nodes:
            xi, yi = coords[i]
            xj, yj = coords[j]
            distance[(i, j)] = math.sqrt((xi - xj) ** 2 + (yi - yj) ** 2)

    return nodes, coords, flow, distance, p, alpha, chi, delta


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


def plot_solution(coords, flow, selected_hubs, selected_routes, output_path, title=None):
    """Plota a rede com hubs destacados e largura proporcional ao fluxo agregado."""
    fig, ax = plt.subplots(figsize=(12, 8))
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
        "fluxo_azul",
        ["#d9e3ee", "#93abc1", "#486c8c", "#163a5b"],
    )

    for (a, b), edge_flow in edge_flows.items():
        xa, ya = coords[a]
        xb, yb = coords[b]
        scaled_flow = math.sqrt(edge_flow / max_flow)
        is_hub_link = a in hub_set and b in hub_set

        ax.plot(
            [xa, xb],
            [ya, yb],
            color=flow_cmap(flow_norm(edge_flow)),
            linewidth=0.6 + 5.6 * scaled_flow,
            alpha=0.9 if is_hub_link else 0.72,
            solid_capstyle="round",
            zorder=2 if is_hub_link else 1,
        )

    for node, (x_coord, y_coord) in coords.items():
        if node in hub_set:
            ax.scatter(
                x_coord, y_coord, marker="o", s=250, color="#d62728",
                edgecolors="black", linewidths=1.2, zorder=4,
            )
            ax.annotate(
                f"H{node}", (x_coord, y_coord), xytext=(0, 13),
                textcoords="offset points", ha="center", fontsize=10,
                fontweight="bold", color="#8b0000", zorder=5,
            )
        else:
            ax.scatter(
                x_coord, y_coord, marker="o", s=75, color="#2166f3",
                edgecolors="white", linewidths=0.8, zorder=3,
            )
            ax.annotate(
                str(node), (x_coord, y_coord), xytext=(5, 5),
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
    ax.set_title(title or "Solucao AP - Rede hub-and-spoke", fontsize=14, pad=12)
    ax.set_xlabel("Coordenada X")
    ax.set_ylabel("Coordenada Y")
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
