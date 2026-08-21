"""Interface Streamlit para executar os modelos SP."""

import contextlib
import io
import os
import time
from pathlib import Path

import streamlit as st


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data" / "SPdata"
OUTPUTS_DIR = ROOT_DIR / "outputs"

from multiple_allocation import solve_multiple_allocation_p_hub
from multiple_allocation_normal import (
    C_COL as NORMAL_C_COL,
    C_ENT as NORMAL_C_ENT,
    C_HUB as NORMAL_C_HUB,
    solve_multiple_allocation_normal,
)
from single_allocation import solve_single_allocation_p_hub
from utilidades import load_sp_instance, plot_solution

C_HUB = 0.0001878125  # R$/pacote/km

SOLVERS = {
    "single": solve_single_allocation_p_hub,
    "multiple_ca": solve_multiple_allocation_p_hub,
    "multiple_normal": solve_multiple_allocation_normal,
}


def read_instance_metadata(path):
    data = load_sp_instance(path, c_hub=C_HUB, alpha=0.75)
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


def load_selected_instance(instance, n_limit, override_p, c_hub=C_HUB, alpha=0.75):
    return load_sp_instance(
        file_path=instance["relative_path"],
        n_limit=n_limit,
        override_p=override_p,
        c_hub=c_hub,
        alpha=alpha,
    )


def instance_insights(instance, n_limit, override_p, c_hub=C_HUB, alpha=0.75):
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


def flow_arc_analysis(result, flow):
    """Agrega os fluxos OD nos arcos usados e os separa por tipo de trecho."""
    arc_flows = {}

    for (origin, destination), (first_hub, second_hub) in result.get("selected_routes", {}).items():
        flow_value = flow.get((origin, destination), 0)
        segments = [
            ("Coleta: spoke → hub", origin, first_hub),
            ("Inter-hub: hub → hub", first_hub, second_hub),
            ("Entrega: hub → spoke", second_hub, destination),
        ]
        for segment_type, start, end in segments:
            if start == end:
                continue
            key = (segment_type, start, end)
            arc_flows[key] = arc_flows.get(key, 0) + flow_value

    rows = [
        {"tipo": segment_type, "origem_arco": start, "destino_arco": end, "fluxo": value}
        for (segment_type, start, end), value in arc_flows.items()
    ]
    rows.sort(key=lambda row: row["fluxo"], reverse=True)

    summary = {}
    for row in rows:
        values = summary.setdefault(row["tipo"], {"fluxo_total": 0, "numero_arcos": 0, "maior_fluxo_arco": 0})
        values["fluxo_total"] += row["fluxo"]
        values["numero_arcos"] += 1
        values["maior_fluxo_arco"] = max(values["maior_fluxo_arco"], row["fluxo"])

    summary_rows = [
        {
            "tipo": segment_type,
            **values,
            "fluxo_medio_arco": values["fluxo_total"] / values["numero_arcos"],
        }
        for segment_type, values in summary.items()
    ]
    return rows, sorted(summary_rows, key=lambda row: row["fluxo_total"], reverse=True)


def route_hub_usage_analysis(result, flow):
    """Conta rotas e fluxos que usam um hub ou dois hubs distintos."""
    groups = {
        "Um hub": {"rotas": 0, "fluxo": 0},
        "Dois hubs": {"rotas": 0, "fluxo": 0},
    }
    routes = result.get("selected_routes", {})
    total_routes = len(routes)
    total_flow = sum(flow.get(pair, 0) for pair in routes)

    for pair, (first_hub, second_hub) in routes.items():
        group = "Um hub" if first_hub == second_hub else "Dois hubs"
        groups[group]["rotas"] += 1
        groups[group]["fluxo"] += flow.get(pair, 0)

    return [
        {
            "uso de hubs": group,
            "quantidade de rotas": values["rotas"],
            "percentual de rotas": values["rotas"] / total_routes if total_routes else 0,
            "fluxo": values["fluxo"],
            "percentual do fluxo": values["fluxo"] / total_flow if total_flow else 0,
        }
        for group, values in groups.items()
    ]


def route_hub_cost_analysis(result):
    """Resume o custo das rotas conforme usem um ou dois hubs distintos."""
    groups = {
        "Um hub": {"rotas": 0, "fluxo": 0, "custo total": 0},
        "Dois hubs": {"rotas": 0, "fluxo": 0, "custo total": 0},
    }
    for row in result.get("route_costs", []):
        group = row["uso de hubs"]
        groups[group]["rotas"] += 1
        groups[group]["fluxo"] += row["fluxo"]
        groups[group]["custo total"] += row["custo total"]

    overall_cost = sum(values["custo total"] for values in groups.values())
    return [
        {
            "uso de hubs": group,
            **values,
            "custo médio por rota": values["custo total"] / values["rotas"] if values["rotas"] else 0,
            "custo por pacote": values["custo total"] / values["fluxo"] if values["fluxo"] else 0,
            "percentual do custo": values["custo total"] / overall_cost if overall_cost else 0,
        }
        for group, values in groups.items()
    ]


