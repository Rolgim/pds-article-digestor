"""
stac_doi_scraper.py

Récupère les DOI des collections STAC via deux sources :
  1. ODE (ode.rsl.wustl.edu) — productDetail.aspx + UpdatePanel postback
  2. Fallback : https://pds-geosciences.wustl.edu/dataserv/doi.htm
     via le champ pds:dataset_id de chaque collection

Usage :
    python stac_doi_scraper.py
    python stac_doi_scraper.py --refresh
    python stac_doi_scraper.py --verbose
"""

import argparse
import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from stac_rag_ingest import (
    STAC_BASE,
    StacCollection,
    load_collections,
    save_collections,
)

##############################################################################
# CONFIG
##############################################################################

DOI_FILE = Path("doi_by_collection.json")
PDS_DOI_PAGE = "https://pds-geosciences.wustl.edu/dataserv/doi.htm"

MAX_CONCURRENT = 5

_IDGEO_RE = re.compile(r"[?&]product_idGeo=(\d+)", re.IGNORECASE)
_DOI_RE    = re.compile(r"10\.\d{4,9}/[^\s\"'<>&]+")
_LID_RE    = re.compile(r"urn:nasa:pds:([\w_]+)")

##############################################################################
# DOI CACHE
##############################################################################

def load_doi_cache() -> dict:
    if DOI_FILE.exists():
        return json.loads(DOI_FILE.read_text(encoding="utf-8"))
    return {}

