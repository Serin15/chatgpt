# MemeScope v0.18.0 — raportare și colectare

Raportul istoric nu se mai calculează în cererea HTTP. Un worker supravegheat produce un
snapshot complet, iar dashboardul citește ultimul rezultat terminat, cu datele și starea
recalculării afișate explicit. Execuția cu bani reali rămâne dezactivată.

## Probleme reproduse și remedii

1. **Raportul depășea timpul de răspuns.** Pe peste 103.000 de candidați, endpointul a depășit
   21 secunde, iar profilarea a identificat aproape 100 secunde de lucru. Fiecare orizont
   recitea politica încorporată în semnal și erau construite sute de mii de dicționare.
   Noul calcul materializează metadatele o dată per semnal și agregă rezultatele prin streaming.
2. **Recalcularea concura cu dashboardul.** Calculul de producție rulează într-un proces finit,
   separat de server, cu conexiuni SQLite `mode=ro`. Acesta nu creează servicii sau clienți API
   și nu generează semnale sau ordine. Oprirea aplicației termină și recuperează
   procesul copil, inclusiv conductele stdout/stderr.
3. **Lucrările viitoare consumau bugetul rezultatelor.** Selecția a 2.000 de rezultate putea
   fi ocupată de orizonturi care nu erau scadente și nu aveau observații noi. Se recalculează
   intrările încă necunoscute, termenele scadente, metadatele incomplete și orizonturile care
   au primit observații noi. MFE/MAE se actualizează în continuare la date noi. Formulele,
   costurile și verificările din bucla de evaluare sunt identice cu versiunea precedentă.
4. **Apelurile independente se așteptau reciproc.** Sursele de piață pentru același lot,
   respectiv discovery și feedul de expunere plătită, rulează suprapus. Precedența surselor
   rămâne pool → Gecko, indiferent de ordinea terminării. Numărul cererilor și bugetele nu cresc.
   Anularea unui lot oprește toate cererile sale; o sursă căzută nu șterge răspunsul celeilalte.
5. **SQL pe firul buclei asincrone.** Politica, indexarea documentelor, ingestia, selectarea
   candidaților și sumarul cozii folosesc workerul de stocare existent. Timpii etapelor sunt
   înregistrați în `opportunity_runtime.timing_seconds` pentru măsurare.
6. **Filtre pe observații arhivate.** `json_extract` direct pe payloadul comprimat producea
   `malformed JSON`. Căutarea, filtrarea și clasamentul folosesc acum `archive_text` pentru bloburi.
   Numărarea fără filtre evită joinul inutil cu observațiile; lista este serializată direct ca JSON.

## Ce înseamnă cache-ul

- Prima pornire nu are încă un raport complet. API-ul răspunde rapid cu **503 și mesaj de
  pregătire**, în timp ce candidații rămân accesibili. Calculul inițial poate dura zeci de secunde.
- După prima calculare, API-ul returnează **200** din ultimul snapshot complet, inclusiv în
  timpul recalculării. Cache-ul nu este prezentat drept o cotație executabilă în timp real.
- Sunt separate `snapshot_at`, `calculated_at`, durata calculului, vârsta datelor și starea
  ultimei încercări. După 120 secunde snapshotul este marcat vechi. O eroare păstrează ultimul
  rezultat complet și expune eșecul, fără valori zero inventate.
- Workerul așteaptă 45 secunde după terminarea unui calcul înainte de următorul. Un calcul
  este limitat la 180 secunde. Frecvența efectivă include timpul calculului; nu promitem date
  noi la fiecare 45 secunde. Cache-ul din memorie se reconstruiește după repornire.
- Rapoartele de bilanț zilnic și Jupiter păstrează fluxul existent; acest release nu le
  transformă în rapoarte persistente sau instantanee.

## Verificare și dovezi

[Directorul de dovezi](performance-v0.18-evidence/) separă datele reale de fixture-uri.

- Comparația vechi/nou pe aceeași tranzacție de citire, cu ceas înghețat, a dat **zero diferențe**
  în raport: 103.819 candidați, 254.631 semnale și peste 451.000 de rezultate. SHA-256-urile
  rapoartelor coincid. Calculul izolat a scăzut de la 79,07s la 34,16s în acea comparație.
