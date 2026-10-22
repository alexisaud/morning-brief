#!/usr/bin/env python3
"""Morning Brief — collecte (tourne sur GitHub Actions).

1. Flux RSS (config/feeds.json)          -> data/news.json, data/news.md, data/feeds_status.json
2. Prévisions neige La Clusaz            -> data/snow.txt
3. Messages Telegram reçus depuis la veille -> data/inbox.json (+ state/telegram.json)
4. Citation du jour (tirage aléatoire)   -> data/today.json (+ state/quotes_used.json)

Chaque étape est indépendante : une erreur n'empêche pas les autres.
"""
import calendar
import datetime as dt
import html
import json
import os
import random
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATE = ROOT / "state"
CONFIG = ROOT / "config"
TZ = ZoneInfo("Europe/Zurich")
NOW = dt.datetime.now(dt.timezone.utc)
TODAY = NOW.astimezone(TZ).date()
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]

DATA.mkdir(exist_ok=True)
STATE.mkdir(exist_ok=True)


def load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def save(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def clean(text, limit=None):
    text = BeautifulSoup(text or "", "html.parser").get_text(" ")
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


# --------------------------------------------------------------------------- RSS
def collect_news():
    cfg = load(CONFIG / "feeds.json", {})
    max_age = dt.timedelta(hours=cfg.get("max_age_hours", 30))
    per_feed = cfg.get("max_items_per_feed", 25)
    items, status = [], []
    for feed in cfg.get("feeds", []):
        if feed.get("enabled") is False:
            continue
        st = {"name": feed["name"], "theme": feed["theme"], "url": feed["url"]}
        try:
            r = requests.get(feed["url"], headers={"User-Agent": UA}, timeout=20)
            st["http"] = r.status_code
            parsed = feedparser.parse(r.content)
            kept = 0
            for e in parsed.entries:
                tm = e.get("published_parsed") or e.get("updated_parsed")
                if tm:
                    pub = dt.datetime.fromtimestamp(calendar.timegm(tm), dt.timezone.utc)
                    if NOW - pub > max_age or pub - NOW > dt.timedelta(hours=2):
                        continue
                    pub_s = pub.astimezone(TZ).strftime("%Y-%m-%d %H:%M")
                else:
                    pub_s = ""
                title = clean(e.get("title"))
                if not title:
                    continue
                items.append({
                    "theme": feed["theme"],
                    "source": feed["name"],
                    "title": title,
                    "summary": clean(e.get("summary") or e.get("description"), 450),
                    "link": e.get("link", ""),
                    "published": pub_s,
                })
                kept += 1
                if kept >= per_feed:
                    break
            st["entries"] = len(parsed.entries)
            st["kept"] = kept
            st["ok"] = r.status_code == 200 and len(parsed.entries) > 0
        except Exception as exc:  # noqa: BLE001
            st["ok"] = False
            st["error"] = str(exc)[:200]
        status.append(st)
        print(f"[rss] {'OK ' if st.get('ok') else 'KO '} {feed['name']}: {st.get('kept', 0)} gardés / {st.get('entries', '?')}")

    # Repérer les sujets couverts par plusieurs sources (signal d'importance).
    def words(t):
        return {w for w in re.findall(r"[a-zà-ÿ0-9]{5,}", t.lower())}
    for it in items:
        ws = words(it["title"])
        it["coverage"] = len({o["source"] for o in items
                              if o is not it and len(ws & words(o["title"])) >= 2}) + 1

    save(DATA / "feeds_status.json", status)

    # Numérotation + regroupement des doublons (même sujet, plusieurs sources).
    order = ["une", "economie", "geopolitique", "tech", "france", "suisse", "vaud"]
    items.sort(key=lambda i: (order.index(i["theme"]) if i["theme"] in order else 99, -i["coverage"]))
    for n, it in enumerate(items, 1):
        it["n"] = n
    kept_heads = []
    for it in items:
        ws = words(it["title"])
        dup = next((h for h in kept_heads if len(ws & words(h["title"])) >= 3), None)
        if dup:
            dup.setdefault("also", []).append(it["n"])
        else:
            kept_heads.append(it)

    # Version compacte (une ligne par sujet), lisible par Claude chaque matin.
    lines = [f"# News collectées le {NOW.astimezone(TZ):%Y-%m-%d %H:%M} (Zurich) — "
             f"{len(items)} articles, {len(kept_heads)} sujets distincts",
             "Format : [n] (xC = nb de sources sur le sujet) source — titre :: début du résumé",
             "Détail complet (résumé + lien) : python3 scripts/item.py <n> [<n> ...]", ""]
    for theme in order:
        sel = [h for h in kept_heads if h["theme"] == theme]
        lines.append(f"## {theme} ({len(sel)})")
        for h in sel:
            short = h["summary"][:150].rsplit(" ", 1)[0] + "…" if len(h["summary"]) > 150 else h["summary"]
            also = f" (+{len(h['also'])} doublon(s))" if h.get("also") else ""
            lines.append(f"[{h['n']}] (x{h['coverage']}) {h['source']} — {h['title']}{also} :: {short}")
        lines.append("")
    (DATA / "news.md").write_text("\n".join(lines), encoding="utf-8")
    save(DATA / "news.json", {"collected_at": NOW.isoformat(), "items": items})


# --------------------------------------------------------------------------- Neige
def collect_snow():
    settings = load(CONFIG / "settings.json", {})
    url = settings.get("snow_url", "https://fr.snow-forecast.com/resorts/La-Clusaz/6day/mid")
    out = [f"Source : {url}", f"Récupéré le {NOW.astimezone(TZ):%Y-%m-%d %H:%M} (Zurich)", ""]
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "fr-FR,fr;q=0.9"}, timeout=30)
        out.append(f"HTTP {r.status_code}")
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()

        # 1) Tableau de prévisions : une ligne par type de donnée.
        table = soup.select_one("table.forecast-table__table") or soup.find("table")
        if table:
            out.append("\n## Tableau de prévisions (une ligne par donnée, cellules séparées par ' | ')")
            for tr in table.find_all("tr"):
                label = tr.get("data-row") or ""
                cells = [clean(c.get_text(" ")) for c in tr.find_all(["th", "td"])]
                cells = [c for c in cells if c]
                if cells:
                    out.append(f"{label}: " + " | ".join(cells))
        # 2) Texte de la page (résumé, hauteurs de neige, etc.), tronqué.
        main = soup.find("main") or soup.body or soup
        text = clean(main.get_text(" "))
        out.append("\n## Texte de la page (extrait)")
        out.append(text[:6000])
    except Exception as exc:  # noqa: BLE001
        out.append(f"ERREUR : {exc}")
    (DATA / "snow.txt").write_text("\n".join(out), encoding="utf-8")
    print(f"[neige] {len(out)} lignes")


