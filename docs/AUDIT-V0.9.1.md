# MemeScope v0.9.1 — audit, corecții și dovezi

Audit din 15–16 octombrie 2026, pornind de la commitul public
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
| Erorile documentelor grupate pe domenii apăreau ca `[object Object]` | Panoul de stare afișează conținutul erorilor structurate, inclusiv domeniul și motivul, cu regresie în browser. |
| `1e999` și `-1e999` deveneau numere infinite în JSON | Citirea comună respinge și depășirile numerice, alături de NaN/Infinity; structurile excesiv de adânci devin erori de sursă. |
| Adaptorul mai vechi folosea încă un parser JSON permisiv | RPC/DEX/GoPlus folosesc acum aceeași decodare strictă; două regresii suplimentare reproduc overflow/NaN și verifică starea de eroare. |
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

- **305 teste unitare/de integrare trecute**, inclusiv 21 verificări noi de audit.
  Un avertisment de deprecări Starlette/httpx rămâne; nu a fost ascuns.
- Pe o copie extrasă din commitul inițial, primele 19 regresii noi au produs
  **15 eșecuri și 4 treceri**. [Reproduceri](audit-v091/before.txt).
  Cele două cazuri suplimentare ale adaptorului vechi au eșuat înaintea corecției:
  [reproducere separată](audit-v091/legacy-json-before.txt).
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
`BROWSER_EXECUTABLE`. Pe codul final
`1d7fca258aedb39235a9722be17eb505b48f1906`,
[CI GitHub Actions](https://github.com/Serin15/chatgpt/actions/runs/38707372941)
a trecut pe ambele sisteme: **305 teste pe Ubuntu și 305 pe Windows**, plus auditul Chromium
pe Linux și pornirea nativă a launcherului Windows dintr-o cale cu spații. Rezultatele etapelor
sunt în [ci.json](audit-v091/ci.json), iar numerele extrase din arhiva oficială de loguri sunt în
[ci-test-counts.json](audit-v091/ci-test-counts.json). Testele folosesc fixture-uri și nu constituie
verificarea serviciilor reale.

[Arhiva ZIP verificată](https://codeload.github.com/Serin15/chatgpt/zip/1d7fca258aedb39235a9722be17eb505b48f1906)
corespunde exact acestui cod. [Dovada de pachet](audit-v091/package.json) include dimensiunea,
SHA-256, verificarea CRC și pornirea pe Linux dintr-un alt director, într-o cale cu spații,
`#`, `%`, `&` și diacritice. Instanța temporară a fost oprită după verificare.

Verificarea nativă Windows a expus și două probleme de testare. Mai întâi, wrapperul CI încerca
să afișeze mesajele românești prin cp1252 și se oprea cu `UnicodeEncodeError`; fluxurile sunt acum
UTF-8. După această corecție, s-au văzut două eșecuri paper din fixture-uri care eșantionau separat
ceasul observației și ceasul analizei. O diferență mică putea produce un snapshot de test considerat
din viitor. [Reproducerea controlată](audit-v091/windows-clock-reproduction.json) eșuează înainte
și trece după folosirea unui singur moment în fixture. Regulile de prospețime, date viitoare,
delay și calculele financiare din aplicație nu au fost relaxate. Logurile eșuate sunt păstrate.

## Servicii reale: ce s-a verificat

Dovezile din 15 octombrie de mai jos sunt păstrate ca rezultate istorice, cu timestampurile lor.
La reluarea din 16 octombrie, mediul cloud a restaurat codul urmărit în Git, fără procesele,
bazele ignorate și fișierele temporare ale instanței anterioare. Instalarea `uv sync --frozen`,
cele 305 teste și cele 10 scenarii Chromium au fost refăcute cu succes în mediul nou.
Acest lucru nu dovedește restaurarea istoricului aplicației: bazele utilizatorului trebuie
păstrate separat și nu au fost înlocuite cu rezultatele testelor.

[Revalidarea live din 16 octombrie](audit-v091/final-pipeline-live.json), pe codul final și o bază
izolată nouă, a trecut **8/8 criterii în 344 secunde**. Candidatul 44, contract Solana
`DkKywKToJSbMFzWDU79Lga9CjMhX6NWfMgkQurQZpump`, a fost descoperit automat la
**08:32:51 UTC**. Alerta 3/semnalul 112 are confirmare de afișare în aplicație la **08:33:19 UTC**.
Scenariul de pool de $50 are observație de intrare la **08:33:53 UTC**, observație de ieșire
la **08:38:56 UTC**, durată observată **303 secunde** și rezultat virtual net **−$7,8705739908624**.
Acesta este modelul estimat de pool, separat de cotațiile Jupiter; niciun swap nu a fost executat.
O descoperire nouă în universul observat nu dovedește o lansare nouă a tokenului.

[Verificarea Jupiter din aceeași rulare](audit-v091/final-routes-live.json) a trecut **5/5 criterii
în 411 secunde**, pentru același candidat și semnal. Cotația reală de intrare este din
**08:34:06 UTC**, iar o cotație nouă pentru ieșirea aceleiași cantități este din **08:40:03 UTC**:
durată **357,66 secunde**, rezultat net virtual **−$10,7490867109662**. Include min-out și
ipotezele de conversie/rețea din politica înghețată. Acest rezultat este separat de estimarea de
pool de mai sus; cele două nu se adună. Ambele conturi manuale au **zero ordine**.
Rezultatele negative nu au fost eliminate, iar pragurile, termenele și politicile nu au fost
schimbate pentru a obține acceptarea. Livrarea verificată este în aplicație, fără trimitere Telegram.

[Universul complet al experimentului](audit-v091/final-live-universe.json) păstrează **166 candidați**,
377 observații, 341 semnale și 10 alerte. Cele 175 experimente Jupiter pe semnale au, pentru
orizontul de 5m: **154 intrări respinse, 14 indisponibile, un rezultat evaluat și 6 în așteptare**.
Numitorul este experimentul pe semnal, nu tokenul unic. Rezultatele lipsă nu sunt ieșiri reușite,
profit zero sau pierderi zero. Ambele baze au backup consistent verificat prin integritate SQLite
și SHA-256. Instanța izolată a fost oprită după salvarea dovezilor; noile orizonturi de 1h/24h
rămân neverificate.

[Browserul pe aceste date reale](audit-v091/browser-live-restored.json) verifică dosarul cu rezultatul
ulterior, pagina de candidați și mobilul de 390 px, fără overflow orizontal sau erori JavaScript.
Capturi: [desktop](screenshots/memescope-audit-v091-desktop.png),
[dosar](screenshots/memescope-audit-v091-routed.png), [mobil](screenshots/memescope-audit-v091-mobile.png).
[Pornirea mediului restaurat](audit-v091/restored-startup.json) este verificată separat, într-o bază
nouă implicită; nu pretinde că a recuperat baza istorică absentă din snapshot.

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

## Fișiere schimbate

| Fișiere | Rolul schimbării |
| --- | --- |
| `app/auth.py`, `app/main.py` | Sesiuni legate de credențiale, sincronizarea autentificării și expunerea rezultatelor filtrate în API. |
| `app/maintenance.py` | URI SQLite escapate pentru backupuri din căi speciale. |
| `app/http_client.py`, `app/providers.py`, `app/onchain.py` | JSON numeric strict și stări de eroare pentru validările HTTP/RPC/on-chain. |
| `app/opportunities.py` | Căutare și verdict înaintea paginării, fără observații viitoare în clasament. |
| `app/jupiter.py`, `app/opportunity_routes.py`, `app/forward.py` | Clasificarea refuzului de risc, compatibilitate numai pentru surse auditate și PnL necunoscut când lipsesc rezultate. |
| `app/notifications.py`, `app/routes_verify.py` | Validarea receiptului Telegram și păstrarea dovezilor verificării întrerupte. |
| `app/static/app.js`, `advanced.js`, `opportunities.js`, `index.html`, `style.css` | Încărcare independentă, erori explicate, păstrarea paginilor/dosarelor și prioritate vizuală pentru candidați. |
| `tests/test_audit_v091.py`, `tests/browser_audit.py`, `tests/conftest.py` | Regresii noi, scenarii Chromium și un singur ceas coerent în fixture-uri. |
| `.github/workflows/checks.yml` | Chromium în CI Linux și diagnostic UTF-8 fără mascarea codului de ieșire pytest pe Windows. |
| `app/__init__.py`, `pyproject.toml`, `uv.lock` | Versiunea aplicației 0.9.1; versiunile dependențelor din lockfile au rămas neschimbate. |
| `README.md`, `docs/AUDIT-V0.9.1.md`, `docs/audit-v091/*`, capturile `docs/screenshots/memescope-audit-v091-*` | Pornire, rezultate, reproduceri, dovezi reale și limitări. |

[Comparația completă a codului față de începutul auditului](https://github.com/Serin15/chatgpt/compare/f92be2208b0d678884712d21a9d2daec7f9d3194...1d7fca258aedb39235a9722be17eb505b48f1906)
permite verificarea modificărilor. Documentația publicată ulterior adaugă dovezile finale, fără
alte schimbări în codul aplicației.
