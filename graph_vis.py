import json
import networkx as nx


def load_graph(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_nx(graph):

    G = nx.DiGraph()

    for dataset, data in graph.items():

        source = data.get("source")

        # Dataset node
        G.add_node(
            dataset,
            group="dataset",
            label=dataset,
            abstract="",
            year="",
            doi=data.get("doi", ""),
        )

        if not source:
            continue

        source_bibcode = source.get("bibcode")

        if not source_bibcode:
            continue

        # Instrument paper node
        G.add_node(
            source_bibcode,
            group="paper",
            label=source.get("title", source_bibcode),
            abstract=source.get("abstract", ""),
            year=source.get("year", ""),
            doi=source.get("doi", ""),
        )

        G.add_edge(dataset, source_bibcode)

        # Downstream papers
        for c in data.get("downstream_science", []):

            citation_bibcode = c.get("bibcode")

            if not citation_bibcode:
                continue

            G.add_node(
                citation_bibcode,
                group="science",
                label=c.get("title", citation_bibcode),
                abstract=c.get("abstract", ""),
                year=c.get("year", ""),
                doi=c.get("doi", ""),
            )

            G.add_edge(source_bibcode, citation_bibcode)

    return G


def visualize(G, output="graph.html"):

    color_map = {
        "dataset": "#ff7f0e",
        "paper": "#1f77b4",
        "science": "#2ca02c",
    }

    nodes_data = []

    for node_id, attr in G.nodes(data=True):

        group = attr.get("group", "other")

        nodes_data.append(
            {
                "id": node_id,
                "label": attr.get("label", node_id)[:60],
                "group": group,
                "color": color_map.get(group, "#808080"),
                "abstract": attr.get("abstract", ""),
                "year": attr.get("year", ""),
                "doi": attr.get("doi", ""),
            }
        )

    edges_data = [
        {"from": u, "to": v}
        for u, v in G.edges()
    ]

    html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">

<title>Science Graph</title>

<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>

<style>

html, body {{
    height:100%;
    margin:0;
    font-family:Arial, sans-serif;
}}

#legend {{
    height:40px;
    display:flex;
    align-items:center;
    gap:20px;
    padding-left:15px;
    border-bottom:1px solid #ddd;
}}

.legend-item {{
    display:flex;
    align-items:center;
}}

.legend-dot {{
    width:12px;
    height:12px;
    border-radius:50%;
    margin-right:6px;
}}

#main {{
    display:flex;
    height:calc(100% - 40px);
}}

#graph {{
    flex:3;
}}

#panel {{
    flex:1;
    min-width:350px;
    border-left:2px solid #ddd;
    padding:20px;
    overflow-y:auto;
}}

#node-title {{
    font-weight:bold;
    font-size:16px;
    margin-bottom:10px;
}}

#node-group {{
    color:#666;
    margin-bottom:10px;
}}

#node-meta {{
    margin-bottom:15px;
}}

#node-abstract {{
    line-height:1.5;
}}

</style>
</head>

<body>

<div id="legend">

<div class="legend-item">
<span class="legend-dot" style="background:#ff7f0e"></span>
Dataset
</div>

<div class="legend-item">
<span class="legend-dot" style="background:#1f77b4"></span>
Dataset Paper
</div>

<div class="legend-item">
<span class="legend-dot" style="background:#2ca02c"></span>
Downstream Science
</div>

</div>

<div id="main">

<div id="graph"></div>

<div id="panel">

<div id="node-title">
Sélectionnez un nœud
</div>

<div id="node-group"></div>

<div id="node-meta"></div>

<div id="node-abstract">
Cliquez sur un nœud pour afficher ses informations.
</div>

</div>

</div>

<script>

const nodes = new vis.DataSet(
{json.dumps(nodes_data, ensure_ascii=False)}
);

const edges = new vis.DataSet(
{json.dumps(edges_data, ensure_ascii=False)}
);

const container = document.getElementById("graph");

const network = new vis.Network(
    container,
    {{
        nodes: nodes,
        edges: edges
    }},
    {{
        physics: {{
            solver: "forceAtlas2Based",
            forceAtlas2Based: {{
                gravitationalConstant: -50,
                springLength: 100,
                springConstant: 0.08
            }},
            stabilization: {{
                iterations: 150
            }}
        }},
        nodes: {{
            shape: "dot",
            size: 14,
            font: {{
                size: 12
            }}
        }},
        edges: {{
            arrows: {{
                to: {{
                    enabled: true,
                    scaleFactor: 0.5
                }}
            }},
            smooth: {{
                type: "continuous"
            }}
        }}
    }}
);

network.on("click", function(params) {{

    if(params.nodes.length === 0)
        return;

    const nodeId = params.nodes[0];

    const node = nodes.get(nodeId);

    document.getElementById("node-title").innerText =
        node.label;

    document.getElementById("node-group").innerText =
        node.group;

    document.getElementById("node-meta").innerHTML =
        "<b>DOI:</b> " + (node.doi || "-") + "<br>" +
        "<b>Year:</b> " + (node.year || "-");

    document.getElementById("node-abstract").innerText =
        node.abstract || "Pas d'abstract disponible.";

}});

</script>

</body>
</html>
"""

    with open(output, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✔ saved: {output}")


if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "graph_json",
        help="graph.json produit par build_graph.py"
    )

    parser.add_argument(
        "-o",
        "--output",
        default="graph.html"
    )

    args = parser.parse_args()

    graph = load_graph(args.graph_json)

    G = build_nx(graph)

    print(f"Nodes : {G.number_of_nodes()}")
    print(f"Edges : {G.number_of_edges()}")

    visualize(G, args.output)