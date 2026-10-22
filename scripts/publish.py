#!/usr/bin/env python3
"""Morning Brief — production audio + envoi Telegram (tourne sur GitHub Actions).

  python scripts/publish.py                 # publie le dernier épisode pas encore envoyé
  python scripts/publish.py --date 2026-10-23
  python scripts/publish.py --samples       # échantillons de voix -> samples/
  python scripts/publish.py --notify "texte" # simple message Telegram

Un épisode = dossier episodes/<date>/ avec :
  script.txt    texte lu à voix haute (pas de markdown, pas d'URL)
  message.html  version écrite pour Telegram (HTML Telegram : <b>, <i>, <a href>)
  meta.json     {"title": "..."} (optionnel)
Résultat : episodes/<date>/sent.json
"""
import argparse
import asyncio
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
API = f"https://api.telegram.org/bot{TOKEN}"


def load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


SETTINGS = load(ROOT / "config/settings.json", {})


# --------------------------------------------------------------------------- voix
async def _tts(text, voice, rate, out):
    import edge_tts
    await edge_tts.Communicate(text, voice, rate=rate).save(str(out))


def tts(text, out, voice=None, rate=None):
    voice = voice or SETTINGS.get("voice", "fr-FR-RemyMultilingualNeural")
    rate = rate or SETTINGS.get("rate", "+0%")
    last = None
    for _ in range(3):
        try:
            asyncio.run(_tts(text, voice, rate, out))
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise RuntimeError(f"edge-tts a échoué ({voice}) : {last}")


def duration(path):
    from mutagen.mp3 import MP3
    return round(MP3(str(path)).info.length)


# --------------------------------------------------------------------------- Telegram
def chat_id():
    st = load(ROOT / "state/telegram.json", {})
    if st.get("chat_id"):
        return st["chat_id"]
    # Pas encore enregistré : on regarde les messages en attente (sans les consommer).
    res = requests.get(f"{API}/getUpdates", timeout=30).json()
    for up in res.get("result", []):
        chat = (up.get("message") or {}).get("chat", {})
        if chat.get("type") == "private":
            return chat["id"]
    return None


def tg(method, files=None, **data):
    r = requests.post(f"{API}/{method}", data=data, files=files, timeout=120)
    res = r.json()
    if not res.get("ok"):
        raise RuntimeError(f"{method}: {res.get('description')}")
    return res["result"]


def split_html(text, limit=3900):
    parts, cur = [], ""
    for block in text.split("\n\n"):
        if len(cur) + len(block) + 2 > limit and cur:
            parts.append(cur)
            cur = ""
        cur = f"{cur}\n\n{block}" if cur else block
    if cur:
        parts.append(cur)
    return parts


def send_text(cid, html_text):
    ids = []
    for part in split_html(html_text):
        try:
            ids.append(tg("sendMessage", chat_id=cid, text=part, parse_mode="HTML",
                          disable_web_page_preview="true")["message_id"])
        except RuntimeError:
            plain = re.sub(r"<[^>]+>", "", part)
            ids.append(tg("sendMessage", chat_id=cid, text=plain,
                          disable_web_page_preview="true")["message_id"])
    return ids


# --------------------------------------------------------------------------- modes
def publish(date=None):
    eps = ROOT / "episodes"
    if date:
        ep = eps / date
    else:
        cands = sorted(d for d in eps.iterdir() if d.is_dir() and (d / "script.txt").exists()
                       and not (d / "sent.json").exists()) if eps.exists() else []
        if not cands:
            print("Aucun épisode à publier.")
            return 0
        ep = cands[-1]
    script = (ep / "script.txt").read_text(encoding="utf-8").strip()
    message = (ep / "message.html").read_text(encoding="utf-8").strip() if (ep / "message.html").exists() else ""
    meta = load(ep / "meta.json", {})
    report = {"episode": ep.name, "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "words": len(script.split()), "voice": SETTINGS.get("voice"), "errors": []}

    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    mp3 = out / f"morning-brief-{ep.name}.mp3"
    try:
        tts(script, mp3)
        report["duration_s"] = duration(mp3)
        report["measured_wpm"] = round(report["words"] / (report["duration_s"] / 60), 1)
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(str(exc))

    if not TOKEN:
        report["errors"].append("TELEGRAM_TOKEN absent")
    else:
        cid = chat_id()
        if not cid:
            report["errors"].append("chat_id inconnu : envoyer /start au bot")
        else:
            title = meta.get("title") or f"Morning Brief — {ep.name}"
            try:
                if mp3.exists():
                    with mp3.open("rb") as fh:
                        res = tg("sendAudio", files={"audio": (mp3.name, fh, "audio/mpeg")},
                                 chat_id=cid, title=title, performer="Morning Brief",
                                 duration=report.get("duration_s", 0))
                    report["audio_message_id"] = res["message_id"]
                elif report["errors"]:
                    send_text(cid, "⚠️ Audio indisponible ce matin, voici la version écrite.")
                if message:
                    report["text_message_ids"] = send_text(cid, message)
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(str(exc))

    report["ok"] = not report["errors"]
    report["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    (ep / "sent.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


SAMPLE = ("Bonjour Alexis, on est jeudi 23 octobre, et voici ton Morning Brief. "
          "En Suisse, la BNS maintient son taux directeur. À Lausanne, le Conseil communal "
          "débat du budget 2027. Côté tech, OpenAI, Google et Anthropic accélèrent sur les agents IA. "
          "Aujourd'hui, tu as un rendez-vous à 14 heures avec le cabinet M&BD Consulting. "
          "Et pour bien commencer la journée : le pessimisme est d'humeur, l'optimisme est de volonté.")


def samples():
    out = ROOT / "samples"
    out.mkdir(exist_ok=True)
    rep = {}
    for v in SETTINGS.get("candidate_voices", []):
        f = out / f"{v}.mp3"
        try:
            tts(SAMPLE, f, voice=v, rate=SETTINGS.get("rate"))
            d = duration(f)
            rep[v] = {"duration_s": d, "wpm": round(len(SAMPLE.split()) / (d / 60), 1)}
        except Exception as exc:  # noqa: BLE001
            rep[v] = {"error": str(exc)[:200]}
    (out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    if TOKEN and (cid := chat_id()):
        for v, info in rep.items():
            if "error" not in info:
                with (out / f"{v}.mp3").open("rb") as fh:
                    tg("sendAudio", files={"audio": (f"{v}.mp3", fh, "audio/mpeg")},
                       chat_id=cid, title=v, performer="Échantillon de voix")
    return 0


def notify(text):
    if TOKEN and (cid := chat_id()):
        send_text(cid, text)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--samples", action="store_true")
    ap.add_argument("--notify")
    a = ap.parse_args()
    if a.samples:
        sys.exit(samples())
    if a.notify:
        sys.exit(notify(a.notify))
    sys.exit(publish(a.date))
