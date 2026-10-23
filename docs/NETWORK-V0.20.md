# MemeScope v0.20.0 — timp comun pentru colectare

Limitele pe apel se puteau aduna: mai multe verificări de securitate a câte 30s,
fallbackuri de 15s și până la patru cotații Jupiter de câte 20s. O sursă lentă putea
amâna observațiile următorilor candidați. Această versiune limitează așteptările și
separă cererile amânate de eșecurile efectiv observate. Nu schimbă pragurile sau costurile.

## Ce s-a reparat

- Ciclul folosește un ceas monotonic și un termen comun pentru cereri: intervalul
  configurat minus 5s. La configurația standard de 60s, termenul este 55s.
- Fallbackul, securitatea și eșantioanele opționale împart cel mult
  `min(30s, interval/4)`: 15s la configurația standard, în total, nu per token.
- Discovery și expunerea plătită rulează în paralel, cu cel mult
  `min(10s, interval/6)`; citirile de piață pentru un lot au cel mult
  `min(15s, interval/4)`, limitate și de timpul rămas. Precedența Dex → Gecko se păstrează
  când ambele surse răspund; o sursă căzută nu șterge rezultatul celeilalte.
- RPC și GoPlus sunt citite în paralel. Ordinea dovezilor și erorilor rămâne deterministă.
  Dovezile lipsă nu sunt înlocuite cu răspunsuri simulate sau cu aprobări de securitate.
- Cotațiile Jupiter sunt admise una câte una, în bugetul numeric existent. O cotație
  nu pornește dacă nu mai este timp pentru limita existentă de 20s. Lucrările neîncepute
  rămân pending; nu sunt înregistrate drept tranzacții eșuate. Filtrele, primul receipt,
  ferestrele originale și costurile din `opportunity_routes.py` sunt neschimbate.
- Un lot ulterior care nu ajunge să ceară prețuri nu primește observații de eșec inventate.
  Joburile sale rămân pending și fără `last_dispatch_at`. Pentru loturile pornite se
  păstrează timpul inițial al cererilor după terminarea lor. O oprire înainte de această
  persistare rămâne un worker gap; nu este o dovadă de lipsă a lichidității.
- Joburile promise își păstrează termenele: dacă amânarea le depășește, sunt raportate
  ca ratate. Nu sunt prelungite pentru a produce un rezultat favorabil.
- Contorul de securitate consumă un slot numai când bugetul de timp admite operația.
  Scrierea marcajelor de dispatch și a stării cotațiilor folosește workerul de stocare.
- Detaliile colectării arată timpul ciclului, timeouturile, candidații pentru care a pornit
  citirea prețului și amânările. O coadă Jupiter fără lucrări eligibile nu este etichetată
  în mod fals ca având tranzacții amânate.
- Profilarea a identificat și o căutare fără index pe contract: pentru fiecare candidat
  erau parcurse pool-urile întregii rețele pentru a găsi promovări raportate. Pe 60 de
  candidați a consumat 22,34s, față de 0,013s pentru citirea istoricelor. Indexul
  `(chain, contract, last_seen_at DESC)` restrânge căutarea la contractul cerut și păstrează
  ordinea după ultima observație. Migrarea este idempotentă și nu modifică payloaduri.

## Ce garantează bugetul și ce nu garantează

Termenul comun controlează așteptările cooperative ale operațiilor. Scrierile SQLite,
închiderea cererilor, calculul și finalizarea rezultatelor sunt lăsate să se termine.
Un ciclu poate depăși 60s. Nu întrerupem o tranzacție de stocare și nu eliberăm lease-ul
în timp ce scrierea sa continuă. Primul ciclu live a durat 66,43s, inclusiv concurență
cu teste și rapoarte; depășirea rămâne vizibilă.

Există un compromis: o verificare amânată lasă securitatea necunoscută și poate reduce
numărul alertelor. Acest lucru nu face tokenul sigur. Amânările pot produce ferestre ratate;
PnL-ul necunoscut și ieșirile indisponibile nu devin profit zero sau filluri reușite.

## Instalare și pornire

Din directorul proiectului:

```bash
uv sync --frozen
uv run --frozen python -m app.desktop
```

