"""
Construit et visualise le graphe dataset → articles citants.

Source :
  - citing_articles.json : métadonnées + articles citant chaque dataset

Usage :
    python graph_viz.py
    python graph_viz.py --cit citing_articles.json -o graph.html
    python graph_viz.py --min-citations 2
    python graph_viz.py --targets Mars
"""

import argparse
import json
import re
from pathlib import Path

import networkx as nx

Path("docs").mkdir(exist_ok=True)

############################################################################
# Couleurs
############################################################################

BODY_COLORS = {
    "mercury": "#BDA266",
    "venus":   "#F5EB27",
    "moon":    "#c0bdb8",
    "mars":    "#c1440e",
}
BODY_DEFAULT  = "#EDEDED"
ARTICLE_COLOR = "#4a90d9"

############################################################################
# Détection des corps célestes
############################################################################

_BODY_KEYWORDS = {
    "mercury": ["mercury"],
    "venus":   ["venus"],
    "earth":   ["earth"],
    "moon":    ["moon", "lunar"],
    "mars":    ["mars"],
}

def _find_body_in_meta(meta: dict, cid: str = "") -> list[str]:
    cid_lower = cid.lower()
    for body in _BODY_KEYWORDS:
        if cid_lower.startswith(body + "-") or f"-{body}-" in cid_lower:
            return [body]

    target_fields = [
        "target", "target_information",
        "name", "identifier",
        "mission_information", "investigation",
        "description",
    ]
    found = set()
    for field in target_fields:
        value = meta.get(field, "")
        if isinstance(value, list):
            value = " ".join(value)
        if not isinstance(value, str):
            continue
        value_lower = value.lower()
        for body, keywords in _BODY_KEYWORDS.items():
            for kw in keywords:
                if kw in value_lower:
                    found.add(body)

    return list(found)


def _body_color(meta: dict, cid: str = "") -> str:
    bodies = _find_body_in_meta(meta, cid)
    for body in bodies:
        if body in BODY_COLORS:
            return BODY_COLORS[body]
    return BODY_DEFAULT


def _body_label(meta: dict, cid: str = "") -> str:
    bodies = _find_body_in_meta(meta, cid)
    for body in bodies:
        if body in BODY_COLORS:
            return body.capitalize()
    return "Others"

############################################################################
# Helpers
############################################################################

def _get_doi(entry) -> str | None:
    if isinstance(entry, dict):
        return entry.get("doi")
    return entry or None


def _get_meta(entry) -> dict:
    if isinstance(entry, dict):
        return entry
    return {"doi": entry}


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

############################################################################
# Construction du graphe NetworkX
############################################################################

