"""
Construit le graphe NetworkX à partir de citing_articles.json.
Responsabilités :
  - Détection des corps célestes
  - Normalisation des DOI
  - Construction des nœuds dataset et article
  - Statistiques
"""

import re
import networkx as nx

##############################################################################
# Couleurs & mots-clés
##############################################################################

BODY_COLORS: dict[str, str] = {
    "mercury": "#BDA266",
    "venus":   "#F5EB27",
    "moon":    "#c0bdb8",
    "mars":    "#c1440e",
}
BODY_DEFAULT  = "#EDEDED"
ARTICLE_COLOR = "#4a90d9"

_BODY_KEYWORDS: dict[str, list[str]] = {
    "mercury": ["mercury"],
    "venus":   ["venus"],
    "earth":   ["earth"],
    "moon":    ["moon", "lunar"],
    "mars":    ["mars"],
}

_TARGET_FIELDS = [
    "target", "target_information",
    "name", "identifier",
    "mission_information", "investigation",
    "description",
]

_DATASET_SKIP_KEYS = {
    "doi", "citing_articles", "citing_count", "_status",
    "title", "name", "description", "data_set_abstract",
}

##############################################################################
# Détection des corps célestes
##############################################################################

def find_bodies(meta: dict, cid: str = "") -> list[str]:
    """
    Retourne la liste des corps célestes détectés.
    Priorité 1 : préfixe/segment du collection ID (mars-mex-..., moon-lro-...).
    Priorité 2 : champs textuels PDS4 + PDS3.
    """
    cid_lower = cid.lower()
    for body in _BODY_KEYWORDS:
        if cid_lower.startswith(body + "-") or f"-{body}-" in cid_lower:
            return [body]

    found: set[str] = set()
    for field in _TARGET_FIELDS:
        value = meta.get(field, "")
        if isinstance(value, list):
            value = " ".join(value)
        if not isinstance(value, str):
            continue
        value_lower = value.lower()
        for body, keywords in _BODY_KEYWORDS.items():
            if any(kw in value_lower for kw in keywords):
                found.add(body)

    return list(found)


def body_color(meta: dict, cid: str = "") -> str:
    bodies = find_bodies(meta, cid)
    return BODY_COLORS.get(bodies[0], BODY_DEFAULT) if bodies else BODY_DEFAULT


def body_label(meta: dict, cid: str = "") -> str:
    bodies = find_bodies(meta, cid)
    return bodies[0].capitalize() if bodies else "Others"

##############################################################################
# Helpers
##############################################################################

def _get_doi(entry: dict | str | None) -> str | None:
    if isinstance(entry, dict):
        return entry.get("doi")
    return entry or None


def _get_meta(entry: dict | str | None) -> dict:
    if isinstance(entry, dict):
        return entry
    return {"doi": entry}


def _norm_doi(doi) -> str | None:
    if not doi:
        return None
    if isinstance(doi, list):
        doi = doi[0] if doi else None
    if not doi:
        return None
    s = str(doi).lower().strip()
    s = re.sub(r'^https?://(dx\.)?doi\.org/', '', s)
    return s.rstrip('/') or None


def _author_str(authors) -> str:
    if not isinstance(authors, list):
        return str(authors)
    suffix = " et al." if len(authors) > 3 else ""
    return "; ".join(authors[:3]) + suffix


def _pds_extra_fields(meta: dict) -> list[tuple[str, str]]:
    """Retourne les champs PDS scrappés non réservés, sous forme (label, valeur)."""
    rows = []
    for k, v in meta.items():
        if k in _DATASET_SKIP_KEYS or not v:
            continue
        if isinstance(v, (dict, list)):
            continue
        rows.append((k.replace("_", " ").capitalize(), str(v)))
    return rows

##############################################################################
# Construction du graphe
##############################################################################

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
            bodies = find_bodies(meta, cid)
            if not any(target_filter.lower() in b for b in bodies):
                continue

        # Attributs dataset
        bodies      = find_bodies(meta, cid)
        doi         = _get_doi(meta) or ""
        label       = meta.get("title") or meta.get("name") or cid
        node_color  = BODY_COLORS.get(bodies[0], BODY_DEFAULT) if bodies else BODY_DEFAULT
        body        = bodies[0].capitalize() if bodies else "Others"
        n_cit       = len(articles)
        size        = max(14, min(44, 14 + n_cit // 3))
        targets_str = ", ".join(bodies) or "—"
        desc        = meta.get("description") or meta.get("data_set_abstract") or ""
        extra       = _pds_extra_fields(meta)

        G.add_node(cid,
            nodeGroup   = "dataset",
            label       = label,
            doi         = doi,
            node_color  = node_color,
            body        = body,
            targets     = targets_str,
            n_citations = n_cit,
            size        = size,
            desc        = desc,
            extra       = extra,   # list[tuple[str,str]] — rendu côté renderer
        )

        # Articles citants
        for art in articles:
            title = art.get("title", "").strip()
            if not title:
                continue

            art_doi     = _norm_doi(art.get("doi"))
            authors     = _author_str(art.get("authors", []))
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
                G.add_node(node_id,
                    nodeGroup = "article",
                    label     = title,
                    doi       = art_doi or "",
                    authors   = authors,
                    year      = year,
                    abstract  = abstract,
                    sources   = sources_str,
                )

            if not G.has_edge(cid, node_id):
                G.add_edge(cid, node_id)

    return G

##############################################################################
# Statistiques
##############################################################################

def print_stats(G: nx.DiGraph) -> None:
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