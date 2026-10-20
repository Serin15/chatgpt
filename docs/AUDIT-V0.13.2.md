# MemeScope v0.13.2 — audit suplimentar

Șapte probleme confirmate și corectate. Toate au cazuri de regresie reproduse
înaintea corecției. Nu se declară că toate bugurile posibile au fost eliminate.
Codul final al aplicației/testelor: `1abf57cc611459faae8d8732e26516634b1eecea`.

## Probleme și corecții

| Problemă | Corecție și dovadă înainte |
| --- | --- |
| Jupiter compara timestampuri UTC cu `time.time()`, care poate avea altă precizie pe Windows | Același ceas UTC la citirea FX, validarea quote-ului și programare. Cotațiile realmente viitoare/vechi rămân respinse; [regresii](followup-evidence/clock-before.txt) |
| Un cutoff de test deja trecut putea fi acceptat cu ceasul mai puțin precis | Cutoff-urile noi trebuie să fie strict viitoare în UTC. Cutoff-ul existent poate fi păstrat; nu se mută cel original din 18 octombrie |
| `int()` transforma silențios răspunsuri Jupiter fracționare/booleene în cantități întregi | Cantități doar întregi exacte sau șiruri ASCII de cifre; slippage doar întreg, fără bool. Păstrează limitele și validările existente; [8 regresii](followup-evidence/schema-before.txt) |
| SQL elimina fracțiunile de secundă la recuperare și la raportarea termenelor | Compară timestampul întreg prin funcție SQLite, fără expirare prematură. GET-ul raportului rămâne numai în citire; [2 regresii](followup-evidence/deadlines-before.txt) |
| O sursă veche apărea cu „ok” în detalii, deși bara o avertiza | Identitatea sursei și eticheta „date vechi” sunt păstrate separat și consecvent |
| Erorile workerilor erau numărate, dar cauza lipsea din detalii | Workerii au rând separat cu stare, eroare, pornire și reporniri; [ambele regresii UI](followup-evidence/browser-before.json) |
| Verificatorul Jupiter putea combina tokenuri/semnale, accepta un rezultat viitor ori PnL lipsă/nefinit | Urmărește un singur candidat și semnal, leagă ID-urile încercărilor, quote-urile, cantitatea vândută și rezultatul finit după costuri; [7 regresii](followup-evidence/verifier-before.txt) |

## Fișierele modificate

| Fișier | Schimbare |
| --- | --- |
| `app/jupiter.py` | Tipuri exacte ale răspunsului și validarea FX pe ceas UTC |
| `app/opportunity_routes.py` | UTC, timestampuri SQL complete, metadate noi și compatibilitate limitată |
| `app/opportunities.py` | Cutoff nou strict viitor în UTC |
| `app/routes_verify.py` | Dovezi legate de același semnal, încercări, quote-uri și rezultat finit deja observat |
| `app/static/app.js` | Date vechi consistente în detalii și diagnosticele workerilor |
| `tests/test_engine_clock.py`, `test_opportunity_routes.py`, `test_routes_verify.py` | Regresii de clock, schemă, termene, compatibilitate și verificator |
| `tests/browser_audit.py`, `browser_regressions.py` | Stare surse/workeri și formulare corectă pentru o componentă |
| `app/__init__.py`, `app/static/index.html`, `pyproject.toml`, `uv.lock`, README | Versiunea v0.13.2; fără dependențe noi |

## Compatibilitate și date

`app/paper.py` și formulele de umplere/cost rămân neschimbate. Analiza AST,
normalizând doar sursa ceasului, confirmă metodele financiare identice:
[compatibility.json](followup-evidence/compatibility.json). Nu există perioadă
suplimentară de toleranță pentru timestampuri viitoare sau expirate.

Pentru solicitări viitoare, parserul quote-urilor refuză acum tipuri invalide.
Politicile noi înregistrează `timestamp_clock` și `quote_schema_version=2`.
Compatibilitatea execuției în așteptare include strict fingerprintul anterior
`7f7dae89b7e9f79ff350b046112243f379a2025f5941b4bf75b6c62677becb42`, pe lângă
cele două upgrade-uri deja auditate. Hashurile necunoscute rămân blocate.

Testele execută intrare/ieșire pentru toate cele trei implementări anterioare
permise și confirmă că politica salvată nu se schimbă. Refuzurile terminale,
întreruperile și callbacks târzii nu primesc reîncercări favorabile. Duratele
ferestrelor, slippage-ul, costurile și selecția strictă a primei observații
Jupiter rămân păstrate. Această corecție nu implementează alinierea ferestrei
Jupiter cu regula de prefetch v2 a modelului de pool.

Înainte de repornire s-a făcut backup consistent prin SQLite, în afara Git,
pentru ambele baze: [backup.json](followup-evidence/backup.json).
Cele **140.643 de semnale** și **14 politici** existente atunci, împreună cu
configurația, păstrează toate hashurile:
[preservation.json](followup-evidence/preservation.json). Înregistrările noi se
adaugă. Cutoff-ul cloud `2026-10-18T00:00:00Z` rămâne neschimbat; instalațiile
Windows își păstrează propria configurație. Baza principală are aproximativ 3 GB; nu s-au șters ori rescris rezultate.

## Teste izolate

