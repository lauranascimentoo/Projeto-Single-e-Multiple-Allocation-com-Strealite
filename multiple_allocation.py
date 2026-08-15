"""Multiple allocation p-hub median, inspirado em Campbell (1996).

Modelagem implementada
----------------------
Conjuntos:
    N = conjunto de nos que podem ser origem, destino e hub.

Parametros:
    w_ij = fluxo de i para j.
    C_col_ik = custo unitario de coleta da origem i pelo hub k.
    C_hub_km = custo unitario de transferencia entre os hubs k e m.
    C_ent_mj = custo unitario de entrega do hub m ao destino j.
    p = quantidade de hubs a abrir.

Variaveis:
    z_k = 1 se o no k e escolhido como hub.
    x_ijkm = 1 se o fluxo i -> j usa a rota i -> k -> m -> j.

Funcao objetivo:
    min soma_{i,j,k,m} w_ij *
        (C_col_ik + C_hub_km + C_ent_mj) * x_ijkm

Restricoes:
    1. soma_k z_k = p
       Abre exatamente p hubs.

    2. soma_{k,m} x_ijkm = 1, para todo fluxo i -> j
       Cada par origem-destino escolhe uma unica rota por hubs.

    3. soma_m x_ijkm <= z_k, para todo i,j,k
       O no k so pode ser usado como primeiro hub se estiver aberto.

    4. soma_m x_ijmk <= z_k, para todo i,j,k
       O no k so pode ser usado como segundo hub se estiver aberto.

    5. z_k e x_ijkm binarias.
"""

import os
import time

import gurobipy as gp
from gurobipy import GRB

from utilidades import ExecutionTimeLimitReached, write_execution_log


def _solve_multiple_allocation_p_hub(
    type,
    distance,
    nodes,
    flow,
    c_col,
    c_ent,
    c_hub,
    p,
    instance_path,
    time_limit=300,
    execution_log_path="Logs/gurobi_execucoes.log",
):
    start_time = time.perf_counter()
    estimated_route_vars = len(flow) * len(nodes) * len(nodes)
    write_execution_log(
        execution_log_path,
        instance_path,
        nodes,
        flow,
        p,
        event="INICIO_MULTIPLE",
        detail=(
            f"variaveis_rota_estimadas={estimated_route_vars};"
            f"limite_tempo_s={time_limit}"
        ),
    )
    print(f"\nInstancia em execucao: {instance_path}")
    print("Modelo: multiple allocation p-hub median")
    print(f"Variaveis de rota estimadas: {estimated_route_vars}")

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
        mdl = gp.Model("AP_multiple_allocation_p_hub")
    except gp.GurobiError as error:
        print("\nErro ao iniciar o Gurobi.")
        print("Verifique a instalacao e a licenca do Gurobi.")
        print(f"Detalhe do erro: {error}")
        finish_log("ERRO_INICIALIZACAO", detail=f"erro={error}")
        return None, [], {}

    os.makedirs("Logs", exist_ok=True)
    mdl.Params.LogFile = "Logs/gurobi.log"
    remaining_time("criacao_variaveis_hub")

    # Variavel z_k: indica se k foi escolhido como hub.
    z = mdl.addVars(nodes, vtype=GRB.BINARY, name="z")

    # Variavel x_ijkm: indica se o fluxo i -> j passa por k como primeiro hub
    # e por m como segundo hub. No multiple allocation, fluxos diferentes de
    # uma mesma origem podem usar hubs diferentes.
    x = gp.tupledict()
    flow_pairs = list(flow)
    batch_size = 25

    for batch_start in range(0, len(flow_pairs), batch_size):
        remaining_time("criacao_variaveis_rota")
        batch_pairs = flow_pairs[batch_start:batch_start + batch_size]
        batch_keys = [
            (i, j, k, m)
            for (i, j) in batch_pairs
            for k in nodes
            for m in nodes
        ]
        x.update(mdl.addVars(batch_keys, vtype=GRB.BINARY, name="x"))

    # Restricao 1: abrir exatamente p hubs.
    remaining_time("criacao_restricoes")
    mdl.addConstr(gp.quicksum(z[k] for k in nodes) == p, name="number_of_hubs")

    # Restricao 2: cada fluxo origem-destino escolhe exatamente uma rota
    # i -> hub k -> hub m -> j.
    for (i, j) in flow:
        remaining_time("criacao_restricoes_atribuicao")
        mdl.addConstr(
            gp.quicksum(x[i, j, k, m] for k in nodes for m in nodes) == 1,
            name=f"assign_{i}_{j}",
        )

    # Restricoes 3 e 4: uma rota so pode usar hubs que foram abertos.
    # Esta forma agregada reduz a quantidade de restricoes em comparacao com
    # impor x_ijkm <= z_k e x_ijkm <= z_m para todo i,j,k,m.
    for (i, j) in flow:
        remaining_time("criacao_restricoes_hubs")
        for k in nodes:
            mdl.addConstr(
                gp.quicksum(x[i, j, k, m] for m in nodes) <= z[k],
                name=f"use_first_hub_{i}_{j}_{k}",
            )
            mdl.addConstr(
                gp.quicksum(x[i, j, m, k] for m in nodes) <= z[k],
                name=f"use_second_hub_{i}_{j}_{k}",
            )

    # Funcao objetivo de Campbell/multiple:
    # custo total do fluxo i -> j quando ele usa os hubs k e m.
    objective = gp.LinExpr()

    for position, ((i, j, k, m), variable) in enumerate(x.items()):
        if position % 10000 == 0:
            remaining_time("construcao_objetivo")
        if type == "multiple_ca":
            coefficient = (
                flow[(i, j)]
                * (
                    distance[(i, k)]
                    + c_hub[(k, m)]
                    + distance[(m, j)]
                )
            )
        else:
            coefficient = (
                flow[(i, j)]
                * (
                    c_col[(i, k)]
                    + c_hub[(k, m)]
                    + c_ent[(m, j)]
                )
            )
        objective.addTerms(coefficient, variable)

    mdl.setObjective(objective, GRB.MINIMIZE)
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

    selected_hubs = [k for k in nodes if z[k].X > 0.5]
    selected_routes = {}

    for (i, j) in flow:
        found_route = False

        for k in nodes:
            for m in nodes:
                if x[i, j, k, m].X > 0.5:
                    selected_routes[(i, j)] = (k, m)
                    found_route = True
                    break

            if found_route:
                break

    print("\nSolucao encontrada.")
    print("Status:", mdl.Status)
    print("Custo objetivo:", mdl.ObjVal)
    print("Hubs escolhidos:", selected_hubs)
    finish_log(
        "SOLUCAO_MULTIPLE",
        detail=(
            f"status={mdl.Status};tempo_gurobi_s={mdl.Runtime:.3f};"
            f"objetivo={mdl.ObjVal:.6f};hubs_escolhidos={selected_hubs}"
        ),
    )

    print("\nRotas escolhidas:")
    for (i, j), (k, m) in selected_routes.items():
        print(f"{i} -> {j}: {i} -> hub {k} -> hub {m} -> {j}")

    return mdl, selected_hubs, selected_routes


def solve_multiple_allocation_p_hub(*args, **kwargs):
    try:
        return _solve_multiple_allocation_p_hub(*args, **kwargs)
    except ExecutionTimeLimitReached as error:
        print(f"\n{error}")
        return None, [], {}
