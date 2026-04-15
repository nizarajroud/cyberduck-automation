#!/usr/bin/env python3
"""
Usage:
    python bendoc_download.py <url>

    Confluence : https://confluence.int.beneva.ca/spaces/.../pages/567083024/...
    Backstage  : https://portail-developpeur.pati.int.beneva.ca/catalog/...
"""

import argparse
import os
import re
from urllib.parse import urlparse
import subprocess
import sys
from pathlib import Path

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
PATI_DOC_URL           = os.environ.get("PATI_DOC_URL", "")

if not JSESSIONID or not CONFLUENCE_BASE_URL:
    sys.exit("[✗] JSESSIONID ou CONFLUENCE_BASE_URL manquant dans .env")


def extract_title(content: bytes) -> str:
    """Extrait le titre depuis le fichier MIME/HTML exporté par Confluence."""
    import quopri, re
    # Decode quoted-printable
    try:
        decoded = quopri.decodestring(content).decode("utf-8", errors="replace")
    except Exception:
        decoded = content.decode("utf-8", errors="replace")
    m = re.search(r"<title>(.*?)</title>", decoded, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""


def safe_filename(title: str, page_id: str) -> str:
    clean = "".join(c if c.isalnum() or c in " -_" else " " for c in title).strip()
    clean = " ".join(clean.split())[:50].strip()
    return f"{page_id}-{clean}.doc" if clean else f"{page_id}.doc"


def upload_to_s3(local_path: Path, s3_bucket: str, s3_key: str):
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


def ensure_aws_session():
    script = Path(__file__).parent / "cyberduck-sso.bash"
    if not script.exists():
        sys.exit(f"[✗] cyberduck-sso.bash introuvable : {script}")
    subprocess.run(["bash", str(script)], check=True)


def parse_confluence_page_id(url: str) -> str | None:
    """Extrait le page ID depuis une URL Confluence standard."""
    m = re.search(r"/pages/(\d+)", url)
    return m.group(1) if m else None


def is_backstage_url(url: str) -> bool:
    return "portail-developpeur" in urlparse(url).netloc


def handle_backstage(url: str):
    m = re.search(r"/documentation/(.+?)/?$", url)
    if not m:
        sys.exit(f"[✗] Impossible d'extraire le chemin après /documentation/ depuis : {url}")
    doc_path = m.group(1).rstrip("/") + ".md"
    if not PATI_DOC_URL:
        sys.exit("[✗] PATI_DOC_URL manquant dans .env")
    full_url = PATI_DOC_URL.rstrip("/") + "/" + doc_path
    print(f"[i] URL Backstage → {full_url}")
    print("[!] Traitement Backstage non encore implémenté.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="URL Confluence ou Backstage")
    parser.add_argument("--s3-bucket", default=S3_BUCKET or None, help="Nom du bucket S3 (optionnel)")
    parser.add_argument("--output-dir", default=CONFLUENCE_DOWNLOAD_DIR, help="Dossier de destination")
    args = parser.parse_args()

    if is_backstage_url(args.url):
        handle_backstage(args.url)
        return

    page_id = parse_confluence_page_id(args.url)
    if not page_id:
        sys.exit(f"[✗] Impossible d'extraire le page ID depuis : {args.url}")

    ensure_aws_session()

    url = f"{CONFLUENCE_BASE_URL}/{CONFLUENCE_EXPORT_PATH}?pageId={page_id}"
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
    filename = safe_filename(title, page_id)
    output_path = Path(args.output_dir) / filename
    output_path.write_bytes(resp.content)
    print(f"[✓] Sauvegardé : {output_path}")

    if args.s3_bucket:
        s3_key = f"{S3_PREFIX.rstrip('/')}/{filename}"
        upload_to_s3(output_path, args.s3_bucket, s3_key)


if __name__ == "__main__":
    main()

