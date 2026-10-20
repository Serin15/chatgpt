# MemeScope v0.13.3 — ferestre Jupiter

Corecție pentru observațiile preluate înainte de începutul ferestrei de măsurare.
Codul aplicației și testelor: `367153c4d446faee07ad6218a0dcf919425f5ced`.

## Problema reprodusă

Un preț poate fi preluat înainte de termen, iar verificările de securitate și
salvarea observației se termină după termen. Jupiter selecta prima înregistrare
salvată în interval și respingea definitiv experimentul deoarece prețul fusese
preluat prea devreme. În plus, jobul `routed_exit` folosea versiunea regulii de
pool, care putea diferi de regula Jupiter înghețată pentru același semnal.

Cele 12 cazuri inițiale au produs **4 eșecuri și 8 controale trecute** înaintea
corecției: [regression-before.txt](jupiter-window-evidence/regression-before.txt).

## Ce s-a schimbat

- `app/opportunity_routes.py`: noile politici `jupiter-forward-v2` declară
  `forward_quote_window_version=2`. Se omit numai observațiile pentru care prețul
  a fost demonstrabil preluat înaintea ferestrei; experimentul așteaptă în
  interiorul termenului original. Versiunea absentă păstrează prima înregistrare.
- `app/opportunity_sampling.py`: pentru `routed_exit`, versiunea provine din
  politica Jupiter a semnalului. Intrările, ieșirile de pool și checkpointurile
  continuă să folosească propria regulă.
- `tests/test_routed_windows.py`: intrare/ieșire, versiuni diferite pool/Jupiter,
  limita exactă a intervalului, expirare fără prelungire, păstrarea primei erori
  reale chiar dacă există ulterior date bune și politici nemodificate.
- `tests/test_opportunity_routes.py`: compatibilitatea versiunilor anterioare
  verifică politici fără noul câmp. Încă un hash auditat admis explicit.
- Fișierele versiunii, README și acest document: v0.13.3, fără dependențe noi.

Lipsa prețului, HTTP 400/401, refuzul de risc, întreruperea unei solicitări și
expirarea ferestrei rămân rezultate finale. Nu există reîncercare favorabilă,
backfill cu prețul actual, ieșire inventată sau PnL zero pentru date lipsă.

## Compatibilitate și păstrarea datelor

`paper.py`, `jupiter.py`, `opportunity_outcomes.py` și `opportunity_rules.py` sunt
identice cu v0.13.2. În clasa `Routes` se schimbă doar `policy` și `ready`;
metodele de cerere, calcul, închidere, raportare și deduplicare sunt identice AST:
[compatibility.json](jupiter-window-evidence/compatibility.json).

Componenta nouă are SHA256
`a1a61cf2fd3d2947d3be48c3e004cdeb4e0bbcc70799587d889b590ec1f69060`.
Hashul v0.13.2 `fe46e95ea88180be8f23662d47dfac23276d4b24e7e96c5ceec9d1c6cb61d828`
este admis explicit pentru solicitările viitoare cu regula veche. Hashurile
necunoscute rămân blocate. Nicio politică veche nu primește retroactiv versiunea 2.

Backup SQLite consistent înaintea repornirii, cu `quick_check=ok` pentru ambele
baze: [backup.json](jupiter-window-evidence/backup.json). După repornire au fost
comparate toate cele **149.545 semnale**, **15 politici**, configurația,
**86.892 politici Jupiter** și **259.836 rezultate Jupiter deja finale** din
backup. Numărul și hashurile sunt identice:
[preservation.json](jupiter-window-evidence/preservation.json).

Cutoff-ul original `2026-10-18T00:00:00Z` rămâne nemodificat. Politica nouă 16,
declarată ulterior, este `unassigned` pentru acel split; nu reprezintă un nou
test independent. Baza principală are aproximativ 3,16 GB. Nu s-a șters istoric.

## Verificări izolate

- Suita completă: **474 passed**, un avertisment Starlette/httpx de deprecare,
  115,33 secunde: [pytest.txt](jupiter-window-evidence/pytest.txt).
- Chromium: **25/25** scenarii, baze temporare și furnizori izolați:
  [browser.json](jupiter-window-evidence/browser.json).
