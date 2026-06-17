"""
Point d'entrée CLI. Orchestre build_graph() et export_html().

Usage :
    python graph_cli.py
    python graph_cli.py --cit citing_articles.json -o docs/index.html
    python graph_cli.py --min-citations 2
    python graph_cli.py --targets Mars
"""

import argparse
import json
from pathlib import Path

from graph_builder  import build_graph, print_stats
from graph_renderer import export_html

Path("docs").mkdir(exist_ok=True)

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Visualise le graphe dataset -> articles citants"
    )
    parser.add_argument("--cit",           default="..docs/citing_articles.json")
    parser.add_argument("-o", "--output",  default="..docs/index.html")
    parser.add_argument("--min-citations", type=int, default=0)
    parser.add_argument("--targets",       default=None)
    args = parser.parse_args()

    cit_map = json.loads(Path(args.cit).read_text(encoding="utf-8"))

    G = build_graph(
        cit_map,
        min_citations=args.min_citations,
        target_filter=args.targets,
    )
    print_stats(G)
    export_html(G, args.output)


if __name__ == "__main__":
    main()