"""
ads_citations.py
----------------
Récupère les articles citant chaque dataset STAC depuis 3 sources :
  1. NASA ADS   — référence en planétologie/astronomie
  2. OpenAlex   — couverture large toutes disciplines, open
  3. Crossref Event Data — citations inter-éditeurs

Résultat : citing_articles.json
{
  "collection-id": {
    "doi": "10.XXXX/YYYY",
    "citing_count": 42,
    "citing_articles": [
      {
        "title": "...", "authors": [...], "year": 2023,
        "doi": "10.XXX/YYY", "abstract": "...",
        "sources": ["ads", "openalex"]
      }, ...
    ]
  }
}

Usage :
    export ADS_TOKEN="..."
    python ads_citations.py
    python ads_citations.py --refresh
    python ads_citations.py --verbose
"""

import argparse
import asyncio
import json
import os
import re
from pathlib import Path
import urllib.parse
import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DOI_FILE    = Path("doi_by_collection.json")
OUTPUT_FILE = Path("citing_articles.json")

ADS_BASE      = "https://api.adsabs.harvard.edu/v1/search/query"
OA_BASE       = "https://api.openalex.org"
CR_EVENTS_BASE = "https://api.eventdata.crossref.org/v1/events"

MAX_CONCURRENT = 3
ADS_DELAY   = 0.2   # ~5 req/s
OA_DELAY    = 0.1   # ~10 req/s (polite pool)
CR_DELAY    = 0.1

ADS_PAGE    = 200   # max par page ADS
OA_PAGE     = 200   # max par page OpenAlex
CR_PAGE     = 1000

# ---------------------------------------------------------------------------
# Normalisation DOI
# ---------------------------------------------------------------------------
def _norm_doi(doi) -> str | None:
    if not doi:
        return None

    if isinstance(doi, list):
        doi = doi[0] if doi else None
    if not doi:
        return None

    doi = str(doi)

    doi = urllib.parse.unquote(doi)

    doi = doi.lower().strip()
    doi = re.sub(r'^https?://(dx\.)?doi\.org/', '', doi)
    doi = doi.rstrip('/')

    doi = doi.replace("\r", "").replace("\n", "")

    return doi or None


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

def _make_clients(token: str):
    ads = httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0, follow_redirects=True,
    )
    oa = httpx.AsyncClient(
        headers={"User-Agent": "article-digestor/1.0 (mailto:your@email.com)"},
        timeout=30.0, follow_redirects=True,
    )
    cr = httpx.AsyncClient(
        headers={"User-Agent": "article-digestor/1.0"},
        timeout=30.0, follow_redirects=True,
    )
    return ads, oa, cr

# ---------------------------------------------------------------------------
# ADS — pagination complète
# ---------------------------------------------------------------------------

async def _fetch_ads(
    client: httpx.AsyncClient,
    doi: str,
    lock: asyncio.Lock,
    verbose: bool,
    cid: str,
) -> list[dict]:
    articles, start = [], 0

    while True:
        async with lock:
            await asyncio.sleep(ADS_DELAY)
            try:
                r = await client.get(ADS_BASE, params={
                    "q":     f'references(doi:"{doi}")',
                    "fl":    "bibcode,title,author,year,doi,abstract",
                    "rows":  ADS_PAGE,
                    "start": start,
                    "sort":  "year desc",
                })
                r.raise_for_status()
            except Exception as e:
                if verbose:
                    print(f"    [ADS] {cid} erreur: {e}")
                break

        resp  = r.json()["response"]
        docs  = resp["docs"]
        total = resp["numFound"]
        articles.extend(docs)

        if verbose and start == 0:
            print(f"    [ADS] {cid}: {total} articles")

        if len(articles) >= total or not docs:
            break
        start += ADS_PAGE

    result = []
    for d in articles:
        title = d.get("title", "")
        if isinstance(title, list):
            title = title[0] if title else ""
        result.append({
            "title":    title,
            "authors":  d.get("author", []),
            "year":     d.get("year"),
            "doi":      _norm_doi(d.get("doi")),
            "abstract": d.get("abstract", ""),
            "bibcode":  d.get("bibcode"),
            "_source":  "ads",
        })
    return result

# ---------------------------------------------------------------------------
# OpenAlex — résolution DOI → ID puis cites:ID, cursor pagination
# ---------------------------------------------------------------------------

