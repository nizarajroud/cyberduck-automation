#!/usr/bin/env python3
"""
Usage:
    python confluence_download.py --url "https://confluence.int.beneva.ca/exportword?pageId=9389103"
"""

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv
import requests

load_dotenv()

JSESSIONID = os.environ.get("JSESSIONID", "")
if not JSESSIONID:
    sys.exit("[✗] JSESSIONID manquant dans .env")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="URL à télécharger")
    parser.add_argument("--output-dir", default=".", help="Dossier de destination")
    args = parser.parse_args()

    session = requests.Session()
    session.verify = False
    session.cookies.set("JSESSIONID", JSESSIONID)
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    print(f"[→] Téléchargement : {args.url}")
    resp = session.get(args.url, timeout=30, stream=True)

    if resp.status_code == 401:
        sys.exit("[✗] 401 : JSESSIONID invalide ou expiré")
    if not resp.ok:
        sys.exit(f"[✗] Erreur HTTP {resp.status_code}")

    # Nom du fichier depuis Content-Disposition ou URL
    cd = resp.headers.get("Content-Disposition", "")
    if "filename=" in cd:
        filename = cd.split("filename=")[-1].strip().strip('"')
    else:
        params = parse_qs(urlparse(args.url).query)
        page_id = params.get("pageId", ["unknown"])[0]
        filename = f"confluence_page_{page_id}.doc"

    output_path = Path(args.output_dir) / filename
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)

    print(f"[✓] Sauvegardé : {output_path}")


if __name__ == "__main__":
    main()
