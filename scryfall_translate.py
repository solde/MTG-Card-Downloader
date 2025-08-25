#!/usr/bin/env python3
"""
Traduce un listado de cartas de Magic del inglés al español usando Scryfall.

Uso:
  python scryfall_translate.py --input cartas.txt --out traducciones.csv --lang es

Entrada:
  - Una carta por línea.
  - Se ignoran cantidades iniciales y comentarios con "#".
  - Soporta cartas de dos caras con " // ".

Salida:
  - CSV con columnas:
      original_name, spanish_name, found, set, collector_number, lang, scryfall_uri
  - Opcionalmente, un TXT con el mazo traducido: --deckout deck_es.txt
"""

import argparse
import csv
import os
import re
import sys
import time
from typing import Dict, List, Optional, Tuple

try:
    import requests
except ImportError:
    print("Falta la librería 'requests'. Instálala con: pip install requests")
    sys.exit(1)

API_NAMED = "https://api.scryfall.com/cards/named"
API_SEARCH = "https://api.scryfall.com/cards/search"
REQUEST_DELAY = 0.12  # ~8 req/s recomendado


def parse_names_from_file(path: str) -> List[str]:
    if not os.path.exists(path):
        print(f"No se encontró el archivo: {path}")
        sys.exit(1)
    names: List[str] = []
    seen = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Elimina comentarios
            line = line.split("#", 1)[0].strip()
            # Elimina cantidad inicial
            m = re.match(r"^\s*\d+\s+(.*)$", line)
            if m:
                line = m.group(1).strip()
            # Normaliza separador de dos caras
            line = re.sub(r"\s*//\s*", " // ", line)
            if line and line not in seen:
                seen.add(line)
                names.append(line)
    return names


def http_get(url: str, params: Dict) -> Optional[Dict]:
    try:
        r = requests.get(url, params=params, timeout=25)
        if r.status_code == 200:
            return r.json()
        return None
    except requests.RequestException:
        return None


def assemble_printed_name(card: Dict) -> str:
    """
    Obtiene el nombre impreso en el idioma del objeto carta.
    Maneja cartas de dos caras.
    """
    # Caso simple
    if card.get("printed_name"):
        return card["printed_name"]
    # Dos caras
    faces = card.get("card_faces")
    if isinstance(faces, list) and faces:
        parts = []
        for face in faces:
            parts.append(face.get("printed_name") or face.get("name") or "")
        return " // ".join([p for p in parts if p])
    # Fallback al nombre oracle
    return card.get("name", "")


def fetch_named(name: str, lang: Optional[str], fuzzy: bool = False) -> Optional[Dict]:
    params = {"fuzzy" if fuzzy else "exact": name}
    if lang:
        params["lang"] = lang
    data = http_get(API_NAMED, params)
    time.sleep(REQUEST_DELAY)
    return data if data and data.get("object") == "card" else None


def search_spanish_prints_by_oracle(oracle_id: str) -> Optional[Dict]:
    # Busca impresiones en español de este oracle_id
    q = f"oracleid:{oracle_id} lang:es"
    params = {"q": q, "order": "released", "unique": "prints"}
    data = http_get(API_SEARCH, params)
    time.sleep(REQUEST_DELAY)
    if not data or data.get("object") != "list":
        return None
    cards = data.get("data", [])
    if not cards:
        return None
    # Elige la más reciente
    return cards[0]


def translate_name(name: str, lang: str) -> Tuple[str, Optional[Dict]]:
    """
    Devuelve (spanish_name, card_used or None)
    """
    # 1) Intento directo exacto en español
    card = fetch_named(name, lang=lang, fuzzy=False)
    if card:
        spanish = assemble_printed_name(card)
        if card.get("lang") == lang and spanish:
            return spanish, card

    # 2) Fuzzy en español
    card = fetch_named(name, lang=lang, fuzzy=True)
    if card and card.get("lang") == lang:
        spanish = assemble_printed_name(card)
        if spanish:
            return spanish, card

    # 3) Obtén oracle_id en inglés, luego busca impresiones en español
    base_card = fetch_named(name, lang=None, fuzzy=False) or fetch_named(name, lang=None, fuzzy=True)
    if base_card and base_card.get("oracle_id"):
        es_print = search_spanish_prints_by_oracle(base_card["oracle_id"])
        if es_print:
            spanish = assemble_printed_name(es_print)
            if spanish:
                return spanish, es_print

    # 4) Sin traducción disponible
    return "", None


def main():
    ap = argparse.ArgumentParser(description="Traduce nombres de cartas usando Scryfall.")
    ap.add_argument("--input", required=True, help="Archivo con el listado de cartas.")
    ap.add_argument("--out", default="traducciones.csv", help="CSV de salida con las traducciones.")
    ap.add_argument("--deckout", default="", help="Ruta opcional para escribir el mazo traducido (TXT).")
    ap.add_argument("--lang", default="es", help="Idioma de destino, por defecto 'es'.")
    args = ap.parse_args()

    names = parse_names_from_file(args.input)
    if not names:
        print("No se han encontrado cartas en la entrada.")
        sys.exit(1)

    rows = [["original_name", "spanish_name", "found", "set", "collector_number", "lang", "scryfall_uri"]]
    translated_lines: List[str] = []

    for idx, name in enumerate(names, 1):
        print(f"[{idx}/{len(names)}] {name}")
        spanish, card = translate_name(name, args.lang)
        found = bool(spanish)
        set_code = card.get("set", "") if card else ""
        collector = card.get("collector_number", "") if card else ""
        lang_used = card.get("lang", "") if card else ""
        uri = card.get("scryfall_uri", "") if card else ""
        rows.append([name, spanish, "yes" if found else "no", set_code, collector, lang_used, uri])
        translated_lines.append(spanish if spanish else name)

    # Escribe CSV
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    print(f"CSV escrito en: {args.out}")

    # Escribe mazo traducido si se solicita
    if args.deckout:
        with open(args.deckout, "w", encoding="utf-8") as f:
            for line in translated_lines:
                f.write(line + "\n")
        print(f"Mazo traducido en: {args.deckout}")


if __name__ == "__main__":
    main()