- Aceasta verifică echivalența agregării, nu profitabilitatea semnalelor sau performanța universală.
  Durata depinde de disc, volum și procese concurente.
- Regresiile folosesc SQLite real cu furnizori și ceasuri izolate: buget umplut de peste 2.000
  de lucrări viitoare, actualizări MFE/MAE, anulare, eșecuri parțiale, precizie Decimal, arhivare,
  snapshot coerent și căi cu spații, Unicode și `#`.
- Testele procesului separat verifică și refuzul scrierii, refuzul creării unei baze inexistente,
  păstrarea schemei și închiderea copilului la anulare. Chromium verifică etichetele cache/vechime.
- Măsurătorile HTTP și ciclurile din aplicația normală sunt în `live-performance.json`.
  Acestea folosesc sursele și istoricul existente, fără înlocuirea răspunsurilor.
  Au fost **25 răspunsuri 200**, cu mediană **10,9 ms** și maxim **204 ms**. În trei cicluri
  s-au colectat câte 60 de observații și s-au înregistrat 53 de candidați noi, fără erori ale
  motorului în acel interval. Etapa de rezultate/stare a durat 1,08–2,14s. Eșantionul este mic
  și nu stabilește o performanță garantată a API-urilor sau a semnalelor.
- **560 teste Python și 39 scenarii Chromium trecute**. Un avertisment existent Starlette/httpx
  este păstrat în log. Verificarea normală a dashboardului a avut zero erori JavaScript și
  zero HTTP 5xx; pregătirea inițială a raportului folosește intenționat HTTP 503.

Comenzi din folderul proiectului:

```bash
uv sync --frozen
uv run --frozen ruff check app tests
uv run --frozen pytest -q
node --check app/static/app.js
node --check app/static/advanced.js
node --check app/static/opportunities.js
BROWSER_EXECUTABLE=/usr/bin/chromium uv run --frozen --with playwright python tests/browser_audit.py
```

Pentru calcul manual, doar citire, pe istoricul unei aplicații deja inițializate:

```bash
uv run --frozen python -m app.performance_worker --database data/research.sqlite3 --news-database data/news_paper/research.sqlite3 > report.json
```

În Windows: oprește aplicația veche, păstrează întregul folder `data` și deschide
`start-windows.cmd` din versiunea extrasă. Alternativ, din terminalul proiectului:

```powershell
uv sync --frozen
uv run --frozen python -m app.desktop
```

Deschide adresa afișată de launcher, implicit `http://127.0.0.1:8000/#opportunities`, și folosește
`Ctrl+F5` după actualizare. Nu sunt necesare chei, abonamente sau dependențe noi pentru raportare.
Procesul suplimentar consumă CPU și RAM local, fără cereri suplimentare către furnizorii crypto.

## Istoric și limite

- Nu se șterg candidați, semnale sau rezultate. Politicile și protocoalele vechi rămân intacte;
  modificarea codului operațional produce o politică nouă cu propriul test prospectiv viitor.
  Schimbarea nu reprezintă o nouă dovadă de profitabilitate și nu mută retrospectiv pragurile.
- Filtrele de securitate, limitele de prospețime, comisioanele, slippage-ul și bugetele pentru
  cotații Jupiter rămân aceleași. Lipsa unui preț sau a unei ieșiri rămâne necunoscută.
- Coada istorică nu dispare prin optimizare. Capacitatea de API, durata verificărilor și numărul
  candidaților pot încă produce întârzieri și observații ratate. Totalurile brute și partea în
  pauză rămân vizibile. Nu promitem acoperirea tuturor lansărilor.
  La finalul măsurătorii erau 27.102 reevaluări periodice eligibile scadente și 67.697 în pauză;
  observațiile promise sunt contabilizate separat. Aceste valori nu sunt ascunse sau resetate.
- Validarea locală folosește Linux/Chromium și procese Python reale. Viewporturile mobile nu sunt
  telefoane fizice, iar o execuție pe Linux nu substituie verificarea nativă Windows.

Fișiere principale: `performance_reporting.py`, `performance_cache.py`, `performance_worker.py`,
`opportunity_outcomes.py`, `opportunities.py`, `main.py`, etichetele dashboardului și testele noi.