def financial_segment_analysis(result):
    """Resume os custos de coleta, inter-hub e entrega de uma solução."""
    route_costs = result.get("route_costs", [])
    total_flow = sum(row["fluxo"] for row in route_costs)
    components = [
        ("Coleta", "custo coleta", "pacotes coleta"),
        ("Inter-hub", "custo inter-hub", "pacotes inter-hub"),
        ("Entrega", "custo entrega", "pacotes entrega"),
    ]
    component_values = {
        label: sum(row[field] for row in route_costs)
        for label, field, _ in components
    }
    component_packages = {
        label: sum(row.get(package_field, 0) for row in route_costs)
        for label, _, package_field in components
    }
    total_cost = sum(component_values.values())
    rows = [
        {
            "etapa": label,
            "número de pacotes": component_packages[label],
            "custo total": value,
            "percentual do custo": value / total_cost if total_cost else 0,
            "custo por pacote": value / component_packages[label] if component_packages[label] else 0,
        }
        for label, value in component_values.items()
    ]
    return rows, total_cost, total_flow


def run_model(
    model_name,
    instance,
    n_limit,
    override_p,
    c_hub,
    ca_alpha,
    normal_alpha,
    time_limit,
):
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
            alpha=ca_alpha,
        )
        nodes, coords, flow, distance, p = (
            data["nodes"], data["coords"], data["flow"], data["distance"], data["p"]
        )

        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            common_args = {
                "nodes": nodes,
                "flow": flow,
                "distance": distance,
                "p": p,
                "instance_path": instance["relative_path"],
                "time_limit": time_limit,
            }
            if model_name == "multiple_ca":
                route_c_col, route_c_ent, route_c_hub = data["c_col"], data["c_ent"], data["c_hub"]
                model, selected_hubs, selected_routes = SOLVERS[model_name](
                    **common_args,
                    c_col=data["c_col"],
                    c_ent=data["c_ent"],
                    c_hub=data["c_hub"],
                )
            else:
                route_c_col = {(i, k): NORMAL_C_COL * distance[(i, k)] for i in nodes for k in nodes}
                route_c_hub = {
                    (k, m): NORMAL_C_HUB * normal_alpha * distance[(k, m)]
                    for k in nodes for m in nodes
                }
                route_c_ent = {(m, j): NORMAL_C_ENT * distance[(m, j)] for m in nodes for j in nodes}
                model, selected_hubs, selected_routes = SOLVERS[model_name](
                    **common_args,
                    alpha=normal_alpha,
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

        route_costs = []
        for (origin, destination), (first_hub, second_hub) in selected_routes.items():
            flow_value = flow[(origin, destination)]
            collection_cost = flow_value * route_c_col[(origin, first_hub)]
            inter_hub_cost = flow_value * route_c_hub[(first_hub, second_hub)]
            delivery_cost = flow_value * route_c_ent[(second_hub, destination)]
            route_costs.append({
                "origem": origin,
                "destino": destination,
                "uso de hubs": "Um hub" if first_hub == second_hub else "Dois hubs",
                "fluxo": flow_value,
                "pacotes coleta": flow_value if origin != first_hub else 0,
                "pacotes inter-hub": flow_value if first_hub != second_hub else 0,
                "pacotes entrega": flow_value if second_hub != destination else 0,
                "custo coleta": collection_cost,
                "custo inter-hub": inter_hub_cost,
                "custo entrega": delivery_cost,
                "custo total": collection_cost + inter_hub_cost + delivery_cost,
            })

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
            "route_costs": route_costs,
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


def main():
    configure_page()

    st.title("SP Hub Location")
    st.caption("Execute o modelo Multiple Allocation com os custos pré-calculados da instância SP.")

    instances = list_instances()

    if not instances:
        st.error("Nenhuma instância válida foi encontrada em data/SPdata.")
        return

    default_index = next(
        (index for index, instance in enumerate(instances) if instance["name"] == "50.3"),
        0,
    )

    with st.sidebar:
        st.header("Configuração")

        model_name = st.segmented_control(
            "Modelo",
            options=["multiple_ca", "multiple_normal"],
            default="multiple_ca",
            format_func=lambda value: {
                "multiple_ca": "Multiple com CA",
                "multiple_normal": "Multiple normal",
            }[value],
        )
        if model_name == "multiple_ca":
            st.caption("Custos de coleta e entrega pré-calculados pela aproximação contínua.")
        else:
            st.caption("Formulação tradicional baseada em distância, com Chi = Delta = 1 e Alpha ajustável.")

        selected_name = st.selectbox(
            "Instância",
            options=[instance["name"] for instance in instances],
            index=default_index,
            format_func=lambda name: next(
                f"{item['name']} ({item['nodes']} nós, p={item['hubs']})"
                for item in instances
                if item["name"] == name
            ),
        )
        selected_instance = next(item for item in instances if item["name"] == selected_name)

        n_limit = st.number_input(
            "Número de nós",
            min_value=2,
            max_value=selected_instance["nodes"],
            value=selected_instance["nodes"],
            step=1,
        )

        override_p = st.number_input(
            "Número de hubs",
            min_value=1,
            max_value=int(n_limit),
            value=min(selected_instance["hubs"], int(n_limit)),
            step=1,
        )

        if model_name == "multiple_ca":
            st.markdown("### Custo inter-hub — CA")
            hub_cost_col, alpha_col = st.columns(2)
            with hub_cost_col:
                ca_c_hub = st.number_input(
                    "c_hub (R$/pacote/km)",
                    min_value=0.0,
                    value=C_HUB,
                    step=0.001,
                    format="%.9f",
                )
            with alpha_col:
                ca_alpha = st.number_input(
                    "Alpha CA", min_value=0.0, max_value=1.0, value=0.75,
                    step=0.01, format="%.2f",
                )
            st.caption("Usa C_col e C_ent da instância e calcula C_hub = alpha × c_hub × distância.")
            normal_alpha = 0.75
        else:
            st.markdown("### Coeficientes do modelo normal")
            normal_alpha = st.number_input(
                "Alpha — inter-hub", min_value=0.0, value=0.75, step=0.01, format="%.2f"
            )
            st.caption(
                "Chi = 1 e Delta = 1 (fixos). Usa fluxo × "
                "(d_ik + alpha·d_km + d_mj) / 1000."
            )
            ca_c_hub, ca_alpha = C_HUB, 0.75

        time_limit = st.number_input(
            "Tempo limite (segundos)",
            min_value=1,
            max_value=86400,
            value=300,
            step=30,
        )

        run_clicked = st.button("Calcular", type="primary", use_container_width=True)

    estimates = estimate_size(model_name, int(n_limit))
    insights = instance_insights(
        selected_instance, int(n_limit), int(override_p), float(ca_c_hub), float(ca_alpha)
    )

    metric_columns = st.columns(3)
    metric_columns[0].metric("Fluxos", format_int_br(estimates["flows"]))
    metric_columns[1].metric("Variáveis estimadas", format_int_br(estimates["variables"]))
    metric_columns[2].metric("Restrições/termos estimados", format_int_br(estimates["terms"]))
    with st.expander("Como estes valores estimados são calculados"):
        st.markdown(
            """
            - **Fluxos**: quantidade máxima de pares origem-destino considerados, calculada por `n * (n - 1)`.
            - **Variáveis estimadas**:
              - no modelo **single**, `n² + n`, sendo `n²` variáveis binárias de alocação e `n` variáveis contínuas da formulação EMMRr.
              - no modelo **multiple**, `fluxos * n² + n`, sendo uma variável de rota para cada fluxo e par de hubs, mais `n` variáveis de hub.
            - **Restrições/termos estimados**:
              - no **single**, estimativa de restrições da formulação linear EMMRr: `2n² + n + 1`.
              - no **multiple**, estimativa dos termos/rotas possíveis: `fluxos * n²`.
            """
        )

    result_placeholder = st.container()

    if run_clicked:
        with st.spinner("Executando o modelo..."):
            result = run_model(
                model_name=model_name,
                instance=selected_instance,
                n_limit=int(n_limit),
                override_p=int(override_p),
                c_hub=float(ca_c_hub),
                ca_alpha=float(ca_alpha),
                normal_alpha=float(normal_alpha),
                time_limit=int(time_limit),
            )
        st.session_state["last_result"] = result
        st.session_state["last_config"] = {
            "model_name": model_name,
            "instance": selected_instance["name"],
            "n_limit": int(n_limit),
            "override_p": int(override_p),
            "c_hub": float(ca_c_hub),
            "alpha": float(ca_alpha),
            "time_limit": int(time_limit),
        }
        comparison_key = (
            selected_instance["name"], int(n_limit), int(override_p),
        )
        st.session_state.setdefault("model_results", {})[model_name] = {
            "result": result,
            "comparison_key": comparison_key,
        }

    result = st.session_state.get("last_result")
    last_config = st.session_state.get("last_config")

    with result_placeholder:
        if not result:
            st.info("Escolha os parâmetros na barra lateral e clique em Calcular.")
            return

        status_label = "Concluído" if result.get("ok") else "Sem solução"
        if result.get("error"):
            status_label = "Erro"

        st.subheader("Resultado")
        summary_columns = st.columns(3)
        summary_columns[0].metric("Status", status_label)
        summary_columns[1].metric("Tempo total", f"{format_br(result['elapsed'])} s")
        summary_columns[2].metric(
            "Função objetivo",
            format_br(result.get("objective")),
        )

        network_columns = st.columns(3)
        network_columns[0].metric("Hubs", ", ".join(map(str, result.get("selected_hubs", []))) or "-")
        network_columns[1].metric("Gap", format_percent_br(result.get("gap")))
        network_columns[2].metric("Status do solver", "-" if result.get("model_status") is None else result["model_status"])

        solver_columns = st.columns(3)
        solver_columns[0].metric("Tempo do Gurobi", "-" if result.get("runtime") is None else f"{format_br(result['runtime'])} s")
        solver_columns[1].metric("Variáveis reais", format_int_br(result.get("num_vars")))
        solver_columns[2].metric("Restrições reais", format_int_br(result.get("num_constraints")))
        with st.expander("O que significam os valores do resultado"):
            st.markdown(
                """
                - **Status**: indica se uma solução foi encontrada.
                - **Tempo total**: tempo total medido pela aplicação, incluindo o carregamento da instância, a construção do modelo, a otimização e a geração da figura.
                - **Função objetivo**: é o valor que o modelo busca minimizar. Aqui ele representa o custo total da rede selecionada: quanto custa enviar os fluxos entre origens e destinos passando pelos hubs selecionados. Quanto menor esse valor, melhor é a solução para os dados usados.
                - **Hubs**: nós escolhidos como hubs.
                - **Gap**: diferença relativa entre a melhor solução encontrada e o melhor limite do Gurobi; `0` indica otimalidade comprovada.
                - **Status do solver**: código numérico retornado pelo Gurobi. Em geral, `2` significa solução ótima.
                - **Tempo do Gurobi**: tempo gasto apenas na otimização do modelo pelo Gurobi.
                - **Variáveis reais**: quantidade de decisões que o modelo precisou criar para resolver o problema. Por exemplo: decidir se um nó se torna hub, decidir a qual hub cada nó será ligado e, dependendo do modelo, decidir quais rotas serão utilizadas.
                - **Restrições reais**: quantidade de regras que o modelo precisou respeitar. Por exemplo: abrir exatamente o número de hubs escolhido, garantir que cada nó seja ligado a um hub, impedir que um nó seja ligado a um hub que não foi aberto e manter as rotas coerentes.
                """
            )

        if result.get("error"):
            st.error(result["error"])

        tabs = st.tabs([
            "Figura", "Rotas", "Análise de fluxos", "Análise financeira",
            "Atendimento por hub", "Aproximação contínua", "Log",
        ])

        with tabs[0]:
            st.subheader("Dados da instância")
            with st.expander("O que estes indicadores significam"):
                st.markdown(
                    """
                    - **Nós**: quantidade de pontos considerados na instância.
                    - **Fluxos positivos**: quantidade de pares origem-destino com demanda maior do que zero.
                    - **Fluxo total**: soma de todos os fluxos positivos da matriz da instância.
                    - **Distância média**: média das distâncias entre todos os pares de nós distintos.
                    - **Fluxo médio**: fluxo total dividido pela quantidade de fluxos positivos.
                    - **Maior fluxo**: maior valor encontrado na matriz de fluxos.
                    - **Par do maior fluxo**: origem e destino associados ao maior fluxo.
                    - **Distância máxima**: maior distância entre dois nós da instância.

                    Os valores de **fluxo** vêm diretamente do arquivo escolhido em
                    `data/SPdata`. Cada instância tem uma matriz de fluxos: o valor na
                    linha `i` e coluna `j` representa quanto deve sair do nó `i` e
                    chegar ao nó `j`.
                    """
                )
            stats = insights["stats"]
            data_columns = st.columns(4)
            data_columns[0].metric("Nós", format_int_br(stats["nos"]))
            data_columns[1].metric("Fluxos positivos", format_int_br(stats["fluxos_positivos"]))
            data_columns[2].metric("Fluxo total", format_br(stats["fluxo_total"]))
            data_columns[3].metric("Distância média", format_br(stats["distancia_media"]))

            extra_columns = st.columns(4)
            extra_columns[0].metric("Fluxo médio", format_br(stats["fluxo_medio"]))
            extra_columns[1].metric("Maior fluxo", format_br(stats["fluxo_maximo"]))
            extra_columns[2].metric("Par do maior fluxo", stats["maior_fluxo"])
            extra_columns[3].metric("Distância máxima", format_br(stats["distancia_maxima"]))

            st.subheader("Ranking de nós")
            with st.expander("Como o ranking é calculado"):
                st.markdown(
                    """
                    - **fluxo_enviado**: soma dos fluxos que saem do nó.
                    - **fluxo_recebido**: soma dos fluxos que chegam ao nó.
                    - **fluxo_total**: fluxo enviado mais fluxo recebido.
                    - **distancia_media**: média da distância do nó para todos os outros nós.

                    Quando o ranking é ordenado por fluxo, valores maiores aparecem primeiro.
                    Quando é ordenado por distância média, valores menores aparecem primeiro,
                    pois indicam nós mais centrais.
                    """
                )
            ranking_mode = st.selectbox(
                "Ordenar o ranking por",
                ["fluxo_total", "fluxo_enviado", "fluxo_recebido", "distancia_media"],
                index=0,
            )
            ranking_reverse = ranking_mode != "distancia_media"
            ranking_rows = sorted(insights["ranking"], key=lambda row: row[ranking_mode], reverse=ranking_reverse)
            st.dataframe(
                format_rows(ranking_rows, ["fluxo_enviado", "fluxo_recebido", "fluxo_total", "distancia_media"]),
                use_container_width=True,
                hide_index=True,
            )

            st.subheader("Figura")
            image_path = result.get("image_path")
            if image_path and Path(image_path).exists():
                st.image(str(image_path), use_container_width=True)
            else:
                st.warning("A figura será exibida quando uma solução viável for encontrada.")

        with tabs[1]:
            route_rows = routes_table(result, insights["flow"])
            if route_rows:
                nodes = insights["nodes"]
                hubs = result.get("selected_hubs", [])
                route_columns = st.columns(3)
                selected_origins = route_columns[0].multiselect("Origem", nodes)
                selected_destinations = route_columns[1].multiselect("Destino", nodes)
                selected_hubs = route_columns[2].multiselect("Hub", hubs)
                st.dataframe(
                    format_rows(
                        filter_routes(route_rows, selected_origins, selected_destinations, selected_hubs),
                        ["fluxo"],
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("Nenhuma rota disponível para esta execução.")

        with tabs[2]:
            st.subheader("Fluxo agregado nos arcos da solução")
            st.caption(
                "A demanda entre cada par origem–destino é a mesma nos dois modelos. "
                "Esta análise mostra onde ela passa depois que cada modelo escolhe seus hubs e rotas."
            )
            with st.expander("Detalhamento do cálculo dos fluxos"):
                st.markdown(
                    """
                    1. A instância informa quantos pacotes precisam ir de cada origem para
                       cada destino.
                    2. O modelo escolhe o caminho desses pacotes. Um caminho pode ter:
                       - **um hub:** origem → hub → destino;
                       - **dois hubs:** origem → primeiro hub → segundo hub → destino.
                    3. A ferramenta separa o caminho em **coleta**, **inter-hub** e **entrega**.
                    4. Quando várias rotas usam a mesma ligação, seus pacotes são somados.

                    **Exemplo:** se 800 pacotes seguem por `1 → 3 → 7 → 5`, são
                    registrados 800 na coleta `1 → 3`, 800 no inter-hub `3 → 7` e
                    800 na entrega `7 → 5`.

                    Se o primeiro e o segundo hub forem iguais, a rota usa somente um hub e
                    não existe trecho inter-hub. Ligações de um ponto para ele mesmo não
                    entram na contagem.

                    **Atenção:** o fluxo total dos trechos não representa pacotes únicos.
                    O mesmo pacote aparece em cada parte do caminho que percorre. A demanda é
                    igual nos dois modelos; o que muda é o caminho escolhido para ela.
                    """
                )
            model_labels = {"multiple_ca": "Multiple com CA", "multiple_normal": "Multiple normal"}
            current_key = (
                selected_instance["name"], int(n_limit), int(override_p),
            )
            comparable = {
                name: item["result"]
                for name, item in st.session_state.get("model_results", {}).items()
                if item.get("comparison_key") == current_key and item.get("result", {}).get("ok")
            }
            if len(comparable) < 2:
                st.info(
                    "Para comparar lado a lado, execute Calcular uma vez em Multiple com CA e "
                    "uma vez em Multiple normal, mantendo a mesma configuração."
                )

            comparison_rows = []
            hub_usage_rows = []
            hub_cost_rows = []
            analyses = {}
            results_to_show = comparable or ({model_name: result} if result.get("ok") else {})
            for saved_model, saved_result in results_to_show.items():
                arc_rows, summary_rows = flow_arc_analysis(saved_result, insights["flow"])
                analyses[saved_model] = arc_rows
                comparison_rows.extend(
                    {"modelo": model_labels[saved_model], **row} for row in summary_rows
                )
                hub_usage_rows.extend(
                    {"modelo": model_labels[saved_model], **row}
                    for row in route_hub_usage_analysis(saved_result, insights["flow"])
                )
                hub_cost_rows.extend(
                    {"modelo": model_labels[saved_model], **row}
                    for row in route_hub_cost_analysis(saved_result)
                )

            if comparison_rows:
                st.markdown("#### Rotas por quantidade de hubs")
                formatted_usage = []
                for row in hub_usage_rows:
                    formatted_usage.append({
                        **row,
                        "percentual de rotas": format_percent_br(row["percentual de rotas"]),
                        "fluxo": format_br(row["fluxo"]),
                        "percentual do fluxo": format_percent_br(row["percentual do fluxo"]),
                    })
                st.dataframe(formatted_usage, use_container_width=True, hide_index=True)

                st.markdown("#### Fluxo por tipo de trecho")
                st.dataframe(
                    format_rows(comparison_rows, ["fluxo_total", "maior_fluxo_arco", "fluxo_medio_arco"]),
                    use_container_width=True,
                    hide_index=True,
                )
                if {"multiple_ca", "multiple_normal"}.issubset(analyses):
                    totals_by_model = {
                        (row["modelo"], row["tipo"]): row["fluxo_total"]
                        for row in comparison_rows
                    }
                    difference_rows = []
                    for segment_type in [
                        "Coleta: spoke → hub",
                        "Inter-hub: hub → hub",
                        "Entrega: hub → spoke",
                    ]:
                        ca_value = totals_by_model.get(("Multiple com CA", segment_type), 0)
                        normal_value = totals_by_model.get(("Multiple normal", segment_type), 0)
                        difference = ca_value - normal_value
                        variation = difference / normal_value if normal_value else None
                        if abs(difference) < 1e-9:
                            interpretation = "Mesmo fluxo total"
                        elif difference > 0:
                            interpretation = "CA transporta mais fluxo neste tipo de trecho"
                        else:
                            interpretation = "CA transporta menos fluxo neste tipo de trecho"
                        difference_rows.append({
                            "tipo de trecho": segment_type,
                            "com CA": format_br(ca_value),
                            "normal": format_br(normal_value),
                            "diferença (CA - normal)": format_br(difference),
                            "variação sobre o normal": "-" if variation is None else format_percent_br(variation),
                            "interpretação": interpretation,
                        })

                    st.markdown("#### Diferença entre os modelos")
                    st.dataframe(difference_rows, use_container_width=True, hide_index=True)
                    st.caption(
                        "A diferença é calculada como fluxo do modelo com CA menos fluxo do modelo normal. "
                        "Valor positivo indica mais fluxo no modelo com CA; valor negativo indica menos."
                    )
                for saved_model, arc_rows in analyses.items():
                    with st.expander(f"Fluxos por par de pontos — {model_labels[saved_model]}"):
                        st.dataframe(format_rows(arc_rows, ["fluxo"]), use_container_width=True, hide_index=True)
                st.markdown(
                    "**Como interpretar:** compare o fluxo total `Inter-hub` com a soma de `Coleta` e "
                    "`Entrega` para avaliar hubs versus hubs–spokes. `maior_fluxo_arco` identifica a "
                    "conexão individual mais carregada."
                )
            else:
                st.info("Execute um dos modelos para gerar a análise.")

        with tabs[3]:
            st.subheader("Análise financeira das soluções")
            st.caption(
                "Compara quanto cada modelo gasta na coleta, na transferência inter-hub e na entrega."
            )
            with st.expander("Como os custos são calculados"):
                st.markdown(
                    """
                    Para cada origem e destino, a ferramenta pega a quantidade de pacotes e
                    multiplica pelo custo do caminho escolhido:

                    `custo da rota = fluxo × (custo de coleta + custo inter-hub + custo de entrega)`

                    Depois, os custos de todas as rotas são somados. Uma rota com apenas um
                    hub não tem custo inter-hub. O **custo por pacote** divide o custo pelo
                    fluxo transportado e permite comparar grupos com volumes diferentes.

                    Os dois modelos usam a mesma demanda, mas podem escolher caminhos
                    diferentes e atribuir valores diferentes a cada trecho.
                    """
                )

            financial_models = {}
            for saved_model, saved_result in results_to_show.items():
                segment_rows, total_cost, total_flow = financial_segment_analysis(saved_result)
                if saved_result.get("route_costs"):
                    financial_models[saved_model] = {
                        "segments": segment_rows,
                        "total_cost": total_cost,
                        "total_flow": total_flow,
                    }

            if not financial_models:
                st.info("Execute novamente pelo menos um modelo para gerar a análise financeira.")
            else:
                summary_financial = []
                segment_financial = []
                for saved_model, values in financial_models.items():
                    label = model_labels[saved_model]
                    summary_financial.append({
                        "modelo": label,
                        "custo total (R$)": format_br(values["total_cost"]),
                        "fluxo total": format_br(values["total_flow"]),
                        "custo por pacote (R$)": format_br(
                            values["total_cost"] / values["total_flow"] if values["total_flow"] else 0,
                            6,
                        ),
                    })
                    for row in values["segments"]:
                        segment_financial.append({
                            "modelo": label,
                            "etapa": row["etapa"],
                            "número de pacotes": format_br(row["número de pacotes"]),
                            "custo total (R$)": format_br(row["custo total"]),
                            "percentual do custo": format_percent_br(row["percentual do custo"]),
                            "custo por pacote (R$)": format_br(row["custo por pacote"], 6),
                        })

                st.markdown("#### Resumo financeiro")
                st.dataframe(summary_financial, use_container_width=True, hide_index=True)

                st.markdown("#### Custo por etapa da rota")
                st.dataframe(segment_financial, use_container_width=True, hide_index=True)

                if {"multiple_ca", "multiple_normal"}.issubset(financial_models):
                    ca_financial = financial_models["multiple_ca"]
                    normal_financial = financial_models["multiple_normal"]
                    ca_by_stage = {row["etapa"]: row["custo total"] for row in ca_financial["segments"]}
                    normal_by_stage = {row["etapa"]: row["custo total"] for row in normal_financial["segments"]}
                    financial_difference = []
                    comparison_stages = [
                        ("Total da solução", ca_financial["total_cost"], normal_financial["total_cost"]),
                        *[
                            (stage, ca_by_stage.get(stage, 0), normal_by_stage.get(stage, 0))
                            for stage in ["Coleta", "Inter-hub", "Entrega"]
                        ],
                    ]
                    for stage, ca_value, normal_value in comparison_stages:
                        difference = ca_value - normal_value
                        variation = difference / normal_value if normal_value else None
                        financial_difference.append({
                            "item": stage,
                            "com CA (R$)": format_br(ca_value),
                            "normal (R$)": format_br(normal_value),
                            "diferença CA - normal (R$)": format_br(difference),
                            "variação": "-" if variation is None else format_percent_br(variation),
                            "mais barato": "Com CA" if difference < 0 else "Normal" if difference > 0 else "Mesmo custo",
                        })
                    st.markdown("#### Diferença financeira entre os modelos")
                    st.dataframe(financial_difference, use_container_width=True, hide_index=True)
                    st.caption(
                        "Diferença negativa significa que o modelo com CA ficou mais barato; "
                        "diferença positiva significa que o modelo normal ficou mais barato."
                    )

                if any(row["custo total"] for row in hub_cost_rows):
                    st.markdown("#### Custo das rotas com um ou dois hubs")
                    formatted_costs = [{
                        "modelo": row["modelo"],
                        "uso de hubs": row["uso de hubs"],
                        "quantidade de rotas": row["rotas"],
                        "fluxo": format_br(row["fluxo"]),
                        "custo total (R$)": format_br(row["custo total"]),
                        "percentual do custo": format_percent_br(row["percentual do custo"]),
                        "custo médio por rota (R$)": format_br(row["custo médio por rota"]),
                        "custo por pacote (R$)": format_br(row["custo por pacote"], 6),
                    } for row in hub_cost_rows]
                    st.dataframe(formatted_costs, use_container_width=True, hide_index=True)
                    st.caption(
                        "O custo total depende do volume de cada grupo. Para comparar rotas com "
                        "um e dois hubs, observe principalmente o custo por pacote."
                    )

        with tabs[4]:
            route_rows = routes_table(result, insights["flow"])
            if route_rows:
                with st.expander("De onde vêm estes valores"):
                    st.markdown(
                        """
                        O **fluxo atendido por hub** é calculado a partir das rotas da
                        solução e da matriz de fluxos da instância.

                        Para cada rota `origem -> hub_origem -> hub_destino -> destino`,
                        o app pega o fluxo original daquele par `origem -> destino`.
                        Esse fluxo é somado ao `hub_origem` e também ao `hub_destino`
                        quando eles são diferentes.

                        Assim, o valor mostra quanto fluxo passa por cada hub dentro da
                        solução encontrada. Ele não é um dado novo do solver; é um
                        resumo calculado a partir da solução e dos fluxos da instância.
                        """
                    )
                served = {}
                for row in route_rows:
                    served[row["hub_origem"]] = served.get(row["hub_origem"], 0) + row["fluxo"]
                    if row["hub_destino"] != row["hub_origem"]:
                        served[row["hub_destino"]] = served.get(row["hub_destino"], 0) + row["fluxo"]

                st.dataframe(
                    format_rows([
                        {"hub": hub, "fluxo_atendido": value}
                        for hub, value in sorted(served.items(), key=lambda item: item[1], reverse=True)
                    ], ["fluxo_atendido"]),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("Nenhum atendimento por hub disponível.")

        with tabs[5]:
            st.subheader("Aproximação contínua — dados da instância")
            if model_name == "multiple_normal":
                st.info(
                    "Estas matrizes pertencem à instância, mas não entram na função objetivo "
                    "do Multiple normal. Essa opção utiliza distâncias, Chi = Delta = 1 e Alpha ajustável."
                )
            st.caption(
                "Os custos de coleta e entrega abaixo já foram calculados pelo gerador da instância. "
                "Somente o custo inter-hub é calculado nesta ferramenta."
            )

            params = insights["params"]
            st.markdown("### Parâmetros carregados")
            parameter_rows = [
                {"grupo": "Demanda", "parâmetro": "gamma", "valor": params["gamma"]},
                {"grupo": "Demanda", "parâmetro": "T", "valor": params["T"]},
                {"grupo": "Coleta", "parâmetro": "rho_col", "valor": params["rho_col"]},
                {"grupo": "Coleta", "parâmetro": "Q_col", "valor": params["Q_col"]},
                {"grupo": "Coleta", "parâmetro": "beta_col", "valor": params["beta_col"]},
                {"grupo": "Coleta", "parâmetro": "c_col", "valor": params["c_col"]},
                {"grupo": "Entrega", "parâmetro": "rho_ent", "valor": params["rho_ent"]},
                {"grupo": "Entrega", "parâmetro": "Q_ent", "valor": params["Q_ent"]},
                {"grupo": "Entrega", "parâmetro": "beta_ent", "valor": params["beta_ent"]},
                {"grupo": "Entrega", "parâmetro": "c_ent", "valor": params["c_ent"]},
                {"grupo": "Inter-hub (usuário)", "parâmetro": "c_hub", "valor": insights["c_hub_per_km"]},
                {"grupo": "Inter-hub (usuário)", "parâmetro": "alpha", "valor": insights["alpha"]},
            ]
            st.dataframe(parameter_rows, use_container_width=True, hide_index=True)

            def nested_matrix(matrix):
                return {
                    row: {column: matrix[(row, column)] for column in insights["nodes"]}
                    for row in insights["nodes"]
                }

            ca_results = {
                "regions": {},
                "C_col": nested_matrix(insights["c_col"]),
                "C_ent": nested_matrix(insights["c_ent"]),
                "C_hub": nested_matrix(insights["c_hub"]),
            }

            if isinstance(ca_results, dict):
                regions = ca_results.get("regions", ca_results)
                if not isinstance(regions, dict):
                    regions = {}

                region_rows = []
                for hub, data in sorted(regions.items()):
                    region_rows.append({
                        "hub": hub,
                        "area": data.get("area", 0.0),
                        "out_volume": data.get("out_volume", 0.0),
                        "in_volume": data.get("in_volume", 0.0),
                        "n_stops_col": data.get("n_stops_col", 0.0),
                        "n_stops_ent": data.get("n_stops_ent", 0.0),
                        "m_col": data.get("m_col", 0),
                        "m_ent": data.get("m_ent", 0),
                        "R_col": data.get("R_col", 0),
                        "R_ent": data.get("R_ent", 0),
                        "N_col": data.get("N_col", 0.0),
                        "N_ent": data.get("N_ent", 0.0),
                        "L_col": data.get("L_col", 0.0),
                        "L_ent": data.get("L_ent", 0.0),
                        "C_unit_col": data.get("C_unit_col", 0.0),
                        "C_unit_ent": data.get("C_unit_ent", 0.0),
                        "avg_interhub_cost": data.get("avg_interhub_cost", 0.0),
                    })

                C_col = ca_results.get("C_col") if isinstance(ca_results.get("C_col"), dict) else {}
                C_ent = ca_results.get("C_ent") if isinstance(ca_results.get("C_ent"), dict) else {}
                C_hub = ca_results.get("C_hub") if isinstance(ca_results.get("C_hub"), dict) else {}

                if C_col or C_ent or C_hub:
                    with st.expander("Sumário das matrizes de custo", expanded=False):
                        st.markdown(
                            """
                            As matrizes calculam o custo de cada combinação possível entre regiões
                            e hubs. As fórmulas são apresentadas separadamente abaixo.
                            """
                        )

                        st.markdown(
                            """
                            **1. Coleta (`C_col`) — região → hub**

                            Calcula o custo médio, por unidade de volume, para coletar em uma região
                            usando um determinado hub.
                            """
                        )
                        st.latex(
                            r"C^{col}_{ik}="
                            r"\frac{c_{col}\left(2d_{ik}R_i+\beta\sqrt{A_iN_i}\right)}{D_i}"
                        )
                        st.markdown(
                            """
                            O primeiro termo representa as viagens de ida e volta entre a região e
                            o hub. O segundo estima o percurso realizado dentro da própria região.
                            Depois, o custo total é dividido pelo volume coletado.
                            """
                        )

                        st.markdown(
                            """
                            **2. Entrega (`C_ent`) — hub → região**

                            Calcula o custo médio, por unidade de volume, para sair de um hub e fazer
                            as entregas em uma região.
                            """
                        )
                        st.latex(
                            r"C^{ent}_{mj}="
                            r"\frac{c_{ent}\left(2d_{mj}R_j+\beta\sqrt{A_jN_j}\right)}{D_j}"
                        )
                        st.markdown(
                            """
                            A lógica é a mesma da coleta: viagens de ida e volta entre hub e região,
                            mais o percurso interno necessário para atender os pontos de entrega. O
                            resultado é dividido pelo volume entregue.
                            """
                        )

                        st.markdown(
                            """
                            **3. Transferência (`C_hub`) — hub → hub**

                            Calcula o custo direto de transportar entre dois hubs.
                            """
                        )
                        st.latex(r"C^{hub}_{km}=\alpha\,c_{hub}\,d_{km}")
                        st.markdown(
                            """
                            O fator `alpha` aplica o desconto inter-hub. O custo é zero quando o hub
                            de origem e o de destino são o mesmo.

                            **Significado dos símbolos**

                            - `d`: distância entre a região e o hub, ou entre dois hubs;
                            - `R`: quantidade de rotas necessárias;
                            - `A`: área estimada da região;
                            - `N`: número estimado de paradas;
                            - `D`: volume coletado ou entregue;
                            - `beta`: coeficiente da aproximação contínua;
                            - `c_col`, `c_ent` e `c_hub`: custos por quilômetro;
                            - `alpha`: fator de desconto do transporte entre hubs.
                            """
                        )

                    st.markdown("### Matrizes completas de custos")
                    st.write("C_col (região × hub)")
                    st.dataframe(
                        {i: {k: format_br(v) for k, v in row.items()} for i, row in C_col.items()},
                        use_container_width=True,
                    )
                    st.write("C_ent (hub × região de destino)")
                    st.dataframe(
                        {m: {j: format_br(v) for j, v in row.items()} for m, row in C_ent.items()},
                        use_container_width=True,
                    )
                    st.write("C_hub (hub × hub)")
                    st.dataframe(
                        {k: {m: format_br(v) for m, v in row.items()} for k, row in C_hub.items()},
                        use_container_width=True,
                    )
                else:
                    if region_rows:
                        st.info("Matrizes CA não foram retornadas no formato esperado. Exibindo apenas dados por região.")
                    else:
                        st.info("Nenhuma matriz CA disponível para exibição.")

                if not region_rows and not (C_col or C_ent or C_hub):
                    st.write("Retorno CA cru:")
                    st.json(ca_results)
            else:
                st.info("Nenhum dado de CA disponível ou a estimativa CA retornou um formato inesperado.")

        with tabs[6]:
            st.code(result.get("log") or "Nenhuma saída registrada.", language="text")


if __name__ == "__main__":
    main()
