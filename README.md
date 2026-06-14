
## A tool to visualize articles based on NASA Planetary Data System (PDS)

```
dois_scraper.py                 →  doi_by_collection.json  {"cid": "10.XXX/YYY"}
       ↓
scrape_pds_info.py              →  datasets_enriched.json  {"cid": {"doi": "...", ...métadonnées PDS...}}
       ↓
downstream_science_paper.py     →  citing_articles.json    {"cid": {"doi": "...", ...métadonnées..., citing_articles: [...]}}
       ↓
graph_vis.py                    →  docs/index.html
```

- dois_scraper: uses ODE STAC API to get the proper PDS page and scrap there the DOI of ODE datasets

- scrape_pds_info: uses the DOI to get the detailed PDS page, and scrape it

- downstream_science_paper: uses ADS and others APIs to find papers citing a datasets.

- graph_vis: generates a html page to visualize the datasets and citing articles