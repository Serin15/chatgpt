# Dovezi v0.22.0

Cod final: `7115eca8741c7c491b9697a0ddf59881c7b67ee0`; baza de comparație: `e007f3b23e09fc2123b4f6d6b2c5cfb3ed35b22b`. Documentația se adaugă ulterior, fără schimbarea codului verificat.

## Teste controlate

- `pytest-verified.txt`: 662 teste trecute, cu SQLite/fișiere/subprocessuri reale pe baze temporare și furnizori simulați. Nu este test de profitabilitate sau generare AI live.
- `browser-release.txt`: 49 scenarii Chromium cu furnizori izolați/interceptări, inclusiv configurație backup invalidă și căi lungi pe mobil.
- `backup-before.txt`: cinci regresii eșuate înaintea implementării destinației externe. `focused-final.txt` și `final-fault-tests.txt`: verificări după corecții.
- `missing-volume-regression.json`: codul helperului din b91d27f într-un subprocess cu rădăcină indisponibilă simulată a depășit timeoutul de 2 s și a fost oprit. Codul corectat respinge cazul cu ValueError, fără buclă.
- `external-backup-proof.json`: baze **sintetice mici**, dar volume, fișiere, SQLite, ZIP și restaurare reale. Device IDs confirmă volume distincte. Nu este copia bazei mari de producție.
- Rezultatele CI se găsesc în `ci-final.json`/`ci-excerpts.txt`, legate de commitul sursă de mai sus.

## Date și instanță reale

- `api-before.json`: latențe înaintea implementării, inclusiv căutare HTTP 503 după 5 s. `api-prototype.json` păstrează răspunsurile temporare 503 din prototipul indexului; varianta finală suprapune restul mic de actualizări.
- `equivalence.json`/`equivalence.txt`: comparația finală, aceeași tranzacție SQLite și aceeași oră, toate cele șase rezultate complete identice și hashuri canonice egale. Limita de 5 s a căutării vechi este dezactivată numai în verificator pentru comparația completă. Timpii interni nu sunt latențe HTTP garantate.
- `equivalence-trial.json`: încercarea anterioară cu materializare forțată, inclusiv regresia daily la 116 s; **nu este implementarea finală**. `daily-final-equivalence.json` confirmă corecția pe alt snapshot, cu raport identic și fără acea regresie.
- `api-verified.json`: trei runde HTTP sub sarcina verificărilor, inclusiv daily de 29,78 s. `api-normal-load.json`: eșantion ulterior. Timpii variabili și cache-ul vechi sunt păstrați explicit, nu eliminați pentru a prezenta numai cazurile rapide.
- `index-build.json`: progresul workerului normal până la 198.820 candidați indexați; prima captură avea deja 8.999, deci diferența timestampurilor nu este durata completă de la zero.
- `live-collection.json`: șase criterii trecute, 111 s, 3 capturi alerte / 5 control, în ferestrele promise și în intervalul verificării. Numărul capturilor distincte nu este numărul de tokenuri profitabile.
- `live-ui.json` și PNG-urile: browser pe API real fără interceptări, 50 rânduri, nouă destinații, 320–1536 px, zero erori JavaScript. HTTP 507 al backupului insuficient este așteptat și păstrat în log.
- `preservation-before.json`/`preservation-after.json`, `frozen-sources.json`: configurația, regulile, declarațiile, conturile și înregistrările originale de referință păstrate. Numerele de candidați/observații continuă să crească prin colectarea normală.
- `runtime-final.json`, `storage-final.json`: stare la momentul capturii, nu garanție de uptime sau capacitate viitoare. Backupul complet al producției este încă blocat de spațiu.
- `source-manifest.json`: hashurile fișierelor de runtime/test/config; acestea rămân identice cu sursa CI după commitul de documentație.

Repetare după pornirea normală, cu portul afișat de launcher:

```bash
uv run --frozen pytest -q
uv run --with playwright python tests/browser_audit.py
uv run --frozen python -m app.collection_verify --url http://127.0.0.1:8001 --duration 900 --output live-collection.json
uv run --frozen python -m app.storage status --data-dir data
```

Nu reseta pilotul, nu schimba pragurile pentru a forța criteriile și nu interpreta observațiile lipsă ca profit zero. Tranzacțiile reale, AI plătit și Telegram nu au fost activate.
