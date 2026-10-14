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

## PULSE v0.4 — verificarea documentului și a contractului

Verificare pe 14 octombrie 2026:

- **144 teste pytest trecute**, Ruff, JavaScript și `uv sync --frozen`: exit 0. Nicio dependență
  runtime nouă. Manifestul, lockfile-ul, API-ul și interfața indică 0.4.0 / v0.4.
- Cazuri noi: adrese complete față de prefixe/nume, scripturi/headere/elemente ascunse, atribute
  HTML fără valoare, chain greșit și rânduri de tabel separate, negații inclusiv în contextul unui
  link de explorer, redacție care nu poate fi emitent, contract incompatibil cu activul selectat,
  hosturi private/false, redirecturi, document prea mare, format nesuportat și indisponibilitate
  după o citire reușită. O reverificare manuală nu folosește succesul anterior din cache.
- Evaluări de sursă: confirmare explicită, justificare, înlocuire în același scope, expirare,
  retragere și restart. Rezultatele sunt legate de activ și articol; două știri despre aceeași
  monedă nu primesc automat aceeași afiliere. Semnalul și exportul păstrează copia inițială.
- Colectarea automată este limitată și nu deschide URL-uri de agregator. Un mint Solana poate fi
  descoperit din adresa citată într-o pagină primară, fără asemănări de nume; asocierea cere date
  de piață pentru exact acel mint și rămâne neconfirmată ca afiliere. Sursele primare rămân în
  lista procesată chiar după peste 100 de titluri de agregator mai noi.
- Backupul a fost extras în test: tabelele noi, retragerea evaluării și dovezile originale ale
  semnalului au supraviețuit; `integrity_check=ok` și zero ordine necerute.
- Browser: smoke-ul pentru ambele round-trip-uri paper de $50 și regresiile v0.3 au trecut.
  Noul test `tests/browser_announcements.py` verifică document → contract → evaluare manuală →
  reverificare → semnal → retragere → context negativ. Exportul păstrează dovada veche, cash
  rămâne $500 cu zero ordine. Layout 390px, fără erori JavaScript.
- Probă live într-o bază temporară: pagina Solana Sync Native, HTTP 200, contract wrapped SOL
  găsit, amprenta documentului salvată. Rezultat conservator `chain_unconfirmed`, afiliere
  `unverified`, fără afirmație verificată sau ordin. Pagina nu a fost folosită ca recomandare.
- În instanța cloud, colectarea automată a citit un articol Kraken eligibil: titlu, sursă,
  timestamp, extras și SHA-256 persistate, `claim_verified=false`. Nu s-au inventat contracte.
- Proba live de piață a trecut: 12 profiluri Solana, wrapped SOL/RPC/GoPlus, 25 de active
  CoinGecko, book BTC Coinbase și 10 titluri CoinDesk. Nu au fost trimise ordine.
- Backup SQLite consistent înainte de upgrade; Scanner $100 / Research $500, zero ordine,
  istoricul existent păstrat. Interfața actualizată a trecut verificarea cu date reale.

Circle Developers și Anthropic au fost testate cu răspunsuri simulate; accesul live din acest
cloud a rămas blocat cu `ProxyError`, inclusiv după salvarea domeniilor în draft. Nu declarăm
aceste integrări validate live sau configurația aplicată. Un timeout temporar Google News pentru
Zelenski a fost vizibil ca eroare de sursă; ulterior sursa a răspuns din nou.

Nu sunt validate semantic afirmațiile/afilierea, profitabilitatea sau execuția reală. Windows
nativ, pagini care necesită JavaScript și restaurarea într-un task cloud nou rămân netestate.
Limitele de interpretare și de acoperire sunt în [V0.4.md](V0.4.md).

## PULSE v0.5 — AI opțional și evaluare cu proveniență

Verificare pe 14 octombrie 2026:

- **175 teste pytest trecute**, Ruff, JavaScript și instalare frozen: exit 0. Nicio dependență
  runtime nouă. Rămâne vizibil warningul Starlette/httpx al TestClient.
- Cele 31 de teste noi acoperă configurații invalide/secrete respinse, citări fabricate, schema
  strictă, identitate/chain/rol de sursă incompatibil cu o ipoteză pozitivă, limite zilnice persistente,
  timeout/429/JSON invalid/răspuns prea mare și eșec după succes fără rezultat vechi substituit.
  Promptul de model nu include portofoliu; cheia apare numai în headerul cererii simulate.
- API și persistență: context AI legat de activ și știre, refuzul unui context fără asociere,
  same-origin, semnale/export cu copii originale și backup SQLite restaurat cu `integrity_check=ok`.
- **Toate patru suitele browser au trecut**: `browser_smoke.py`, `browser_regressions.py`,
  `browser_announcements.py`, `browser_ai.py`. Noua suită verifică setare motor, conexiune, citate,
  semnal/export, respingere host arbitrar și layout desktop/390px, fără ordine automate.
  Motorul AI din teste este simulat; suitele nu măsoară calitatea unui model real.
- Set inițial: 12 cazuri, două extrase din pagini Solana/Kraken citite live și zece scenarii
  sintetice marcate. Raportul offline validează structura, cu `model_run=false`, `metrics=null`.
  Testul metricilor verifică includerea eșecurilor și a asocierilor fals pozitive în raport.
- Local Ollama: conexiunea la serviciul local a eșuat cu `ConnectError`; niciun model instalat.
  Nicio cheie API disponibilă. OpenAI/Ollama sunt adaptoare testate cu transport simulat,
  **fără generare live validată și fără precizie măsurată**. Documentația externă a celor două
  servicii nu a putut fi citită din cloud; compatibilitatea curentă trebuie verificată la activare.
- Backup consistent înainte de upgrade în `/workspace/backups/pulse-v0.5-20261014T053448Z`.
  Instanța 0.5.0 pornește cu patru workeri, AI oprit și zero generări, Scanner $100 / Research
  $500, zero ordine. Datele anterioare sunt păstrate. Interfața cu date reale și capturile desktop,
  dosar, panou AI oprit și mobil au trecut fără erori JavaScript sau overflow.

Nu sunt validate semantic toate afirmațiile, afilierea, fundamentele, profitabilitatea sau
execuția reală. Nici Windows nativ sau restaurarea într-un task cloud nou. Configurarea și
evaluarea separată a modelului, limitele setului și pașii necesari sunt în [V0.5.md](V0.5.md).
