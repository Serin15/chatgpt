# MemeScope v0.14.0 — colectare la timp și evaluare prospectivă

Cod aplicație/teste: `e0b574e0673e66e935054cc0c36667df51f12943`.
Cele trei priorități sunt implementate ca mecanisme verificabile. Nu înseamnă
că selecțiile sunt validate statistic sau că toate observațiile vor fi disponibile.

## 1. Securitate și cotații înainte de expirare

În v0.13.3, cotațiile rutate porneau după întregul lot. O verificare de securitate
încă validă la salvarea observației putea expira până la cererea Jupiter.

Acum motorul solicită cotațiile după salvarea observațiilor, înainte de a continua
cu alți candidați lenți. Există un **singur buget total per ciclu**: implicit
maximum 4 încercări rutate, nu câte 4 pentru fiecare candidat. Erorile dintr-o
încercare rămân vizibile chiar dacă următoarea verificare nu găsește nimic de cotat.

Cache-ul de securitate este reîmprospătat mai devreme, în bugetul existent de
maximum 8 verificări. Rezerva este `min(max_snapshot_age, quote_timeout * budget + 5)`,
implicit 85 secunde. Aceasta schimbă momentul citirii datelor, fără să prelungească
limita de prospețime de 120 secunde. Dacă reîmprospătarea eșuează, evidența rămâne
necunoscută și filtrele continuă să blocheze tranzacția virtuală.

## 2. Prețuri mai recente pentru loturile următoare

Loturile păstrează limita de 30 subiecți și numărul de cereri de piață anterior.
Lotul următor este cerut după procesarea celui curent. Astfel, prețurile lui nu
mai așteaptă după verificările și cotațiile pentru toate loturile precedente.

Prima observație eligibilă, regulile de prefetch v1/v2, termenele, lichiditatea,
riscul și regulile de cost rămân păstrate. Refuzurile terminale și cotațiile
întrerupte nu sunt reîncercate pentru a căuta un rezultat mai bun. Datele lipsă
nu devin PnL zero sau ieșiri reușite.

## 3. Protocol viitor, separat de cutoff-urile istorice

O politică nouă primește o declarație prospectivă înaintea primelor semnale.
Folosește cutoff-ul configurat dacă este încă viitor; altfel, testul separat
începe la 24 de ore după declarație. Declarația este salvată o singură dată,
legată de hashul politicii și protejată de modificare/ștergere prin triggeri SQLite.
O politică cu baseline-uri deja existente nu poate fi înscrisă retroactiv.

Raportul zilnic și exportul adaugă `forward_evaluation`, cu dezvoltare/test,
eliminarea observațiilor de la graniță, grupul selectat și controlul fără
suprapunere. Candidații lipsă/respinși rămân în numitor; mediile PnL se calculează
numai pentru rezultatele evaluate. Parametrii nu se optimizează după acest raport.
Cutoff-urile și comparațiile originale rămân neschimbate, în câmpurile existente.

În dashboard: **Oportunități timpurii → Bilanț zilnic → Validare prospectivă**.
O perioadă de test începută este etichetată drept colectare, fără afirmație de
validare/profitabilitate. Pentru baza cloud, politica 17 a fost declarată la
**21 octombrie 2026, 04:27:18 UTC**, cu test de la **22 octombrie, 04:27:18 UTC**.
Cutoff-ul original `2026-10-18T00:00:00Z` este păstrat. Pe PC, politica nouă
primește propria declarație la pornirea versiunii, fără resetare la repornire.
Colectarea continuă numai cât aplicația rulează. Opririle rămân lipsuri în date;
prețurile actuale nu reconstruiesc observațiile ratate.

## Dovezi și teste

- Înaintea corecției: **3 regresii reproduse, 1 control trecut** — întârzierea
  ieșirii, securitate apropiată de expirare și prefetch al lotului următor.
- Suita completă: **486 passed**, un avertisment Starlette/httpx de deprecare,
  125,34 secunde local. Testele de furnizori sunt simulate.
- Chromium: **26/26** scenarii cu furnizori/baze izolate; include protocolul
  viitor, PnL negativ, control fără rezultate și layout mobil.
- Ruff, sintaxa celor trei fișiere JS, `uv sync --frozen` și `git diff --check`:
  trecute, fără dependențe noi.
