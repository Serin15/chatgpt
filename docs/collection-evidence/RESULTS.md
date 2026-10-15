# Dovezi v0.8 — 15 octombrie 2026

Problema a fost reprodusă înainte de modificare pe datele reale: **6402** prime evaluări fără
alertă nu aveau observație de intrare la timp. Coada raportată avea **9962**
candidați scadenți și **3639** fără încercare de îmbogățire.
[Snapshot original](before.json), commit de bază `81186cee42568093c11e2faadaf17d3dd586e672`.

## Servicii reale

[Prima probă](live-first-pass.json), la `2026-10-15T03:58:16.147530+00:00`, dintr-un director de date nou, cu workerul
normal și API-uri publice. Fără injectare de tokenuri, praguri relaxate, ordine manuale sau
tranzacții reale:

| Grup | Intrări observate în fereastră | Termene de intrare ratate | Încă în așteptare |
| --- | ---: | ---: | ---: |
| Alerte | 10 | 0 | 0 |
| Control fix | 25 | 0 | 3 |

La acel moment existau și **4** ferestre de ieșire observate pentru
alerte. Controlul avea încă ieșiri viitoare în așteptare. Acoperirea observațiilor nu înseamnă că
tokenurile sunt sigure, toate intrările sunt modelabile sau rezultatele sunt profitabile.
Un eșantion scurt nu garantează aceeași acoperire la alte încărcări ori în timpul unei întreruperi.

[Verificarea ulterioară](live-final.json) conține exemple cu contracte, chain, ora cotației,
ora observației și termenele originale, în ambele grupuri. [Regresia live a întregului flux](core-regression-live.json)
a trecut toate cele opt criterii Level 3, inclusiv un rezultat paper ulterior și dashboardul.
Telegram live rămâne neverificat; nu era necesar pentru această modificare.

Proba finală a colectării, cu toate cele **6 criterii trecute**, este
[live-checkpoints.json](live-checkpoints.json), la `2026-10-15T04:17:31.541884+00:00`:

| Grup | Intrări observate | Ieșiri observate | Repere de preț observate | Termene ratate |
| --- | ---: | ---: | ---: | ---: |
| Alerte | 23 | 16 | 0 | 0 |
| Control fix | 88 | 3 | 1 | 0 |

Mai existau intrări și orizonturi viitoare în așteptare. Reperul de control la 5 minute a păstrat
cotația chiar dacă filtrul paper a respins tokenul: [dovadă](rejected-checkpoint.json).
O încercare observată nu înseamnă fill valid. [Verificarea interfeței cu date reale](browser-live.json)
a confirmat panoul, reperele, lipsa erorilor JavaScript și lățimea de 390px.
Capturi: [desktop](../screenshots/memescope-collection-desktop.png),
[mobil](../screenshots/memescope-collection-mobile.png).

Comenzi executate:

```bash
DATA_DIR=/workspace/memescope-observations-live .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8766
.venv/bin/python -m app.collection_verify --duration 900 --output /tmp/memescope-observation-live-proof.json
.venv/bin/python -m app.collection_verify --duration 120 --output /tmp/memescope-observation-live-final.json
.venv/bin/python -m app.collection_verify --duration 900 --output /tmp/memescope-observation-checkpoints-live.json
UV_CACHE_DIR=/workspace/.cache/uv uv run --with playwright python -m app.level3_verify --existing-url http://127.0.0.1:8766 --duration 120 --browser /usr/bin/chromium --output /tmp/memescope-observation-core-proof.json
```

[Proba migrării](migration.json) folosește copia bazei reale, nu fixture-uri. Hashurile tabelelor
`opportunity_signals`, `opportunity_outcomes` și `orders` sunt identice înainte/după migrare.
Se adaugă înscrieri și sarcini viitoare; starea istorică nu este reconstruită sau îmbunătățită artificial.
Conturile manuale păstrează zero ordine. [Instanța principală](production.json) a pornit v0.8.
Arhiva istorică încă neîmbogățită rămâne vizibilă, cu prioritate limitată; nu pretindem că a fost
observată complet doar fiindcă verificările vechi au fost reprogramate mai rar.

## Teste cu date simulate

[pytest.txt](pytest.txt): **263 passed**, un avertisment de deprecare Starlette/httpx.
[lint.txt](lint.txt): Ruff a trecut; verificările Node pentru toate cele trei fișiere JS au trecut.
Comenzi: `uv run pytest -q`, `uv run ruff check app tests`, `node --check app/static/app.js`,
`node --check app/static/advanced.js`, `node --check app/static/opportunities.js`.
Furnizorii HTTP/RPC sunt fixture-uri
explicite. Cele 19 regresii noi verifică apartenența fixă la control, concurența cu un backlog mare
de alerte, bugete mici, termenele reale, suprapunerile, erori API, date preluate prea devreme,
cohorte istorice separate, reluarea orizonturilor după migrare, păstrarea configurației personalizate,
expirarea termenelor în API, securitatea expirată în statistici și reperele de control după respingere.

[Browser](browser-tests.json): Chromium real cu baze temporare și furnizori simulați. Include
panoul de colectare, bugetul salvat din interfață, 390px și regresiile existente de navigare,
dosare, știri defecte, export și backup. Acestea sunt distincte de probele cu API-uri reale.
Comenzi: `uv run --with playwright python tests/browser_opportunities.py`,
`uv run --with playwright python tests/browser_regressions.py` (Chromium instalat în mediu).

## Pachet descărcat și Windows nativ

Codul verificat este commitul `1391fb1b0375e00d12f5aae90d2c7b169e73c786`.
[GitHub Actions](https://github.com/Serin15/chatgpt/actions/runs/38680775088) a trecut pe
**Ubuntu și Windows**, inclusiv pasul Windows nativ `start-windows.cmd` dintr-o cale cu spații.
[ci.json](ci.json) păstrează concluziile reale ale joburilor și pașilor; nu este o simulare Windows.

[package.json](package.json) păstrează URL-ul, dimensiunea și SHA-256 al ZIP-ului efectiv
descărcat din GitHub. Pe Linux a fost extras într-o cale cu spații, diacritice și `&`, cu
dependențe/date noi, și a pornit din alt director curent. `/api/status` a confirmat v0.8.0,
cei cinci workeri, AI oprit, tranzacții reale dezactivate și conturi noi $500/$100 fără ordine.
Această probă Linux este separată de proba Windows din CI.

Pe Windows: descarcă arhiva, **Extrage tot**, apoi pornește `start-windows.cmd`. Dintr-un
terminal în proiect, comenzile comune sunt `uv sync --frozen` și
`uv run --frozen python -m app.desktop`. Necesită Python 3.12+ sau uv; nu este un executabil
care include Python. [Instrucțiuni](../../DESCHIDE-APLICATIA.md).

Instanța principală continuă colectarea pe datele existente. Instanța separată folosită pentru
probe a fost oprită după salvarea dovezilor și a unui backup SQLite consistent; lipsa observațiilor
după oprirea ei nu reprezintă un rezultat favorabil și nu intră în proba de mai sus.

## Limite

Comparația înainte/după demonstrează defectul de programare și funcționarea noului colector în
proba observată. Regimurile au trafic, bugete și intervale diferite; nu este un experiment statistic
care dovedește superioritatea semnalelor sau o rată de acoperire garantată. Vechile lipsuri rămân
în raport. 1h/24h și perioadele de test necesită timp și date noi. Nu există concluzie de profitabilitate.
