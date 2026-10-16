# MemeScope v0.10.0 — beta Solana: știri, dovezi și bilanț zilnic

Această etapă completează cercetarea zilnică pe motorul existent. Nu introduce abonamente,
conturi multiple, tranzacții reale sau o promisiune de randament. Aplicația rămâne un produs
de cercetare în beta, cu surse parțiale și rezultate paper.

## Ce este nou

**Legătura document → contract nu mai depinde de un răspuns DEX sau de AI.** Un index local
citește documentele deja colectate din catalogul permis și păstrează adresa Solana, chain-ul,
contextul, hashul sursei și momentul la care dovada a fost efectiv indexată. Maximum 250 de
documente sunt indexate într-un ciclu; extragerea existentă este limitată la 12 contracte/document.
Citirea automată acoperă și redacțiile din catalog, în același buget existent de trei documente
per refresh de știri, cu backoff. Domeniile și regulile HTTPS/fără redirecturi nu sunt extinse.

O adresă exactă și un chain neambiguu reprezintă o **mențiune documentară**, nu o confirmare
a emitentului, a unei listări, a susținerii de către o persoană sau a adevărului afirmației.
Numele similare, chain-ul ambiguu și contextul negativ sunt afișate separat. Contextul negativ
este un indiciu de cercetat, nu dovada că tokenul este fraudulos. Dovezile contradictorii
nu primesc bonusul narativ de fiabilitate. O versiune ulterioară a documentului care elimină
adresa ori o neagă nu permite reutilizarea automată a vechii asocieri pozitive.

Momentul disponibilității folosește precizia timestampului original. Nu este înlocuit cu data
publicării și nu folosește rotunjirea la milisecundă a `julianday` pentru această decizie.
Indexarea nu citește rețeaua și nu blochează ciclul cu o generare AI. Un document incompatibil
rămâne invalid, iar ceilalți candidați continuă să fie procesați.

**Știrile sunt vizibile și cu AI oprit.** Panoul „Știri, contracte și dovezi” arată titlul,
publicarea, prima observare, starea documentului și candidații legați prin adresă. Un titlu RSS
al cărui document nu poate fi citit rămâne etichetat astfel. Dosarul tokenului arată separat
dovezile disponibile acum; semnalele, scorurile și politicile originale nu sunt rescrise.
Contoarele de titluri nu reprezintă măsurători ale audienței sociale sau independenței editoriale.

**Bilanțul zilnic fixează cohorta după ziua descoperirii în UTC.** Include candidați excluși,
respinși, fără prima evaluare și fără rezultat. Rezultatele sunt cele cunoscute la generarea
raportului, inclusiv cele apărute după ziua descoperirii. Nu este o reconstrucție a informației
disponibile la sfârșitul unei zile istorice.

Modelele de pool și Jupiter sunt separate. Pentru fiecare orizont sunt raportate toate primele
evaluări, selecțiile făcute atunci și controlul prospectiv prestabilit, cu suprapunerea lor,
stări, eșantioane, PnL net, intervale Wilson orientative și politici distincte. Alertele ulterioare
nu transformă retroactiv o primă evaluare într-o selecție inițială. Lipsurile păstrează PnL null.
Termenele expirate neprocesate sunt proiectate read-only, fără modificarea sarcinilor prin GET.

Separarea development/test folosește numai cutoff-ul înghețat în politica semnalului și declarat
în avans. Ferestrele de development care se suprapun cu testul sunt excluse din comparație.
Fără cutoff declarat, datele sunt **unassigned**. Raportul nu optimizează praguri și nu declară
profitabilitate. Experimentele independente nu sunt un cont cu capital limitat; nu inventăm
un drawdown de portofoliu din suma lor.

## Verificări

- [Reproducerea inițială](beta-evidence/document-link-before.txt): document cu adresă și chain
  valid, fără `news_matches`; asocierea lipsea din semnal înaintea corecției.
- [Teste unitare/de integrare](beta-evidence/pytest.txt): **327 trecute**, un avertisment cunoscut
  Starlette/httpx. Furnizorii și documentele din aceste teste sunt fixture-uri explicite.
- [Chromium](beta-evidence/browser.json): **14 scenarii trecute**, inclusiv schimbarea rapidă
  a zilei, export JSON, izolarea unei erori de raport și mobil de 390 px. Date simulate.
- [Migrare pe copia bazei reale](beta-evidence/migration.json): **664 candidați**, integritate OK,
  API-uri HTTP 200 și hashuri neschimbate pentru tabelele comparate de istoric și cont.