- CI nativ Windows/Linux:
  [39544217200](https://github.com/Serin15/chatgpt/actions/runs/39544217200).
  **Succes pe ambele platforme**: logurile oficiale confirmă 486 teste fiecare,
  70,74 secunde pe Ubuntu și 502,24 secunde pe Windows. Chromium: 26/26 pe Linux;
  launcherul nativ Windows dintr-un folder cu spații: trecut.
  [ci.json](freshness-evidence/ci.json).

Artefacte: [reproducere](freshness-evidence/collection-before.txt),
[pytest](freshness-evidence/pytest.txt), [Chromium](freshness-evidence/browser.json),
[backup](freshness-evidence/backup.json),
[integritatea istoricului](freshness-evidence/preservation.json),
[compatibilitate](freshness-evidence/compatibility.json),
[browser pe date reale](freshness-evidence/browser-live.json).

Verificările pe servicii reale sunt separate de acestea și documentate în
`freshness-evidence/`. Un observator numai GET fixează candidatul/semnalul după
intrarea cotată și înaintea ieșirii, fără schimbarea pragurilor sau înlocuirea
candidatului dacă pierde/eșuează. Un test de 24 de ore nu poate fi grăbit prin
modificarea ceasului sau atribuirea retrospectivă a datelor.

### Caz real fixat înaintea ieșirii

| Etapă | Dovadă reală, UTC |
| --- | --- |
| Descoperire | 21 octombrie 04:27:18, CHAMPI / SOL, candidat 74616 |
| Contract | `4YumeWB5HptRuAnZPqAo1NnHBBkMd2kX6B6fQ3tn81GV` pe Solana |
| Semnal / politică / alertă | 181553 / 17 / 4376; selectat înaintea ieșirii, în afara controlului fix |
| Intrare Jupiter | 04:28:23, cotație reală pentru poziția virtuală de $50 |
| Ieșire Jupiter | 04:34:24; durată efectivă 361,26 secunde pentru ținta de 5 minute, în fereastra declarată |
| Rezultat | +$13,70 **modelat** după costuri; nu este tranzacție executată sau dovadă de avantaj predictiv |
| Securitate | La primirea cotației: 2,79 secunde vechime la intrare și 3,03 secunde la ieșire; limita de 120 secunde păstrată |
| Întârziere după salvarea observației | 0,38 secunde la intrare, 1,66 secunde la ieșire; un singur caz, fără estimare generală de îmbunătățire |
| Dashboard | Alerta confirmată în aplicație, dosar accesibil și `evaluated · PnL virtual 13,70 USD`; fără erori JS |

[live-window.json](freshness-evidence/live-window.json) păstrează observațiile,
cotațiile și încercările legate de același semnal;
[live-summary.json](freshness-evidence/live-summary.json) calculează vârstele și
timpii de dispatch. [candidate-browser.json](freshness-evidence/candidate-browser.json)
confirmă afișarea, fără interceptări sau stare injectată. Conturile manuale
au rămas $500/$100, cu zero ordine. Cazul vechi nereușit din v0.13.3 rămâne
nemodificat în istoric.

[daily-live.json](freshness-evidence/daily-live.json) și
[protocol-browser.json](freshness-evidence/protocol-browser.json) confirmă
declarația prospectivă reală și afișarea ei pe desktop/mobil. În această etapă,
**rezultatele perioadei de test viitoare sunt neverificate**, deoarece aceasta
nu a început. Rezultatul pozitiv de mai sus aparține dezvoltării.
Exportul real în citire este confirmat în
[offline-export-summary.json](freshness-evidence/offline-export-summary.json).

## Compatibilitate și date

| Fișiere | Schimbare |
| --- | --- |
| `app/opportunities.py` | Reîmprospătare preventivă, loturi la momentul procesării, dispatch incremental și declarații înaintea semnalelor |
| `app/opportunity_routes.py` | Limită rămasă din bugetul comun și compatibilitate explicită cu v0.13.3 |
| `app/forward_evaluation.py` | Registru imuabil și comparații separate după protocolul viitor |
| `app/daily_research.py` | Extinde raportul/exportul păstrând raportarea istorică |
| `app/static/opportunities.js` | Panou prospectiv cu stări, perioade și control distinct |
| `tests/test_collection_timing.py`, `tests/test_forward_evaluation.py`, `tests/browser_audit.py` | Regresii de timp, buget, erori păstrate, protocol, export în citire și mobil |
| Fișierele versiunii, README și documentația | v0.14.0; fără pachete noi |

`paper.py`, `jupiter.py`, regulile de scor, selecția observațiilor și sampling-ul
sunt identice cu v0.13.3. În clasa `Routes`, doar `cycle` primește limita pentru
dispatch incremental; metodele de claim, fill, finish, validare și recuperare
rămân identice AST. Componenta anterioară `a1a61c…` este admisă explicit;
hashurile necunoscute rămân blocate. Metadatele de colectare sunt înghețate în
noile politici. Formulele de preț, cost și cantitate nu sunt schimbate.

Înainte de pornire: backup SQLite consistent, `quick_check=ok` pentru ambele baze.
După pornire sunt confirmate identice toate cele **181.476 semnale**, **16 politici**,
configurația, **106.874 politici Jupiter** și **319.887 rezultate Jupiter deja
finale** din backup. Datele noi sunt adăugate; rezultatele vechi în așteptare pot
evolua normal sau pot înregistra termene ratate în timpul opririi. Baza are
aproximativ **3,8 GB**, fără ștergerea istoricului. Schema adaugă registrul
protocoalelor și un index pentru căutarea semnalelor după politică.

## Instalare și verificare

```bash
uv sync --frozen
uv run --frozen python -m app.desktop
uv run --frozen pytest -q
uv run --frozen ruff check app tests
uv run --frozen --with playwright python tests/browser_audit.py
uv run --frozen python -m app.routes_verify --url http://127.0.0.1:8000 --duration 900 --output routed-proof.json
uv run --frozen python -m app.research_evaluate --data-dir data --output discovery-report.json
```

Auditul browserului cere Chromium; `BROWSER_EXECUTABLE` poate indica executabilul.
Aplicația obișnuită folosește browserul sistemului. Verificatorul general poate
găsi și dovezi istorice: verifică politica și hashul componentei înainte de a
atribui un rezultat acestei versiuni.

Windows: oprește aplicația veche, fă backup la `data` și `.env` dacă există,
extrage arhiva completă, copiază datele existente în noul folder și pornește
`start-windows.cmd`. Folosește portul afișat și Ctrl+F5; versiunea trebuie să fie
v0.14.0. Actualizarea cloud nu schimbă automat copia de pe PC.

## Costuri și limite rămase

Nu sunt necesare chei sau abonamente noi pentru această corecție. Se folosesc
aceleași surse de piață/securitate, RPC, Jupiter și FX. Plafonul per ciclu este
neschimbat, dar reîmprospătarea mai devreme poate crește consumul mediu până la
limita configurată. Accesul, cotele și tarifele rămân cele ale furnizorilor.

- Disponibilitatea tuturor cotațiilor și verificărilor nu este garantată. API
  failures, epuizarea bugetului, latența sau lipsa lichidității pot bloca ieșirea.
- Reducerea procentuală a lipsurilor necesită un eșantion comparabil suficient;
  nu este estimată dintr-un singur caz.
- Testul prospectiv abia este declarat. Colectarea datelor viitoare și separarea
  de dezvoltare sunt implementate; avantajul statistic/profitabilitatea nu sunt
  demonstrate.
- Arhivarea și capacitatea pentru baza în creștere rămân următoarea prioritate.
- AI, Telegram, Base, afilierea știre–contract și găzduirea publică nu sunt extinse
  sau validate în această etapă. Execuția cu bani reali rămâne dezactivată.

| Funcție din această etapă | Stare |
| --- | --- |
| Dispatch incremental și buget comun | Implementate, verificate prin integrare și pe fluxul real descris |
| Reîmprospătare preventivă a securității | Implementată, regresia aproape de expirare verificată cu fixture-uri; cotațiile reale au rămas sub limita originală |
| Loturi cerute la momentul procesării | Implementate, ordinea și numărul cererilor verificate prin regresie |
| Registru prospectiv, raport și export | Implementate, verificate în SQLite, export real și browser desktop/mobil |
| Rezultatele viitoarei perioade de test | Neverificate: perioada începe la 22 octombrie 04:27 UTC pentru baza cloud |
| Reducere generală a observațiilor lipsă / avantaj predictiv | Nedemonstrate: necesită colectare continuă și comparații suficiente |
