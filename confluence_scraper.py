#!/usr/bin/env python3
"""
confluence_scraper.py
---------------------
Scrape une page Confluence (via View Source) et uploade le contenu
vers un bucket S3 en JSON structuré, avec les images séparées.
Upload final via Cyberduck CLI (duck).

Usage:
    python confluence_scraper.py --page-id 278661148
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup

load_dotenv()

JSESSIONID       = os.environ.get("JSESSIONID", "")
CONFLUENCE_BASE_URL = os.environ.get("CONFLUENCE_BASE_URL", "")
S3_BUCKET        = os.environ.get("S3_BUCKET", "")
S3_PREFIX        = os.environ.get("S3_PREFIX", "confluence/")

if not all([JSESSIONID, CONFLUENCE_BASE_URL, S3_BUCKET]):
    sys.exit("[✗] Variables manquantes dans .env : JSESSIONID, CONFLUENCE_BASE_URL, S3_BUCKET")

# ─────────────────────────────────────────────


def build_session() -> requests.Session:
    """Crée une session HTTP avec authentification par cookie JSESSIONID."""
    session = requests.Session()
    session.verify = False
    session.cookies.set("JSESSIONID", JSESSIONID)
    session.headers.update({"User-Agent": "Mozilla/5.0 (confluence-scraper/1.0)"})
    return session


def fetch_page(session: requests.Session, url: str) -> str:
    """Télécharge le HTML source de la page Confluence."""
    print(f"[→] Téléchargement de la page : {url}")
    resp = session.get(url, timeout=30)

    if resp.status_code == 401:
        sys.exit("[✗] Erreur 401 : authentification refusée. Vérifie tes credentials.")
    if resp.status_code == 403:
        sys.exit("[✗] Erreur 403 : accès interdit à cette page.")
    if not resp.ok:
        sys.exit(f"[✗] Erreur HTTP {resp.status_code} : {resp.text[:200]}")

    print(f"[✓] Page téléchargée ({len(resp.content)} octets)")
    return resp.text


def parse_content(html: str, base_url: str, page_id: str) -> dict:
    """
    Parse le HTML et extrait :
    - titre
    - texte brut structuré (par section/heading)
    - liste des images avec leurs URLs
    - métadonnées
    """
    soup = BeautifulSoup(html, "html.parser")

    # ── Titre ──
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else f"page_{page_id}"
    # Nettoyer le suffixe Confluence du titre
    title = re.sub(r"\s*-\s*Confluence\s*$", "", title).strip()

    # ── Contenu principal ──
    # Confluence wrap le contenu dans #main-content ou .wiki-content
    main = (
        soup.find(id="main-content")
        or soup.find(class_="wiki-content")
        or soup.find("body")
        or soup
    )

    # ── Sections structurées par headings ──
    sections = []
    current_section = {"heading": "Introduction", "level": 0, "content": []}

    for element in main.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p",
                                   "ul", "ol", "table", "pre", "code", "div"]):
        tag = element.name

        if tag in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            # Sauvegarder la section précédente si elle a du contenu
            if current_section["content"]:
                sections.append(current_section)
            current_section = {
                "heading": element.get_text(strip=True),
                "level": int(tag[1]),
                "content": []
            }

        elif tag == "p":
            text = element.get_text(strip=True)
            if text:
                current_section["content"].append({"type": "paragraph", "text": text})

        elif tag in ["ul", "ol"]:
            items = [li.get_text(strip=True) for li in element.find_all("li") if li.get_text(strip=True)]
            if items:
                current_section["content"].append({"type": "list", "items": items})

        elif tag == "table":
            rows = []
            for tr in element.find_all("tr"):
                row = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if any(row):
                    rows.append(row)
            if rows:
                current_section["content"].append({"type": "table", "rows": rows})

        elif tag in ["pre", "code"]:
            code_text = element.get_text()
            if code_text.strip():
                current_section["content"].append({"type": "code", "text": code_text})

    # Ajouter la dernière section
    if current_section["content"]:
        sections.append(current_section)

    # ── Images ──
    images = []
    for img in main.find_all("img"):
        src = img.get("src", "")
        if not src or src.startswith("data:"):
            continue
        # Résoudre les URLs relatives
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            src = base_url + src
        elif not src.startswith("http"):
            src = base_url + "/" + src

        images.append({
            "url": src,
            "alt": img.get("alt", ""),
            "title": img.get("title", ""),
            "filename": os.path.basename(urllib.parse.urlparse(src).path) or f"image_{len(images)}.png"
        })

    # ── Liens ──
    links = []
    for a in main.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        if text and href and not href.startswith("#"):
            if href.startswith("/"):
                href = base_url + href
            links.append({"text": text, "url": href})

    # ── Texte complet (pour vectorisation) ──
    full_text = main.get_text(separator="\n", strip=True)
    # Nettoyer les lignes vides multiples
    full_text = re.sub(r"\n{3,}", "\n\n", full_text)

    return {
        "metadata": {
            "page_id": page_id,
            "title": title,
            "source_url": f"{base_url}/pages/viewpage.action?pageId={page_id}",
            "scraped_at": datetime.utcnow().isoformat() + "Z",
            "image_count": len(images),
            "section_count": len(sections),
        },
        "full_text": full_text,
        "sections": sections,
        "images": images,
        "links": links,
    }


def download_images(session: requests.Session, images: list, output_dir: Path) -> list:
    """Télécharge les images localement et retourne la liste mise à jour avec les chemins locaux."""
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)

    updated = []
    for i, img in enumerate(images):
        url = img["url"]
        # Générer un nom de fichier unique et propre
        ext = Path(urllib.parse.urlparse(url).path).suffix or ".png"
        filename = f"image_{i:03d}{ext}"
        local_path = images_dir / filename

        try:
            print(f"  [→] Image {i+1}/{len(images)} : {url[:80]}...")
            resp = session.get(url, timeout=20, stream=True)
            if resp.ok:
                with open(local_path, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        f.write(chunk)
                img["local_filename"] = filename
                img["local_path"] = str(local_path)
                print(f"  [✓] Sauvegardée : {filename}")
            else:
                print(f"  [!] Erreur {resp.status_code} pour : {url[:60]}")
                img["local_filename"] = None
                img["local_path"] = None
        except Exception as e:
            print(f"  [!] Échec téléchargement image : {e}")
            img["local_filename"] = None
            img["local_path"] = None

        updated.append(img)

    return updated


def save_json(data: dict, output_dir: Path, page_id: str) -> Path:
    """Sauvegarde le JSON structuré sur disque."""
    filename = f"confluence_page_{page_id}.json"
    json_path = output_dir / filename
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[✓] JSON sauvegardé : {json_path}")
    return json_path


def upload_to_s3(local_path: Path, s3_bucket: str, s3_prefix: str):
    """
    Upload un fichier (ou dossier) vers S3 via duck CLI.
    duck doit être installé et accessible dans le PATH.
    """
    # Construire l'URL S3 destination
    s3_prefix = s3_prefix.rstrip("/") + "/"
    s3_url = f"s3://{s3_bucket}/{s3_prefix}"

    print(f"\n[→] Upload vers S3 : {local_path} → {s3_url}")

    cmd = [
        "duck",
        "--quiet",
        "--retry",
        "--existing", "overwrite",
        "--upload", s3_url,
        str(local_path)
    ]

    # duck utilise les credentials AWS depuis l'environnement ou le keychain
    # Pour passer explicitement : duck --username ACCESS_KEY --password SECRET_KEY
    aws_key = os.environ.get("AWS_ACCESS_KEY_ID")
    aws_secret = os.environ.get("AWS_SECRET_ACCESS_KEY")
    if aws_key and aws_secret:
        cmd = [
            "duck",
            "--username", aws_key,
            "--password", aws_secret,
            "--quiet",
            "--retry",
            "--existing", "overwrite",
            "--upload", s3_url,
            str(local_path)
        ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"[✓] Upload réussi : {local_path.name}")
        if result.stdout:
            print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"[✗] Erreur duck : {e.stderr}")
        raise
    except FileNotFoundError:
        sys.exit("[✗] 'duck' introuvable. Installe Cyberduck CLI : sudo apt-get install duck")


def main():
    parser = argparse.ArgumentParser(description="Scrape Confluence → JSON → S3 via duck")
    parser.add_argument("--page-id", required=True, help="ID de la page Confluence")
    parser.add_argument("--output-dir", default=None, help="Dossier de sortie local (optionnel)")
    parser.add_argument("--no-upload", action="store_true", help="Ne pas uploader vers S3 (debug local)")
    args = parser.parse_args()

    url = f"{CONFLUENCE_BASE_URL}/plugins/viewsource/viewpagesrc.action?pageId={args.page_id}"

    if args.output_dir:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        temp_ctx = None
    else:
        temp_ctx = tempfile.TemporaryDirectory()
        output_dir = Path(temp_ctx.name)

    try:
        print(f"\n{'='*55}")
        print(f"  Page ID  : {args.page_id}")
        print(f"  Base URL : {CONFLUENCE_BASE_URL}")
        print(f"{'='*55}\n")

        session = build_session()
        html = fetch_page(session, url)

        print("[→] Extraction du contenu...")
        data = parse_content(html, CONFLUENCE_BASE_URL, args.page_id)
        print(f"[✓] {len(data['sections'])} sections, {len(data['images'])} images trouvées")

        if data["images"]:
            print(f"\n[→] Téléchargement de {len(data['images'])} image(s)...")
            data["images"] = download_images(session, data["images"], output_dir)

        json_path = save_json(data, output_dir, args.page_id)

        if not args.no_upload:
            page_prefix = f"{S3_PREFIX.rstrip('/')}/page_{args.page_id}/"
            upload_to_s3(json_path, S3_BUCKET, page_prefix)
            images_dir = output_dir / "images"
            if images_dir.exists() and any(images_dir.iterdir()):
                upload_to_s3(images_dir, S3_BUCKET, page_prefix + "images/")
        else:
            print(f"\n[i] Mode --no-upload : fichiers dans {output_dir}")

        print(f"\n{'='*55}")
        print("  ✓ Terminé avec succès!")
        print(f"{'='*55}\n")

    finally:
        if temp_ctx:
            temp_ctx.cleanup()


if __name__ == "__main__":
    main()