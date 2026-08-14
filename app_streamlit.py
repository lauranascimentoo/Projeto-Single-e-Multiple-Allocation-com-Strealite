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
from single_allocation import solve_single_allocation_p_hub
from multiple_allocation_ca import estimate_ca
from utilidades import load_ap_instance, plot_solution


SOLVERS = {
    "single": solve_single_allocation_p_hub,
    "multiple": solve_multiple_allocation_p_hub,
}


def read_instance_metadata(path):
    tokens = path.read_text(encoding="utf-8").split()
    n = int(tokens[0])
    flow_size = n * n
    metadata_start = 1 + n * 2 + flow_size
    metadata = tokens[metadata_start:]
    p = int(metadata[0]) if len(metadata) > 0 else 0
    params = [float(value) for value in metadata[1:]]
    delta = params[0] if len(params) > 0 else 0.75
    alpha = params[1] if len(params) > 1 else delta
    chi = params[2] if len(params) > 2 else delta
    return {
        "name": path.name,
        "path": path,
        "relative_path": path.relative_to(ROOT_DIR).as_posix(),
        "nodes": n,
        "hubs": p,
        "delta": delta,
        "alpha": alpha,
        "chi": chi,
    }


def estimate_ca_compat(**kwargs):
    """Compatibility wrapper for estimate_ca.

    Tries to call `estimate_ca` using keyword args; if a TypeError about an
    unexpected keyword occurs (some runtime mismatch), falls back to calling
    `estimate_ca` using positional arguments in the expected order.
    """
    try:
        return estimate_ca(**kwargs)
    except TypeError as e:
        msg = str(e)
        if "unexpected keyword" not in msg:
            raise

    # Build positional call using known argument names / defaults.
    nodes = kwargs.get("nodes")
    coords = kwargs.get("coords")
    flow = kwargs.get("flow")
    distance = kwargs.get("distance")
    hub_indices = kwargs.get("hub_indices")
    p = kwargs.get("p")
    Q_col = kwargs.get("Q_col") if "Q_col" in kwargs else kwargs.get("Q") or kwargs.get("Q_col")
    rho_col = kwargs.get("rho_col") if "rho_col" in kwargs else kwargs.get("rho")
    beta_col = kwargs.get("beta_col") if "beta_col" in kwargs else kwargs.get("beta")
    Q_ent = kwargs.get("Q_ent") if "Q_ent" in kwargs else kwargs.get("Q")
    rho_ent = kwargs.get("rho_ent") if "rho_ent" in kwargs else kwargs.get("rho")
    beta_ent = kwargs.get("beta_ent") if "beta_ent" in kwargs else kwargs.get("beta")
    area_per_node = kwargs.get("area_per_node")
    cost_per_km_col = kwargs.get("cost_per_km_col") if "cost_per_km_col" in kwargs else kwargs.get("cost_per_km")
    cost_per_km_ent = kwargs.get("cost_per_km_ent") if "cost_per_km_ent" in kwargs else kwargs.get("cost_per_km")
    c_hub = kwargs.get("c_hub")
    alpha = kwargs.get("alpha")
    v = kwargs.get("v", 40.0)

    return estimate_ca(
        nodes,
        coords,
        flow,
        distance,
        hub_indices,
        p,
        Q_col,
        rho_col,
        beta_col,
        Q_ent,
        rho_ent,
        beta_ent,
        area_per_node,
        cost_per_km_col,
        cost_per_km_ent,
        c_hub,
        alpha,
        v,
    )


def _nearest_nodes_to_centroids(nodes, coords, centroids):
    """Given centroids (list of (lat,lon) or dict values), return a list
    of node indices (from `nodes`) that are nearest to each centroid.

    `centroids` can be a list of (x,y) tuples or a list/dict of objects with
    latitude/longitude keys. The returned list preserves the order of centroids
    as given.
    """
    seeds = []
    # Normalize centroids input
    pts = []
    if isinstance(centroids, dict):
        # values are records
        for v in centroids.values():
            if isinstance(v, (list, tuple)) and len(v) >= 2:
                pts.append((v[0], v[1]))
    elif isinstance(centroids, list):
        for item in centroids:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                pts.append((item[0], item[1]))
            elif isinstance(item, dict):
                lat = item.get("Latitude_Centroide") or item.get("Latitude") or item.get("lat")
                lon = item.get("Longitude_Centroide") or item.get("Longitude") or item.get("lon")
                if lat is not None and lon is not None:
                    pts.append((lat, lon))

    for cx, cy in pts:
        best = None
        bestd = float("inf")
        for n in nodes:
            x, y = coords.get(n, (None, None))
            if x is None or y is None:
                continue
            d = (x - cx) ** 2 + (y - cy) ** 2
            if d < bestd:
                bestd = d
                best = n
        if best is not None:
            seeds.append(best)

    return seeds


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


def load_selected_instance(instance, n_limit, override_p):
    return load_ap_instance(
        file_path=instance["relative_path"],
        n_limit=n_limit,
        override_p=override_p,
    )


