# Verificare milestone 1

Executat în mediul cloud pe 13 octombrie 2026:

- Scriptul de instalare salvat: `uv sync --frozen`, Ruff și pytest; exit 0, **53 teste trecute**.
- `node --check app/static/app.js`: exit 0.
- Browser smoke izolat cu răspunsuri simulate: scanare → semnal → așteptare → intrare paper →
  ieșire → PnL net. Desktop și viewport mobil de 390px, fără erori JavaScript.
- Browser pe aplicația cu surse reale: dashboard încărcat, tabel populat și layout mobil fără
  overflow al paginii. Captura este un artefact local, nu un deployment public.
- `.venv/bin/python -m app.smoke`: exit 0. Discovery a returnat 12 adrese Solana valide; wrapped
  SOL a furnizat un preț și lichiditate, RPC și GoPlus au răspuns și verificările de bază au trecut.
  Wrapped SOL a fost folosit numai ca probă de infrastructură, fără ordine și fără inserare ca
  memecoin în baza aplicației.
- Server pornit/restartat cu instrucțiunile documentate. Health, token detail și istoric HTTP 200;
  observațiile SQLite au supraviețuit restartului, soldul paper a rămas $100, cu 0 ordine în baza
  reală. Round-trip-urile din teste au folosit numai baze temporare.

Suita acoperă veto-uri de securitate, extensii nesuportate, date lipsă/expirate, parsing de API,
semnale vechi/prea noi, comisioane și break-even, alocare/exposure, pierderi realizate zilnice,
reutilizare de semnale, ordine concurente, lichiditate zero, cache inutilizabil la eșec și CSRF origin.

Un warning de deprecation din Starlette TestClient/httpx apare în teste; testele se execută și
trec. Nu am ascuns warningul sau dezactivat assertions.

Nu s-au verificat: quotes de swap, tranzacții on-chain, memecoin profitability, wallet skill,
backtest, Base, AI sau Telegram. Nu s-a publicat mediul și nu s-a testat restaurarea într-un task
nou. Configurația draft salvează `install_script`, `start_skill` și domeniile personalizate;
publicarea se face de utilizator în setările mediului. La validarea inițială nu se făcuse commit/push GitHub.

## Clarificarea fluxului de știri și ordinul virtual de $50

Verificare ulterioară în aceeași zi: **66 teste trecute**, inclusiv parsing RSS, eliminarea
titlurilor cu „100x”/„price prediction”, deduplicare, cronologia poolului, respingerea asocierilor
neînregistrate, păstrarea articolului original în jurnal și separarea conturilor.

Browser test izolat: titlu → token posibil asociat → semnal → ordin manual de $50 → ieșire și PnL.
Debitul simulat a fost $50,01, soldul contului test „Știri” a devenit $449,99, contul test „Scanner”
a rămas $100. La preț neschimbat round-trip-ul a pierdut costurile. Acestea sunt rezultate din
fixtures, nu o tranzacție pe piață sau dovadă de profitabilitate.

Google News RSS și DEX search au răspuns live pentru ambele subiecte. După restart, aplicația a
afișat titluri colectate și potriviri de tokenuri, fără erori JavaScript; viewport mobil 390px fără
overflow. Contul real al aplicației „Scanner” a rămas $100, iar noul cont fictiv „Știri” a fost
inițializat cu $500; ambele aveau 0 ordine. Nu am plasat un ordin în locul utilizatorului.

Verificarea integrală a articolelor și cauzalitatea știre–token nu sunt implementate. Toate
articolele păstrează `article_verified=false` și potrivirile `lexical_hypothesis`. Nu afirmăm că
poolurile găsite sunt tokenuri noi. Nu există notificări în afara aplicației sau Telegram.

## PULSE v0.2 — crypto generale și UI

Verificare pe 13 octombrie 2026:

- `uv sync --frozen`, Ruff și `node --check app/static/app.js`: exit 0.
- **87 teste trecute**. Se verifică suplimentar bid/ask, cantități L1, comisioane, modelul de
  referință, timestamp lipsă/expirat/invalid, respingerea unei ieșiri fără book, separarea
  conturilor și equity necunoscut când lipsește o evaluare validă. Testele de știri verifică
  filtrarea politicii fără crypto, prioritatea surselor fără a confirma susținerea tokenului,
  Bitcoin Cash versus Bitcoin și păstrarea primei asocieri la actualizarea potrivirilor.
- Browser smoke izolat: știre → DEX paper $50 → ieșire; activ crypto general → piețe → ipoteză
  scrisă → paper $50 → ieșire. Fără erori JavaScript; viewport 390px fără overflow.
- Probe live `python -m app.smoke`: 12 profiluri Solana valide, RPC/GoPlus funcționale, 26 de
  active păstrate în cache, book BTC public și 10 titluri CoinDesk eligibile. Niciun ordin.
- Pornire prin `python -m app.desktop --no-browser`: aplicație gata pe portul local 8000,
  `app_id=pulse_crypto_research`, versiune 0.2.0. Nu s-a testat scriptul `.cmd` pe Windows real;
  helper-ul Python și pornirea serverului s-au testat în Linux.
- Feedurile au răspuns pentru toate cele 9 surse/subiecte; Zelenski și Ethereum Foundation
  au avut zero titluri recente eligibile. Nu s-au inventat informații pentru a completa feedul.
