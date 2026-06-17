"""
Transforme un graphe NetworkX en fichier HTML vis.js.
Responsabilités :
  - Sérialisation des nœuds/arêtes en JSON vis.js
  - Construction du panel HTML pour chaque nœud
  - Injection des données dans graph_template.html
"""

import json
from pathlib import Path

import networkx as nx

from graph_builder import (
    BODY_COLORS,
    BODY_DEFAULT,
    ARTICLE_COLOR,
)

TEMPLATE_PATH = Path(__file__).parent / "graph_template.html"

##############################################################################
# Panel HTML
##############################################################################

def _doi_link(doi: str) -> str:
    if not doi:
        return "-"
    return f'<a href="https://doi.org/{doi}" target="_blank">{doi}</a>'


def _dataset_panel(attr: dict) -> str:
    doi_link    = _doi_link(attr.get("doi", ""))
    node_color  = attr.get("node_color", BODY_DEFAULT)
    body        = attr.get("body", "Others")
    label       = attr.get("label", "")
    n_cit       = attr.get("n_citations", 0)
    desc        = attr.get("desc", "")
    extra       = attr.get("extra", [])   # list[tuple[str, str]]

    extra_rows = "".join(
        f'<tr><td class="pk">{k}</td><td>{v}</td></tr>'
        for k, v in extra
    )
    extra_table = f'<table class="ph-table">{extra_rows}</table>' if extra_rows else ""
    desc_block  = f'<div class="ph-desc">{desc}</div>' if desc else ""

    return f"""
<div class="ph-type dataset">Dataset</div>
<div class="ph-title">{label}</div>
<div class="ph-body">
  <span class="ph-dot" style="background:{node_color}"></span>{body}
</div>
<div class="ph-section">
  <div class="ph-row"><span class="ph-key">DOI</span><span class="ph-val">{doi_link}</span></div>
  <div class="ph-row"><span class="ph-key">Citations</span><span class="ph-val">{n_cit}</span></div>
</div>
{desc_block}
{extra_table}
""".strip()


def _article_panel(attr: dict) -> str:
    doi_link    = _doi_link(attr.get("doi", ""))
    title       = attr.get("label", "")
    year        = attr.get("year", "")
    authors     = attr.get("authors", "")
    sources     = attr.get("sources", "")
    abstract    = attr.get("abstract", "—")
    abstract_tr = abstract[:800] + ("…" if len(abstract) > 800 else "")

    return f"""
<div class="ph-type article">Citation</div>
<div class="ph-title">{title}</div>
<div class="ph-meta">{year} · {authors}</div>
<div class="ph-section">
  <div class="ph-row"><span class="ph-key">DOI</span><span class="ph-val">{doi_link}</span></div>
  <div class="ph-row"><span class="ph-key">Sources</span><span class="ph-val">{sources}</span></div>
</div>
<div class="ph-abstract">{abstract_tr}</div>
""".strip()

##############################################################################
# Sérialisation vis.js
##############################################################################

def _build_nodes_edges(G: nx.DiGraph) -> tuple[list[dict], list[dict]]:
    nodes_data: list[dict] = []

    for node_id, attr in G.nodes(data=True):
        node_group = attr.get("nodeGroup", "article")

        if node_group == "dataset":
            bg = attr.get("node_color", BODY_DEFAULT)
            nodes_data.append({
                "id":        node_id,
                "label":     (attr.get("label") or node_id)[:35],
                "color": {
                    "background": bg,
                    "border":     "#ffffff44",
                    "highlight":  {"background": bg, "border": "#fff"},
                    "hover":      {"background": bg, "border": "#fff"},
                },
                "size":      attr.get("size", 18),
                "nodeGroup": "dataset",
                "body":      attr.get("body", "others").lower(),
                "hidden":    False,
                "panelHtml": _dataset_panel(attr),
            })
        else:
            nodes_data.append({
                "id":        node_id,
                "label":     (attr.get("label") or node_id)[:35],
                "color": {
                    "background": ARTICLE_COLOR,
                    "border":     "#2a5a9a",
                    "highlight":  {"background": "#6aaaf0", "border": "#fff"},
                    "hover":      {"background": "#6aaaf0", "border": "#fff"},
                },
                "size":      8,
                "nodeGroup": "article",
                "hidden":    True,
                "panelHtml": _article_panel(attr),
            })

    edges_data = [{"from": u, "to": v, "hidden": True} for u, v in G.edges()]
    return nodes_data, edges_data


def _build_legend() -> list[dict]:
    items = [{"label": k.capitalize(), "color": v} for k, v in BODY_COLORS.items()]
    items.append({"label": "Others",   "color": BODY_DEFAULT})
    items.append({"label": "Citation", "color": ARTICLE_COLOR})
    return items

##############################################################################
# Export HTML
##############################################################################

def export_html(G: nx.DiGraph, output: str) -> None:
    nodes_data, edges_data = _build_nodes_edges(G)
    legend_items = _build_legend()

    n_datasets = sum(1 for d in nodes_data if d["nodeGroup"] == "dataset")
    n_articles = sum(1 for d in nodes_data if d["nodeGroup"] == "article")
    n_edges    = G.number_of_edges()

    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    html = (template
        .replace("%%NODES_JSON%%",      json.dumps(nodes_data,   ensure_ascii=False))
        .replace("%%EDGES_JSON%%",      json.dumps(edges_data,   ensure_ascii=False))
        .replace("%%LEGEND_JSON%%",     json.dumps(legend_items, ensure_ascii=False))
        .replace("%%N_DATASETS%%",      str(n_datasets))
        .replace("%%N_ARTICLES%%",      str(n_articles))
        .replace("%%N_EDGES%%",         str(n_edges))
        .replace("%%N_DATASETS_TOTAL%%", str(n_datasets))
    )

    Path(output).write_text(html, encoding="utf-8")
    print(f"[OK] graph -> {output}")