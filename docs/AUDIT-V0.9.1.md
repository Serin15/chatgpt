# MemeScope v0.9.1 — audit, corecții și dovezi

Audit din 15 octombrie 2026, pornind de la commitul public
`f92be2208b0d678884712d21a9d2daec7f9d3194`. Codul a fost modificat, problemele au
regresii executabile, iar instanța cu istoricul existent a fost repornită fără resetarea conturilor.
Tranzacțiile reale rămân dezactivate. Aceasta este o verificare a comportamentelor descrise mai
jos, fără o garanție că orice defect posibil ori indisponibilitate viitoare a furnizorilor a dispărut.

## Probleme reproduse și reparate

| Problemă | Corecție și dovadă |
| --- | --- |
| Un refuz Jupiter pentru impact devenea „JSON/schema incompatibilă” | `Rejected` moștenește `ValueError`; tratarea excepțiilor păstrează acum motivul de risc. Refuz real verificat și regresie izolată. |
| RPC cu HTTP 200 și eroare JSON-RPC rămânea „ok” | Starea furnizorului devine eroare și pentru refuzurile din validarea aplicației. |
| Un răspuns on-chain fără mint valid lăsa starea „ok” | Validarea tokenului actualizează explicit starea adaptorului. |
| Erorile scenariilor automate Jupiter lipseau din indicatorul general | `routed_quotes` intră în agregare; indicatorul poate fi deschis pentru a identifica fiecare componentă. |
| `1e999` și `-1e999` deveneau numere infinite în JSON | Citirea comună respinge și depășirile numerice, alături de NaN/Infinity; structurile excesiv de adânci devin erori de sursă. |
| Sesiunile vechi rămâneau valide după schimbarea parolei | Sesiunile sunt legate prin HMAC de parola folosită la autentificare. Migrarea invalidează sesiunile vechi fără această legătură; nu stochează parola. |
| Autentificările simultane puteau ocoli limita de încercări | Actualizarea limitei și verificarea autentificării sunt protejate de un lock între threaduri. Regresia pornește simultan opt cereri. |
| Backupul dintr-un folder cu `#` putea produce o arhivă cu baze goale | Căile SQLite folosesc URI escapate corect. Testul restaurează efectiv ambele baze și verifică soldurile și integritatea, inclusiv într-o cale cu `%`, `&` și diacritice. |
| Căutarea și filtrul de verdict inspectau doar prima pagină încărcată | Filtrarea are loc în SQLite înainte de paginare; numărul total de potriviri este afișat. `%` este text literal, iar căutarea tratează Unicode prin casefold. |
| O observație datată în viitor putea ocupa primul loc | Clasamentul verifică ambele limite ale ferestrei de prospețime și normalizează timestampurile pentru comparație. |
| Un raport Jupiter lent bloca afișarea candidaților | Secțiunile se încarcă independent; erorile sunt vizibile și datele păstrate sunt etichetate. Pornirea după verificarea sesiunii permite și ea încărcare independentă de știri. |
| Selectările rapide puteau afișa dosarul cererii mai vechi | Răspunsurile sunt acceptate numai dacă aparțin selecției și cererii curente. |
| Dovezile deschise din dosar se închideau la actualizare | Starea secțiunilor deschise se păstrează pentru același candidat. |
| Eșecul confirmării primei alerte oprea redarea alertelor următoare | Toate alertele sunt construite înainte de confirmări; fiecare confirmare gestionează separat eșecul. |
| Actualizarea periodică ștergea paginile suplimentare încărcate | Pagina de descoperiri recente reîncarcă adâncimea deschisă, cu deduplicare și protecție împotriva răspunsurilor întârziate. |
| Telegram manual accepta alt destinatar ori ID boolean/zero | Ambele fluxuri folosesc validare comună a destinatarului și a unui ID de mesaj întreg pozitiv. Rezultatul ambiguu nu este retrimis automat. |
| Raportul forward mai vechi arăta profit zero fără rezultate evaluabile | PnL agregat rămâne `null`, afișat ca necunoscut. |
| Verificatorul live pierdea raportul la deconectarea serviciului | Scrie criteriile parțiale, eroarea și ordine necunoscute ca `null`; întoarce eșec, fără a raporta succes. |
| Panourile tehnice împingeau monedele prea jos | Lista candidaților apare înaintea rapoartelor tehnice, inclusiv când acestea sunt deschise. Panoul de colectare era deja pliabil în codul inițial; captura nu dovedea o deschidere automată. |

