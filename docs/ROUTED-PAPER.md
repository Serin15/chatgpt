# v0.9 — paper trading cu cotații Jupiter

15 octombrie 2026. Această etapă adaugă scenarii independente de intrare și ieșire cu cotații
de swap observate, alături de modelul de pool existent. Ordinele și conturile manuale nu sunt
modificate de motorul automat. Aplicația nu construiește, semnează sau transmite tranzacții.

## Fluxul implementat

Fiecare nouă evaluare primește și un experiment rutat, inclusiv evaluările respinse. Se îngheață
configurația, suma USD, fee-urile presupuse, slippage-ul, ferestrele și versiunea componentei.
Evaluările istorice rămân fără măsurare Jupiter; nu li se atașează prețuri actuale.

După întârzierea minimă a semnalului, workerul folosește prima observație de piață ulterioară
disponibilă în fereastră. Verifică riscul, prospețimea pieței/securității, precizia mintului și
cere `GET /swap/v1/quote`, ExactIn, USDC → token. Salvează răspunsul, slotul, ora recepției,
cantitatea conservatoare `otherAmountThreshold`, ratele de conversie și costurile. Nicio cheie
de API nu intră în politica salvată sau în răspunsul HTTP al aplicației.

Pentru fiecare orizont se programează o observație separată la **ora cotației de intrare + orizont**.
Atunci se cere token → USDC pentru exact cantitatea virtuală primită. Nu se recalculează
cantitatea din prețul ulterior. Ieșirea trebuie să respecte fereastra originală și costurile
înghețate. PnL este suma celor două cash flow-uri USD simulate, după costuri.

O ieșire viitoare nu este cunoscută la intrare. Cotația ulterioară nu schimbă scorul sau alerta
inițială. Alertarea păstrează modelul estimativ existent; panoul Jupiter arată separat dacă
scenariul rutat a putut fi măsurat. Ruta poate traversa alte pooluri decât poolul descoperirii.

## Costuri și semnificația rezultatului

- `outAmount` și pragul conservator provin din Jupiter. Fee-urile poolurilor incluse în quote
  nu se adaugă încă o dată ca fee-ul estimat de pool. Separarea fiecărui fee în USD poate lipsi.
- Conversia USD/USDC folosește bid/ask și cantități L1 observate. Kraken este sursa principală,
  Coinbase este fallback. În proba inițială, vechiul produs Coinbase a răspuns HTTP 404.
  Fără un book valid sau volum L1 suficient, scenariul rămâne indisponibil; nu presupunem paritate.
- Fee-ul de conversie și taxa de rețea sunt presupuneri configurate, nu comisioane măsurate ale
  contului unui exchange sau ale unei tranzacții Solana. Nu simulăm transferurile dintre exchange
  și wallet, prioritatea, chiria conturilor, MEV ori garantarea unui fill la pragul minim.
- Bugetul implicit de $50 include conversia presupusă; taxa de rețea se adaugă separat.
  Rotunjirea la unitățile mintului este păstrată. Slippage implicit: 50 bps = 0,5%.
- Cotațiile nu sunt rezervări de lichiditate. Un rezultat `evaluated` este o simulare cu două
  cotații observate, nu dovada executării sau a profitabilității strategiei.

## Eșecuri și reluare

`entry_rejected` păstrează un candidat respins de filtre. `entry_unavailable`/`exit_unavailable`
păstrează PnL null, motivul și încercarea, inclusiv cotația brută dacă a fost primită dar respinsă.
Un răspuns incompatibil, un timeout, un HTTP 400 sau securitatea expirată nu confirmă automat
că tokenul este imposibil de vândut. Nu se alege o cotație ulterioară mai favorabilă pentru a
înlocui prima încercare nereușită. Modelul estimativ de pool rămâne un experiment separat.

Claim-ul SQLite împiedică dublarea aceleiași cereri între workeri. După o întrerupere, o cerere
cu rezultat necunoscut devine indisponibilă. Un callback întârziat nu poate transforma acea
încercare în succes. Schimbarea implementării oprește calculul scenariilor încă în așteptare,
cu motiv explicit; nu recalculează rezultatele terminale.