- [CI nativ Windows/Ubuntu](beta-evidence/ci.json),
  [rularea oficială](https://github.com/Serin15/chatgpt/actions/runs/38880600504): **327 teste pe
  fiecare sistem**, launcher Windows pornit dintr-o cale cu spații și Chromium pe Linux.
  Prima rulare Windows a avut un [eșec de fixture](beta-evidence/windows-fixture-before.txt):
  două citiri apropiate ale ceasului puteau fi egale, dar testul presupunea o diferență strictă.
  Testul folosește acum un moment de indexare explicit; codul aplicației și filtrele temporale
  nu au fost relaxate. Commitul final de cod/teste este `296bda0cfbac45a9548c81f1f9d98c66cf0f1253`.

## Date și servicii reale

[Fluxul principal](beta-evidence/pipeline-live.json) a trecut **8/8 criterii în 365s**, iar
[Jupiter](beta-evidence/routes-live.json) **5/5 în 410s**, pe o instanță normală izolată, cu
surse reale și fără injectarea unui token, schimbarea pragurilor sau ordine manuale/reale.
Același candidat 32, `acajNA5meGJMkLq4E8cVepGkm88RqTSxWyqFBvUpump`, a fost descoperit la
09:21:42 UTC pe 16 octombrie. Semnalul 99 are cotație de intrare la 09:23:04 UTC și o nouă
cotație de ieșire la 09:28:46 UTC, cu aceeași cantitate și durată de 342,27s. Scenariul de $50
are **PnL virtual net +$57,0579949540656**, fără swap executat sau garanția executării sale.

[Întreg universul probei](beta-evidence/universe-live.json) păstrează **215 candidați**, 534
observații și 216 experimente Jupiter pe semnale. Pentru 5m: 190 intrări respinse, 13
indisponibile, trei rezultate evaluate, două ieșiri indisponibile și opt încă în așteptare.
Cele trei rezultate sunt **+$57,06, −$3,60 și −$3,06**; eșecurile și lipsurile nu au fost eliminate.
Acesta este un eșantion tehnic mic și incomplet, fără dovadă de profitabilitate ori independență
statistică. Descoperirea în feed nu este dovada unei lansări noi. Ambele baze sunt păstrate
în backupuri consistente, iar instanța de probă a fost oprită după salvarea dovezilor.

[Browser pe istoricul cloud existent](beta-evidence/browser-live.json): **838 candidați** la
captură, bilanț zilnic actualizat, șase documente citite, afișare mobilă fără overflow și fără
erori JavaScript. AI era oprit. Conturile Research/Scanner au rămas **$500/$100 și zero ordine**.
Rapoarte API: [zilnic](beta-evidence/daily-live.json), [știri](beta-evidence/narratives-live.json).
Capturi: [bilanț](screenshots/memescope-beta-daily.png), [știri](screenshots/memescope-beta-stories.png),
[mobil](screenshots/memescope-beta-mobile.png). Acest istoric este separat de proba izolată de mai sus.

**Asocierea pozitivă automată cu o știre recentă despre un memecoin rămâne neverificată live**:
documentele observate nu conțineau adresa exactă necesară. Legătura, contradicțiile și refuzul
asocierilor prin nume au fost verificate cu fixture-uri; nu le declarăm demonstrate pe o știre
reală doar pentru că citirea documentelor a reușit.

În cloud a fost [declarată prospectiv](beta-evidence/prospective-declaration.json) perioada de
test de la **18 octombrie 2026, 00:00 UTC**, prin politica 3, declarată pe 16 octombrie la
09:30:38 UTC. Celelalte setări au fost păstrate. Datele anterioare fără cutoff nu sunt relabelate
ca test. Acest lucru nu modifică datele locale Windows și nu înseamnă că holdout-ul a fost deja
colectat sau evaluat. Noile orizonturi 1h/24h ale probei rămân neverificate.

[Arhiva verificată](beta-evidence/package.json) a fost descărcată din GitHub, verificată prin CRC,
SHA-256 și compararea tuturor fișierelor cu obiectele Git. Pornirea din alt director și dintr-o
cale cu spații, `#` și diacritice a trecut, inclusiv noile două API-uri. Nu au fost schimbate
versiunile dependențelor și nici implementarea financiară sau sursele de execuție Jupiter.

```bash
uv sync --frozen
uv run --frozen ruff check app tests
uv run --frozen pytest -q
node --check app/static/opportunities.js
uv run --with playwright python tests/browser_audit.py
```

## Starea funcțiilor acestei etape

| Funcție | Stare |
| --- | --- |
| Colectare Solana, scoruri, alerte în aplicație, observație și rezultat ulterior | Implementate și verificate live în proba izolată. |
| Știri și citire de documente cu AI oprit | Implementate și verificate pe feeduri/documente reale. |
| Legătură automată document–contract, chain ambiguu, contradicții și eliminarea unei mențiuni | Implementate și verificate cu fixture-uri; asocierea pozitivă cu un memecoin rămâne neverificată live. |
| Bilanț zilnic și păstrarea numitorilor/necunoscutelor | Implementate și verificate pe istoricul real și în teste. Exportul JSON și schimbările rapide de zi sunt verificate în browser cu fixture-uri. |
| Holdout prospectiv | Declarație persistentă verificată în cloud; colectarea și evaluarea viitoare sunt în așteptare. |
| Funcționare fără browser | Verificată cât timp procesul/mașina rulează; găzduirea publică 24/7 este blocată de infrastructura externă neconfigurată. |

Fișiere principale: `app/story_evidence.py` (index și proveniență), `app/narratives.py`
(agregare și feed), `app/announcements.py` (citire din catalog și documente invalide),
`app/daily_research.py` (cohorte și raportare), `app/opportunities.py`/`opportunity_rules.py`
(conectare și politica nouă), `app/main.py` (API), `app/opportunity_outcomes.py` (versiunea
regulilor raportată), `app/static/index.html`/`opportunities.js` (interfață), cele două fișiere
noi de teste și `tests/browser_audit.py`. Versiunea proiectului este actualizată în
`app/__init__.py`, `pyproject.toml` și `uv.lock`; dependențele sunt aceleași.

## Instalare și utilizare

Windows: închide versiunea veche, fă o copie a întregului folder `data`, extrage arhiva nouă,
copiază `data` în folderul proiectului nou și deschide `start-windows.cmd`. Din PowerShell,
în folderul care conține `pyproject.toml`:

```powershell
uv sync --frozen
uv run --frozen python -m app.desktop
```

În „Oportunități timpurii”, candidații rămân primii. „Bilanț zilnic” permite alegerea zilei UTC
și descărcarea JSON-ului afișat. Raportul unei zile fără date rămâne gol, fără profit zero fictiv.
API: `GET /api/opportunities/daily?day=YYYY-MM-DD`. API-urile păstrează autentificarea existentă.

Pentru o probă live izolată, folosește un **DATA_DIR nou**, fără ledgerul utilizatorului:

```bash
DATA_DIR=/tmp/memescope-beta-proof uv run --frozen python -m uvicorn app.main:app --host 127.0.0.1 --port 8767
# În alte terminale; aceeași instanță rămâne pornită pentru ambele verificatoare.
uv run --with playwright python -m app.level3_verify --existing-url http://127.0.0.1:8767 --duration 1200 --browser /usr/bin/chromium --output /tmp/beta-core.json
uv run --frozen python -m app.routes_verify --url http://127.0.0.1:8767 --duration 1200 --output /tmp/beta-routes.json
```

Pe Windows setează `$env:DATA_DIR` înainte de comanda uvicorn. Browserul live cere Chromium
instalat și calea lui pentru sistemul respectiv. Lipsa unei știri reale cu adresă exactă nu
autorizează injectarea unei asocieri pentru a declara verificarea narativă completă.

## Funcționare continuă și limite

Workerii continuă când fila browserului este închisă, cât timp procesul și mașina sunt pornite.
Închiderea terminalului, sleep-ul sau oprirea PC-ului opresc colectarea. Pentru 24/7 este necesar
un server activ; configurația existentă Docker Compose are restart `unless-stopped`, volum
persistent, autentificare și proxy HTTPS. Publicarea cere server/domeniu și configurare externă;
nu a fost cumpărată sau publicată găzduire prin această etapă. Nu există încă produs multi-user.

Nu sunt necesare chei noi pentru aceste două funcții. Se păstrează limitele furnizorilor publici;
AI, Telegram și RPC-urile plătite rămân opționale. Costul comercial al redistribuirii datelor și
capacitatea pentru clienți trebuie evaluate înaintea vânzării publice. Nu a fost cumpărat un abonament.

Știrile cu adresă exactă pot fi rare în catalog. Social global, holder/deployer intelligence
complet, Base Level 3 și calitatea predictivă rămân incomplete sau nedemonstrate. OpenAI și
livrarea Telegram au nevoie de credențiale pentru verificare reală; evaluarea Ollama anterioară
nu a demonstrat calitate semantică suficientă. Noile rezultate 1h/24h necesită timp efectiv și
colector pornit. Nici numărul de teste, nici un rezultat paper nu demonstrează un avantaj financiar.

Prioritatea următoare: o cohortă prospectivă cu cutoff declarat înaintea testului, acoperire
urmărită timp suficient și evaluare pe date noi. Apoi surse autorizate mai bune pentru știrile
specifice tokenurilor, holderi și deployer. Plățile și extinderea la alte blockchainuri pot aștepta.