Fișierele de execuție și calcul financiar nu au fost rescrise. Pentru compatibilitatea scenariilor
Jupiter în curs, [comparația AST](audit-v091/route-compatibility.json) arată că funcțiile de fill,
conversie, validarea cotațiilor acceptate și clasa `Routes` sunt neschimbate; se schimbă ordinea
tratării refuzurilor. Doar hashurile auditate sunt compatibile. Nu au fost recalculări retroactive
ale rezultatelor, resetări ale termenelor sau completări istorice cu prețuri viitoare.

## Testare efectivă

- **303 teste unitare/de integrare trecute**, inclusiv 19 verificări noi de audit.
  Un avertisment de deprecări Starlette/httpx rămâne; nu a fost ascuns.
- Pe o copie extrasă din commitul inițial, aceleași regresii noi au produs
  **15 eșecuri și 4 treceri**. [Reproduceri](audit-v091/before.txt).
- **10 scenarii noi de browser trecute** cu furnizori izolați:
  [înainte](audit-v091/browser-before.json), [după](audit-v091/browser-after.json).
- Au trecut și cele șapte scripturi de browser existente: oportunități, regresii generale,
  știri blocate, smoke/manual paper, autentificare/advanced, AI și documente/anunțuri.
- Ruff și cele trei verificări de sintaxă Node au trecut. Auditul PyPI al dependențelor
  instalate nu a raportat vulnerabilități cunoscute: [rezultat](audit-v091/dependencies.json).
- [Migrarea pe o copie a bazei reale](audit-v091/migration.json): **13.078 candidați**,
  tabelele de istoric comparate prin hash neschimbate, integritate SQLite OK, șase API-uri cu HTTP 200.
- [Instanța existentă](audit-v091/production.json): v0.9.1, cinci workeri porniți,
  conturi Research **$500**, Scanner **$100**, **zero ordine**, execuție reală dezactivată.
- [Browser cu date reale păstrate](audit-v091/browser-live.json): listă, stări explicate,
  dosar cu rezultat Jupiter ulterior și mobil de 390 px, fără erori JavaScript.

Comenzi executabile, din rădăcina proiectului:

```bash
uv sync --frozen
uv run --frozen ruff check app tests
uv run --frozen pytest -q
node --check app/static/app.js
node --check app/static/advanced.js
node --check app/static/opportunities.js
uv run --with playwright python tests/browser_audit.py
uv run --with playwright python tests/browser_opportunities.py
uv run --with playwright python tests/browser_regressions.py
uv run --with playwright python tests/browser_slow_news.py
uv run --with playwright python tests/browser_smoke.py
uv run --with playwright python tests/browser_advanced.py
uv run --with playwright python tests/browser_ai.py
uv run --with playwright python tests/browser_announcements.py
```

Scripturile de browser existente cer Chromium la `/usr/bin/chromium`; noul script acceptă și
`BROWSER_EXECUTABLE`. CI include acum și noul audit Chromium pe Linux. Rezultatul CI Windows/Linux
și verificarea ZIP-ului publicat sunt înregistrate separat după publicarea codului.

## Servicii reale: ce s-a verificat

[Fluxul principal](audit-v091/pipeline-live.json) a trecut **8/8 criterii** în 433 secunde, pe o
bază izolată nouă și furnizori reali. Exemplu descoperit automat: contract Solana
`9a98oQHtxfqmr4EyzsP6wfw69uYAK3JbUeVEuNW1pump`. Criteriile includ securitate/piață,
scoruri, verdict cu dovezi, persistență, alertă afișată cu receipt, observație viitoare și
rezultat paper afișat în browser. Telegram nu a fost folosit.