Windows: închide aplicația veche, păstrează întregul folder `data` și configurația locală,
apoi rulează `start-windows.cmd` din versiunea nouă. Reîncarcă browserul cu `Ctrl+F5`.
Folosește adresa și portul afișate de launcher; implicit `http://127.0.0.1:8000`.

Nu sunt necesare pachete, chei sau abonamente noi. Se folosesc serviciile deja configurate,
în bugetele numerice existente; tarifele și limitele furnizorilor rămân aplicabile.
AI, Telegram și tranzacțiile reale nu sunt activate de acest release.

## Verificare

```bash
uv run --frozen ruff check app tests
uv run --frozen pytest -q
node --check app/static/app.js
node --check app/static/advanced.js
node --check app/static/opportunities.js
BROWSER_EXECUTABLE=/usr/bin/chromium uv run --frozen --with playwright python tests/browser_audit.py
uv run --frozen python -m app.collection_verify --url http://127.0.0.1:8000 --duration 600 --output data/collection-check.json
```

**594 teste Python și 41 de scenarii Chromium au trecut local.** Furnizorii din aceste
teste sunt izolați; SQLite și anularea taskurilor sunt reale. Regresiile acoperă servicii
blocate, plafonul comun, anularea ambelor surse, lipsa sloturilor consumate fără cereri,
joburi neîncepute, amânarea fără claim de tranzacție, cotații incrementale și layout mobil.
Regresia indexului verifică și actualizarea unei baze existente, echivalența rezultatului
cu pool-uri multiple pentru același contract și folosirea efectivă a contractului în planul SQL.

Verificările cu surse reale sunt separate în [directorul de dovezi](network-v0.20-evidence/).
Ele demonstrează colectarea și păstrarea rezultatelor în intervalul măsurat, nu profitabilitatea.

După indexare, trei cicluri live au procesat **180 de observații și 56 de candidați noi**,
în **22,72s, 55,41s și 22,43s**. Unul a raportat erori/limite ale surselor și cotații
amânate, dar a continuat colectarea. Eșantionul este mic și nu garantează această durată.
Verificatorul strict a trecut toate criteriile în **96s**, cu două capturi distincte pentru
alerte și șase pentru control, toate capturate și primite în propria rulare.

Pe același snapshot SQLite, cu 131.640 de pool-uri și aceiași 60 de candidați, căutarea
forțată prin vechiul index pe rețea a durat 12,68s, iar căutarea pe contract 0,000394s.
Rezultatele și hashurile lor au fost identice. Acesta este un benchmark local de query,
nu un factor de accelerare garantat pentru întreaga aplicație.

Alerta reală 7794 / candidatul 123058 a fost aleasă înainte de rezultatul ulterior și livrată
în aplicație. Experimentul estimativ de pool, pentru un cost virtual de 50,01 USD, a ajuns
la evaluarea de 5 minute cu **pierdere de aproximativ 5,56 USD**. Este un rezultat al
modelului estimativ, nu un ordin executat și nici dovada unei cotații Jupiter de ieșire.
Exemplul negativ este păstrat. O singură observație de performanță nu stabilește calitatea selecției.

Politica 31 a fost declarată pe **23 octombrie 2026, 21:18:33, Europe/Bucharest**;
holdoutul său începe pe **24 octombrie, 21:18:33**, în același fus orar. Politicile și
declarațiile 1–30 nu au fost mutate. Indexul SQL este o optimizare cu rezultat echivalent,
fără schimbarea scorurilor sau a regulilor, și nu creează o declarație nouă.

## Limite și următorul pas

- Coada istorică este păstrată. Accesul parțial la piață, sursele lente și capacitatea
  insuficientă pot produce în continuare observații incomplete și termene ratate.
- Mai trebuie măsurat și redus timpul calculelor/stocării, separat de așteptările API.
  Durata unui ciclu normal nu este o garanție pentru orice încărcare viitoare.
- Verificarea locală folosește Linux și Chromium cu dimensiuni mobile; nu este testare
  pe telefoane fizice și nu înlocuiește rezultatul Windows al acestei versiuni.
- Politicile, cohortele și declarațiile anterioare rămân păstrate. Programarea nouă are
  un holdout nou; limitele financiare și rezultatele vechi nu sunt modificate retrospectiv.
- Narațiunile, selecția timpurie și utilitatea financiară necesită în continuare evaluarea
  prospectivă după costuri. Nu există aici o demonstrație a identificării unor viitoare 10x.
