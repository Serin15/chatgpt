# Dovezi v0.9 — 15 octombrie 2026

## Servicii și date reale

[Proba completă](pipeline-live.json), capturată la `2026-10-15T06:03:17.445401+00:00`, a trecut **toate cele 5 criterii**.
Instanță nouă, worker normal, feeduri publice, fără injectare de tokenuri, schimbare de praguri,
ordine manuale sau tranzacții reale. Conturile au rămas fără ordine.

Exemplul este candidatul `23`, Solana, contract `CoHH4XfCpEcAuQga8iSr3hCta3vyFxYW6BtQRAV3xQMo`:

- Semnalul `90` a primit cotația de intrare la `2026-10-15T05:57:08.409525+00:00`.
- Cotația token → USDC pentru cantitatea exactă primită a sosit la `2026-10-15T06:03:14.466512+00:00`.
- Orizontul a fost 300s; deținerea efectivă a fost **366.057s**, în fereastra declarată.
- Ambele răspunsuri brute, sloturile, L1 USDC/USD, cantitățile, costurile și politica înghețată sunt
  în fișier. PnL este virtual, după costurile modelate, cu `execution_verified=false`.

La acel snapshot, primul orizont avea **153** prime evaluări, dintre care
**1** cu rezultat rutat evaluat. Stările complete erau:

```json
{
  "entry_rejected": 145,
  "entry_unavailable": 4,
  "evaluated": 1,
  "exit_unavailable": 2,
  "pending": 1
}
```

Acesta este un test de funcționare. Numărul foarte mic de rezultate evaluate, eșecurile și
selecția feedurilor nu susțin o concluzie de profitabilitate. Nu se folosește exemplul pozitiv
pentru ajustarea pragurilor sau pentru promisiuni de randament. 1h/24h sunt încă neverificate
în această probă; necesită trecerea reală a timpului.

[Universul păstrat](universe.json) include toți candidații existenți în baza izolată la captura
sa, inclusiv respingeri, indisponibilități și lipsa unei evaluări. Capturile au ore diferite,
deci numărul candidaților poate crește. Universul feedurilor rămâne parțial.

[Regresia fluxului existent](core-regression-live.json) a trecut toate cele **8 criterii Level 3**,
inclusiv alertă recepționată în browser și rezultat paper ulterior. [Browserul cu date reale](browser-live.json)
a confirmat afișarea rezultatului Jupiter separat de pool, erorile, PnL virtual și 390px fără
JavaScript errors. Capturi: [dosar](../screenshots/memescope-routed-detail.png),
[mobil](../screenshots/memescope-routed-mobile.png). Telegram nu a fost activat sau verificat live.

## Probleme reproduse și corectate

1. Adaptorul vechi refuza local orice cerere fără `JUPITER_API_KEY`. Cererea directă a returnat
   [o cotație validă](initial-direct-quote.json), fără cheie proprie. Acum se încearcă accesul
   disponibil; 401/403 cere credențiale valide și nu produce fill estimat.
2. Coinbase `USDC-USD/book` a răspuns HTTP 404. [Proba inițială](initial-fx-failure.json)
   a eșuat. S-a adăugat L1 Kraken, cu validarea perechii, prețurilor și volumului. Accesul Kraken
   a fost inițial refuzat de proxy; domeniul `api.kraken.com` a fost adăugat în draft. Ulterior,
   instanța a primit efectiv L1 Kraken; salvarea draftului singură nu a fost considerată probă.
3. Nu exista măsurare automată Jupiter forward. Noua componentă păstrează intrarea, ieșirea,
   costurile originale și toate eșecurile, separat de modelul de pool.
4. S-au întărit validările slippage-ului, cantității raw, slotului, intervalului și book-ului.
   Quote-uri incompatibile și securitate expirată au apărut și în proba reală, rămânând eșecuri
   cu PnL necunoscut. Nu sunt înlocuite prin încercări ulterioare mai favorabile.

[Proba directă a adaptorului](adapter-live.json) a trecut separat, cu WSOL drept referință
lichidă și cotații în ambele sensuri. Nu este proba unui token nou și nu validează un holdout.
[Prima verificare scurtă](early-incomplete.json) a rămas incompletă înainte să existe o ieșire;
verificarea finală a așteptat orizontul real. Dovezile incomplete sunt păstrate.