[Jupiter](audit-v091/routes-live.json) a trecut **5/5 criterii** pe istoricul aceleiași instanțe.
Pentru `HMYd9tosnUXuNHmq7pXmoePRVBLBBjA3JBfydq6upump`, semnalul 115 are intrare virtuală
cu cotație la **07:51:52 UTC**, ieșire cu o cotație nouă la **07:58:24 UTC**, aceeași cantitate
și **PnL net virtual −$1,6870733251212**. Orizontul nominal este 5 minute, iar durata observată
392,36 secunde, în fereastra înghețată. Rezultatul negativ este păstrat împreună cu refuzurile,
încercările eșuate și observațiile lipsă. Este o verificare a conectării sistemului, fără dovadă
de profitabilitate. Comisioanele de conversie/rețea rămân ipoteze configurate.

Demonstrația principală își închide automat serverul. Primul verificator Jupiter a fost întrerupt
din această cauză: [încercarea păstrată](audit-v091/routes-initial-interrupted.txt). Verificatorul
a fost corectat, instanța normală a fost repornită cu aceeași bază izolată, iar verificarea
ulterioară a citit rezultatul stocat. Nu au fost injectate tokenuri, schimbate praguri, resetate
termene sau retrimise cotații eșuate pentru a obține un rezultat mai bun.

[Cotații GET directe](audit-v091/services-live.json): o cotație WSOL validă și un refuz pentru
impact la un token real, acum etichetat corect `Rejected`. Accesul Jupiter fără cheie a funcționat
în acest mediu; nu este garantat pentru alte medii ori în viitor.

[Ollama real](audit-v091/ai-live.json): două generări locale finalizate cu citări pe un set înghețat
de **dezvoltare**, un extras observat și un caz sintetic. Nu sunt transporturi simulate. Verificarea
semantică a ieșit cu **cod 1**, cu o etichetă finală corectă din două; modelul a propus o asociere
falsă, blocată de gate. Regula conservatoare a lăsat ambele asocieri insuficient dovedite, inclusiv
cazul pozitiv. Predicțiile brute au avut o etichetă corectă din două. Nu declarăm modelul precis și nu
relaxăm verificarea dovezilor pentru a îmbunătăți artificial scorul. Setul de test nu a fost folosit
pentru ajustări. AI rămâne opțional și dezactivat pe instanța cu datele utilizatorului.