- Capturi ale aplicației cu date reale în [screenshots](screenshots/). Desktop, știri, piață și
  mobil fără erori JavaScript. Capturile nu reprezintă un site public.
- După upgrade: Scanner $100, Research $500, ambele cu 0 ordine. Baza de date și istoricul
  observațiilor au fost păstrate, cu backup SQLite consistent în afara repository-ului.

Warningul de deprecation Starlette/httpx rămâne vizibil. Testele software și probele de surse
nu demonstrează profitabilitate, afiliere oficială sau calitatea fundamentelor unui proiect.
Contractele și linkurile metadata rămân declarații ale furnizorului. Accesul înaintea unei
listări viitoare nu este stabilit. Detalii despre acoperire și surse în [V0.2.md](V0.2.md).

## Remedierea pornirii Windows — pachet incomplet

Utilizatorul a raportat `--no-dev has no effect when used outside of a project`, urmat de
`No module named 'app'`. Mesajele indică lipsa proiectului în directorul de pornire; lansarea
direct din ZIP sau copierea exclusivă a scriptului sunt cauze posibile. Nu am inspectat PC-ul.

Launcherul verifică manifestul, lockfile-ul și fișierele aplicației înainte de instalare/pornire.
Dacă lipsesc, afișează pașii pentru **Extrage tot**. Folosește `pushd` și transmite explicit
`--directory` și `--project` către ambele variante de invocare `uv`.

Verificare funcțională: arhiva completă extrasă într-un director temporar cu spații, diacritice și
`&`, pornire dintr-un alt director, dependențe/date noi, comanda `uv run` cu directorul explicit.
Serverul și dashboardul au răspuns, Research avea $500 fictivi și zero ordine. Procesul de test
a fost oprit și datele temporare șterse. Testul s-a executat în Linux; scriptul `.cmd`, ramura
Python Launcher și căile UNC nu au fost executate pe Windows real.

## PULSE v0.3 — remedieri și experiment măsurabil

Verificare pe 14 octombrie 2026:

- `uv sync --frozen`, Ruff pentru `app`/`tests`, verificare sintaxă JavaScript și diff: exit 0.
  Manifestul și lockfile-ul sunt 0.3.0, fără dependențe runtime noi.
- **108 teste pytest trecute.** Regresiile includ break-even verificat printr-un round-trip
  independent, migrarea știrilor cu ID/read-state/semnale păstrate, metadata neconforme, prețuri
  expirate, prioritate pentru poziții vechi, versiune/director de date la launcher și Host allowlist.
- Dosare: evaluări manuale persistente, retragere, restart, citat fără confirmarea afirmației,
  contract invalid respins, confirmare expirată și dispută care nu dispare prin vechime. Semnalul
  păstrează copia dosarului inițial chiar dacă evaluarea este retrasă ulterior.
- Măsurători: ordine reușite/respinse, rezultat după costuri, equity lipsă, interval BTC aliniat,
  export integral și izolarea conturilor. O eroare simulată la metrici nu raportează un fill deja
  înregistrat drept eșuat. Backupul ZIP este extras, ambele baze trec `integrity_check`, iar soldul
  și toate cele trei ordine ale experimentului test sunt păstrate în baza restaurată.
- Browser smoke: ambele round-trip-uri manuale de $50, DEX și crypto general, trecute. Browser
  regressions: știri 503 cu cash actualizat, RPC degradat vizibil, preț 0,000012, logo, căutare și
  watchlist, dovadă manuală/retragere, semnal invalidat la schimbarea ipotezei, export JSON, backup
  ZIP, contracte și jurnal pe mobil. Rulare finală fără erori JavaScript sau de rutare a fixture-ului.
- Proba live, într-un `DATA_DIR` separat: 12 profiluri Solana, wrapped SOL cu RPC/GoPlus, 25 de
  active CoinGecko, book BTC Coinbase și 10 titluri CoinDesk eligibile. Niciun ordin.
- Backup SQLite consistent înainte de upgrade în afara repository-ului. Instanța cloud 0.3.0
  pornește cu patru workeri, istoricul existent și cash Scanner $100 / Research $500, zero ordine.
  Toate cele nouă surse/subiecte de știri au răspuns; unele au avut zero articole eligibile.
- Capturi actualizate cu date reale: desktop, știri, piață, dosar, jurnal și mobil 390px, fără
  overflow sau erori JS. În aceste capturi nu s-au adăugat evaluări ori ordine fictive.
- Pachetul candidat din fișierele pregătite pentru commit a fost extras într-un director nou cu
  spații, diacritice și `&`. Pornirea din alt director prin `uv --directory --project --frozen
  --no-dev` a instalat dependențele și a pornit API/UI 0.3.0 cu date noi, $500/$100 și zero ordine.
  Procesul de test a fost oprit; datele temporare au fost șterse.

Warningul de deprecation Starlette/httpx din TestClient rămâne vizibil. Execuția nativă `.cmd`,
Python Launcher și UNC nu a fost testată aici. Nu s-au validat profitabilitatea, execuția reală,
afilierea unui token sau un proiect concret ca „solid”. În v0.3, evaluarea dovezilor rămâne manuală.
Scripturile istorice din `docs/audit` reproduc buguri pe commitul vechi și nu sunt acceptance tests
pentru această versiune. Acoperirea, limitele și etapele următoare sunt în [V0.3.md](V0.3.md).