Cotarea rulează într-un task separat de colectarea pieței. Implicit are 4 încercări/ciclu și
timeout total de 20s/încercare. Jumătate din locuri protejează alternativ alertele și controlul,
cu deduplicarea suprapunerilor și împrumutarea capacității. Un buget insuficient poate rata
termene; API-ul arată și termene expirate încă neprocesate. Nu există latență garantată.

Rapoartele separă scenariile pe orizont, politica originală și dezvoltare/test. Controlul fix
include respingeri; poate include și alerte. Pragurile nu au fost optimizate pe proba live.
PnL al experimentelor independente nu este randamentul unui portofoliu cu capital limitat.

## Configurare și pornire

```bash
uv sync --frozen
uv run --frozen python -m app.desktop
```

Pe Windows, extrage arhiva și deschide `start-windows.cmd`. Python 3.12+ sau uv este necesar.
Panoul **Paper cu cotații Jupiter** și dosarul tokenului arată rezultatele păstrate separat.
În **Praguri și funcționare** există activarea, bugetul și slippage-ul. Modificarea se aplică
politicilor noi. Dezactivarea oprește cererile; scenariile deja deschise pot rămâne fără ieșire.

`OPPORTUNITY_ROUTED_QUOTES=0` dezactivează funcția numai la crearea unei configurații noi.
După aceea, setarea persistată în aplicație este autoritară. Modul manual rămâne separat,
controlat de `PAPER_SOLANA_EXECUTION=jupiter`.

Servicii necesare: `api.jup.ag`, `api.kraken.com`, RPC-ul Solana configurat și feedurile existente.
`api.exchange.coinbase.com` este fallback pentru FX. În cloud, domeniul Kraken trebuie permis
în configurația de rețea. A fost adăugat în draft; salvarea draftului nu demonstrează singură
aplicarea sau publicarea. Probele live verifică accesul efectiv separat.

În acest mediu s-au primit cotații Jupiter fără cheie. Aceasta nu garantează acces public în
alte medii sau în viitor. Pentru HTTP 401/403 configurează `JUPITER_API_KEY` în setările securizate
sau `JUPITER_API_KEY_FILE` în afara Git. Nu introduce cheia în chat sau în configurația UI.
Nu s-a cumpărat un abonament. Limitele și tarifele planului ales rămân aplicabile. Bugetul plin
de 4 încercări/minut înseamnă cel mult aproximativ 5.760 încercări/zi, cu RPC, FX și quote pentru
fiecare; nu este o capacitate promisă. AI/Telegram nu sunt necesare acestei etape.

## Verificare executabilă

Într-un director de date **nou**, pornit din repository:

```bash
DATA_DIR=/tmp/memescope-routed-demo uv run --frozen python -m uvicorn app.main:app --host 127.0.0.1 --port 8767
```

În alt terminal:

```bash
uv run --frozen python -m app.routes_verify --url http://127.0.0.1:8767 --duration 1200 --output /tmp/routed-proof.json
```

Verificatorul folosește numai GET. Cere candidat cu observații reale, cotație de cumpărare
salvată, cotație de vânzare după minimum 5 minute, rezultat net și politică/încercări persistente.
Lipsa datelor produce `complete=false`, exit 1. Nu injectează tokenuri sau ordine și nu relaxează
filtre. Pe PowerShell setează `$env:DATA_DIR` înainte de pornire și folosește căi Windows pentru
fișierul de rezultat. Rulează separat testele simulate:

```bash
uv run pytest -q
uv run ruff check app tests
node --check app/static/opportunities.js
uv run --with playwright python tests/browser_opportunities.py
```

[Dovezi și rezultate](routed-evidence/RESULTS.md). 1h/24h și performanța pe un holdout declarat
necesită colectare ulterioară. Următoarea etapă este un experiment prospectiv, cu politică și
perioadă de test fixate înaintea datelor, suficiente observații și incertitudine raportată.
