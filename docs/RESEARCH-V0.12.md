# MemeScope v0.12 — surse, referințe de pool și evaluare prospectivă

Continuarea celor trei priorități: legătura știre–token, calitatea surselor și
comparația rezultatelor după costuri. Execuția cu bani reali rămâne dezactivată.
Nu s-au trimis mesaje Telegram și nu s-au plasat ordine în portofoliile virtuale.

## Modificări

- Feedurile directe păstrează până la 30 de articole acceptate, cu prioritate
  pentru titlurile memecoin. Căutările Google rămân limitate la 10. Colectorul
  documentelor inspectează independent până la 250 de știri recente, fără să
  depindă de limita de 100 de rânduri a ecranului. Bugetul rămâne trei documente
  per refresh, cu backoff și fără redirecturi.
- Titlurile suficient de lungi, identice după normalizare și publicate într-un
  interval de șase ore se grupează în panoul de dovezi. Rândurile originale,
  dosarele și sursele se păstrează. Documentele cu contracte nu se grupează;
  publicațiile diferite nu sunt declarate surse editoriale independente.
- Un link explicit `dexscreener.com/solana/<pool>` dintr-un document permis poate
  fi rezolvat prin API-ul DEX Screener: maximum două referințe/document, opt
  secunde/cerere, fără căutare după nume. Se compară chain-ul și pool-ul, apoi se
  validează separat adresele base/quote, prețul, lichiditatea și timestampurile.
  Adresa pool-ului nu devine mint. API-ul răspunde cu identitatea pieței, nu cu
  dovada emitentului. Se păstrează hashul răspunsului JSON canonicalizat.
- Numai perechile cu SOL/USDC/USDT drept cotație și context fără negare pot
  iniția cercetarea automată. Celelalte referințe rămân dovezi limitate. Toți
  candidații noi trec prin filtrele normale de securitate/lichiditate/scoruri.
  O referință de pool nu primește bonusul narativ rezervat mențiunii exacte.
  Creșterea anterioară de 24h raportată la rezolvarea referinței este marcată ca
  extensie excesivă dacă depășește pragul existent; datele viitoare nu se folosesc.
- Bilanțul zilnic compară separat fiecare politică, orizont și cohortă
  development/test/neatribuit/graniță exclusă. Arată selecția inițială, controlul
  fix, suprapunerea și controlul fără selecții. Include experimentele planificate
  fără rând de model, modelele dezactivate și rezultatele necunoscute în numitor.
  Diferențele mediilor sunt descriptive și condiționate de rezultatele evaluate.
  Limitele de sensibilitate pentru lipsuri nu sunt probabilități de succes.
- Exportul offline deschide SQLite numai în citire, fără worker, migrare sau
  cereri externe. Scrierea JSON este atomică și nu suprascrie baza printr-un
  hard link. Raportul general extrage doar câmpurile necesare din JSON, evitând
  încărcarea repetată a istoricului complet. Calculele financiare nu s-au schimbat.

## Dovezi și limite

Rezultatele și logurile sunt în [research-evidence/RESULTS.md](research-evidence/RESULTS.md).
Testele cu fixture-uri sunt separate de cererile reale și de simulările paper.

Pe 19 octombrie 2026, Decrypt și Cointelegraph au răspuns HTTP 200. Motorul normal
a colectat știri reale, iar browserul a afișat comparația stocată pentru 18
octombrie, fără erori JavaScript/API și fără overflow la 390 px. Un articol real
mai vechi a permis identificarea unui mint prin linkul de pool; nu a fost
introdus în univers ca știre nouă. Perechea avea cotație nesuportată și nu a fost
acceptată pentru descoperire automată.

**O știre nouă eligibilă → candidat nou → alertă livrată → outcome pe aceeași
dovadă nu a fost demonstrată live în această etapă.** Calea pozitivă are teste cu
fixture-uri. Un articol vechi, o alertă din altă rută sau un test simulat nu
completează acest criteriu. Nu s-au injectat tokenuri/știri, relaxat filtre,
backdatat date sau fabricat confirmări de livrare.

Evaluarea offline a cohortei din 18 octombrie, înaintea reluării colectării, a
numărat 1.590 candidați, 1.587 prime evaluări și 53 selecții inițiale. La 5 minute:

