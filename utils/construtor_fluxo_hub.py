import csv
import os 


def build_hub_pair_flows(selected_routes, flow):
    edge_flows = {}

    for (i, j), (k, m) in selected_routes.items():
        if k == m:
            continue

        edge = tuple(sorted((k, m)))
        edge_flows[edge] = edge_flows.get(edge, 0) + flow[(i, j)]

    return edge_flows


def export_hub_pair_flows_csv(
    output_path,
    selected_routes,
    flow,
    p,
    alpha,
    instance_name=None,
):
    """
    Escreve um CSV com uma linha por par de hubs (k, m), o fluxo agregado
    que passa por esse link, e os parâmetros usados na execução (p, alpha).

    Colunas: hub_origem, hub_destino, fluxo_agregado, p, alpha
    [, instancia se instance_name for informado]
    """
    pair_flows = build_hub_pair_flows(selected_routes, flow)

    os.makedirs(os.path.dirname(str(output_path)) or ".", exist_ok=True)

    header = ["hub_origem", "hub_destino", "fluxo_agregado", "p", "alpha"]
    if instance_name is not None:
        header.append("instancia")

    with open(output_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(header)

        for (k, m), aggregated_flow in sorted(pair_flows.items()):
            row = [k, m, aggregated_flow, p, alpha]
            if instance_name is not None:
                row.append(instance_name)
            writer.writerow(row)

    print(f"CSV de fluxos entre hubs salvo em: {output_path}")
    return output_path