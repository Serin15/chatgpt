# Memecoin Research — primul milestone

Tool personal de cercetare pentru Solana: scanner cu date reale, verificări de risc explicabile,
istoric SQLite, watchlist, știri și portofoliu paper. Interfața este în română.

## Fluxul principal: știre → ipoteză → ordin virtual

În fila **Știri & tokenuri**, aplicația caută la fiecare 5 minute titluri despre Claude/Anthropic și
anunțuri Trump, prin Google News RSS. Afișează titlul original, publicația, data raportată și linkul.
Filtrează expresii precum „100x”, „price prediction” și „price today”. Nu verifică integral articolul,
nu stabilește adevărul titlului și nu interpretează încă semantic toate știrile din internet.

Pentru fiecare subiect, caută tokenuri Solana prin DEX Screener și păstrează potrivirile după
nume/simbol. Acestea sunt **ipoteze**, nu afilieri oficiale și nici dovada că știrea a creat tokenul.
Compară data creării poolului cu data articolului; data creării tokenului rămâne necunoscută.
Un pool mai vechi decât articolul este etichetat explicit. Nu afirmăm „tocmai s-a creat” dintr-o
simplă potrivire de nume. Nu sunt încă suportate detectarea tuturor evenimentelor virale și
asocierile indirecte (de exemplu un token cu alt nume inspirat de un citat).

Apasă **Analizează pentru paper**, citește verificările, apoi **Salvează semnal** și
**Simulează intrarea**. Suma implicită este **$50 virtuali**. Contul „Știri” are **$500 fictivi**
inițial în `data/news_paper/research.sqlite3`; contul anterior „Scanner” și istoricul său rămân
separate, selectabile din portofoliu. Niciun ordin nu se plasează automat.

După intrare vezi PnL net estimat pentru o ieșire simulată la ultima observație validă. La ieșire,
jurnalul înregistrează PnL net realizat și păstrează titlul/sursa/asocierea disponibile când ai
salvat ipoteza. Actualizările ulterioare ale știrii nu rescriu acel context.

Feedul este informarea în aplicație, actualizată periodic când serverul rulează. Nu sunt mesaje
proactive în chat, email sau Telegram. Exemplul „Claude a descoperit o planetă” nu este tratat drept
știre verificată și nu este introdus ca date reale.

Acest milestone nu demonstrează un avantaj de trading. Scorurile sunt euristici, iar simulările
de execuție sunt scenarii aproximative. Nu există conectare de wallet, semnare sau tranzacții reale.

Pentru pornire pe Windows/macOS/Linux după descărcare, vezi
[DESCHIDE-APLICATIA.md](DESCHIDE-APLICATIA.md). Windows: `start-windows.cmd` pornește aplicația
și deschide browserul; păstrează fereastra de comandă deschisă.

## Pornire

Necesită Python 3.12+ și `uv` (deja disponibile în mediul cloud).

