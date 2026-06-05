import os
import json
import httpx

ADS_TOKEN = os.environ["ADS_TOKEN"]

client = httpx.Client(
    headers={"Authorization": f"Bearer {ADS_TOKEN}"},
    timeout=30.0
)

###########################################################
# 1. PARSING PDS                                         ##
###########################################################

def parse_pds_key(key: str):
    """
    moon-lro-lola-rdr
    mars-mro-hirise-edr
    venus-mgn-rdrs-gsdr
    """

    parts = key.split("-")

    if len(parts) < 3:
        return None

    return {
        "body": parts[0],
        "mission": parts[1],
        "instrument": parts[2],
        "product": "-".join(parts[3:]) if len(parts) > 3 else None,
        "raw": key
    }


def build_dataset_index(pds_json):
    index = {}

    for key, doi in pds_json.items():
        parsed = parse_pds_key(key)
        if not parsed:
            continue

        index[key] = {
            "doi": doi,
            **parsed
        }

    return index


###########################################################
# 2. ADS HELPERS                                         ##
###########################################################

def norm(x):
    if x is None:
        return ""
    if isinstance(x, list):
        return " ".join(map(str, x))
    return str(x)


def doi_to_bibcode(doi):
    if not doi:
        return None

    r = client.get(
        "https://api.adsabs.harvard.edu/v1/search/query",
        params={
            "q": f"doi:{doi}",
            "fl": "bibcode,title,author,year,abstract,doi",
            "rows": 1,
        },
    )

    docs = r.json()["response"]["docs"]
    return docs[0] if docs else None


def get_citations(bibcode):
    if not bibcode:
        return []

    r = client.get(
        "https://api.adsabs.harvard.edu/v1/search/query",
        params={
            "q": f"citations(bibcode:{bibcode})",
            "fl": "bibcode,title,author,year,abstract,doi",
            "rows": 200,
        },
    )

    return r.json()["response"]["docs"]


###########################################################
# 3. GRAPH BUILDER                                      ###
###########################################################

def build_graph(pds_json):

    index = build_dataset_index(pds_json)
    graph = {}

    for dataset, meta in index.items():

        doi = meta["doi"]

        source = doi_to_bibcode(doi)

        # source enrichment
        if source:
            title = norm(source.get("title"))
            abstract = norm(source.get("abstract"))

            source_text = f"{title} {abstract}"
        else:
            title = ""
            abstract = ""
            source_text = ""

        # instrument is deterministic (IMPORTANT FIX)
        instrument_tags = [meta["instrument"]]

        # citations
        citations = get_citations(source["bibcode"] if source else None)

        downstream = []

        for c in citations:

            c_title = norm(c.get("title"))
            c_abstract = norm(c.get("abstract"))

            downstream.append({
                "bibcode": c.get("bibcode"),
                "title": c_title,
                "author": norm(c.get("author")),
                "year": c.get("year"),
                "abstract": c.get("abstract"),
                "doi": c.get("doi"),
                "instrument_tags": instrument_tags,  # propagation simple
            })

        # node assembly
        graph[dataset] = {
            "doi": doi,
            "pds": meta,

            "source": {
                "bibcode": source.get("bibcode") if source else None,
                "title": title,
                "abstract": abstract,
                "year": source.get("year") if source else None,
                "doi": source.get("doi") if source else doi,
                "instrument_tags": instrument_tags,
            },

            "downstream_science": downstream
        }

    return graph


###########################################################
# 4. CLI
###########################################################

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("input_json")
    parser.add_argument("-o", "--output", default="graph.json")

    args = parser.parse_args()

    with open(args.input_json, "r") as f:
        pds_json = json.load(f)

    graph = build_graph(pds_json)

    with open(args.output, "w") as f:
        json.dump(graph, f, indent=2)

    print("✔ graph written →", args.output)