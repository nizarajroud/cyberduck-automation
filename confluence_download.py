#!/usr/bin/env python3
"""
Usage:
    python confluence_download.py --page-id 9389103
    python confluence_download.py --page-id 9389103 --s3-bucket mon-bucket
"""

import argparse
import re
import os
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

if not JSESSIONID or not CONFLUENCE_BASE_URL:
    sys.exit("[✗] JSESSIONID ou CONFLUENCE_BASE_URL manquant dans .env")


def get_aws_credentials() -> tuple[str, str, str]:
    """Lit les credentials du profil cyberduck-sso depuis WIN_AWS_DIR/.aws/credentials."""
    win_aws_dir = os.environ.get("WIN_AWS_DIR", "")
    creds_file = Path(win_aws_dir) / "credentials" if win_aws_dir else None

    if not creds_file or not creds_file.exists():
        return "", "", ""

    content = creds_file.read_text()
    section = re.search(r"\[cyberduck-sso\](.*?)(?=\[|\Z)", content, re.DOTALL)
    if not section:
        return "", "", ""

    def get(key):
        m = re.search(rf"^{key}\s*=\s*(.+)$", section.group(1), re.MULTILINE)
        return m.group(1).strip() if m else ""

    return get("aws_access_key_id"), get("aws_secret_access_key"), get("aws_session_token")


def upload_to_s3(local_path: Path, s3_bucket: str, s3_prefix: str):
    s3_url = f"s3://{s3_bucket}/{s3_prefix.rstrip('/')}/"
    print(f"[→] Upload vers S3 : {local_path.name} → {s3_url}")

    aws_key, aws_secret, aws_token = get_aws_credentials()
    if not aws_key:
        aws_key    = os.environ.get("AWS_ACCESS_KEY_ID", "")
        aws_secret = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
        aws_token  = os.environ.get("AWS_SESSION_TOKEN", "")

    if not aws_key:
        sys.exit("[✗] Credentials AWS introuvables. Lance cyberduck-sso.bash d'abord.")

    cmd = ["duck", "--username", aws_key, "--password", aws_secret,
           "--quiet", "--retry", "--existing", "overwrite", "--upload", s3_url, str(local_path)]

    env = os.environ.copy()
    if aws_token:
        env["AWS_SESSION_TOKEN"] = aws_token

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
        print(f"[✓] Upload réussi : {local_path.name}")
    except subprocess.CalledProcessError as e:
        sys.exit(f"[✗] Erreur duck (exit {e.returncode}):\n  stdout: {e.stdout}\n  stderr: {e.stderr}")
    except FileNotFoundError:
        sys.exit("[✗] 'duck' introuvable. Installe Cyberduck CLI : sudo apt-get install duck")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--page-id", required=True, help="ID de la page Confluence")
    parser.add_argument("--s3-bucket", default=S3_BUCKET or None, help="Nom du bucket S3 (optionnel)")
    parser.add_argument("--output-dir", default=CONFLUENCE_DOWNLOAD_DIR, help="Dossier de destination")
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

    if args.s3_bucket:
        upload_to_s3(output_path, args.s3_bucket, f"{S3_PREFIX.rstrip('/')}/page_{args.page_id}/")


if __name__ == "__main__":
    main()

