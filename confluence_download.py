#!/usr/bin/env python3
"""
Usage:
    python confluence_download.py --page-id 9389103
    python confluence_download.py --page-id 9389103 --s3-bucket mon-bucket
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from bs4 import BeautifulSoup
from dotenv import load_dotenv
import requests
import urllib3

load_dotenv()
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

JSESSIONID             = os.environ.get("JSESSIONID", "")
CONFLUENCE_BASE_URL    = os.environ.get("CONFLUENCE_BASE_URL", "")
CONFLUENCE_EXPORT_PATH = os.environ.get("CONFLUENCE_EXPORT_PATH", "exportword")
S3_BUCKET              = os.environ.get("S3_BUCKET", "")
S3_PREFIX              = os.environ.get("S3_PREFIX", "confluence/")
CONFLUENCE_DOWNLOAD_DIR = os.environ.get("CONFLUENCE_DOWNLOAD_DIR", ".")

if not JSESSIONID or not CONFLUENCE_BASE_URL:
    sys.exit("[✗] JSESSIONID ou CONFLUENCE_BASE_URL manquant dans .env")


def extract_title(content: bytes) -> str:
    """Extrait le premier texte en gras du document (HTML déguisé en .doc)."""
    soup = BeautifulSoup(content, "html.parser")
    bold = soup.find(["b", "strong"]) or soup.find("p", style=lambda s: s and "bold" in s)
    if bold:
        return bold.get_text(strip=True)
    title = soup.find("title")
    return title.get_text(strip=True) if title else ""


def safe_filename(title: str, page_id: str) -> str:
    """Construit un nom de fichier propre : titre - id.doc"""
    clean = "".join(c if c.isalnum() or c in " -_" else " " for c in title).strip()
    clean = " ".join(clean.split())  # collapse spaces
    return f"{clean} - {page_id}.doc" if clean else f"{page_id}.doc"


(local_path: Path, s3_bucket: str, s3_key: str):
    s3_url = f"s3://{s3_bucket}/{s3_key}"
    print(f"[→] Upload vers S3 : {local_path.name} → {s3_url}")

    cmd = ["aws", "s3", "cp", str(local_path), s3_url, "--profile", "cyberduck-sso"]

    try:
        subprocess.run(cmd, check=True)
        print(f"[✓] Upload réussi : {local_path.name}")
    except subprocess.CalledProcessError as e:
        sys.exit(f"[✗] Erreur aws s3 cp (exit {e.returncode})")
    except FileNotFoundError:
        sys.exit("[✗] 'aws' CLI introuvable.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("page_id", help="ID de la page Confluence")
    parser.add_argument("--s3-bucket", default=S3_BUCKET or None, help="Nom du bucket S3 (optionnel)")
    parser.add_argument("--output-dir", default=CONFLUENCE_DOWNLOAD_DIR, help="Dossier de destination")
    args = parser.parse_args()

    url = f"{CONFLUENCE_BASE_URL}/{CONFLUENCE_EXPORT_PATH}?pageId={args.page_id}"
    session = requests.Session()
    session.verify = False
    session.cookies.set("JSESSIONID", JSESSIONID)
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    print(f"[→] Téléchargement : {url}")
    resp = session.get(url, timeout=30)

    if resp.status_code == 401:
        sys.exit("[✗] 401 : JSESSIONID invalide ou expiré")
    if not resp.ok:
        sys.exit(f"[✗] Erreur HTTP {resp.status_code}")

    title = extract_title(resp.content)
    filename = safe_filename(title, args.page_id)
    output_path = Path(args.output_dir) / filename
    output_path.write_bytes(resp.content)
    print(f"[✓] Sauvegardé : {output_path}")

    if args.s3_bucket:
        s3_key = f"{S3_PREFIX.rstrip('/')}/{filename}"
        upload_to_s3(output_path, args.s3_bucket, s3_key)


if __name__ == "__main__":
    main()

