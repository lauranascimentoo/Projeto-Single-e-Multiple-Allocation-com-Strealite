"""Single allocation p-hub median com formulacao EMMRr.

Baseado em Espejo, Marin, Munoz-Ocana e Rodriguez-Chia (2023).

A formulacao substitui a funcao objetivo quadratica de O'Kelly por uma
formulacao linear compacta: usa as variaveis binarias y_ik de
localizacao/alocacao e uma variavel continua S_i para o custo agregado dos
pares i < j.
"""

import os
import time

import gurobipy as gp
from gurobipy import GRB

from utils.utilidades import ExecutionTimeLimitReached, write_execution_log


def route_cost(flow_value, origin, destination, first_hub, second_hub, c_col, c_ent, c_hub):
    return (
        flow_value
        * (
            c_col[(origin, first_hub)]
            + c_hub[(first_hub, second_hub)]
            + c_ent[(second_hub, destination)]
        )
    )


def aggregated_pair_cost(i, j, k, m, flow, c_col, c_ent, c_hub):
    forward = route_cost(flow.get((i, j), 0), i, j, k, m, c_col, c_ent, c_hub)
    backward = route_cost(flow.get((j, i), 0), j, i, m, k, c_col, c_ent, c_hub)
    return forward + backward


def _solve_single_allocation_p_hub(
    nodes,
    flow,
    distance,
    c_col,
    c_ent,
    c_hub,
    p,
    instance_path,
    time_limit=300,
    execution_log_path="Logs/gurobi_execucoes.log",
):
    start_time = time.perf_counter()
    estimated_binary_vars = len(nodes) * len(nodes)
    estimated_continuous_vars = len(nodes)
    estimated_constraints = 2 * len(nodes) * len(nodes) + len(nodes) + 1
    write_execution_log(
        execution_log_path,
        instance_path,
        nodes,
        flow,
        p,
        event="INICIO_SINGLE_EMMRR",
        detail=(
            f"variaveis_binarias={estimated_binary_vars};"
            f"variaveis_continuas={estimated_continuous_vars};"
            f"restricoes_estimadas={estimated_constraints};"
            f"limite_tempo_s={time_limit}"
        ),
    )
    print(f"\nInstancia em execucao: {instance_path}")
    print("Modelo: single allocation p-hub median - EMMRr linear")
    print(f"Variaveis binarias estimadas: {estimated_binary_vars}")
    print(f"Variaveis continuas estimadas: {estimated_continuous_vars}")
    print(f"Restricoes estimadas: {estimated_constraints}")

    def finish_log(event, detail=None):
        elapsed = time.perf_counter() - start_time
        write_execution_log(
            execution_log_path,
            instance_path,
            nodes,
            flow,
            p,
            event=event,
            elapsed=elapsed,
            detail=detail,
        )
        print(f"Tempo total da execucao: {elapsed:.3f} s")
        print(f"Log de execucao: {execution_log_path}")

    def remaining_time(stage):
        elapsed = time.perf_counter() - start_time
        remaining = time_limit - elapsed

        if remaining <= 0:
            finish_log("TIMEOUT_TOTAL", detail=f"etapa={stage};limite_tempo_s={time_limit}")
            raise ExecutionTimeLimitReached(f"Tempo limite total atingido durante: {stage}.")

        return remaining

    try:
        mdl = gp.Model("AP_single_allocation_EMMRr")
    except gp.GurobiError as error:
        print("\nErro ao iniciar o Gurobi.")
        print("Verifique a instalacao e a licenca do Gurobi.")
        print(f"Detalhe do erro: {error}")
        finish_log("ERRO_INICIALIZACAO", detail=f"erro={error}")
        return None, [], {}

    os.makedirs("Logs", exist_ok=True)
    mdl.Params.LogFile = "Logs/gurobi.log"
    remaining_time("criacao_variaveis")

    y = mdl.addVars(nodes, nodes, vtype=GRB.BINARY, name="y")
    s = mdl.addVars(nodes, lb=0, vtype=GRB.CONTINUOUS, name="S")

    remaining_time("criacao_restricoes")
    mdl.addConstr(gp.quicksum(y[k, k] for k in nodes) == p, name="number_of_hubs")

    for i in nodes:
        remaining_time("restricoes_atribuicao")
        mdl.addConstr(gp.quicksum(y[i, k] for k in nodes) == 1, name=f"assign_node_{i}")

    for i in nodes:
        remaining_time("restricoes_hubs")
        for k in nodes:
            mdl.addConstr(y[i, k] <= y[k, k], name=f"assign_only_to_hub_{i}_{k}")

    pair_cost = {}
    max_pair_cost = {}

    for i in nodes:
        remaining_time("pre_calculo_custos")
        for j in nodes:
            if j <= i:
                continue

            for k in nodes:
                values = []
                for m in nodes:
                    cost = aggregated_pair_cost(i, j, k, m, flow, c_col, c_ent, c_hub)
                    pair_cost[(i, j, k, m)] = cost
                    values.append(cost)

                max_pair_cost[(i, j, k)] = max(values, default=0)

    for i in nodes:
        for k in nodes:
            remaining_time("restricoes_EMMRr")
            rhs = gp.LinExpr()

            for j in nodes:
                if j <= i:
                    continue

                for m in nodes:
                    rhs.addTerms(pair_cost[(i, j, k, m)], y[j, m])

                max_cost = max_pair_cost[(i, j, k)]
                rhs.addTerms(max_cost, y[i, k])
                rhs.addConstant(-max_cost)

            mdl.addConstr(s[i] >= rhs, name=f"EMMRr_{i}_{k}")

    mdl.setObjective(gp.quicksum(s[i] for i in nodes), GRB.MINIMIZE)
    mdl.Params.TimeLimit = remaining_time("inicio_otimizacao")
    mdl.update()

    print("\nResumo do modelo:")
    print(f"Variaveis totais: {mdl.NumVars}")
    print(f"Restricoes totais: {mdl.NumConstrs}")

    try:
        mdl.optimize()
    except gp.GurobiError as error:
        print("\nErro ao resolver o modelo.")
        print("Verifique a instalacao e a licenca do Gurobi.")
        print(f"Detalhe do erro: {error}")
        finish_log("ERRO_OTIMIZACAO", detail=f"erro={error}")
        return mdl, [], {}

    if mdl.SolCount == 0:
        print("\nNenhuma solucao encontrada.")
        finish_log("SEM_SOLUCAO", detail=f"status={mdl.Status};tempo_gurobi_s={mdl.Runtime:.3f}")
        return mdl, [], {}

    selected_hubs = [k for k in nodes if y[k, k].X > 0.5]
    assignment = {}

    for i in nodes:
        for k in nodes:
            if y[i, k].X > 0.5:
                assignment[i] = k
                break

    selected_routes = {
        (i, j): (assignment[i], assignment[j])
        for (i, j) in flow
    }

    print("\nSolucao encontrada.")
    print("Status:", mdl.Status)
    print("Custo objetivo:", mdl.ObjVal)
    print("Hubs escolhidos:", selected_hubs)
    print("Atribuicao dos nos:", assignment)
    finish_log(
        "SOLUCAO_SINGLE_EMMRR",
        detail=(
            f"status={mdl.Status};tempo_gurobi_s={mdl.Runtime:.3f};"
            f"objetivo={mdl.ObjVal:.6f};hubs_escolhidos={selected_hubs};"
            f"atribuicao={assignment}"
        ),
    )

    print("\nRotas escolhidas:")
    for (i, j), (k, m) in selected_routes.items():
        print(f"{i} -> {j}: {i} -> hub {k} -> hub {m} -> {j}")

    return mdl, selected_hubs, selected_routes


def solve_single_allocation_p_hub(*args, **kwargs):
    try:
        return _solve_single_allocation_p_hub(*args, **kwargs)
    except ExecutionTimeLimitReached as error:
        print(f"\n{error}")
        return None, [], {}
