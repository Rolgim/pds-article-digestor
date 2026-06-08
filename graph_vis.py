"""
Construit et visualise le graphe dataset → articles citants.

Sources :
  - doi_by_collection.json  : métadonnées des collections (description, niveau, cibles...)
  - citing_articles.json    : articles citant chaque dataset (ADS + OpenAlex + Crossref)

Usage :
    python graph_viz.py
    python graph_viz.py --doi doi_by_collection.json --cit citing_articles.json -o graph.html
    python graph_viz.py --min-citations 2   # filtre les datasets avec peu de citations
    python graph_viz.py --targets Mars      # filtre par corps céleste
"""

import argparse
import json
import re
from pathlib import Path

import networkx as nx

############################################################################
# Chargement
############################################################################

def load_data(doi_path: str, cit_path: str) -> tuple[dict, dict]:
    doi_map = json.loads(Path(doi_path).read_text(encoding="utf-8"))
    cit_map = json.loads(Path(cit_path).read_text(encoding="utf-8"))
    return doi_map, cit_map


def _get_doi(entry) -> str | None:
    if isinstance(entry, dict):
        return entry.get("doi")
    return entry or None


def _get_meta(entry) -> dict:
    if isinstance(entry, dict):
        return entry
    return {"doi": entry}

############################################################################
# Construction du graphe NetworkX
############################################################################

def build_graph(
    doi_map: dict,
    cit_map: dict,
    min_citations: int = 0,
    target_filter: str | None = None,
) -> nx.DiGraph:
    G = nx.DiGraph()

    # Index des articles par DOI normalisé pour déduplication inter-datasets
    article_index: dict[str, str] = {}   # doi_norm -> node_id

    def _norm(doi) -> str | None:
        if not doi:
            return None
        if isinstance(doi, list):
            doi = doi[0] if doi else None
        if not doi:
            return None
        s = str(doi).lower().strip()
        s = re.sub(r'^https?://(dx\.)?doi\.org/', '', s)
        return s.rstrip('/') or None

    for cid, cit_entry in cit_map.items():
        articles = cit_entry.get("citing_articles", [])

        # Filtre min_citations
        if len(articles) < min_citations:
            continue

        # Métadonnées du dataset
        meta = _get_meta(doi_map.get(cid, {}))
        targets = meta.get("targets", [])
        if isinstance(targets, str):
            targets = [targets]

        # Filtre target
        if target_filter:
            if not any(target_filter.lower() in t.lower() for t in targets):
                continue

        doi = _get_doi(meta) or cit_entry.get("doi", "")
        label = meta.get("title") or cid

        G.add_node(cid,
            group        = "dataset",
            label        = label,
            doi          = doi,
            description  = meta.get("description", ""),
            product_name = meta.get("product_name", ""),
            proc_level   = meta.get("processing_level", "unknown"),
            targets      = ", ".join(targets),
            n_products   = meta.get("n_products") or "",
            n_citations  = len(articles),
        )

        for art in articles:
            title = art.get("title", "").strip()
            if not title:
                continue

            art_doi = _norm(art.get("doi"))
            authors = art.get("authors", [])
            if isinstance(authors, list):
                author_str = "; ".join(authors[:3])
                if len(authors) > 3:
                    author_str += " et al."
            else:
                author_str = str(authors)

            # Déduplication : même article cité par plusieurs datasets
            if art_doi and art_doi in article_index:
                node_id = article_index[art_doi]
            else:
                node_id = art_doi or title  # fallback sur le titre si pas de DOI
                article_index[art_doi or title] = node_id

                sources = art.get("sources", [])
                if isinstance(sources, set):
                    sources = list(sources)

                G.add_node(node_id,
                    group    = "article",
                    label    = title[:60],
                    title    = title,
                    doi      = art_doi or "",
                    authors  = author_str,
                    year     = art.get("year") or "",
                    abstract = art.get("abstract", ""),
                    sources  = ", ".join(sources),
                )

            if not G.has_edge(cid, node_id):
                G.add_edge(cid, node_id)

    return G

############################################################################
# Statistiques
############################################################################

