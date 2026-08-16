"""Interface Streamlit para executar os modelos SP."""
from configs.paths import DATA_DIR, OUTPUTS_DIR, ROOT_DIR
import contextlib
import io
import os
import time
from pathlib import Path

import streamlit as st

from multiple_allocation import solve_multiple_allocation_p_hub
from single_allocation import solve_single_allocation_p_hub
from utils.utilidades import load_sp_instance, plot_solution


SOLVERS = {
    "single": solve_single_allocation_p_hub,
    "multiple": solve_multiple_allocation_p_hub,
}


def read_instance_metadata(path):
    data = load_sp_instance(path, c_hub=1.0, alpha=0.75)
    return {
        "name": path.name,
        "path": path,
        "relative_path": path.relative_to(ROOT_DIR).as_posix(),
        "nodes": data["original_n"],
        "hubs": 5,
        "params": data["params"],
    }


def list_instances():
    instances = []

    for path in DATA_DIR.iterdir():
        if not path.is_file():
            continue

        try:
            instances.append(read_instance_metadata(path))
        except (ValueError, IndexError, UnicodeDecodeError):
            continue

    return sorted(instances, key=lambda item: (item["nodes"], item["name"]))


def format_br(value, decimals=2):
    if value is None:
        return "-"

    formatted = f"{float(value):,.{decimals}f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def format_int_br(value):
    if value is None:
        return "-"

    return f"{int(value):,}".replace(",", ".")


def format_percent_br(value):
    if value is None:
        return "-"

    return format_br(value * 100, 4) + "%"


def format_rows(rows, decimal_columns):
    formatted_rows = []

    for row in rows:
        formatted = dict(row)
        for column in decimal_columns:
            if column in formatted:
                formatted[column] = format_br(formatted[column])
        formatted_rows.append(formatted)

    return formatted_rows


def estimate_size(model_name, nodes):
    flows = nodes * (nodes - 1)

    if model_name == "single":
        return {
            "flows": flows,
            "variables": nodes * nodes + nodes,
            "terms": 2 * nodes * nodes + nodes + 1,
        }

    return {
        "flows": flows,
        "variables": flows * nodes * nodes + nodes,
        "terms": flows * nodes * nodes,
    }


def load_selected_instance(instance, n_limit, override_p, c_hub=1.0, alpha=0.75):
    return load_sp_instance(
        file_path=instance["relative_path"],
        n_limit=n_limit,
        override_p=override_p,
        c_hub=c_hub,
        alpha=alpha,
    )


def instance_insights(instance, n_limit, override_p, c_hub=1.0, alpha=0.75):
    data = load_selected_instance(instance, n_limit, override_p, c_hub, alpha)
    nodes = data["nodes"]
    coords = data["coords"]
    flow = data["flow"]
    distance = data["distance"]
    flow_values = list(flow.values())
    distance_values = [
        distance[(i, j)]
        for i in nodes
        for j in nodes
        if i != j
    ]
    biggest_flow = max(flow.items(), key=lambda item: item[1], default=((None, None), 0))

    sent = {node: 0 for node in nodes}
    received = {node: 0 for node in nodes}
    centrality = {}

    for (origin, destination), value in flow.items():
        sent[origin] += value
        received[destination] += value

    for node in nodes:
        centrality[node] = sum(distance[(node, other)] for other in nodes if other != node) / max(len(nodes) - 1, 1)

    ranking = [
        {
            "no": node,
            "fluxo_enviado": sent[node],
            "fluxo_recebido": received[node],
            "fluxo_total": sent[node] + received[node],
            "distancia_media": centrality[node],
        }
        for node in nodes
    ]

    return {
        "nodes": nodes,
        "coords": coords,
        "flow": flow,
        "distance": distance,
        "p": data["p"],
        "params": data["params"],
        "c_col": data["c_col"],
        "c_ent": data["c_ent"],
        "c_hub": data["c_hub"],
        "c_hub_per_km": data["c_hub_per_km"],
        "alpha": data["alpha"],
        "stats": {
            "nos": len(nodes),
            "fluxos_positivos": len(flow),
            "fluxo_total": sum(flow_values),
            "fluxo_medio": sum(flow_values) / max(len(flow_values), 1),
            "fluxo_maximo": biggest_flow[1],
            "maior_fluxo": f"{biggest_flow[0][0]} -> {biggest_flow[0][1]}",
            "distancia_media": sum(distance_values) / max(len(distance_values), 1),
            "distancia_maxima": max(distance_values, default=0),
        },
        "ranking": ranking,
    }


