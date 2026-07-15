"""Interface Streamlit para executar os modelos AP."""

import contextlib
import io
import os
import time
from pathlib import Path

import streamlit as st


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data" / "APdata"
OUTPUTS_DIR = ROOT_DIR / "outputs"

from multiple_allocation import solve_multiple_allocation_p_hub
from single_allocation import solve_single_allocation_p_hub
from utilidades import load_ap_instance, plot_solution


SOLVERS = {
    "single": solve_single_allocation_p_hub,
    "multiple": solve_multiple_allocation_p_hub,
}


def read_instance_metadata(path):
    tokens = path.read_text(encoding="utf-8").split()
    return {
        "name": path.name,
        "path": path,
        "relative_path": path.relative_to(ROOT_DIR).as_posix(),
        "nodes": int(tokens[0]),
        "hubs": int(tokens[1 + int(tokens[0]) * 2 + int(tokens[0]) * int(tokens[0])]),
    }


@st.cache_data(show_spinner=False)
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


def run_model(model_name, instance, n_limit, override_p, time_limit):
    os.environ["MPLBACKEND"] = "Agg"
    os.environ["AP_SKIP_PLOT_SHOW"] = "1"
    os.makedirs(OUTPUTS_DIR, exist_ok=True)

    previous_cwd = Path.cwd()
    buffer = io.StringIO()
    started = time.perf_counter()

    try:
        os.chdir(ROOT_DIR)
        nodes, coords, flow, distance, p, alpha, chi, delta = load_ap_instance(
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
                image_path = OUTPUTS_DIR / f"ap_solution_{model_name}.png"
                plot_solution(
                    coords=coords,
                    flow=flow,
                    selected_hubs=selected_hubs,
                    selected_routes=selected_routes,
                    output_path=str(image_path),
                    title=f"Solução AP - alocação {model_name}",
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
        page_title="AP Hub Location",
        page_icon=":material/hub:",
        layout="wide",
    )


def main():
    configure_page()

    st.title("AP Hub Location")
    st.caption("Execute os modelos de 'Single Allocation' e 'Multiple Allocation' utilizando as instâncias AP locais.")

    instances = list_instances()

    if not instances:
        st.error("Nenhuma instância válida foi encontrada em data/APdata.")
        return

    default_index = next(
        (index for index, instance in enumerate(instances) if instance["name"] == "50.3"),
        0,
    )

    with st.sidebar:
        st.header("Configuração")

        model_name = st.segmented_control(
            "Modelo",
            options=["single", "multiple"],
            default="single",
            format_func=lambda value: "Single Allocation" if value == "single" else "Multiple Allocation",
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

        time_limit = st.number_input(
            "Tempo limite (segundos)",
            min_value=1,
            max_value=86400,
            value=300,
            step=30,
        )

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
                time_limit=int(time_limit),
            )
        st.session_state["last_result"] = result
        st.session_state["last_config"] = {
            "model_name": model_name,
            "instance": selected_instance["name"],
            "n_limit": int(n_limit),
            "override_p": int(override_p),
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

        tabs = st.tabs(["Figura", "Rotas", "Atendimento por hub", "Log"])

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
                    `data/APdata`. Cada instância tem uma matriz de fluxos: o valor na
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
            st.code(result.get("log") or "Nenhuma saída registrada.", language="text")


if __name__ == "__main__":
    main()