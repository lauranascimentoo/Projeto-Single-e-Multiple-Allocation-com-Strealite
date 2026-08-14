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
from utilidades import load_sp_instance, plot_solution


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
        nodes, coords, flow, p = data["nodes"], data["coords"], data["flow"], data["p"]

        solver = SOLVERS[model_name]

        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            model, selected_hubs, selected_routes = solver(
                nodes=nodes,
                flow=flow,
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

        st.markdown("### Custo inter-hub")
        hub_cost_col, alpha_col = st.columns(2)
        with hub_cost_col:
            ca_c_hub = st.number_input(
                "c_hub (R$/km)", min_value=0.0, value=1.0, step=0.1, format="%.2f"
            )
        with alpha_col:
            ca_alpha = st.number_input(
                "Alpha", min_value=0.0, max_value=1.0, value=0.75, step=0.01, format="%.2f"
            )
        st.caption("C_hub[k,m] = alpha × c_hub × distância geográfica em km.")

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
                alpha=float(ca_alpha),
                time_limit=int(time_limit),
            )
        st.session_state["last_result"] = result

    result = st.session_state.get("last_result")

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
            st.subheader("Aproximação contínua — dados da instância")
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
                "C_col": nested_matrix(insights["c_col"]),
                "C_ent": nested_matrix(insights["c_ent"]),
                "C_hub": nested_matrix(insights["c_hub"]),
            }

            if isinstance(ca_results, dict):
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
                    st.info("Nenhuma matriz CA disponível para exibição.")

                if not (C_col or C_ent or C_hub):
                    st.write("Retorno CA cru:")
                    st.json(ca_results)
            else:
                st.info("Nenhum dado de CA disponível ou a estimativa CA retornou um formato inesperado.")

        with tabs[4]:
            st.code(result.get("log") or "Nenhuma saída registrada.", language="text")


if __name__ == "__main__":
    main()