def save_doi_cache(doi_map: dict):
    DOI_FILE.write_text(
        json.dumps(doi_map, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

##############################################################################
# COLLECTIONS
##############################################################################

async def _fetch_collections(force_refresh=False) -> list[StacCollection]:
    if not force_refresh:
        cached = load_collections()
        if cached:
            print(f"{len(cached)} collections chargées depuis cache")
            return cached

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{STAC_BASE}/collections")
        raw = r.json()

    if isinstance(raw, list):
        cols = raw
    elif "collections" in raw:
        cols = raw["collections"]
    elif "features" in raw:
        cols = raw["features"]
    else:
        raise RuntimeError(f"Format inconnu : {list(raw.keys())}")

    collections = [
        StacCollection(
            id=c["id"],
            description=c.get("description", ""),
            extent=c.get("extent", {}),
        )
        for c in cols
    ]
    save_collections(collections)
    print(f"{len(collections)} collections récupérées")
    return collections

##############################################################################
# PDS DOI PAGE FALLBACK
##############################################################################

# Regex PDS3 dataset ID : ex. MEX-M-MARSIS-3-RDR-SS-V2.0
_PDS3_RE = re.compile(r"[A-Z0-9]+-[A-Z]-[A-Z0-9/_-]+-V\d+\.\d+", re.IGNORECASE)


async def _fetch_pds_doi_page() -> dict[str, str]:
    """
    Scrape https://pds-geosciences.wustl.edu/dataserv/doi.htm
    Retourne un dict avec deux types de clés :
      - LID PDS4 suffix  : "mex_marsis_optim"     -> "10.17189/..."
      - Dataset ID PDS3  : "MEX-M-MARSIS-3-RDR-SS-V2.0" -> "10.17189/..."
    """
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.get(PDS_DOI_PAGE)

    soup = BeautifulSoup(r.text, "html.parser")
    result: dict[str, str] = {}

    for elem in soup.find_all(["tr", "li", "p", "td"]):
        text = elem.get_text(" ", strip=True)
        m_doi = _DOI_RE.search(text)
        if not m_doi:
            continue
        doi = m_doi.group(0).rstrip(".,;)")

        # PDS4 LID
        m_lid = _LID_RE.search(text)
        if m_lid:
            result[m_lid.group(1)] = doi

        # PDS3 dataset IDs (peut y en avoir plusieurs dans la cellule)
        for m_pds3 in _PDS3_RE.finditer(text):
            result[m_pds3.group(0).upper()] = doi

    print(f"{len(result)} DOI chargés depuis pds-geosciences.wustl.edu")
    return result


def _normalize_dataset_id(dataset_id: str) -> str:
    """
    Extrait le premier dataset ID PDS3 ou PDS4 d'une chaîne qui peut
    contenir du texte parasite : "MEX-M-MARSIS-3-RDR-SS-V2.0 (and all ...)"
    → "MEX-M-MARSIS-3-RDR-SS-V2.0"
    """
    # Coupe au premier espace ou parenthèse
    return re.split(r"[\s(]", dataset_id.strip())[0].upper()


def _match_pds_doi(dataset_id: str, pds_dois: dict[str, str]) -> str | None:
    """
    Match entre pds:dataset_id de la collection et les clés du dict PDS.
    1. Exact (après normalisation)
    2. Préfixe : la clé PDS est un préfixe du dataset_id (troncature page)
    3. Préfixe inverse : dataset_id est préfixe de la clé PDS
    """
    if not dataset_id:
        return None

    norm = _normalize_dataset_id(dataset_id)

    # 1. Exact
    if norm in pds_dois:
        return pds_dois[norm]

    # 2 & 3. Préfixe dans les deux sens
    for key, doi in pds_dois.items():
        key_up = key.upper()
        if norm.startswith(key_up) or key_up.startswith(norm):
            return doi

    return None


async def _get_pds_dataset_id(
    client: httpx.AsyncClient,
    collection_id: str,
) -> str | None:
    """Fetch pds:dataset_id depuis les métadonnées de la collection STAC."""
    try:
        r = await client.get(f"{STAC_BASE}/collections/{collection_id}")
        r.raise_for_status()
        return r.json().get("pds:dataset_id")
    except Exception:
        return None

##############################################################################
# LANDING URL
##############################################################################

def _extract_landing_url(links: list) -> str | None:
    # 1. titre explicitement "product landing page"
    for link in links:
        if (
            "product landing page" in link.get("title", "").lower()
            and link.get("href", "").startswith("http")
        ):
            return link["href"]

    # 2. href contient product_idGeo
    for link in links:
        href = link.get("href", "")
        if "product_idgeo=" in href.lower():
            return href

    # 3. rels standard
    for link in links:
        if (
            link.get("rel", "").lower() in {"about", "landing_page", "alternate", "via"}
            and link.get("href", "").startswith("http")
        ):
            return link["href"]

    return None


async def _get_landing_url(
    client: httpx.AsyncClient,
    collection_id: str,
    verbose: bool = False,
) -> str | None:
    try:
        r = await client.get(
            f"{STAC_BASE}/collections/{collection_id}/items",
            params={"limit": 1},
        )
        r.raise_for_status()
        features = r.json().get("features", [])
    except Exception as e:
        if verbose:
            print(f"{collection_id}: erreur items : {repr(e)}")
        return None

    if not features:
        if verbose:
            print(f"{collection_id}: aucun item")
        return None

    item = features[0]

    url = _extract_landing_url(item.get("links", []))
    if url:
        if verbose:
            print(f"{collection_id}: landing link={url}")
        return url

    for key, asset in item.get("assets", {}).items():
        roles = {x.lower() for x in asset.get("roles", [])}
        href  = asset.get("href", "")
        if not href.startswith("http"):
            continue
        if (
            "landing_page" in roles
            or "landing" in asset.get("title", "").lower()
            or key.lower() in {"landing_page", "product_landing_page"}
        ):
            if verbose:
                print(f"{collection_id}: landing asset={href}")
            return href

    if verbose:
        print(f"{collection_id}: pas de landing")
    return None

##############################################################################
# DOI VIA ODE
##############################################################################

async def _get_doi_from_ode(
    collection_id: str,
    landing_url: str,
    verbose: bool = False,
) -> str | None:
    """
    Client dédié par appel pour éviter les conflits de cookies entre
    requêtes concurrentes (le __VIEWSTATE est lié à la session serveur).
    """
    m = _IDGEO_RE.search(landing_url)
    if not m:
        return None

    product_idgeo = m.group(1)
    parsed = urlparse(landing_url)
    detail_url = (
        f"{parsed.scheme}://{parsed.netloc}"
        f"{parsed.path.rsplit('/', 1)[0]}/productDetail.aspx"
    )
    params = {"product_idgeo": product_idgeo, "option": "hideResize"}

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as ode:
        # GET : récupère le viewstate lié à cette session
        try:
            r1 = await ode.get(detail_url, params=params)
        except Exception:
            return None

        soup = BeautifulSoup(r1.text, "html.parser")
        hidden = {
            inp["name"]: inp.get("value", "")
            for inp in soup.select("input[type=hidden]")
            if inp.get("name")
        }
        if "__VIEWSTATE" not in hidden:
            return None

        # POST : UpdatePanel ASP.NET
        payload = {
            **hidden,
            "ScriptManager1": "UpdatePanel2|lblProdDescAndDataSetDocuments",
            "__EVENTTARGET": "lblProdDescAndDataSetDocuments",
            "__EVENTARGUMENT": "",
            "__ASYNCPOST": "true",
            "txtScrollLeft": "0",
            "txtScrollTop": "0",
        }
        try:
            r2 = await ode.post(
                detail_url,
                params=params,
                data=payload,
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "X-MicrosoftAjax": "Delta=true",
                    "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                },
            )
        except Exception:
            return None

    matches = _DOI_RE.findall(r2.text)
    if matches:
        doi = matches[0].rstrip(".,;)")
        if verbose:
            print(f"{collection_id}: ODE -> {doi}")
        return doi

    return None

##############################################################################
# PIPELINE PAR COLLECTION
##############################################################################

async def _get_doi_from_datacite(
    dataset_id: str,
    verbose: bool = False,
    collection_id: str = "",
) -> str | None:
    """
    3e fallback : DataCite API.
    Cherche sur le nom de base du dataset (sans version ni EXT).
    Ex: "MEX-M-MARSIS-3-RDR-SS-V2.0 (and all...)" -> "MEX-M-MARSIS-3-RDR-SS"
    Retourne le DOI du premier résultat (souvent une extension du dataset).
    """
    base = re.split(r"[\s(]", dataset_id.strip())[0]
    base = re.sub(r"-V\d+\.\d+$", "", base)
    base = re.sub(r"-EXT\w+$", "", base, flags=re.IGNORECASE)

    if not base:
        return None

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as dc:
            r = await dc.get(
                "https://api.datacite.org/dois",
                params={"query": base, "page[size]": 1},
            )
        results = r.json().get("data", [])
        if results:
            doi = results[0]["id"]
            if verbose:
                print(f"{collection_id}: DataCite -> {doi}")
            return doi
    except Exception:
        pass

    return None


async def _scrape_doi_for_collection(
    client: httpx.AsyncClient,
    collection_id: str,
    pds_dois: dict[str, str],
    sem: asyncio.Semaphore,
    verbose: bool = False,
) -> tuple[str, str | None]:

    async with sem:
        # --- Source 1 : ODE ---
        landing = await _get_landing_url(client, collection_id, verbose)
        doi = None

        if landing:
            doi = await _get_doi_from_ode(collection_id, landing, verbose)

        # --- Sources 2 & 3 : PDS page puis DataCite ---
        if not doi:
            dataset_id = await _get_pds_dataset_id(client, collection_id)
            if dataset_id:
                # Source 2 : page PDS Geosciences
                if pds_dois:
                    doi = _match_pds_doi(dataset_id, pds_dois)
                    if doi and verbose:
                        print(f"{collection_id}: PDS page -> {doi}")

                # Source 3 : DataCite
                if not doi:
                    doi = await _get_doi_from_datacite(dataset_id, verbose, collection_id)

        return collection_id, doi

##############################################################################
# MAIN
##############################################################################

async def scrape_dois(force_refresh=False, verbose=False):
    collections = await _fetch_collections(force_refresh)
    pds_dois    = await _fetch_pds_doi_page()
    doi_map     = load_doi_cache()

    already_done = {cid for cid, doi in doi_map.items() if doi is not None}
    todo = [c for c in collections if c.id not in already_done]
    print(f"\n{len(todo)} collections à traiter ({len(already_done)} déjà en cache)")

    sem = asyncio.Semaphore(MAX_CONCURRENT)
    limits  = httpx.Limits(max_connections=MAX_CONCURRENT, max_keepalive_connections=MAX_CONCURRENT)
    timeout = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)

    async with httpx.AsyncClient(timeout=timeout, limits=limits, follow_redirects=True) as client:
        tasks = [
            _scrape_doi_for_collection(client, c.id, pds_dois, sem, verbose)
            for c in todo
        ]

        completed = 0
        for coro in asyncio.as_completed(tasks):
            cid, doi = await coro
            doi_map[cid] = doi
            completed += 1
            status = doi if doi else "NON TROUVÉ"
            print(f"[{completed}/{len(todo)}] {cid} -> {status}")

            if completed % 20 == 0:
                save_doi_cache(doi_map)
                print("Sauvegarde intermédiaire")

    save_doi_cache(doi_map)
    found = sum(1 for x in doi_map.values() if x)
    print(f"\nDOI trouvés : {found}/{len(doi_map)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    asyncio.run(scrape_dois(args.refresh, args.verbose))


if __name__ == "__main__":
    main()