```bash
cd /workspace/chatgpt
export UV_CACHE_DIR=/workspace/.cache/uv
uv sync --frozen
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Serverul servește dashboardul la ruta `/` și API-ul la `/api/*`. Portul implicit este 8000.
Este destinat rulării locale personale; păstrează bind-ul pe loopback. Expunerea publică necesită
autentificare, HTTPS și alte controale într-o etapă separată.

Nu sunt necesare chei API pentru operațiile read-only verificate în acest milestone.
Nu introduce private keys sau seed phrases. Variabilele opționale sunt în `.env.example`;
fișierul `.env` nu se încarcă automat. Exportă numai variabilele necesare în shell.
`SOLANA_RPC_URL` poate înlocui RPC-ul public cu un furnizor ales ulterior; folosește HTTPS.

`data/research.sqlite3` păstrează observațiile, semnalele, ordinele și soldul fictiv.
Nu se resetează la restart. `PAPER_START_USD=50` stabilește capitalul numai pentru o bază nouă;
pentru un experiment separat, folosește un alt `DATA_DIR`, fără ștergerea istoricului existent.
Oprește serverul înainte de backup și păstrează întregul director `data`, inclusiv fișierele WAL.

## Ce funcționează

- Discovery periodic din cele mai recente profiluri Solana DEX Screener; maximum 12 profiluri
  per ciclu. Sunt monitorizate maximum 30 de adrese per ciclu, cu prioritate pentru poziții și
  watchlist; maximum 20 de tokenuri în watchlist. Ciclul următor începe la 90s după încheierea
  precedentului. Aceasta este polling, nu un flux websocket.
- Adăugare manuală a unui mint valid, selecția poolului cu cea mai mare lichiditate raportată
  unde mintul este tokenul de bază, preț, volum, tranzacții buy/sell și vechimea poolului.
- RPC `getAccountInfo` verifică autoritățile mint/freeze. GoPlus furnizează avertismente terțe.
  Sunt acceptate SPL clasic și Token-2022 cu o listă de extensii complet interpretată și limitată
  la `metadataPointer`/`tokenMetadata`. Alte extensii/programe blochează paper trading.
- Veto pentru autorități active, restricții cunoscute, taxe de transfer nesimulate și lichiditate
  sub prag. Datele lipsă sunt necunoscute, nu rapoarte „clean”. Risc securitate `null` după trecerea
  verificărilor de bază înseamnă că riscul total nu a fost cuantificat.
- Istoric, dosar token, scoruri, surse/erori și timestamp-uri. La afișare și la simulare sunt
  reverificate condițiile de prospețime.
- Semnale salvate înainte de intrare. Fill-ul folosește o observație nouă după semnal, minimum
  3 secunde întârziere, maximum 120 secunde vechime. Dacă refresh-ul eșuează nu se folosește cache
  pentru a înregistra un fill.
- Calcule financiare cu `Decimal`, debit/credit atomic în SQLite și protecție contra reutilizării
  semnalului. Jurnalul include dovezi, costuri, impact, prag orientativ de break-even și respingeri.

Discovery este un eșantion de profiluri, nu toate lansările, toate memecoinurile sau participanți
unici. Profilurile/atenția pot fi cumpărate. Tokenurile fără preț/lichiditate raportată rămân fără
snapshot, cu eroarea explicită. RPC-ul și rapoartele de securitate sunt read-only.

## Reguli și scoruri

Parametrii pot fi configurați prin variabilele din `.env.example`. Setările implicit folosite:

| Regulă | Valoare |
| --- | --- |
| Capital fictiv inițial | $100 |
| Alocare maximă per poziție, inclusiv costuri | 20% din capitalul conservator |
| Expunere totală la cost | 50% din capitalul conservator |
| Capital conservator | min(capital inițial, cash + costul pozițiilor deschise) |
| Pierderi realizate zilnice | 10% din capitalul inițial, zi UTC; câștigurile nu șterg pierderile |
| Lichiditate minimă raportată | $25.000 |
| Impact estimat maxim | 2% |
| Poziție minimă | $2 |
| Comision swap presupus | 0,3% pe sens |
| Cost rețea presupus | $0,01 pe sens |

Activitate = min(60, volum 5m / lichiditate × 300) + min(40, număr tranzacții 5m / 2).
Momentum = clamp(50 + variație procentuală 5m × 2, 0, 100).
Lichiditate/ieșire = min(100, lichiditate / prag × 50).
Prioritate research = 60% activitate + 20% momentum + 20% lichiditate/ieșire, sau 0 când
filtrul paper nu este trecut. Lipsa datelor de activitate/momentum produce `null`; la prioritate
componenta lipsă contribuie 0, fără a inventa o măsurătoare.
Completitudinea verificărilor MVP = 30 pentru preț/lichiditate + 20 pentru toate ferestrele de
piață folosite + 25 pentru verificările RPC suportate + 25 pentru câmpurile GoPlus de bază.
Acest 100/100 nu înseamnă că avem toate datele necesare pentru trading.

`reject` înseamnă veto, `monitor` dovezi incomplete/activitate mică, `investigate` prioritate de
cercetare cu verificările MVP trecute. Niciuna nu reprezintă recomandare de cumpărare sau probabilitate.

## Limite ale paper tradingului

Modelul presupune un pool constant-product cu jumătate din lichiditatea USD pe fiecare latură.
Acest lucru nu descrie corect poolurile cu lichiditate concentrată, bonding curves sau rutarea
multi-hop. Costurile nu provin dintr-o cotație Jupiter și nu includ ATA rent, prioritate variabilă,
MEV, schimbarea prețului între cotație și execuție sau costurile tranzacțiilor eșuate on-chain.
Impactul estimat nu este o limită garantată de slippage. Toate fill-urile au `execution_verified=false`.

Eșecurile înregistrate acum sunt respingeri înainte de execuția ipotetică, fără debit de fee.
Nu inventăm probabilități de eșec. O ieșire nevalidabilă nu închide poziția și nu creditează soldul;
pozițiile neieșite nu sunt prezentate ca pierderi realizate. Nu avem încă equity/drawdown complet.
Pragul break-even este valabil numai în același model, cu lichiditate constantă și fee-urile presupuse.

Nu sunt încă verificate concentrarea pe proprietari, istoricul deployerului, LP locks/withdrawals,
wash trading, conturi individuale înghețate sau posibilitatea unui swap real. Un mint fără freeze
authority poate avea conturi înghețate anterior. Nu există stop-loss automat sau garanție de ieșire.

## Verificare

```bash
cd /workspace/chatgpt
.venv/bin/pytest -q
.venv/bin/ruff check app tests
node --check app/static/app.js
.venv/bin/python -m app.smoke
```

`pytest` folosește răspunsuri simulate și baze temporare. `app.smoke` contactează API-urile reale;
folosește wrapped SOL doar pentru verificarea infrastructurii, fără să îl introducă în scanner
ca memecoin și fără ordine. Testul live eșuează cu exit nonzero dacă probele obligatorii eșuează.

Test opțional în browser, cu Chromium instalat:

```bash
UV_CACHE_DIR=/workspace/.cache/uv uv run --with playwright python tests/browser_smoke.py
```

Browser test pornește un server fixture separat și o bază temporară; nu scrie date fictive în
aplicația reală. Verifică scanare, semnal, întârziere, intrare, ieșire, jurnal și layout mobil.

Sursele, costurile și observațiile de validare sunt în [docs/SOURCES.md](docs/SOURCES.md).
Etapele următoare și criteriile de acceptare sunt în [docs/ROADMAP.md](docs/ROADMAP.md).
