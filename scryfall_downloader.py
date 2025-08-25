#!/usr/bin/env python3
"""
Descarga imágenes de cartas de Magic desde Scryfall a partir de un listado.
Autor: ChatGPT

Uso:
  python scryfall_downloader.py --input cartas.txt --out imgs --size normal --lang es

Formato esperado del archivo de entrada:
  - Una carta por línea.
  - Puedes incluir cantidades al inicio (se ignoran): "1 Krenko, Mob Boss"
  - Puedes añadir comentarios con '#': "1 Krenko, Mob Boss # !Commander"
  - Se ignoran líneas vacías.

Ejemplo de contenido:
  1 Krenko, Mob Boss # !Commander
  1 Shatterskull Smashing // Shatterskull, the Hammer Pass
  1 Sensei's Divining Top
"""

import argparse
import csv
import os
import re
import sys
import time
import unicodedata
from typing import Dict, List, Tuple, Optional

try:
    import requests
except ImportError:
    print("Falta la librería 'requests'. Instálala con: pip install requests")
    sys.exit(1)


API_BASE = "https://api.scryfall.com/cards/named"
# Scryfall recomienda no superar ~10 solicitudes por segundo
REQUEST_DELAY = 0.12


def slugify(value: str) -> str:
    """
    Convierte un texto en un nombre de archivo seguro.
    """
    value = str(value)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s\-\.\(\)]", "", value).strip().lower()
    value = re.sub(r"[\s]+", "_", value)
    return value[:200]  # evita nombres extremadamente largos


def parse_names_from_file(path: str) -> List[str]:
    """
    Lee el archivo y devuelve una lista de nombres de cartas únicos en orden.
    """
    if not os.path.exists(path):
        print(f"No se encontró el archivo: {path}")
        sys.exit(1)

    seen = set()
    names: List[str] = []

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            # Elimina comentarios
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            line = line.split("#", 1)[0].strip()
            # Elimina cantidad inicial
            m = re.match(r"^\s*\d+\s+(.*)$", line)
            if m:
                line = m.group(1).strip()
            # Normaliza espacios alrededor de //
            line = re.sub(r"\s*//\s*", " // ", line)
            if line and line not in seen:
                seen.add(line)
                names.append(line)
    return names


def choose_image_uri(card: Dict, size: str) -> List[Tuple[str, str]]:
    """
    Devuelve una lista de (url, sufijo) con una o varias imágenes para descargar.
    - size puede ser: small, normal, large, png, art_crop, border_crop
    - Si la carta tiene dos caras, devuelve ambas.
    - Si el tamaño solicitado no existe, se intenta con 'png', luego 'large', luego 'normal'.
    """
    def pick_from_image_uris(image_uris: Dict) -> Optional[str]:
        for key in [size, "png", "large", "normal"]:
            if key in image_uris and image_uris[key]:
                return image_uris[key]
        return None

    results: List[Tuple[str, str]] = []
    if "image_uris" in card and isinstance(card["image_uris"], dict):
        url = pick_from_image_uris(card["image_uris"])
        if url:
            results.append((url, ""))
    elif "card_faces" in card and isinstance(card["card_faces"], list):
        for idx, face in enumerate(card["card_faces"], start=1):
            if "image_uris" in face:
                url = pick_from_image_uris(face["image_uris"])
                if url:
                    results.append((url, f"-{idx}"))
    return results


def fetch_card(name: str, lang: Optional[str]) -> Tuple[Optional[Dict], str]:
    """
    Intenta recuperar la carta desde Scryfall siguiendo este orden:
      1) exact + lang
      2) exact sin lang
      3) fuzzy + lang
      4) fuzzy sin lang
    Devuelve (card_json, estrategia_usada).
    """
    strategies = []
    if lang:
        strategies.append({"exact": name, "lang": lang})
    strategies.append({"exact": name})
    if lang:
        strategies.append({"fuzzy": name, "lang": lang})
    strategies.append({"fuzzy": name})

    for params in strategies:
        try:
            r = requests.get(API_BASE, params=params, timeout=20)
            if r.status_code == 200:
                data = r.json()
                # Objeto carta válido
                if data.get("object") == "card":
                    return data, "&".join([f"{k}={v}" for k, v in params.items()])
                # Si devuelve un list/array de coincidencias, ignóralo y sigue
            elif r.status_code == 404:
                pass
            else:
                print(f"[{name}] Respuesta HTTP {r.status_code} para {params}")
        except requests.RequestException as e:
            print(f"[{name}] Error de red: {e}")
        time.sleep(REQUEST_DELAY)
    return None, ""


def download_image(url: str, dest_path: str) -> bool:
    """
    Descarga la imagen a dest_path. Devuelve True si tiene éxito.
    """
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            if r.status_code != 200:
                print(f"HTTP {r.status_code} al descargar {url}")
                return False
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        return True
    except requests.RequestException as e:
        print(f"Fallo descargando {url}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Descarga imágenes de cartas desde Scryfall.")
    parser.add_argument("--input", required=True, help="Ruta al archivo con el listado de cartas.")
    parser.add_argument("--out", default="cards_images", help="Directorio de salida para las imágenes.")
    parser.add_argument("--size", default="normal", choices=["small","normal","large","png","art_crop","border_crop"],
                        help="Tamaño de imagen en Scryfall.")
    parser.add_argument("--lang", default="es", help="Código de idioma preferido, por ejemplo es, en, fr.")
    parser.add_argument("--csv", default="download_summary.csv", help="Nombre del CSV resumen.")
    args = parser.parse_args()

    names = parse_names_from_file(args.input)
    if not names:
        print("El archivo no contiene cartas válidas.")
        sys.exit(1)

    print(f"Cartas detectadas: {len(names)}")
    results_rows = []

    for i, name in enumerate(names, start=1):
        print(f"[{i}/{len(names)}] Buscando: {name}")
        card, used = fetch_card(name, args.lang)
        if not card:
            print(f"  No encontrada en Scryfall: {name}")
            results_rows.append([name, "", "", "", "", "", "NO_ENCONTRADA"])
            continue

        # Nombre y metadatos
        printed_name = card.get("printed_name") or card.get("name") or name
        lang_used = card.get("lang", "")
        set_code = card.get("set", "")
        collector = card.get("collector_number", "")

        images = choose_image_uri(card, args.size)
        if not images:
            print(f"  La carta no tiene image_uris disponibles: {printed_name}")
            results_rows.append([name, printed_name, lang_used, set_code, collector, "", "SIN_IMAGEN"])
            continue

        saved_paths: List[str] = []
        base_filename = slugify(f"{printed_name}_{lang_used or 'xx'}_{set_code}{collector}")
        for url, suffix in images:
            ext = ".png" if ".png" in url.lower() else ".jpg"
            filename = f"{base_filename}{suffix}{ext}"
            dest = os.path.join(args.out, filename)
            ok = download_image(url, dest)
            if ok:
                saved_paths.append(dest)
                print(f"  Guardado: {dest}")
            else:
                print(f"  Error al guardar: {dest}")

        results_rows.append([name, printed_name, lang_used, set_code, collector, "|".join(saved_paths), used])
        time.sleep(REQUEST_DELAY)

    # Escribe CSV con el resumen
    csv_path = os.path.join(args.out, args.csv)
    os.makedirs(args.out, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Nombre original", "Nombre Scryfall/impreso", "Idioma", "Set", "Número", "Ficheros guardados", "Búsqueda"])
        writer.writerows(results_rows)

    print("\nHecho.")
    print(f"Resumen CSV: {csv_path}")


if __name__ == "__main__":
    main()