async def _fetch_openalex(
    client: httpx.AsyncClient,
    doi: str,
    lock: asyncio.Lock,
    verbose: bool,
    cid: str,
) -> list[dict]:

    # Étape 1 : résoudre le DOI en OpenAlex ID
    async with lock:
        await asyncio.sleep(OA_DELAY)
        try:
            r = await client.get(f"{OA_BASE}/works/https://doi.org/{doi}")
            r.raise_for_status()
            oa_id = r.json().get("id")  # ex: "https://openalex.org/W1234"
        except Exception:
            return []

    if not oa_id:
        return []

    # Étape 2 : articles qui citent cet OA ID — cursor pagination
    articles = []
    cursor = "*"

    while cursor:
        async with lock:
            await asyncio.sleep(OA_DELAY)
            try:
                r = await client.get(f"{OA_BASE}/works", params={
                    "filter":   f"cites:{oa_id}",
                    "per-page": OA_PAGE,
                    "cursor":   cursor,
                    "select":   "id,title,authorships,publication_year,doi,abstract_inverted_index",
                })
                r.raise_for_status()
            except Exception as e:
                if verbose:
                    print(f"    [OA] {cid} erreur: {e}")
                break

        data    = r.json()
        meta    = data.get("meta", {})
        results = data.get("results", [])
        total   = meta.get("count", 0)
        articles.extend(results)

        if verbose and not articles[len(results):]:  # premier tour
            print(f"    [OA] {cid}: {total} articles")

        cursor = meta.get("next_cursor")
        if not results:
            break

    out = []
    for w in articles:
        authors = [
            a["author"].get("display_name", "")
            for a in w.get("authorships", [])
        ]
        # abstract depuis inverted index
        inv = w.get("abstract_inverted_index") or {}
        if inv:
            words = [""] * (max(max(v) for v in inv.values()) + 1)
            for word, positions in inv.items():
                for p in positions:
                    words[p] = word
            abstract = " ".join(words)
        else:
            abstract = ""

        out.append({
            "title":      w.get("title", ""),
            "authors":    authors,
            "year":       w.get("publication_year"),
            "doi":        _norm_doi(w.get("doi")),
            "abstract":   abstract,
            "openalex_id": w.get("id"),
            "_source":    "openalex",
        })
    return out

# ---------------------------------------------------------------------------
# Crossref Event Data
# ---------------------------------------------------------------------------

async def _fetch_crossref_events(
    client: httpx.AsyncClient,
    doi: str,
    lock: asyncio.Lock,
    verbose: bool,
    cid: str,
) -> list[dict]:
    """
    Crossref Event Data indexe les citations entre éditeurs.
    Retourne des métadonnées légères (pas d'abstract).
    """
    articles = []
    cursor = None

    while True:
        params = {
            "obj-id":       f"https://doi.org/{doi}",
            "relation-type": "cites",
            "rows":         CR_PAGE,
        }
        if cursor:
            params["cursor"] = cursor

        async with lock:
            await asyncio.sleep(CR_DELAY)
            try:
                r = await client.get(CR_EVENTS_BASE, params=params)
                r.raise_for_status()
            except Exception as e:
                if verbose:
                    print(f"    [CR] {cid} erreur: {e}")
                break

        data   = r.json()
        events = data.get("message", {}).get("events", [])
        total  = data.get("message", {}).get("total-results", 0)
        articles.extend(events)

        if verbose and not articles[len(events):]:
            print(f"    [CR] {cid}: {total} events")

        cursor = data.get("message", {}).get("next-cursor")
        if not events or not cursor:
            break

    out = []
    for ev in articles:
        subj = ev.get("subj", {})
        doi_val = _norm_doi(subj.get("alternative-id") or subj.get("url", ""))
        out.append({
            "title":   subj.get("title", ""),
            "authors": [],
            "year":    (lambda s: int(s) if s.isdigit() else None)(ev.get("occurred_at", "")[:4]),
            "doi":     doi_val,
            "abstract": "",
            "_source": "crossref_events",
        })
    return out

# ---------------------------------------------------------------------------
# Fusion + déduplication
# ---------------------------------------------------------------------------

def _merge_articles(sources: list[list[dict]]) -> list[dict]:
    """
    Fusionne les résultats de plusieurs sources.
    Déduplique sur le DOI normalisé (si dispo) ou (titre, année).
    Merge les champs source quand un article est trouvé plusieurs fois.
    """
    seen: dict[str, dict] = {}   # clé -> article fusionné

    for batch in sources:
        for art in batch:
            src = art.pop("_source", "unknown")

            doi = art.get("doi")
            title = (art.get("title") or "").lower().strip()
            year  = art.get("year")

            key = doi if doi else f"{title}|{year}"
            if not key:
                continue

            if key in seen:
                seen[key]["sources"].add(src)
                # enrichit les champs vides
                for field in ("abstract", "authors", "bibcode", "openalex_id"):
                    if not seen[key].get(field) and art.get(field):
                        seen[key][field] = art[field]
            else:
                art["sources"] = {src}
                seen[key] = art

    # Convertit les sets en listes pour la sérialisation JSON
    result = []
    for art in seen.values():
        art["sources"] = sorted(art["sources"])
        result.append(art)

    result.sort(key=lambda x: int(x.get("year") or 0), reverse=True)
    return result