Citirea live a paginii Anthropic a reușit. URL-ul Circle vechi
`/stablecoins/usdc-on-main-networks` a răspuns **HTTP 404**; pagina canonică actuală
[`/stablecoins/usdc-contract-addresses`](https://developers.circle.com/stablecoins/usdc-contract-addresses)
a fost citită și verificată prin hash. Nu au fost ocolite regulile de citire sau urmate redirecturi
către domenii neacceptate. Un URL dispărut rămâne indisponibil și nu confirmă o afirmație.

Comenzi pentru o nouă verificare live:

```bash
# Director NOU; scriptul pornește și oprește propria instanță.
uv run --with playwright python -m app.level3_verify --data-dir /tmp/memescope-fresh-proof --duration 1200 --browser /usr/bin/chromium --output /tmp/core-proof.json

# Pentru Jupiter, păstrează o instanță normală deschisă într-un alt terminal.
DATA_DIR=/tmp/memescope-routes-fresh uv run --frozen python -m uvicorn app.main:app --host 127.0.0.1 --port 8767
uv run --frozen python -m app.routes_verify --url http://127.0.0.1:8767 --duration 1200 --output /tmp/routes-proof.json

# Opțional: un model Ollama deja instalat; poate produce evaluări nereușite, păstrate în raport.
uv run --frozen python -m app.ai_evaluation --run-model --provider ollama --model pulse-qwen7b-audit:latest --partition development --limit 2 --output /tmp/ai-proof.json
```

## Starea funcțiilor și limitările rămase

| Funcție | Stare și limită practică |
| --- | --- |
| Descoperire/enrichment Solana | Implementată și verificată live; univers parțial de feeduri, fără garanția tuturor lansărilor. |
| Filtre, scoruri, verdict și alertă în aplicație | Implementate și verificate live; euristici cu necunoscute explicite, fără probabilități de câștig. |
| Tracking și scenarii paper din pool | Implementate și verificate live; costuri/impact estimate și observații lipsă păstrate. |
| Scenarii Jupiter cu ieșire viitoare | Implementate și verificate cu cotații reale; execuția on-chain nu este realizată sau garantată. |
| Paper manual, jurnal, export, backup | Verificate în browser cu fixture-uri; migrare/backup verificate și pe date păstrate, fără ordine în conturile reale ale utilizatorului. |
| Ollama | Integrare verificată cu generări reale; evaluarea semantică a eșuat pe eșantionul mic. Calitatea modelului rămâne insuficient demonstrată. |
| OpenAI | Implementată și testată cu fixture-uri; neverificată live în acest audit: lipsesc cheia și accesul la un model cu credit API. |
| Știri și documente | Integrare păstrată; [starea live](audit-v091/live-status.json) și [citiri de documente](audit-v091/documents-live.json) indică rezultatele surselor. Anthropic/Circle sunt documente publice, fără integrare în API-uri comerciale ale acelor companii. |
| Afiliere, fundamentale și audit de contract | Parțiale prin dovezi/manual, observații și necunoscute. Numele sau menționarea unui contract nu confirmă emitentul, echipa, auditul, unlocks ori tokenomics. |
| Wallet intelligence | Parțială, read-only, pentru walleturi configurate; nu dovedește acumulare smart-money, PnL sau proprietari reali. |
| Base | Discovery/cercetare parțiale, în afara clasamentului automat Solana; nu este declarat Level 3 complet. |
| Telegram | Două fluxuri implementate, destinație/receipt testate cu mock-uri; livrare reală blocată de lipsa botului și chatului configurate. |
| Găzduire cu autentificare | Autentificare/CSRF/logout verificate în browser; publicarea HTTPS este blocată de domeniu/DNS/server și configurarea administratorului. |
| Performanță predictivă | Nedemonstrată: cohortă prospectivă cu politică declarată și eșantion suficient încă necesare. Un rezultat paper ori un test tehnic reușit nu demonstrează un avantaj financiar. |

Priorități rămase: **P1**, calitatea analizei AI și evaluare prospectivă fără leakage; verificarea
OpenAI/Telegram când există acces; **P2**, acoperire de date pentru deținători, deployer, social,
fundamentale și Base; **P3**, publicare găzduită dacă se dorește. Aceste limite nu au fost înlocuite
cu date inventate. Orizonturile noi de 1h/24h cer timp efectiv și nu sunt validate de experimentul scurt.

## Instalare, chei și costuri

Pe Windows: închide aplicația veche, păstrează o copie a folderului `data`, extrage versiunea nouă
și copiază `data` în folderul ei. Deschide **`start-windows.cmd`**. Dacă autentificarea este activată,
actualizarea cere o nouă autentificare pentru sesiunile vechi. Launcherul afișează portul efectiv.

```powershell
uv sync --frozen
uv run --frozen python -m app.desktop
```

Nu sunt necesare chei noi pentru fluxurile publice verificate și nu a fost cumpărat un abonament.
Furnizorii pot impune limite sau acces cu cheie. Opțional: `JUPITER_API_KEY[_FILE]`,
`PULSE_AI_API_KEY[_FILE]`/`OPENAI_API_KEY[_FILE]`, model disponibil, credit OpenAI;
`TELEGRAM_BOT_TOKEN[_FILE]`, `TELEGRAM_CHAT_ID`; RPC propriu Solana/Base pentru capacitate suplimentară.
Secretele se introduc în mediu sau fișiere externe Git, niciodată în chat ori cod.

Cost suplimentar API în verificările acestui audit: **$0** cumpărat. Ollama utilizează resursele
mașinii; infrastructura și energia nu sunt evaluate monetar aici. Costul OpenAI depinde de model,
numărul de cereri și tokeni, conform tarifului curent al furnizorului; nu presupunem un abonament
ChatGPT ca acces API. Găzduirea și RPC-urile plătite necesită o ofertă separată.

Fișierele schimbate: backend `auth.py`, `forward.py`, `http_client.py`, `jupiter.py`, `main.py`,
`maintenance.py`, `notifications.py`, `onchain.py`, `opportunities.py`, `opportunity_routes.py`,
`providers.py`, `routes_verify.py`; cele cinci fișiere UI din `app/static`; două scripturi noi de teste,
workflow CI, versiunea proiectului/lockfile și documentația/dovezile. Versiunile dependențelor
din lockfile au rămas neschimbate.