- `uv run --frozen pytest -q`: **455 passed**, un avertisment de deprecare
  Starlette/httpx; [ieșire integrală](followup-evidence/pytest.txt).
- Audit Chromium: **25/25**, cu furnizori izolați și baze temporare;
  [browser.json](followup-evidence/browser.json).
- Browserul de regresie mai vechi: trecut; include erori parțiale, navigare,
  prețuri mici, dovezi, semnal invalidat, mobil, export și backup.
- Cele 42 de teste țintite și cele opt ale verificatorului au trecut separat.
- Ruff, sintaxa JavaScript, `git diff --check` și `uv sync --frozen`: trecute.
  Fără dependențe ori servicii plătite noi.

CI final [39378231747](https://github.com/Serin15/chatgpt/actions/runs/39378231747)
a trecut pe Windows și Linux. Logurile oficiale confirmă **455 teste** pe fiecare
platformă, **25/25** scenarii Chromium pe Linux și pornirea nativă Windows
dintr-un director cu spații: [ci.json](followup-evidence/ci.json).
Rularea v0.13.1, [39262191716](https://github.com/Serin15/chatgpt/actions/runs/39262191716),
s-a încheiat și ea cu succes între timp.

## Verificări reale

[quote real](followup-evidence/live-quote.json): au reușit `getAccountInfo` pe
Solana, cartea USDC/USD Kraken și cotația Jupiter pentru o poziție virtuală de
$50 în SOL. Scriptul permite numai RPC read-only și GET-uri la endpointurile
specifice; nu construiește, semnează sau trimite tranzacții. Costurile/rețeaua
rămân presupuneri de simulare, iar `execution_verified=false`.

[Browser real](followup-evidence/browser-live.json): instanța normală v0.13.2,
fără interceptări sau stare injectată, a trecut navigarea prin toate cele nouă
secțiuni. Panou de maximum 420 px, fără overflow mobil, erori JavaScript sau
omiterea workerilor. Refuzurile reale Jupiter și HTTP 400 rămân vizibile; o
cotație refuzată nu devine un fill fictiv.

Pe instanța normală, candidatul **58879**, semnalul **140946**,
politica **15** cu noul clock/schema, a fost urmărit fără schimbarea
candidatului. Este un candidat din universul general, cu `selected=0` și
`control_member=0`, folosit pentru verificarea cotațiilor. Verificarea inițială
de 90s era incompletă; urmărirea aceluiași
semnal a observat apoi ieșirea la cel puțin cinci minute și un rezultat net
virtual de aproximativ **3,56 USD**, după costurile modelate. Dovezi:
[same-signal-summary.json](followup-evidence/same-signal-summary.json) și
[înregistrarea completă](followup-evidence/same-signal-live.json).
Nu este o tranzacție executată, o dovadă documentară de știre, o rată de succes
sau o demonstrație statistică. Conturile manuale au rămas fără ordine.

Verificatorul corectat a reevaluat și nouă artefacte arhivate:
[archived-proof-recheck.json](followup-evidence/archived-proof-recheck.json).
Patru conțin un traseu Jupiter complet legat de același semnal. Restul nu oferă
toate dovezile Jupiter cerute; unele sunt rapoarte generale/pool sau verificări
inițial incomplete. Fișierele istorice sunt păstrate, cu hashuri. Această
reevaluare nu dovedește execuția versiunii noi sau profitabilitatea.

## Instalare și verificare reproductibilă

```bash
uv sync --frozen
uv run --frozen python -m app.desktop
uv run --frozen pytest -q
uv run --frozen ruff check app tests
node --check app/static/app.js
uv run --frozen --with playwright python tests/browser_audit.py
uv run --frozen --with playwright python tests/browser_regressions.py
uv run --frozen python -m app.routes_verify --url http://127.0.0.1:8000 --duration 600 --output routed-proof.json
```

Testele browser cer Chromium instalat; pe Windows setează `BROWSER_EXECUTABLE`
la executabilul Chrome/Chromium. Pornirea normală a aplicației folosește browserul
sistemului și nu cere acest audit opțional.

Pe Windows: oprește procesul vechi, salvează `data` și `.env` dacă există,
extrage proiectul complet, copiază datele în noul director și pornește
`start-windows.cmd`. Folosește portul afișat de launcher și `Ctrl+F5` în browser.
Versiunea din sidebar trebuie să fie `v0.13.2`.

## Limite rămase

1. Refuzurile de risc, cotațiile fără rută, HTTP 400/401/429 și datele vechi
   sunt rezultate posibile și trebuie păstrate. API-urile publice nu au SLA.
2. Alinierea Jupiter cu regula de prefetch v2 necesită politică separată și
   compatibilitate explicită. Nu se rescriu lipsurile din trecut.
3. Creșterea bazei și backlogul necesită arhivare/capacitate, păstrând universul,
   respinsele, primele semnale și outcome-urile. Nu se promite operare 24/7.
4. Traseul documentar complet pentru o știre nouă nu a fost revalidat în această
   rundă. Cotațiile SOL sau un pool descoperit nu substituie această dovadă.
5. AI real, livrarea Telegram, Base și găzduirea publică nu au fost extinse ori
   validate aici. Cheile/abonamentele opționale rămân cele din configurație.
6. Avantajul predictiv și profitabilitatea nu sunt demonstrate de aceste teste
   funcționale sau de un singur rezultat virtual.