# ---------------------------------------------------------------------------
# Pipeline par collection
# ---------------------------------------------------------------------------

async def _process_collection(
    ads_client: httpx.AsyncClient,
    oa_client:  httpx.AsyncClient,
    cr_client:  httpx.AsyncClient,
    collection_id: str,
    doi: str,
    sem: asyncio.Semaphore,
    ads_lock: asyncio.Lock,
    oa_lock:  asyncio.Lock,
    cr_lock:  asyncio.Lock,
    verbose: bool,
) -> tuple[str, dict]:

    async with sem:
        if verbose:
            print(f"\n→ {collection_id} ({doi})")

        ads_arts, oa_arts, cr_arts = await asyncio.gather(
            _fetch_ads(ads_client, doi, ads_lock, verbose, collection_id),
            _fetch_openalex(oa_client, doi, oa_lock, verbose, collection_id),
            _fetch_crossref_events(cr_client, doi, cr_lock, verbose, collection_id),
        )

        merged = _merge_articles([ads_arts, oa_arts, cr_arts])

        return collection_id, {
            "doi": doi,
            "citing_count": len(merged),
            "citing_articles": merged,
            "_status": "done"
        }

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def load_output() -> dict:
    if OUTPUT_FILE.exists():
        return json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    return {}

def save_output(data: dict):
    OUTPUT_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run(force_refresh: bool, verbose: bool):
    token = os.environ.get("ADS_TOKEN")
    if not token:
        raise SystemExit(
            "ADS_TOKEN non défini.\n"
            "Créez un token sur https://ui.adsabs.harvard.edu/user/settings/token"
        )

    raw_map = json.loads(DOI_FILE.read_text(encoding="utf-8"))
    # Supporte l'ancien format {"cid": "doi"} et le nouveau {"cid": {"doi": "...", ...}}
    collections_with_doi = {}
    for k, v in raw_map.items():
        doi = v.get("doi") if isinstance(v, dict) else v
        if doi:
            collections_with_doi[k] = doi
    print(f"{len(collections_with_doi)} collections avec DOI")

    results      = {} if force_refresh else load_output()
    already_done = set(results.keys())
    todo = {k: v for k, v in collections_with_doi.items() if k not in already_done}
    print(f"{len(todo)} collections à traiter ({len(already_done)} déjà en cache)")

    if not todo:
        print("Rien à faire.")
        return

    sem      = asyncio.Semaphore(MAX_CONCURRENT)
    ads_lock = asyncio.Lock()
    oa_lock  = asyncio.Lock()
    cr_lock  = asyncio.Lock()

    ads_client, oa_client, cr_client = _make_clients(token)

    for cid in todo.keys():
        if cid not in results:
            results[cid] = {
                "doi": collections_with_doi[cid],
                "citing_count": 0,
                "citing_articles": [],
                "_status": "pending"
            }

    async with ads_client, oa_client, cr_client:
        tasks = [
            _process_collection(
                ads_client, oa_client, cr_client,
                cid, doi, sem,
                ads_lock, oa_lock, cr_lock,
                verbose,
            )
            for cid, doi in todo.items()
        ]

        completed = 0
        for coro in asyncio.as_completed(tasks):
            cid, result = await coro
            results[cid] = result
            completed += 1
            n = result["citing_count"]
            print(f"[{completed}/{len(todo)}] {cid} -> {n} article{'s' if n != 1 else ''}")

            if completed % 30 == 0:
                save_output(results)
                print("Sauvegarde intermédiaire")

    save_output(results)

    total   = sum(r["citing_count"] for r in results.values())
    nonzero = sum(1 for r in results.values() if r["citing_count"] > 0)
    print(f"\n=== Résumé ===")
    print(f"  Collections avec ≥1 article : {nonzero}/{len(results)}")
    print(f"  Total articles (dédupliqués) : {total}")
    print(f"  Résultat -> {OUTPUT_FILE}")


def main():
    parser = argparse.ArgumentParser(
        description="Récupère les articles citant les datasets STAC (ADS + OpenAlex + Crossref)"
    )
    parser.add_argument("--refresh", action="store_true", help="Ignore le cache")
    parser.add_argument("--verbose", action="store_true", help="Détails par collection")
    args = parser.parse_args()
    asyncio.run(run(args.refresh, args.verbose))


if __name__ == "__main__":
    main()