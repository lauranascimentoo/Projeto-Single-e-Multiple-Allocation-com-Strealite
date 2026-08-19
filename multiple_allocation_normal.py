"""Multiple Allocation tradicional baseado em distancia.

Esta versao preserva a funcao objetivo utilizada antes da incorporacao das
matrizes de custo da aproximacao continua:

    w_ij * (d_ik + alpha*d_km + d_mj) / 1000

Os coeficientes de coleta (chi) e entrega (delta) sao fixos e iguais a 1.

As restricoes e variaveis sao compartilhadas com o solver Multiple Allocation
com CA para evitar duas implementacoes divergentes da mesma formulacao.
"""

from multiple_allocation import solve_multiple_allocation_p_hub


def solve_multiple_allocation_normal(
    nodes,
    flow,
    distance,
    p,
    alpha,
    instance_path,
    time_limit=300,
    execution_log_path="Logs/gurobi_execucoes.log",
):
    """Resolve o Multiple tradicional convertendo distancias em matrizes de custo."""
    c_col = {
        (i, k): distance[(i, k)] / 1000
        for i in nodes
        for k in nodes
    }
    c_hub = {
        (k, m): alpha * distance[(k, m)] / 1000
        for k in nodes
        for m in nodes
    }
    c_ent = {
        (m, j): distance[(m, j)] / 1000
        for m in nodes
        for j in nodes
    }

    return solve_multiple_allocation_p_hub(
        nodes=nodes,
        flow=flow,
        distance=distance,
        c_col=c_col,
        c_ent=c_ent,
        c_hub=c_hub,
        p=p,
        instance_path=instance_path,
        time_limit=time_limit,
        execution_log_path=execution_log_path,
    )