def print_stats(G: nx.DiGraph):
    datasets = [n for n, d in G.nodes(data=True) if d.get("group") == "dataset"]
    articles = [n for n, d in G.nodes(data=True) if d.get("group") == "article"]

    print(f"Datasets     : {len(datasets)}")
    print(f"Articles     : {len(articles)}")
    print(f"Liens        : {G.number_of_edges()}")

    # Top datasets par citations
    top = sorted(datasets, key=lambda n: G.nodes[n].get("n_citations", 0), reverse=True)[:10]
    print("\nTop datasets par citations :")
    for n in top:
        d = G.nodes[n]
        print(f"  {d.get('n_citations'):4d}  {n}  [{d.get('proc_level')}]")

    # Articles cités par plusieurs datasets
    multi = [(n, G.in_degree(n)) for n in articles if G.in_degree(n) > 1]
    multi.sort(key=lambda x: x[1], reverse=True)
    if multi:
        print(f"\nArticles citant plusieurs datasets (top 5) :")
        for n, deg in multi[:5]:
            title = G.nodes[n].get("title", n)[:70]
            print(f"  {deg} datasets  {title}")

############################################################################
# Export HTML vis.js
############################################################################

def export_html(G: nx.DiGraph, output: str):
    COLOR = {
        "dataset": "#e07b39",
        "article": "#4a90d9",
    }
    SIZE = {
        "dataset": 20,
        "article": 10,
    }

    nodes_data = []
    for node_id, attr in G.nodes(data=True):
        group  = attr.get("group", "article")
        proc   = attr.get("proc_level", "")
        color  = COLOR.get(group, "#aaa")

        # Datasets : taille proportionnelle aux citations
        n_cit = attr.get("n_citations", 0)
        size  = SIZE.get(group, 10)
        if group == "dataset" and n_cit:
            size = max(14, min(40, 14 + n_cit // 5))

        # Tooltip HTML affiché dans le panel latéral
        if group == "dataset":
            panel_html = f"""
<b>{attr.get('label', node_id)}</b><br>
<small style="color:#888">{attr.get('proc_level','').upper()} · {attr.get('targets','')} · {attr.get('n_products','')} produits</small><br><br>
<b>DOI :</b> <a href="https://doi.org/{attr.get('doi','')}" target="_blank">{attr.get('doi','')}</a><br><br>
<b>Dataset :</b> {attr.get('product_name','')}<br><br>
<b>Description :</b><br>{attr.get('description','') or '—'}<br><br>
<b>Citations :</b> {attr.get('n_citations', 0)}
"""
        else:
            panel_html = f"""
<b>{attr.get('title', node_id)}</b><br>
<small style="color:#888">{attr.get('year','')} · {attr.get('authors','')}</small><br><br>
<b>DOI :</b> <a href="https://doi.org/{attr.get('doi','')}" target="_blank">{attr.get('doi','')}</a><br><br>
<b>Sources :</b> {attr.get('sources','')}<br><br>
<b>Abstract :</b><br>{attr.get('abstract','') or '—'}
"""

        nodes_data.append({
            "id":        node_id,
            "label":     (attr.get("label") or node_id)[:35],
            "color":     color,
            "size":      size,
            "group":     group,
            "panelHtml": panel_html.strip(),
        })

    edges_data = [{"from": u, "to": v} for u, v in G.edges()]

    nodes_json = json.dumps(nodes_data, ensure_ascii=False)
    edges_json = json.dumps(edges_data, ensure_ascii=False)

    n_datasets = sum(1 for d in nodes_data if d["group"] == "dataset")
    n_articles = sum(1 for d in nodes_data if d["group"] == "article")

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>Dataset → Articles</title>
  <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{ height: 100%; font-family: system-ui, sans-serif; overflow: hidden; background: #f0f2f5; }}

    #topbar {{
      display: flex; align-items: center; gap: 20px;
      padding: 8px 16px; background: #1a1a2e; color: #eee; font-size: 13px;
    }}
    #topbar h1 {{ font-size: 15px; font-weight: 600; color: #fff; margin-right: 8px; }}
    .stat {{ color: #aaa; }}
    .stat b {{ color: #fff; }}

    #legend {{ display: flex; gap: 16px; margin-left: auto; }}
    .leg {{ display: flex; align-items: center; gap: 6px; font-size: 12px; }}
    .dot {{ width: 11px; height: 11px; border-radius: 50%; }}

    #search {{
      padding: 4px 10px; border-radius: 4px; border: none;
      background: #2d2d44; color: #eee; font-size: 13px; width: 200px;
    }}

    #main {{ display: flex; height: calc(100% - 40px); }}

    #graph-container {{ flex: 1; height: 100%; }}

    #panel {{
      width: 340px; min-width: 280px; height: 100%;
      overflow-y: auto; background: #fff;
      border-left: 1px solid #ddd; padding: 20px; font-size: 13px;
    }}
    #panel h2 {{ font-size: 14px; color: #1a1a2e; margin-bottom: 6px; line-height: 1.4; }}
    #panel .meta {{ color: #888; font-size: 11px; margin-bottom: 14px; }}
    #panel .body {{ color: #444; line-height: 1.7; }}
    #panel a {{ color: #4a90d9; }}

    #panel-placeholder {{ color: #aaa; font-size: 13px; margin-top: 40px; text-align: center; }}
  </style>
</head>
<body>

<div id="topbar">
  <h1>Dataset → Articles citants</h1>
  <span class="stat"><b>{n_datasets}</b> datasets</span>
  <span class="stat"><b>{n_articles}</b> articles</span>
  <span class="stat"><b>{G.number_of_edges()}</b> liens</span>
  <input id="search" type="text" placeholder="Rechercher un nœud…">
  <div id="legend">
    <div class="leg"><div class="dot" style="background:#e07b39"></div>Dataset</div>
    <div class="leg"><div class="dot" style="background:#4a90d9"></div>Article</div>
  </div>
</div>

<div id="main">
  <div id="graph-container"></div>
  <div id="panel">
    <div id="panel-placeholder">Cliquez sur un nœud<br>pour afficher ses détails</div>
    <div id="panel-content" style="display:none"></div>
  </div>
</div>

<script>
const nodesData = {nodes_json};
const edgesData = {edges_json};

const nodes = new vis.DataSet(nodesData);
const edges = new vis.DataSet(edgesData);

const net = new vis.Network(
  document.getElementById("graph-container"),
  {{ nodes, edges }},
  {{
    physics: {{
      solver: "forceAtlas2Based",
      forceAtlas2Based: {{
        gravitationalConstant: -80,
        centralGravity: 0.01,
        springLength: 120,
        springConstant: 0.06,
        damping: 0.4,
      }},
      stabilization: {{ iterations: 300 }},
    }},
    edges: {{
      arrows: {{ to: {{ enabled: true, scaleFactor: 0.4 }} }},
      color: {{ color: "#ccc", opacity: 0.6 }},
      smooth: {{ type: "continuous" }},
      width: 0.8,
    }},
    nodes: {{
      shape: "dot",
      font: {{ size: 11, color: "#333" }},
      borderWidth: 1.5,
    }},
    interaction: {{ hover: true, tooltipDelay: 200 }},
  }}
);

net.once("stabilizationIterationsDone", () => net.setOptions({{ physics: false }}));

net.on("click", (params) => {{
  if (!params.nodes.length) return;
  const node = nodes.get(params.nodes[0]);
  document.getElementById("panel-placeholder").style.display = "none";
  const content = document.getElementById("panel-content");
  content.style.display = "block";
  content.innerHTML = node.panelHtml;
}});

// Recherche
document.getElementById("search").addEventListener("input", function() {{
  const q = this.value.toLowerCase().trim();
  if (!q) {{ net.unselectAll(); return; }}
  const match = nodesData.filter(n => n.label.toLowerCase().includes(q) || n.id.toLowerCase().includes(q));
  if (match.length) {{
    net.selectNodes(match.map(n => n.id));
    net.focus(match[0].id, {{ scale: 1.2, animation: true }});
  }}
}});
</script>
</body>
</html>"""

    Path(output).write_text(html, encoding="utf-8")
    print(f"✔ graph -> {output}")

############################################################################
# CLI
############################################################################

def main():
    parser = argparse.ArgumentParser(description="Visualise le graphe dataset → articles citants")
    parser.add_argument("--doi", default="doi_by_collection.json")
    parser.add_argument("--cit", default="citing_articles.json")
    parser.add_argument("-o", "--output", default="docs/index.html")
    parser.add_argument("--min-citations", type=int, default=0,
                        help="Filtre les datasets avec moins de N citations")
    parser.add_argument("--targets", default=None,
                        help="Filtre par corps céleste (ex: Mars, Moon)")
    args = parser.parse_args()

    doi_map, cit_map = load_data(args.doi, args.cit)
    G = build_graph(doi_map, cit_map,
                    min_citations=args.min_citations,
                    target_filter=args.targets)
    print_stats(G)
    export_html(G, args.output)


if __name__ == "__main__":
    main()