def build_graph(
    cit_map: dict,
    min_citations: int = 0,
    target_filter: str | None = None,
) -> nx.DiGraph:
    G = nx.DiGraph()
    article_index: dict[str, str] = {}

    for cid, cit_entry in cit_map.items():
        articles = cit_entry.get("citing_articles", [])

        if len(articles) < min_citations:
            continue

        meta = _get_meta(cit_entry)

        if target_filter:
            tf = target_filter.lower()
            bodies = _find_body_in_meta(meta, cid)
            if not any(tf in b for b in bodies):
                continue

        doi        = _get_doi(meta) or ""
        label      = meta.get("title") or meta.get("name") or cid
        node_color = _body_color(meta, cid)
        body       = _body_label(meta, cid)

        n_cit = len(articles)
        size  = max(14, min(44, 14 + n_cit // 3))

        doi_link = f'<a href="https://doi.org/{doi}" target="_blank">{doi}</a>' if doi else "—"

        skip_keys = {
            "doi", "citing_articles", "citing_count", "_status",
            "title", "name", "description", "data_set_abstract",
        }
        pds_fields_html = ""
        for k, v in meta.items():
            if k in skip_keys or not v:
                continue
            if isinstance(v, (dict, list)):
                continue
            label_k = k.replace("_", " ").capitalize()
            pds_fields_html += f'<tr><td class="pk">{label_k}</td><td>{v}</td></tr>'

        targets_str = ", ".join(_find_body_in_meta(meta, cid)) or "—"
        desc = meta.get("description") or meta.get("data_set_abstract") or ""

        panel_html = f"""
<div class="ph-type dataset">Dataset</div>
<div class="ph-title">{label}</div>
<div class="ph-body">
  <span class="ph-dot" style="background:{node_color}"></span>{body}
</div>
<div class="ph-section">
  <div class="ph-row"><span class="ph-key">DOI</span><span class="ph-val">{doi_link}</span></div>
  <div class="ph-row"><span class="ph-key">Citations</span><span class="ph-val">{n_cit}</span></div>
</div>
{f'<div class="ph-desc">{desc}</div>' if desc else ""}
{f'<table class="ph-table">{pds_fields_html}</table>' if pds_fields_html else ""}
""".strip()

        G.add_node(cid,
            nodeGroup   = "dataset",
            label       = label,
            doi         = doi,
            node_color  = node_color,
            body        = body,
            targets     = targets_str,
            n_citations = n_cit,
            size        = size,
            panelHtml   = panel_html,
        )

        for art in articles:
            title = art.get("title", "").strip()
            if not title:
                continue

            art_doi = _norm(art.get("doi"))
            authors = art.get("authors", [])
            author_str = (
                "; ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")
                if isinstance(authors, list) else str(authors)
            )
            year        = art.get("year") or ""
            sources     = art.get("sources", [])
            if isinstance(sources, set):
                sources = list(sources)
            sources_str = ", ".join(sorted(sources))
            abstract    = art.get("abstract", "") or "—"

            if art_doi and art_doi in article_index:
                node_id = article_index[art_doi]
            else:
                node_id = art_doi or title
                article_index[art_doi or title] = node_id

                art_doi_link = (
                    f'<a href="https://doi.org/{art_doi}" target="_blank">{art_doi}</a>'
                    if art_doi else "—"
                )
                art_panel = f"""
<div class="ph-type article">Citation</div>
<div class="ph-title">{title}</div>
<div class="ph-meta">{year} · {author_str}</div>
<div class="ph-section">
  <div class="ph-row"><span class="ph-key">DOI</span><span class="ph-val">{art_doi_link}</span></div>
  <div class="ph-row"><span class="ph-key">Sources</span><span class="ph-val">{sources_str}</span></div>
</div>
<div class="ph-abstract">{abstract[:800]}{"…" if len(abstract) > 800 else ""}</div>
""".strip()

                G.add_node(node_id,
                    nodeGroup = "article",
                    label     = title,
                    doi       = art_doi or "",
                    authors   = author_str,
                    year      = year,
                    abstract  = abstract,
                    sources   = sources_str,
                    panelHtml = art_panel,
                )

            if not G.has_edge(cid, node_id):
                G.add_edge(cid, node_id)

    return G

############################################################################
# Statistiques
############################################################################

def print_stats(G: nx.DiGraph):
    datasets = [n for n, d in G.nodes(data=True) if d.get("nodeGroup") == "dataset"]
    articles = [n for n, d in G.nodes(data=True) if d.get("nodeGroup") == "article"]
    print(f"Datasets : {len(datasets)}")
    print(f"Articles : {len(articles)}")
    print(f"Liens    : {G.number_of_edges()}")
    top = sorted(datasets, key=lambda n: G.nodes[n].get("n_citations", 0), reverse=True)[:10]
    print("\nTop datasets par citations :")
    for n in top:
        d = G.nodes[n]
        print(f"  {d.get('n_citations'):4d}  {n}  [{d.get('body')}]")

############################################################################
# Export HTML vis.js
############################################################################

def export_html(G: nx.DiGraph, output: str):

    nodes_data = []
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
                "panelHtml": attr.get("panelHtml", ""),
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
                "panelHtml": attr.get("panelHtml", ""),
            })

    edges_data = [{"from": u, "to": v, "hidden": True} for u, v in G.edges()]

    legend_items = [{"label": k.capitalize(), "color": v} for k, v in BODY_COLORS.items()]
    legend_items.append({"label": "Others",   "color": BODY_DEFAULT})
    legend_items.append({"label": "Citation", "color": ARTICLE_COLOR})

    n_datasets = sum(1 for d in nodes_data if d["nodeGroup"] == "dataset")
    n_articles = sum(1 for d in nodes_data if d["nodeGroup"] == "article")

    nodes_json  = json.dumps(nodes_data, ensure_ascii=False)
    edges_json  = json.dumps(edges_data, ensure_ascii=False)
    legend_json = json.dumps(legend_items, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>Planetary Datasets & Citations</title>
  <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{
      height: 100%; font-family: 'Inter', system-ui, sans-serif;
      overflow: hidden; background: #1a1d26; color: #e0e2e9;
    }}

    /* ── Loading overlay ── */
    #loading-overlay {{
      position: fixed; inset: 0; z-index: 100;
      background: #1a1d26;
      display: flex; flex-direction: column;
      align-items: center; justify-content: center;
      gap: 16px;
    }}
    .spinner {{
      width: 36px; height: 36px; border-radius: 50%;
      border: 3px solid #2a2d36;
      border-top-color: #5d9cec;
      animation: spin 0.8s linear infinite;
    }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    .loading-text {{ color: #8a94a6; font-size: 12px; letter-spacing: .03em; }}

    /* ── Topbar ── */
    #topbar {{
      display: flex; align-items: center; gap: 18px;
      height: 44px; padding: 0 18px;
      background: #222831; border-bottom: 1px solid #333;
      font-size: 12px; color: #b0b8c3; flex-shrink: 0;
    }}
    #topbar h1 {{
      font-size: 13px; font-weight: 600; color: #f0f2f5;
      letter-spacing: .03em; margin-right: 4px;
    }}
    .stat b {{ color: #f0f2f5; }}
    #search {{
      margin-left: auto;
      padding: 5px 11px; border-radius: 5px;
      border: 1px solid #3a3f4a; background: #2a2d36;
      color: #e0e2e9; font-size: 12px; width: 190px; outline: none;
    }}
    #search:focus {{ border-color: #5d9cec; }}
    #search.has-results {{ border-color: #5d9cec; }}
    #search.no-results  {{ border-color: #c1440e; }}

    /* ── expand/collapse ── */
    .tb-btn {{
      align: right;
      padding: 3px 10px; border-radius: 4px; font-size: 11px;
      border: 1px solid #3a3f4a; background: #2a2d36;
      color: #b0b8c3; cursor: pointer; transition: background 0.15s;
      user-select: none;
    }}
    .tb-btn:hover {{ background: #333a4a; color: #e0e2e9; }}

    /* ── Legend ── */
    #legend {{
      display: flex; gap: 14px; align-items: center;
      padding: 0 18px; height: 32px;
      background: #222831; border-bottom: 1px solid #333;
      font-size: 11px; color: #b0b8c3; flex-shrink: 0;
    }}
    .leg {{
      display: flex; align-items: center; gap: 5px;
      cursor: pointer; border-radius: 4px;
      padding: 2px 6px; transition: opacity 0.2s;
      user-select: none;
    }}
    .leg:last-child {{ cursor: default; }}
    .leg:not(:last-child):hover {{ background: #2a2d36; }}
    .leg-dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
    .leg-active {{ outline: 1px solid #fff4; background: #2a2d36; }}

    /* ── Layout ── */
    #main {{ display: flex; height: calc(100% - 76px); }}
    #graph-container {{ flex: 1; height: 100%; }}

    /* ── Panel ── */
    #panel {{
      width: 320px; min-width: 280px; height: 100%;
      overflow-y: auto; background: #222831;
      border-left: 1px solid #333; padding: 22px 18px;
      font-size: 12px; line-height: 1.6;
    }}
    #panel-placeholder {{
      color: #8a94a6; font-size: 12px;
      margin-top: 60px; text-align: center; line-height: 2;
    }}
    #panel-placeholder svg {{
      opacity: .4; margin-bottom: 10px;
      display: block; margin-inline: auto;
    }}

    /* ── Panel components ── */
    .ph-type {{
      font-size: 9px; font-weight: 700; letter-spacing: .12em;
      padding: 2px 7px; border-radius: 3px; display: inline-block;
      margin-bottom: 8px;
    }}
    .ph-type.dataset {{ background: #E74C3C; color: #f0f2f5; }}
    .ph-type.article {{ background: #2E86C1; color: #f0f2f5; }}
    .ph-title {{
      font-size: 14px; font-weight: 600; color: #f0f2f5;
      margin-bottom: 8px; line-height: 1.4;
    }}
    .ph-meta {{ color: #8a94a6; font-size: 11px; margin-bottom: 12px; }}
    .ph-body {{
      display: flex; align-items: center; gap: 6px;
      font-size: 11px; color: #b0b8c3; margin-bottom: 14px;
    }}
    .ph-dot {{ width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }}
    .ph-section {{
      margin-bottom: 14px; border-top: 1px solid #3a3f4a; padding-top: 12px;
    }}
    .ph-row {{ display: flex; gap: 8px; margin-bottom: 6px; align-items: baseline; }}
    .ph-key {{
      color: #8a94a6; font-size: 10px; text-transform: uppercase;
      letter-spacing: .06em; min-width: 80px; flex-shrink: 0;
    }}
    .ph-val {{ color: #e0e2e9; font-size: 12px; }}
    .ph-val a {{ color: #5d9cec; text-decoration: none; }}
    .ph-val a:hover {{ text-decoration: underline; }}
    .ph-desc {{
      font-size: 11px; color: #8a94a6; line-height: 1.7;
      margin-bottom: 14px; border-top: 1px solid #3a3f4a; padding-top: 12px;
    }}
    .ph-table {{
      width: 100%; border-collapse: collapse;
      margin-bottom: 14px; border-top: 1px solid #3a3f4a;
    }}
    .ph-table td {{ padding: 3px 0; font-size: 11px; vertical-align: top; }}
    .pk {{
      color: #8a94a6; text-transform: uppercase; font-size: 10px;
      letter-spacing: .05em; min-width: 110px; padding-right: 8px;
    }}
    .ph-abstract {{
      font-size: 11px; color: #a0a8b3; line-height: 1.7;
      border-top: 1px solid #3a3f4a; padding-top: 12px; margin-top: 4px;
    }}
  </style>
</head>
<body>

<div id="loading-overlay">
  <div class="spinner"></div>
  <div class="loading-text">Computing graph…</div>
</div>

<div id="topbar">
  <h1>Planetary Datasets &amp; Citations</h1>
  <span class="stat"><b>{n_datasets}</b> datasets</span>
  <span class="stat"><b>{n_articles}</b> citations</span>
  <span class="stat"><b>{G.number_of_edges()}</b> relationships</span>
  <input id="search" type="text" placeholder="Search…">
</div>

<div id="legend">
  <button class="tb-btn" id="btn-expand">Expand</button>
  <button class="tb-btn" id="btn-collapse">Collapse</button>
</div>

<div id="main">
  <div id="graph-container"></div>
  <div id="panel">
    <div id="panel-placeholder">
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" stroke-width="1.5">
        <circle cx="12" cy="12" r="10"/><path d="M12 8v4m0 4h.01"/>
      </svg>
      Click on a dataset<br>to explore its citations
    </div>
    <div id="panel-content" style="display:none"></div>
  </div>
</div>

<script>
const LEGEND    = {legend_json};
const allNodes  = {nodes_json};
const allEdges  = {edges_json};
const N_DATASETS_TOTAL = {n_datasets};

// ── Index pré-calculés ──────────────────────────────────────────────────

const nodesByBody = {{}};
const allDatasetIds = [];
const allArticleIds = [];
// articleId -> [datasetId, ...]
const parentsOf = {{}};


allNodes.forEach(n => {{
  if (n.nodeGroup === "dataset") {{
    allDatasetIds.push(n.id);
    const b = (n.body || "others").toLowerCase();
    if (!nodesByBody[b]) nodesByBody[b] = [];
    nodesByBody[b].push(n.id);
  }} else {{
    allArticleIds.push(n.id);
  }}
}});

// dataset -> [article ids]  +  article -> [dataset ids]
const childrenOf = {{}};
allEdges.forEach(e => {{
  if (!childrenOf[e.from]) childrenOf[e.from] = [];
  childrenOf[e.from].push(e.to);
  if (!parentsOf[e.to]) parentsOf[e.to] = [];
  parentsOf[e.to].push(e.from);
}});

// ── Légende ────────────────────────────────────────────────────────────

const legendEl = document.getElementById("legend");
let activeFilter = null;

LEGEND.forEach(item => {{
  const div = document.createElement("div");
  div.className = "leg";
  div.dataset.body = item.label.toLowerCase();

  const dot = document.createElement("div");
  dot.className = "leg-dot";
  dot.style.background = item.color;
  if (item.label === "Citation") dot.style.border = "1px solid #2a5a9a";

  const lbl = document.createElement("span");
  lbl.textContent = item.label;
  div.appendChild(dot);
  div.appendChild(lbl);

  if (item.label !== "Citation") {{
    div.addEventListener("click", () => {{
      const body = div.dataset.body;

      if (openDataset) {{ hideChildren(openDataset); openDataset = null; }}
      if (openArticle) {{ hideArticleParents(openArticle); openArticle = null; }}

      if (activeFilter === body) {{
        activeFilter = null;
        nodes.update(allDatasetIds.map(id => ({{ id, hidden: false }})));
        legendEl.querySelectorAll(".leg").forEach(l => {{
          l.style.opacity = "1";
          l.classList.remove("leg-active");
        }});
        updateCounter(N_DATASETS_TOTAL);
      }} else {{
        activeFilter = body;
        const matchSet = new Set(nodesByBody[body] || []);
        nodes.update(allDatasetIds.map(id => ({{ id, hidden: !matchSet.has(id) }})));
        legendEl.querySelectorAll(".leg").forEach(l => {{
          const isActive = l.dataset.body === body;
          l.style.opacity = isActive ? "1" : "0.3";
          l.classList.toggle("leg-active", isActive);
        }});
        updateCounter(matchSet.size);
      }}
    }});
  }}

  legendEl.appendChild(div);
}});

// ── vis.js ─────────────────────────────────────────────────────────────

const nodes = new vis.DataSet(allNodes);
const edges = new vis.DataSet(allEdges);

const net = new vis.Network(
  document.getElementById("graph-container"),
  {{ nodes, edges }},
  {{
    physics: {{
      solver: "forceAtlas2Based",
      forceAtlas2Based: {{
        gravitationalConstant: -100,
        centralGravity: 0.01,
        springLength: 140,
        springConstant: 0.05,
        damping: 0.4,
      }},
      stabilization: {{ iterations: 400 }},
    }},
    edges: {{
      arrows: {{ to: {{ enabled: true, scaleFactor: 0.35 }} }},
      color: {{ color: "#5a6a8a", opacity: 0.9 }},
      smooth: {{ type: "continuous" }},
      width: 1.2,
    }},
    nodes: {{
      shape: "dot",
      font: {{ size: 12, color: "#e0e2e9" }},
      borderWidth: 2,
    }},
    interaction: {{ hover: true, tooltipDelay: 150 }},
  }}
);

// ── Loading overlay ─────────────────────────────────────────────────────

net.on("stabilizationProgress", (params) => {{
  const pct = Math.round(params.iterations / params.total * 100);
  document.querySelector(".loading-text").textContent = `Computing graph… ${{pct}}%`;
}});

net.once("stabilizationIterationsDone", () => {{
  net.setOptions({{ physics: false }});
  const overlay = document.getElementById("loading-overlay");
  overlay.style.transition = "opacity 0.4s";
  overlay.style.opacity = "0";
  setTimeout(() => overlay.remove(), 400);
}});

// ── État ───────────────────────────────────────────────────────────────

let openDataset = null;
let openArticle = null;
let allExpanded = false;

function showChildren(datasetId) {{
  const kids = childrenOf[datasetId] || [];
  const nodeUpdates = kids
    .filter(id => nodes.get(id) && nodes.get(id).hidden)
    .map(id => ({{ id, hidden: false }}));
  if (nodeUpdates.length) nodes.update(nodeUpdates);

  const edgeUpdates = [];
  edges.forEach(e => {{
    if (e.from === datasetId) edgeUpdates.push({{ id: e.id, hidden: false }});
  }});
  if (edgeUpdates.length) edges.update(edgeUpdates);
}}

function hideChildren(datasetId) {{
  const kids = childrenOf[datasetId] || [];
  const nodeUpdates = [];
  kids.forEach(articleId => {{
    const stillVisible = (parentsOf[articleId] || []).some(
      dsId => dsId !== datasetId && dsId === openDataset
    );
    if (!stillVisible) nodeUpdates.push({{ id: articleId, hidden: true }});
  }});
  if (nodeUpdates.length) nodes.update(nodeUpdates);

  const edgeUpdates = [];
  edges.forEach(e => {{
    if (e.from === datasetId) edgeUpdates.push({{ id: e.id, hidden: true }});
  }});
  if (edgeUpdates.length) edges.update(edgeUpdates);
}}

function showArticleParents(articleId) {{
  const edgeUpdates = [];
  edges.forEach(e => {{
    if (e.to === articleId) edgeUpdates.push({{ id: e.id, hidden: false }});
  }});
  if (edgeUpdates.length) edges.update(edgeUpdates);
}}

function hideArticleParents(articleId) {{
  const edgeUpdates = [];
  edges.forEach(e => {{
    if (e.to === articleId) edgeUpdates.push({{ id: e.id, hidden: true }});
  }});
  if (edgeUpdates.length) edges.update(edgeUpdates);
}}

// ── Tout déplier / replier ──────────────────────────────────────────────

document.getElementById("btn-expand").addEventListener("click", () => {{
  openDataset = null;
  openArticle = null;
  nodes.update(allArticleIds.map(id => ({{ id, hidden: false }})));
  edges.update(allEdges.map(e => ({{ id: e.id, hidden: false }})));
  allExpanded = true;
}});

document.getElementById("btn-collapse").addEventListener("click", () => {{
  openDataset = null;
  openArticle = null;
  nodes.update(allArticleIds.map(id => ({{ id, hidden: true }})));
  edges.update(allEdges.map(e => ({{ id: e.id, hidden: true }})));
  allExpanded = false;
}});

// ── Interactions ───────────────────────────────────────────────────────

net.on("click", (params) => {{
  if (!params.nodes.length) return;
  const nodeId = params.nodes[0];
  const node   = nodes.get(nodeId);

  document.getElementById("panel-placeholder").style.display = "none";
  const content = document.getElementById("panel-content");
  content.style.display = "block";
  content.innerHTML = node.panelHtml;

  if (node.nodeGroup === "dataset") {{
    if (openDataset === nodeId) {{
      hideChildren(nodeId);
      openDataset = null;
    }} else {{
      if (openDataset) hideChildren(openDataset);
      showChildren(nodeId);
      openDataset = nodeId;
    }}
  }} else if (node.nodeGroup === "article") {{
    if (openArticle === nodeId) {{
      hideArticleParents(nodeId);
      openArticle = null;
    }} else {{
      if (openArticle) hideArticleParents(openArticle);
      showArticleParents(nodeId);
      openArticle = nodeId;
    }}
  }}
}});

// ── Recherche (datasets + articles) ────────────────────────────────────

document.getElementById("search").addEventListener("input", function () {{
  const q = this.value.toLowerCase().trim();
  const searchEl = this;

  if (!q) {{
    net.unselectAll();
    searchEl.className = "";
    return;
  }}

  // Cherche dans datasets
  const dsMatch = allNodes.filter(n =>
    n.nodeGroup === "dataset" &&
    (n.label.toLowerCase().includes(q) || n.id.toLowerCase().includes(q))
  );

  // Cherche dans articles
  const artMatch = allNodes.filter(n =>
    n.nodeGroup === "article" &&
    n.label.toLowerCase().includes(q)
  );

  const totalMatch = [...dsMatch, ...artMatch];

  if (!totalMatch.length) {{
    net.unselectAll();
    searchEl.className = "no-results";
    return;
  }}

  searchEl.className = "has-results";

  // Révèle les articles matchés + leurs parents datasets
  if (artMatch.length) {{
    const articleIdsToShow = artMatch.map(n => n.id).filter(id => nodes.get(id).hidden);
    if (articleIdsToShow.length) nodes.update(articleIdsToShow.map(id => ({{ id, hidden: false }})));

    // Révèle les arêtes vers ces articles
    const edgeUpdates = [];
    edges.forEach(e => {{
      if (artMatch.some(n => n.id === e.to)) edgeUpdates.push({{ id: e.id, hidden: false }});
    }});
    if (edgeUpdates.length) edges.update(edgeUpdates);
  }}

  net.selectNodes(totalMatch.map(n => n.id));
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
    parser = argparse.ArgumentParser(
        description="Visualise le graphe dataset → articles citants"
    )
    parser.add_argument("--cit", default="citing_articles.json")
    parser.add_argument("-o", "--output", default="docs/index.html")
    parser.add_argument("--min-citations", type=int, default=0)
    parser.add_argument("--targets", default=None)
    args = parser.parse_args()

    cit_map = json.loads(Path(args.cit).read_text(encoding="utf-8"))
    G = build_graph(cit_map,
                    min_citations=args.min_citations,
                    target_filter=args.targets)
    print_stats(G)
    export_html(G, args.output)


if __name__ == "__main__":
    main()