[Migrarea pe copia bazei reale](migration.json) a durat aproximativ 0,202s în acest mediu.
Hashurile tabelelor `opportunity_signals`, `opportunity_outcomes` și `orders` sunt identice
înainte/după; nu s-au creat măsurări Jupiter pentru semnale istorice. Backupurile consistente
ale ambelor baze sunt păstrate în afara Git.

## Teste cu furnizori simulați

[pytest.txt](pytest.txt): **282 passed**, un avertisment de deprecare Starlette/httpx.
[lint.txt](lint.txt): Ruff a trecut. Node a verificat toate cele trei fișiere JS.
Cele **19 teste noi** verifică fluxul complet cu transport HTTP/RPC explicit simulat: cantitatea
exactă la ieșire, costuri/slippage înghețate, autentificare, erori, lipsa unui book, deadline-uri,
claim atomic, restart, răspuns întârziat, versiune schimbată și protejarea controlului.

[browser-tests.json](browser-tests.json): Chromium real cu date simulate, inclusiv setările
rutate salvate, panou separat, navigare, export, backup și mobil. Nu sunt probe de livrare API.

Comenzi executate:

```bash
uv sync --frozen
uv run pytest -q
uv run ruff check app tests
node --check app/static/app.js
node --check app/static/advanced.js
node --check app/static/opportunities.js
uv run --with playwright python tests/browser_opportunities.py
uv run --with playwright python tests/browser_regressions.py
DATA_DIR=/workspace/memescope-routed-live .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8767
.venv/bin/python -m app.routes_verify --duration 600 --output /tmp/memescope-routed-final-live.json
uv run --with playwright python -m app.level3_verify --existing-url http://127.0.0.1:8767 --duration 120 --browser /usr/bin/chromium --output /tmp/memescope-routed-core-regression.json
```

Instalarea a fost rerulată după corectarea unei modificări accidentale a versiunii `annotated-types`
în timpul bump-ului aplicației. Versiunile/hashurile dependențelor sunt neschimbate; numai
versiunea proiectului devine 0.9.0. Nu s-a dezactivat verificarea artefactelor.

## Stare și limite

Codul verificat este `e64772e9792c66418308b53863f9af5506342887`.
[CI](https://github.com/Serin15/chatgpt/actions/runs/38690660632) a trecut pe **Ubuntu și Windows**,
inclusiv pornirea Windows nativă prin `start-windows.cmd` dintr-un folder cu spații.
[ci.json](ci.json) păstrează concluziile reale ale joburilor și pașilor.

[package.json](package.json) păstrează URL-ul, dimensiunea și SHA-256 ale arhivei efectiv
descărcate din GitHub. Pe Linux, a pornit v0.9.0 cu dependențe și date noi, dintr-un alt director
curent, cu o cale care conține spații, diacritice și `&`. AI a rămas oprit, cei cinci workeri au
pornit, iar conturile noi au avut $500/$100 și zero ordine. Aceasta este o probă separată de CI Windows.

Instanța principală rulează v0.9 cu datele păstrate: [production.json](production.json).
Instanța izolată a fost oprită după salvarea dovezilor și a unui backup SQLite consistent,
verificat prin `integrity_check`. Oprirea ei nu transformă observațiile viitoare lipsă în rezultate
favorabile. Instanța principală continuă colectarea cât timp mediul este pornit.

Implementat și verificat: orchestrare rutată, persistență, buy/sell cu servicii reale, FX Kraken,
interfață, costuri înghețate, eșecuri păstrate, migrare și regresii. Neverificat: rezultate live
1h/24h pentru acest cohort, profitabilitate, livrare Telegram și execuție on-chain. Ultima rămâne
dezactivată. Accesul fără cheie în acest mediu nu garantează acces în alt mediu sau în viitor.

[Documentație, configurare și costuri](../ROUTED-PAPER.md). Pasul următor: declararea unei
perioade prospective de test, capacitate/RPC monitorizate și suficiente observații pentru o
comparație cu controlul, fără selectarea retrospectivă a pragurilor.
