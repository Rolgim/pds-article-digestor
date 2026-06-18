
## A tool to visualize articles based on NASA Planetary Data System (PDS)

### Workflow

```
scrape_doi.py                 →  doi_by_collection.json  {"cid": "10.XXX/YYY"}
       ↓
enrich_with_pds.py              →  datasets_enriched.json  {"cid": {"doi": "...", ...métadonnées PDS...}}
       ↓
add_citations.py     →  citing_articles.json    {"cid": {"doi": "...", ...métadonnées..., citing_articles: [...]}}
       ↓
graph_cli.py                    →  docs/index.html
```

### Codes

- `scrape_doi`: uses ODE STAC API to get the proper PDS page and scrap there the DOI of ODE datasets

- `enrich_with_pds`: uses the DOI to get the detailed PDS page, and scrape it

- `add_citation`: uses ADS and others APIs to find papers citing a datasets.

- `graph_cli`: generates a html page to visualize the datasets and citing articles
