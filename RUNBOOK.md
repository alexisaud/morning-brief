# Morning Brief — déroulé du matin (tâche planifiée Claude)

Lancé chaque jour vers 7h40 (Zurich). Objectif : épisode reçu sur Telegram à **8h00**.
Travailler sans jamais poser de question. Si une étape échoue, continuer avec le reste
et le signaler en une phrase dans l'épisode écrit.

- Préférences éditoriales : `config/preferences.md` (à lire en entier à chaque fois)
- Réglages (voix, débit, durées) : `config/settings.json`
- Calendrier Google : `alexis.audisio@gmail.com` (+ « Holidays in Switzerland » pour les jours fériés)
- Fuseau : Europe/Zurich. `TODAY` = date du jour à Zurich (`TZ=Europe/Zurich date +%F`).

## 0. Dépôt
Attacher `alexisaud/morning-brief` (add_repo, accès push), le cloner dans
`/home/claude/morning-brief`, travailler depuis là.
Si `episodes/<TODAY>/sent.json` existe déjà avec `"ok": true` → l'épisode du jour est parti : s'arrêter.

## 1. Collecte (GitHub Actions)
```
curl -sS -X POST -H "Accept: application/vnd.github+json" -H "Content-Type: application/json" \
  https://api.github.com/repos/alexisaud/morning-brief/actions/workflows/collect.yml/dispatches -d '{"ref":"main"}'
```
Puis interroger `https://api.github.com/repos/alexisaud/morning-brief/actions/workflows/collect.yml/runs?per_page=1`
toutes les 20 s jusqu'à `status: completed` (max 8 min), puis `git pull`.
Vérifier : `data/today.json` a `date` = TODAY ; `data/news.json` a `collected_at` de moins de 2 h.
- Collecte en échec ou périmée : faire l'épisode quand même (agenda + citation, et neige si en saison),
  dire en une phrase que les news n'ont pas pu être récupérées. Si `data/today.json` n'est pas à jour,
  tirer soi-même une citation au hasard dans `config/quotes.json` avec Python (`random.choice`).

## 2. Messages Telegram d'Alexis (`data/inbox.json`)
Pour chaque message :
- **Préférence** (« moins de géopolitique », « plus court », « ajoute X ») → l'appliquer dès aujourd'hui
  et l'ajouter, datée, dans la section « Ajustements demandés via Telegram » de `config/preferences.md`.
  Si elle contredit une règle plus haut, c'est la plus récente qui gagne.
- **Question ou « creuse la news N »** → y répondre dans le segment « Tes questions » (30 à 60 s par
  question), à partir de sources réelles (WebSearch / WebFetch), sources citées dans la version écrite.
  « La news N » renvoie à l'épisode de la veille (`episodes/<hier>/message.html`).
- Puis écrire `state/inbox_processed.json` : `{"upto": "<date du dernier message traité, format du fichier>"}`.

## 3. Agenda
Google Calendar `list_events`, calendrier `alexis.audisio@gmail.com`, fuseau Europe/Zurich :
- tous les jours : aujourd'hui de 00:00 à 23:59 ;
- **le lundi** : en plus, du lundi au dimanche de la semaine.
Ignorer les événements refusés. Pour chacun : heure, titre, lieu s'il y en a un. Lire le titre tel quel,
sans commentaire sur sa nature. Si le titre contient une heure différente du créneau, le signaler
(« à vérifier »).
Vérifier aussi « Holidays in Switzerland » pour aujourd'hui (le dire si c'est férié).
Journée vide → une phrase (« Rien à l'agenda aujourd'hui, journée libre pour avancer sur tes priorités »).

## 4. Neige La Clusaz (du 1er novembre au 30 avril seulement)
Lire `data/snow.txt` (prévisions 6 jours de snow-forecast, altitude moyenne). En 3 ou 4 phrases :
neige fraîche attendue et quand, hauteur de neige actuelle si disponible, températures / isotherme,
la meilleure journée à venir. Données illisibles → une phrase pour le dire. Hors saison : pas de segment.

## 5. News (`data/news.md`)
`data/news.md` liste une ligne par sujet (doublons regroupés). Repérer 8 à 10 candidats, lire leur
détail avec `python3 scripts/item.py <n> <n> ...`, puis en retenir 4 ou 5 selon `config/preferences.md`.
On peut ouvrir l'article lié (WebFetch) pour préciser un fait, jamais ajouter une info absente des sources. Budget : **≤ 3 minutes**, soit
≤ `3 × words_per_minute` mots (voir `config/settings.json`).

## 6. Rédaction
Créer `episodes/<TODAY>/` avec :

**`script.txt`** — le texte lu par la voix de synthèse :
- français parlé, phrases courtes, transitions naturelles entre les segments ;
- aucun markdown, aucun emoji, aucune URL, pas de puces ; « 14h30 » s'écrit « 14 heures 30 » ;
- longueur totale ≤ `10 × words_per_minute` mots ; viser 4 à 7 minutes un jour normal.
Vérifier avec `wc -w` et raccourcir si besoin (news ≤ `3 × words_per_minute` mots).

**`message.html`** — la version écrite envoyée juste après l'audio sur Telegram (HTML Telegram :
seulement `<b>`, `<i>`, `<a href="...">`, échapper `&`, `<`, `>` ailleurs), blocs séparés par une ligne vide :
```
<b>☀️ Morning Brief — jeudi 23 octobre</b>

<b>📰 News</b>
1. <b>Titre court</b> — 1 ou 2 phrases. <a href="URL">Source</a>
...

<b>📅 Aujourd'hui</b>
• 14:00 — Titre (lieu)

<b>🏔️ La Clusaz</b>            (en saison seulement)
...

<b>💬 Tes questions</b>        (si messages)
...

<i>« Citation »</i> — Auteur
```
Numéroter les news : Alexis peut répondre « creuse la 2 ».

**`meta.json`** — `{"title": "Morning Brief — <jour> <date>"}`

## 7. Envoi
Si l'heure à Zurich est avant 07:58, attendre jusqu'à 07:58 (`sleep`), puis :
```
git add episodes/ config/ state/ && git commit -m "episode <TODAY>" && git pull --rebase && git push
```
Le push déclenche `publish.yml` (voix edge-tts + envoi Telegram). Interroger
`.../actions/workflows/publish.yml/runs?per_page=1` jusqu'à `completed` (max 8 min), `git pull`,
lire `episodes/<TODAY>/sent.json`.
- `ok: true` → mettre à jour `words_per_minute` dans `config/settings.json` avec la moyenne entre
  l'ancienne valeur et `measured_wpm` (arrondie), commit + push. Fin.
- Échec Telegram (token, chat_id, réseau) → envoyer à la place un email (Gmail `send_message`) à
  alexis.audisio@gmail.com, objet = titre de l'épisode, corps = le contenu de `message.html`
  (en `htmlBody`) avec en tête la raison de l'échec.

Terminer par un résumé d'un paragraphe : sujets retenus, durée, erreurs éventuelles.