| Model | Selectate evaluate/planificate | Control fără suprapunere evaluate/planificate |
| --- | --- | --- |
| Pool estimat | 28/53; 25 necunoscute | 1/297; 296 necunoscute |
| Jupiter, scenarii de cotații | 13/53; 40 necunoscute | 0/297; 297 necunoscute |

Mediile nete ale rezultatelor **evaluate** în modelul de pool au fost $4,95 și
−$22,74 pentru poziții independente de $50. Acoperirea inegală, corelațiile și
selecția împiedică o concluzie de superioritate sau profitabilitate. La 24h nu
există rezultate evaluate în acest eșantion. Lipsurile nu înseamnă zero pierdere,
ieșire posibilă sau token confirmat nevandabil. Modelul de pool și cotațiile
Jupiter nu demonstrează executarea unui swap on-chain.

Cutoff-ul vechi `2026-10-18T00:00:00Z` și politicile anterioare se păstrează.
Politicile noii implementări, declarate după acest cutoff, sunt neatribuite;
nu pot revendica vechiul holdout. Raportul este o cohortă zilnică cu rezultate
cunoscute la generare, nu o reconstrucție istorică „as of”. Cele trei evaluări
încă lipsă pot apărea ulterior, cu data și politica lor efective.

## Instalare și verificare

Windows: oprește instanța veche, salvează integral `data`, extrage proiectul nou,
copiază `data` în el și rulează `start-windows.cmd`. Alternativ, din directorul
care conține `pyproject.toml`:

```powershell
uv sync --frozen
uv run --frozen python -m app.desktop
```

Linux/cloud:

```bash
cd /workspace/chatgpt
UV_CACHE_DIR=/workspace/.cache/uv uv sync --frozen
.venv/bin/python -m app.desktop --no-browser
```

Verificare fără modificarea bazei, pe o instanță pornită normal:

```bash
.venv/bin/python -m app.story_verify --duration 900 --output /tmp/story.json
.venv/bin/python -m app.story_verify --duration 900 --evidence-kind market_reference --output /tmp/market-reference.json
.venv/bin/python -m app.research_evaluate --data-dir data --day 2026-10-18 --output /tmp/holdout.json
.venv/bin/pytest -q
.venv/bin/ruff check app tests
node --check app/static/opportunities.js
UV_CACHE_DIR=/workspace/.cache/uv uv run --with playwright python tests/browser_audit.py
```

Pe Windows poți înlocui `.venv/bin/python` cu `uv run --frozen python`.
Verificatorul iese cu codul 1 dacă lipsesc criterii; codul 0 necesită întregul
lanț pentru același candidat. Modul implicit cere mențiune directă de contract;
modul `market_reference` verifică distinct referința și răspunsul API identic.
Niciun mod nu plasează ordine sau confirmări artificiale de livrare.

## Servicii, costuri și ce rămâne

Nu sunt necesare abonamente/chei noi pentru acest cod. Se folosesc catalogul
existent de știri, DEX Screener, feedurile de pool, Solana RPC, GoPlus și Jupiter.
La fiecare refresh de știri, referințele pot adăuga cel mult șase cereri DEX;
refreshul normal este la cinci minute. Disponibilitatea publică, limitele și
licențele pentru redistribuire comercială trebuie verificate înainte de lansare.
Cost incremental de abonament în această etapă: $0; nu s-au cumpărat servicii.

AI este opțional: OpenAI cere credit API separat și un model disponibil, prin
`PULSE_AI_API_KEY`/fișier; Ollama cere serviciu și model instalat. Această etapă
nu demonstrează precizia unui model. `JUPITER_API_KEY` poate deveni necesară dacă
accesul fără cheie este refuzat. Telegram cere bot, chat ID și activare explicită;
livrarea Telegram nu a fost testată. Cheile și bazele nu intră în Git.

Priorități rămase:

1. Prima dovadă recentă eligibilă și urmărirea completă a aceleiași oportunități.
2. Colectare susținută, cu măsurarea și reducerea lipsurilor pentru selecții și
   control. Pauzele de funcționare nu pot fi reparate cu prețurile curente.
3. Un protocol prospectiv separat pentru versiunea finală, declarat înainte de
   datele sale de test, fără reglarea pragurilor pe rezultatele prezentate aici.
4. Reducerea creșterii bazei și a timpului rapoartelor pentru operare de durată,
   păstrând toate semnalele/outcome-urile. Gazda trebuie să rămână pornită pentru
   funcționare continuă; nu s-a făcut o găzduire publică în această etapă.