def instance_insights(instance, n_limit, override_p):
    nodes, coords, flow, distance, p, alpha, chi, delta = load_selected_instance(
        instance, n_limit, override_p
    )
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
        "p": p,
        "alpha": alpha,
        "chi": chi,
        "delta": delta,
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


def run_model(model_name, instance, n_limit, override_p, alpha, chi, delta, time_limit):
    os.environ["MPLBACKEND"] = "Agg"
    os.environ["SP_SKIP_PLOT_SHOW"] = "1"
    os.makedirs(OUTPUTS_DIR, exist_ok=True)

    previous_cwd = Path.cwd()
    buffer = io.StringIO()
    started = time.perf_counter()

    try:
        os.chdir(ROOT_DIR)
        nodes, coords, flow, distance, p, _, _, _ = load_ap_instance(
            file_path=instance["relative_path"],
            n_limit=n_limit,
            override_p=override_p,
        )

        solver = SOLVERS[model_name]

        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            model, selected_hubs, selected_routes = solver(
                nodes=nodes,
                flow=flow,
                distance=distance,
                p=p,
                alpha=alpha,
                chi=chi,
                delta=delta,
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
                    title=f"Solução SP - alocação {model_name}",
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


def main():
    configure_page()

    st.title("SP Hub Location")
    st.caption("Execute o modelo 'Multiple Allocation' para a instância local SP 11.5.")

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
            options=["multiple"],
            default="multiple",
            format_func=lambda value: "Multiple Allocation",
        )

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

        st.markdown("### Parâmetros de custo")
        delta_col, alpha_col, chi_col = st.columns(3)

        with delta_col:
            delta = st.number_input(
                "Delta",
                min_value=0.0,
                value=float(selected_instance.get("delta", 0.75)),
                step=0.01,
                format="%.2f",
            )
            st.markdown("<span style='font-size:0.75em;color:#bbb;display:block;margin-top:0.2em;'>Custo de distribuição do segundo hub para o destino.</span>", unsafe_allow_html=True)

        with alpha_col:
            alpha = st.number_input(
                "Alpha",
                min_value=0.0,
                value=float(selected_instance.get("alpha", 0.75)),
                step=0.01,
                format="%.2f",
            )
            st.markdown("<span style='font-size:0.75em;color:#bbb;display:block;margin-top:0.2em;'>Custo de transferência entre hubs.</span>", unsafe_allow_html=True)

        with chi_col:
            chi = st.number_input(
                "Chi",
                min_value=0.0,
                value=float(selected_instance.get("chi", 0.75)),
                step=0.01,
                format="%.2f",
            )
            st.markdown("<span style='font-size:0.75em;color:#bbb;display:block;margin-top:0.2em;'>Custo de coleta da origem até o primeiro hub.</span>", unsafe_allow_html=True)

        time_limit = st.number_input(
            "Tempo limite (segundos)",
            min_value=1,
            max_value=86400,
            value=300,
            step=30,
        )

        st.markdown("### Aproximação contínua (CA)")
        ca_Q = st.number_input("Capacidade do veículo (pacotes)", min_value=1.0, value=40.0, step=1.0, format="%.1f")
        st.markdown("<span style='font-size:0.75em;color:#bbb;display:block;margin-top:0.2em;'>Número máximo de pacotes que o veículo pode transportar por rota.</span>", unsafe_allow_html=True)

        ca_rho = st.number_input("Pacotes por parada", min_value=0.1, value=1.0, step=0.1, format="%.1f")
        st.markdown("<span style='font-size:0.75em;color:#bbb;display:block;margin-top:0.2em;'>Média de pacotes atendidos em cada parada.</span>", unsafe_allow_html=True)

        ca_beta = st.number_input("Coeficiente CA", min_value=0.0, value=0.75, step=0.01, format="%.2f")
        st.markdown("<span style='font-size:0.75em;color:#bbb;display:block;margin-top:0.2em;'>Coeficiente usado para estimar a distância interna das regiões.</span>", unsafe_allow_html=True)

        ca_cost_per_km = st.number_input("Custo por km", min_value=0.0, value=1.0, step=0.1, format="%.2f")
        st.markdown("<span style='font-size:0.75em;color:#bbb;display:block;margin-top:0.2em;'>Custo operacional por quilômetro usado tanto na coleta quanto na entrega.</span>", unsafe_allow_html=True)

        ca_area_per_node = st.number_input("Área por nó (km²)", min_value=0.01, value=1.0, step=0.1, format="%.2f")
        st.markdown("<span style='font-size:0.75em;color:#bbb;display:block;margin-top:0.2em;'>Área mínima atribuída a cada nó para evitar regiões com área zero.</span>", unsafe_allow_html=True)

        ca_c_hub = st.number_input("Custo inter-hub por km", min_value=0.0, value=1.0, step=0.1, format="%.2f")
        st.markdown("<span style='font-size:0.75em;color:#bbb;display:block;margin-top:0.2em;'>Custo por quilômetro para o transporte entre hubs.</span>", unsafe_allow_html=True)

        ca_alpha = st.number_input("Fator de desconto inter-hub", min_value=0.0, max_value=1.0, value=0.75, step=0.01, format="%.2f")
        st.markdown("<span style='font-size:0.75em;color:#bbb;display:block;margin-top:0.2em;'>Fator aplicado ao custo de transporte entre hubs.</span>", unsafe_allow_html=True)

        st.markdown("**Método de partição/atendimento: Áreas pré-fixadas**")
        ca_method = "Fixed regions"

        run_clicked = st.button("Calcular", type="primary", use_container_width=True)

    estimates = estimate_size(model_name, int(n_limit))
    insights = instance_insights(selected_instance, int(n_limit), int(override_p))

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
                alpha=float(alpha),
                chi=float(chi),
                delta=float(delta),
                time_limit=int(time_limit),
            )
        st.session_state["last_result"] = result
        st.session_state["last_config"] = {
            "model_name": model_name,
            "instance": selected_instance["name"],
            "n_limit": int(n_limit),
            "override_p": int(override_p),
            "alpha": float(alpha),
            "chi": float(chi),
            "delta": float(delta),
            "time_limit": int(time_limit),
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
        summary_columns = st.columns(6)
        summary_columns[0].metric("Status", status_label)
        summary_columns[1].metric("Tempo total", f"{format_br(result['elapsed'])} s")
        summary_columns[2].metric(
            "Função objetivo",
            format_br(result.get("objective")),
        )
        summary_columns[3].metric("Hubs", ", ".join(map(str, result.get("selected_hubs", []))) or "-")
        summary_columns[4].metric("Gap", format_percent_br(result.get("gap")))
        summary_columns[5].metric("Status do solver", "-" if result.get("model_status") is None else result["model_status"])

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

        tabs = st.tabs(["Figura", "Rotas", "Atendimento por hub", "Aproximação contínua", "Log"])

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
                st.image(str(image_path), width=640)
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

        with tabs[3]:
            # Aproximação contínua
            st.subheader("Aproximação contínua — estimativas por região/hub")


            # determine hub seeds selection for CA
            ca_hub_choice = None
            if ca_method.startswith("Voronoi (hubs selecionados)"):
                ca_hub_choice = st.multiselect(
                    "Selecione hubs (índices)",
                    options=insights["nodes"],
                    default=insights["nodes"][:max(1, insights["p"] )],
                )
                ca_hub_choice = [int(x) for x in ca_hub_choice]
                if len(ca_hub_choice) == 0:
                    st.info("Nenhum hub selecionado: será usado top-p por fluxo para a estimativa CA.")
                    ca_hub_choice = None
            elif ca_method.startswith("Fixed regions"):
                # Load centroids file from the spatial model output and map to nearest nodes
                try:
                    import json

                    centroids_path = ROOT_DIR / "sp_spatial_gravity_model" / "output" / "centroides_populacionais_sp.json"
                    if centroids_path.exists():
                        with open(centroids_path, "r", encoding="utf-8") as f:
                            centroids = json.load(f)
                        ca_hub_choice = _nearest_nodes_to_centroids(insights["nodes"], insights["coords"], centroids)
                        if not ca_hub_choice:
                            st.info("Não foi possível mapear centroids para nós: será usado top-p por fluxo.")
                            ca_hub_choice = None
                    else:
                        st.info("Arquivo de centroides não encontrado: será usado top-p por fluxo.")
                        ca_hub_choice = None
                except Exception as e:
                    st.info(f"Erro ao carregar centroides: {e}")
                    ca_hub_choice = None
            else:
                ca_hub_choice = None

            # Run estimation
            try:
                ca_results = estimate_ca_compat(
                    nodes=insights["nodes"],
                    coords=insights["coords"],
                    flow=insights["flow"],
                    distance=insights["distance"],
                    hub_indices=ca_hub_choice,
                    p=int(override_p),
                    Q_col=float(ca_Q),
                    rho_col=float(ca_rho),
                    beta_col=float(ca_beta),
                    Q_ent=float(ca_Q),
                    rho_ent=float(ca_rho),
                    beta_ent=float(ca_beta),
                    area_per_node=float(ca_area_per_node),
                    cost_per_km_col=float(ca_cost_per_km),
                    cost_per_km_ent=float(ca_cost_per_km),
                    c_hub=float(ca_c_hub),
                    alpha=float(ca_alpha),
                )
            except Exception as e:
                st.error(f"Erro ao estimar CA: {e}")
                ca_results = {}

            if isinstance(ca_results, dict):
                regions = ca_results.get("regions", ca_results)
                if not isinstance(regions, dict):
                    regions = {}

                if not regions:
                    st.warning("CA retornou um conjunto de regiões vazio ou em formato não reconhecido.")
                elif "regions" not in ca_results:
                    st.warning("Usando formato CA legado; os dados poderão estar incompletos.")

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

        with tabs[4]:
            st.code(result.get("log") or "Nenhuma saída registrada.", language="text")


if __name__ == "__main__":
    main()
