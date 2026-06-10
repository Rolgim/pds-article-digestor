
# A tool to visualize articles based on NASA Planetary Data System (PDS) Datasets

```
dois_scraper.py                 →  doi_by_collection.json  {"cid": "10.XXX/YYY"}
       ↓
scrape_pds_info.py              →  datasets_enriched.json  {"cid": {"doi": "...", ...métadonnées PDS...}}
       ↓
downstream_science_paper.py     →  citing_articles.json    {"cid": {"doi": "...", ...métadonnées..., citing_articles: [...]}}
       ↓
graph_vis.py                    →  docs/index.html
```