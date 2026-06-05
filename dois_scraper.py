"""
stac_doi_scraper.py

https://pds-geosciences.wustl.edu/dataserv/doi.htm

Récupère les DOI des collections STAC via les pages ODE.

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

MAX_CONCURRENT_REQUESTS = 10

_IDGEO_RE = re.compile(
    r"[?&]product_idGeo=(\d+)",
    re.IGNORECASE,
)

_DOI_RE = re.compile(
    r"10\.\d{4,9}/[^\s\"'<>&]+"
)

##############################################################################
# DOI CACHE
##############################################################################


def load_doi_cache():

    if DOI_FILE.exists():

        return json.loads(
            DOI_FILE.read_text(
                encoding="utf-8"
            )
        )

    return {}


def save_doi_cache(doi_map):

    DOI_FILE.write_text(
        json.dumps(
            doi_map,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


##############################################################################
# COLLECTIONS
##############################################################################


async def _fetch_collections(force_refresh=False):

    if not force_refresh:

        cached = load_collections()

        if cached:

            print(
                f"{len(cached)} collections chargées depuis cache"
            )

            return cached

    async with httpx.AsyncClient(timeout=30) as client:

        r = await client.get(
            f"{STAC_BASE}/collections"
        )

        raw = r.json()

    if isinstance(raw, list):
        cols = raw

    elif "collections" in raw:
        cols = raw["collections"]

    elif "features" in raw:
        cols = raw["features"]

    else:
        raise RuntimeError(
            f"Format inconnu : {raw.keys()}"
        )

    collections = [

        StacCollection(
            id=c["id"],
            description=c.get(
                "description",
                ""
            ),
            extent=c.get(
                "extent",
                {}
            ),
        )

        for c in cols

    ]

    save_collections(
        collections
    )

    print(
        f"{len(collections)} collections récupérées"
    )

    return collections


##############################################################################
# LANDING URL
##############################################################################

def _extract_landing_url(links):

    # 1. privilégier explicitement la landing page produit
    for link in links:

        title = link.get(
            "title",
            ""
        ).lower()

        href = link.get(
            "href",
            ""
        )

        if (
            "product landing page" in title
            and href.startswith("http")
        ):
            return href

    # 2. sinon un lien contenant product_idGeo
    for link in links:

        href = link.get(
            "href",
            ""
        )

        if (
            "product_idgeo="
            in href.lower()
        ):
            return href

    # 3. fallback ancien comportement
    valid_rels = {
        "landing_page",
        "alternate",
        "via",
        "about"
    }

    for link in links:

        rel = link.get(
            "rel",
            ""
        ).lower()

        href = link.get(
            "href",
            ""
        )

        if (
            rel in valid_rels
            and href.startswith("http")
        ):
            return href

    return None

async def _get_landing_url(
    client,
    collection_id,
    verbose=False,
):

    try:

        url = (
            f"{STAC_BASE}/collections/"
            f"{collection_id}/items"
        )

        r = await client.get(
            url,
            params={"limit": 1}
        )

        r.raise_for_status()

        data = r.json()

    except Exception as e:

        if verbose:

            print(
                f"{collection_id}: erreur items : {repr(e)}"
            )

        return None

    features = data.get(
        "features",
        []
    )

    if not features:

        if verbose:

            print(
                f"{collection_id}: aucun item"
            )

        return None

    item = features[0]

    #######################################################
    # 1) links
    #######################################################

    url = _extract_landing_url(

        item.get(
            "links",
            []
        )

    )
    print(url)

    if url:

        if verbose:

            print(
                f"{collection_id}: "
                f"landing link={url}"
            )

        return url

    #######################################################
    # 2) assets
    #######################################################

    assets = item.get(
        "assets",
        {}
    )

    for key, asset in assets.items():

        roles = {

            x.lower()

            for x in asset.get(
                "roles",
                []
            )
        }

        title = asset.get(
            "title",
            ""
        ).lower()

        href = asset.get(
            "href",
            ""
        )

        if not href.startswith(
            "http"
        ):
            continue

        if (

            "landing_page" in roles
            or "landing" in title
            or key.lower()
            in {
                "landing_page",
                "product_landing_page"
            }

        ):

            if verbose:

                print(
                    f"{collection_id}: "
                    f"landing asset={href}"
                )

            return href

    if verbose:

        print(
            f"{collection_id}: "
            f"pas de landing"
        )

    return None


##############################################################################
# DOI
##############################################################################


async def _get_doi_from_ode(
    client,
    collection_id,
    landing_url,
    verbose=False
):

    m = _IDGEO_RE.search(
        landing_url
    )

    if not m:

        return None

    product_idgeo = m.group(
        1
    )

    parsed = urlparse(
        landing_url
    )

    detail_url = (

        f"{parsed.scheme}://"
        f"{parsed.netloc}"
        f"{parsed.path.rsplit('/',1)[0]}"
        f"/productDetail.aspx"

    )

    params = {

        "product_idgeo":
        product_idgeo,

        "option":
        "hideResize"

    }

    ##################################################################
    # GET
    ##################################################################

    try:

        r = await client.get(
            detail_url,
            params=params
        )

    except Exception:

        return None

    soup = BeautifulSoup(
        r.text,
        "html.parser"
    )

    hidden = {}

    for inp in soup.select(
        "input[type=hidden]"
    ):

        name = inp.get(
            "name"
        )

        if not name:
            continue

        hidden[name] = inp.get(
            "value",
            ""
        )

    if "__VIEWSTATE" not in hidden:

        return None

    ##################################################################
    # POST
    ##################################################################

    payload = {

        **hidden,

        "__EVENTTARGET":
        "lblProdDescAndDataSetDocuments",

        "__EVENTARGUMENT":
        "",

        "product_idgeo":
        product_idgeo,

    }

    try:

        r2 = await client.post(
            detail_url,
            params=params,
            data=payload
        )

    except Exception:

        return None

    matches = _DOI_RE.findall(
        r2.text
    )

    if matches:

        doi = matches[0].rstrip(
            ".,;)"
        )

        if verbose:

            print(
                f"{collection_id}: DOI={doi}"
            )

        return doi

    return None


##############################################################################
# PIPELINE
##############################################################################


async def _scrape_doi_for_collection(
    client,
    collection_id,
    sem,
    verbose=False
):

    async with sem:

        print(
            f"Traitement: {collection_id}"
        )

        landing = await _get_landing_url(
            client,
            collection_id,
            verbose
        )

        if not landing:

            return (
                collection_id,
                None
            )

        doi = await _get_doi_from_ode(
            client,
            collection_id,
            landing,
            verbose
        )

        return (
            collection_id,
            doi
        )


##############################################################################
# MAIN
##############################################################################


async def scrape_dois(
    force_refresh=False,
    verbose=False
):

    collections = await _fetch_collections(
        force_refresh
    )

    doi_map = load_doi_cache()

    already_done = {

        cid

        for cid, doi
        in doi_map.items()

        if doi is not None
    }

    todo = [

        c

        for c in collections

        if c.id not in already_done
    ]

    print(
        f"\n{len(todo)} collections à traiter"
    )

    sem = asyncio.Semaphore(5)

    limits = httpx.Limits(
        max_connections=5,
        max_keepalive_connections=5
    )

    timeout = httpx.Timeout(
        connect=10.0,
        read=60.0,
        write=10.0,
        pool=10.0
    )

    async with httpx.AsyncClient(

        timeout=timeout,
        limits=limits,
        follow_redirects=True

    ) as client:

        tasks = [

            _scrape_doi_for_collection(
                client,
                c.id,
                sem,
                verbose
            )

            for c in todo

        ]

        completed = 0

        for task in asyncio.as_completed(
            tasks
        ):

            cid, doi = await task

            doi_map[cid] = doi

            completed += 1

            print(

                f"[{completed}/{len(todo)}] "
                f"{cid} -> "
                f"{doi if doi else 'NON TROUVÉ'}"

            )

            if completed % 20 == 0:

                save_doi_cache(
                    doi_map
                )

                print(
                    "Sauvegarde intermédiaire"
                )

    save_doi_cache(
        doi_map
    )

    found = sum(
        1
        for x in doi_map.values()
        if x
    )

    print(
        f"\nDOI trouvés: {found}/{len(doi_map)}"
    )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--refresh",
        action="store_true"
    )

    parser.add_argument(
        "--verbose",
        action="store_true"
    )

    args = parser.parse_args()

    asyncio.run(
        scrape_dois(
            args.refresh,
            args.verbose
        )
    )


if __name__ == "__main__":
    main()