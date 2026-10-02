"""
Genera la dashboard statica per GitHub Pages.

Produce due file in docs/:
  * index.html — pagina autosufficiente: i dati sono incorporati come JSON, i grafici
    (Plotly) sono interattivi e la pagina si apre anche da file locale;
  * data.json  — lo stesso payload, riutilizzabile da altri client.

La logica numerica sta in dashboard_data.py / metrics.py, il markup in
scripts/templates/dashboard.html.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dashboard_data import build_payload
from price_history import load_price_history

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")


def _render(payload: dict) -> str:
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()
    # "</" dentro <script> chiuderebbe il tag: va escapato.
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", r"<\/")
    return template.replace("__DATA__", data)


def build_html(
    portfolios: dict, signals: dict | None = None, live_prices: dict | None = None
) -> str:
    """HTML completo della dashboard multi-portafoglio (live_prices opzionale)."""
    payload = build_payload(portfolios, signals, load_price_history(), live_prices)
    return _render(payload)


def write_dashboard(portfolios: dict, signals: dict | None = None, docs_dir: str = DOCS_DIR) -> str:
    """Scrive docs/index.html e docs/data.json. Ritorna il percorso di index.html."""
    payload = build_payload(portfolios, signals, load_price_history())
    os.makedirs(docs_dir, exist_ok=True)
    html_path = os.path.join(docs_dir, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(_render(payload))
    with open(os.path.join(docs_dir, "data.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    return html_path