# --------------------------------------------------------------------------- Telegram
def collect_telegram():
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    st_path = STATE / "telegram.json"
    st = load(st_path, {})
    inbox = {"collected_at": NOW.isoformat(), "messages": []}
    if not token:
        inbox["note"] = "TELEGRAM_TOKEN absent : secret à créer dans le dépôt."
        save(DATA / "inbox.json", inbox)
        print("[telegram] pas de token")
        return
    try:
        params = {"timeout": 0}
        if st.get("offset"):
            params["offset"] = st["offset"]
        r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", params=params, timeout=30)
        res = r.json()
        if not res.get("ok"):
            inbox["note"] = f"Erreur Telegram : {res.get('description')}"
        for up in res.get("result", []):
            st["offset"] = up["update_id"] + 1
            msg = up.get("message") or up.get("edited_message")
            if not msg:
                continue
            chat = msg.get("chat", {})
            if chat.get("type") != "private":
                continue
            if not st.get("chat_id"):
                st["chat_id"] = chat["id"]          # premier chat privé = Alexis
                st["chat_name"] = chat.get("first_name", "")
            if chat["id"] != st["chat_id"]:
                continue                            # on ignore tout autre expéditeur
            inbox["messages"].append({
                "date": dt.datetime.fromtimestamp(msg["date"], TZ).strftime("%Y-%m-%d %H:%M"),
                "text": msg.get("text") or msg.get("caption") or "(message non texte)",
                "reply_to": (msg.get("reply_to_message") or {}).get("text", "")[:300],
            })
    except Exception as exc:  # noqa: BLE001
        inbox["note"] = f"Erreur : {exc}"
    # On accumule les messages non encore traités par Claude.
    pending = load(DATA / "inbox.json", {}).get("messages", [])
    if load(STATE / "inbox_processed.json", {}).get("upto"):
        upto = load(STATE / "inbox_processed.json", {})["upto"]
        pending = [m for m in pending if m["date"] > upto]
    seen = {(m["date"], m["text"]) for m in pending}
    inbox["messages"] = pending + [m for m in inbox["messages"] if (m["date"], m["text"]) not in seen]
    save(DATA / "inbox.json", inbox)
    save(st_path, st)
    print(f"[telegram] chat_id={'oui' if st.get('chat_id') else 'non'}, {len(inbox['messages'])} message(s) en attente")


# --------------------------------------------------------------------------- Citation
def pick_quote():
    today = load(DATA / "today.json", {})
    if today.get("date") == TODAY.isoformat() and today.get("quote"):
        print("[citation] déjà tirée aujourd'hui")
        return
    quotes = load(CONFIG / "quotes.json", [])
    used = load(STATE / "quotes_used.json", [])
    recent = set(used[-min(len(quotes) - 1, 120):]) if quotes else set()
    pool = [q for q in quotes if q["text"] not in recent] or quotes
    q = random.SystemRandom().choice(pool) if pool else {"text": "", "author": ""}
    used.append(q["text"])
    save(STATE / "quotes_used.json", used[-300:])
    save(DATA / "today.json", {
        "date": TODAY.isoformat(),
        "label": f"{JOURS[TODAY.weekday()]} {TODAY.day} {MOIS[TODAY.month - 1]} {TODAY.year}",
        "weekday": JOURS[TODAY.weekday()],
        "quote": q,
    })
    print(f"[citation] {q.get('author')}")


if __name__ == "__main__":
    steps = sys.argv[1:] or ["news", "snow", "telegram", "quote"]
    for name, fn in [("news", collect_news), ("snow", collect_snow),
                     ("telegram", collect_telegram), ("quote", pick_quote)]:
        if name in steps:
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                print(f"[{name}] ÉCHEC : {exc}")
