stac_doi_scraper  →  doi_by_collection.json  {"cid": "10.XXX/YYY"}
       ↓
scrape_pds_info   →  datasets_enriched.json  {"cid": {"doi": "...", ...métadonnées PDS...}}
       ↓
ads_citations     →  citing_articles.json    {"cid": {"doi": "...", ...métadonnées..., citing_articles: [...]}}
       ↓
graph_viz         →  docs/index.html