def routes_table(result, flow):
    return [
        {
            "origem": origin,
            "destino": destination,
            "fluxo": flow.get((origin, destination), 0),
            "hub_origem": route[0],
            "hub_destino": route[1],
        }
        for (origin, destination), route in result.get("selected_routes", {}).items()
    ]


def filter_routes(rows, origins, destinations, hubs):
    filtered = rows

    if origins:
        filtered = [row for row in filtered if row["origem"] in origins]
    if destinations:
        filtered = [row for row in filtered if row["destino"] in destinations]
    if hubs:
        filtered = [
            row for row in filtered
            if row["hub_origem"] in hubs or row["hub_destino"] in hubs
        ]

    return sorted(filtered, key=lambda row: row["fluxo"], reverse=True)


def run_model(model_name, instance, n_limit, override_p, c_hub, alpha, time_limit):
    os.environ["MPLBACKEND"] = "Agg"
    os.environ["SP_SKIP_PLOT_SHOW"] = "1"
    os.makedirs(OUTPUTS_DIR, exist_ok=True)

    previous_cwd = Path.cwd()
    buffer = io.StringIO()
    started = time.perf_counter()

    try:
        os.chdir(ROOT_DIR)
        data = load_sp_instance(
            file_path=instance["relative_path"],
            n_limit=n_limit,
            override_p=override_p,
            c_hub=c_hub,
            alpha=alpha,
        )
        nodes, coords, flow, distance, p = (
            data["nodes"], data["coords"], data["flow"], data["distance"], data["p"]
        )

        solver = SOLVERS["multiple"]

        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            model, selected_hubs, selected_routes = solver(
                type=model_name,
                nodes=nodes,
                flow=flow,
                distance=distance,
                c_col=data["c_col"],
                c_ent=data["c_ent"],
                c_hub=data["c_hub"],
                p=p,
                instance_path=instance["relative_path"],
                time_limit=time_limit,
            )

            image_path = None
            if selected_hubs:
                image_path = OUTPUTS_DIR / f"sp_solution_{model_name}.png"
                plot_solution(
                    coords=coords,
                    flow=flow,
                    selected_hubs=selected_hubs,
                    selected_routes=selected_routes,
                    output_path=str(image_path),
                    title="Solução SP - 11 regiões",
                )

        objective = None
        status = None
        runtime = None

        if model is not None:
            status = getattr(model, "Status", None)
            runtime = getattr(model, "Runtime", None)
            if getattr(model, "SolCount", 0) > 0:
                objective = getattr(model, "ObjVal", None)

        return {
            "ok": bool(selected_hubs),
            "log": buffer.getvalue(),
            "model_status": status,
            "runtime": runtime,
            "objective": objective,
            "gap": getattr(model, "MIPGap", None) if model is not None else None,
            "num_vars": getattr(model, "NumVars", None) if model is not None else None,
            "num_constraints": getattr(model, "NumConstrs", None) if model is not None else None,
            "selected_hubs": selected_hubs,
            "selected_routes": selected_routes,
            "image_path": image_path,
            "elapsed": time.perf_counter() - started,
        }
    except Exception as error:
        return {
            "ok": False,
            "log": buffer.getvalue(),
            "error": str(error),
            "elapsed": time.perf_counter() - started,
        }
    finally:
        os.chdir(previous_cwd)


def configure_page():
    st.set_page_config(
        page_title="SP Hub Location",
        page_icon=":material/hub:",
        layout="wide",
    )
    st.markdown(
        """
        <style>
        h1 { font-size: clamp(1.9rem, 4vw, 2.6rem) !important; }
        h2, h3 { line-height: 1.2 !important; }
        [data-testid="stMetricLabel"] p {
            font-size: clamp(0.72rem, 1.3vw, 0.88rem) !important;
        }
        [data-testid="stMetricValue"] {
            font-size: clamp(1.45rem, 3vw, 2rem) !important;
            line-height: 1.15 !important;
        }
        [data-testid="stMetric"] {
            min-width: 0;
        }
        [data-testid="stMetricValue"] > div {
            overflow: visible !important;
            text-overflow: clip !important;
        }
        @media (max-width: 900px) {
            .block-container {
                padding-left: 1.25rem !important;
                padding-right: 1.25rem !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