- Ruff, `git diff --check` și `uv sync --frozen`: trecute.
- CI nativ Windows/Linux:
  [39401899155](https://github.com/Serin15/chatgpt/actions/runs/39401899155).
  **Succes pe ambele platforme**, inclusiv launcherul nativ Windows dintr-un
  director cu spații. Logurile oficiale confirmă **474 teste** pe fiecare:
  81,41 secunde pe Ubuntu și 916,33 secunde pe Windows. Chromium pe Linux:
  **25/25** scenarii; [ci.json](jupiter-window-evidence/ci.json).

Aceste teste folosesc mock-uri pentru RPC, FX și Jupiter. Demonstrează regulile
de selecție și regresiile, fără să pretindă disponibilitate reală a furnizorilor.

## Verificare pe instanța normală

Browserul normal v0.13.3 a navigat prin toate cele nouă secțiuni, fără interceptări
sau stare injectată. Panoul are 420 px, fără overflow mobil sau erori JavaScript;
toți cei cinci workeri și refuzurile reale ale furnizorilor sunt vizibili:
[browser-live.json](jupiter-window-evidence/browser-live.json).

Un observator separat folosește numai GET, fixează un singur candidat/semnal cu
noua politică după intrarea cotată și înaintea ieșirii, apoi păstrează rezultatul
aceluiași experiment. Nu schimbă praguri, nu introduce tokenuri și nu plasează
ordine: [live-window.json](jupiter-window-evidence/live-window.json) și
[rezumat](jupiter-window-evidence/live-summary.json).

Cazul fixat înaintea ieșirii:

| Etapă | Rezultat real, UTC |
| --- | --- |
| Descoperire | Candidat 62676, TADA / SOL, GeckoTerminal, 20 octombrie 09:36:25; pool creat raportat 09:33:58, lansarea tokenului necunoscută |
| Contract Solana | `8nJYCSnp7CctMavMpa93P4osqfPN9tHZV7T55cpBFaob` |
| Semnal și stocare | 149609, `INVESTIGATE`, politică 16, observații reale de piață și securitate |
| Alertă în aplicație | 3743, confirmare de afișare 09:37:29; Telegram nelivrat |
| Intrare | Cotație Jupiter reală la 09:37:52 pentru poziția virtuală de $50; costul de intrare include presupunerile de comisioane |
| Ieșire la 5 minute | **Indisponibilă**: verificările de securitate au expirat înaintea solicitării. PnL **necunoscut**, fără ieșire Jupiter reușită |
| Dashboard | Dosar accesibil, alertă vizibilă și `exit_unavailable · PnL virtual —` afișat pentru același semnal, fără erori JavaScript |

[candidate-browser.json](jupiter-window-evidence/candidate-browser.json) confirmă
afișarea alertei și a rezultatului nereușit. Observația de ieșire 244334 a fost
salvată la 09:43:29 cu securitate de la 09:41:31, încă în limita de 120 secunde.
Încercarea rutată a început la 09:43:53, după expirare. Acesta este un blocaj de
prospețime/programare rămas de rezolvat, nu o dovadă că API-ul era indisponibil.
Rezultatul final nu a fost reîncercat sau înlocuit cu alt candidat.

**Experimentul fixat anticipat nu a validat intrarea–ieșirea cu PnL.**
Ramura de prefetch este verificată cu furnizori simulați; acest caz real nu a
întâlnit-o. Conturile manuale au rămas $500/$100, fiecare cu zero ordine.
Candidatul aparține atât selecțiilor, cât și controlului fix; nu oferă o
comparație între grupuri disjuncte sau dovadă de performanță statistică.

Separat, o verificare tehnică a primului baseline deja finalizat din politica
16, ordonat după ID și fără filtru pe PnL, confirmă un flux complet automat:
candidat **62711**, STICKFU / SOL, contract
`UYjGLdiYXcvfiLUszVo8HqWqQBX3BWvpbA4MfGh2Soc`, semnal **149751**, alertă **3746**.
A fost descoperit la 09:39:26, a primit intrare Jupiter la 09:40:51 și ieșire
la 09:47:59, cu $5,41 PnL **modelat** după costuri. Orizontul țintă era 5 minute;
durata efectivă a fost **428,09 secunde**, în fereastra de ieșire declarată.
Verificatorul leagă ambele cotații, observațiile și cantitatea vândută:
[completed-case.json](jupiter-window-evidence/completed-case.json).
Alerta și rezultatul apar în dashboard:
[completed-browser.json](jupiter-window-evidence/completed-browser.json).

Acest exemplu a fost ales **după finalizare pentru verificarea tehnică**. Nu
înlocuiește experimentul anticipat nereușit și nu validează selectarea viitoarelor
câștiguri. La 09:48:14, universul de **157 baseline-uri** sub politica 16 avea
147 respinse/blocate inițial, 5 intrări indisponibile, 2 ieșiri indisponibile,
1 rezultat evaluat și 2 încă în așteptare. Eșantionul evaluat **n=1** nu susține
o concluzie de profitabilitate; toate stările rămân în
[prospective-snapshot.json](jupiter-window-evidence/prospective-snapshot.json).

## Pornire și reproducere

```bash
uv sync --frozen
uv run --frozen python -m app.desktop
```

Pe Windows: oprește versiunea veche, păstrează un backup pentru `data` și `.env`
dacă există, extrage integral versiunea nouă, copiază datele existente în ea,
apoi deschide `start-windows.cmd`. Folosește portul afișat la `Ready` și Ctrl+F5.
Codul actualizat în cloud nu schimbă automat copia de pe PC.

```bash
uv run --frozen pytest -q
uv run --frozen pytest -q tests/test_routed_windows.py tests/test_opportunity_routes.py tests/test_observation_sampling.py
uv run --frozen ruff check app tests
uv run --frozen --with playwright python tests/browser_audit.py
uv run --frozen python -m app.routes_verify --url http://127.0.0.1:8000 --duration 900 --output routed-proof.json
```

Auditul de browser necesită Chromium (`BROWSER_EXECUTABLE` poate indica
executabilul). Aplicația normală folosește browserul sistemului. Verificatorul
general poate găsi și experimente istorice; verifică hashul componentei și
versiunea ferestrei înainte să atribui dovada acestei versiuni.

## Servicii, costuri și lucruri rămase

Nicio cheie, dependență ori subscripție nouă necesară pentru această corecție.
Rămân RPC Solana, datele de piață/securitate, Jupiter și FX Kraken/Coinbase.
Cheia Jupiter este opțională în client; accesul, cotele și tarifele depind de
furnizor. Bugetele existente rămân 60 observații, 8 verificări de securitate și
4 solicitări rutate per ciclu. Nu s-au activat servicii plătite.

Priorități rămase:

1. Prioritizarea prospețimii securității și a momentului solicitării rutate:
   cazul real arată că o verificare încă validă la salvare poate expira în
   așteptare. Colectare continuă cu buget controlat pentru celelalte lipsuri.
   Corecția rezolvă prefetch-ul, nu aceste întârzieri ori lipsa dovezilor de
   securitate. Nu se poate estima încă o reducere procentuală validă.
2. Compararea prospectivă a selecțiilor cu întregul univers eligibil și cu un
   control separat, raportând lipsurile, mărimea eșantionului și costurile.
   Este necesară o perioadă viitoare declarată separat pentru validarea politicii
   noi. Niciun prag nu a fost ajustat după rezultatele observate aici.
3. Arhivare și capacitate pentru baza de peste 3 GB, păstrând candidații respinși,
   dispăruți, primele semnale și rezultatele nereușite.

Asocierea știre–contract pentru un document proaspăt, livrarea Telegram,
calitatea analizelor AI, extinderea Base și găzduirea publică nu sunt validate
de acest pas. O cotație este o simulare a unui fill posibil, nu execuție reală
garantată. Nu există dovadă statistică de profitabilitate ori predicție 10x/100x.

| Funcție din acest pas | Stare |
| --- | --- |
| Selecția ferestrei Jupiter v2 și păstrarea v1 | Implementată și verificată prin regresii; ramura de prefetch neverificată pe un caz real |
| Legătura joburilor cu versiunea politicii proprii | Implementată și verificată prin integrare SQLite |
| Păstrarea istoricului | Verificată prin comparația hashurilor datelor reale |
| Descoperire → evaluare → alertă → intrare Jupiter | Verificată cu date și servicii reale pentru cazul de mai sus |
| Ieșire Jupiter → PnL net | Verificată tehnic pe cazul suplimentar 62711/149751; experimentul anticipat 62676/149609 rămâne cu ieșire indisponibilă |
| Afișarea alertei și a rezultatului nereușit | Verificată în browserul normal |
| Avantaj statistic al selecțiilor | Nedemonstrat; necesită eșantion prospectiv suficient și test separat |
