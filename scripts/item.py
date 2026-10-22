#!/usr/bin/env python3
"""Affiche le détail (source, heure, titre, résumé complet, lien) d'articles de data/news.json.
Usage : python3 scripts/item.py 12 47 103"""
import json
import sys
from pathlib import Path

items = {i["n"]: i for i in json.loads((Path(__file__).resolve().parent.parent / "data/news.json")
                                       .read_text(encoding="utf-8"))["items"]}
for arg in sys.argv[1:]:
    it = items.get(int(arg))
    if not it:
        print(f"[{arg}] introuvable\n")
        continue
    print(f"[{it['n']}] {it['theme']} · {it['published']} · {it['source']} (x{it['coverage']})")
    print(it["title"])
    if it.get("summary"):
        print(it["summary"])
    print(it["link"])
    if it.get("also"):
        print("Même sujet ailleurs :", ", ".join(f"[{n}] {items[n]['source']}" for n in it["also"]))
    print()
