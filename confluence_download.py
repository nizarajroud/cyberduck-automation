#!/usr/bin/env python3
"""
Usage:
    python confluence_download.py --page-id 9389103
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import requests

load_dotenv()

JSESSIONID          = os.environ.get("JSESSIONID", "")
CONFLUENCE_BASE_URL = os.environ.get("CONFLUENCE_BASE_URL", "")
CONFLUENCE_EXPORT_PATH = os.environ.get("CONFLUENCE_EXPORT_PATH", "exportword")

if not JSESSIONID or not CONFLUENCE_BASE_URL:
    sys.exit("[✗] JSESSIONID ou CONFLUENCE_BASE_URL manquant dans .env")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--page-id", required=True, help="ID de la page Confluence")
    parser.add_argument("--output-dir", default=".", help="Dossier de destination")
    args = parser.parse_args()

    url = f"{CONFLUENCE_BASE_URL}/{CONFLUENCE_EXPORT_PATH}?pageId={args.page_id}"

    session = requests.Session()
    session.verify = False
    session.cookies.set("JSESSIONID", JSESSIONID)
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    print(f"[→] Téléchargement : {url}")
    resp = session.get(url, timeout=30, stream=True)

    if resp.status_code == 401:
        sys.exit("[✗] 401 : JSESSIONID invalide ou expiré")
    if not resp.ok:
        sys.exit(f"[✗] Erreur HTTP {resp.status_code}")

    cd = resp.headers.get("Content-Disposition", "")
    filename = cd.split("filename=")[-1].strip().strip('"') if "filename=" in cd \
        else f"confluence_page_{args.page_id}.doc"

    output_path = Path(args.output_dir) / filename
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)

    print(f"[✓] Sauvegardé : {output_path}")


if __name__ == "__main__":
    main()
