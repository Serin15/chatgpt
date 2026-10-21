# MemeScope v0.16.0 — prioritate pentru descoperirile timpurii

Motorul separă reevaluarea inițială de monitorizarea periodică a candidaților
vechi. După încheierea ferestrei de fundal (implicit **48 de ore de la
înregistrarea în motor**), un candidat fără obligații deschise intră în pauză
pentru colectarea periodică. Dosarul, descoperirea inițială, semnalele, scorurile,
observațiile, rezultatele, politicile și apartenența la control rămân păstrate și
accesibile prin căutare. Pauza nu reprezintă o ieșire reușită sau o pierdere zero.

Nu se elimină rânduri și nu se rescriu termene, grupuri sau rezultate istorice.
Arhivarea fără pierderi din [v0.15](STORAGE-V0.15.md) rămâne disponibilă separat.

## Ce s-a reparat

1. Candidații vechi, cu urmărirea promisă încheiată, erau programați pentru
   reevaluare zilnică fără limită de vârstă. Restanțele creșteau permanent.
2. Locurile rămase după observațiile promise erau alocate exclusiv după
   `next_due`; un candidat vechi putea preceda un token aflat în primele minute
   de urmărire. Acum colectarea inițială, lista personală și referințele recente
   la contract precedă colectarea de fundal.
3. Contorul de restanțe nu diferenția reevaluările periodice în pauză de cele
   încă eligibile. Interfața afișează ambele și păstrează totalul brut.

Regula operațională de 48 de ore nu este optimizată după randamente viitoare.
`background_watch_hours` acceptă 1–168 prin configurația existentă a motorului;
`active_watch_seconds` și bugetele existente rămân respectate. Noua regulă este
inclusă în amprenta codului și în politicile create de acum înainte. Politicile
vechi și granițele lor dezvoltare/testare nu se modifică. Pentru politica nouă
se aplică o nouă declarare prospectivă; datele de dezvoltare nu validează
profitabilitatea viitoare.

## Bugetul verificărilor de securitate

Rularea reală a scos la iveală un al patrulea blocaj: verificările pentru
candidații procesați primii puteau consuma tot bugetul înainte de descoperirile
noi. Se rezervă acum până la `ceil(security_budget / 3)` apeluri pentru
candidații aflați în fereastra activă sau încă fără prima observație. Cu buget de
un singur apel, rezervarea alternează între cicluri. Locurile eliberate pot fi
folosite de candidații procesați ulterior. Unele pot rămâne nefolosite dacă
ultimii candidați nu au nevoie de verificare sau nu au lichiditate suficientă.

Ordinea cotațiilor și termenele observațiilor promise rămân respectate. Nu se
mărește bugetul total și nu se relaxează verificarea de securitate, vechimea
acceptată sau filtrele de lichiditate. Un apel eșuat consumă un loc și lasă
dovezile necunoscute. `status.security_allocation` raportează apelurile încercate
pentru candidații timpurii și pentru ceilalți; nu reprezintă numărul de tokenuri
sigure sau de verificări complete. Schimbarea are propria versiune în politica
înghețată și necesită evaluare prospectivă separată.

## Protecții

- Prima încercare de colectare este obligatorie chiar dacă furnizorul a fost
  indisponibil mai mult de 48 de ore.
- Observațiile de intrare, ieșire, reperele de preț și ieșirile rutate promise
  rămân prioritare, inclusiv când termenul este la șapte zile. Programul periodic
  și limita de vârstă nu le anulează.
- Rezultatele estimate sau rutate încă nerezolvate și intrările rutate în curs
  împiedică punerea în pauză. Termenele deja ratate rămân ratate.
- Lista de urmărire și pozițiile virtuale deschise din ambele conturi sunt
  protejate. Programul periodic și bugetul se respectă în continuare; scannerul
  pozițiilor manuale continuă independent.
- O referință nouă verificată la contract, în documentele deja acceptate de
  modulul de știri, poate relua urmărirea pentru fereastra activă. Se acceptă
  adresa explicită și blockchain-ul corespunzător sau o referință de pool
  calificată. Numele asemănător, dovezile viitoare și cele expirate nu ajung.
  Reluarea nu înseamnă o lansare nouă sau confirmarea unei asocieri oficiale.
- API-urile de stare și dosar sunt read-only pentru această funcție.

`queue.due` continuă să însemne totalul brut de candidați cu `next_due` periodic
scadent. `dispatchable_due` exclude candidații în pauză; `paused_due` păstrează
restul. Observațiile promise pot ocoli programul periodic: numărul lor distinct
este raportat separat prin `promised_due_candidates`, inclusiv partea din afara
cozii periodice. Nu aduna aceste grupuri fără a elimina suprapunerile.

## Căutarea în istoricul mare

Adresele Solana complete sunt căutate prin indexul de identitate, cu literele
mari și mici respectate. O adresă necunoscută nu este înlocuită cu alt token care
diferă numai prin capitalizare. Căutările după nume, simbol sau fragmente de
adresă rămân disponibile, cu o limită SQL de cinci secunde. Dacă o căutare este
prea costisitoare, API-ul răspunde controlat cu 503 și sugerează contractul
exact; datele deja afișate rămân păstrate. Nu se modifică prețurile sau istoricul.

Căutarea textuală în baze foarte mari poate necesita încă un index separat de
metadate înaintea unei lansări publice. Limita previne acumularea nelimitată de
interogări costisitoare; nu garantează că orice căutare textuală va reuși.

## Repornire după întreruperea procesului

La pornire, după obținerea blocării exclusive `RuntimeLock` pentru `DATA_DIR`,
aplicația elimină numai rezervarea temporară a vechiului worker. Astfel, o oprire
forțată nu mai impune așteptarea expirării unei rezervări de până la zece minute.
O a doua instanță încă activă împiedică această recuperare prin blocarea de dosar.
Nu se modifică dosare, semnale, solduri, termene sau rezultate istorice. Observațiile
ratate în timpul opririi rămân ratate.

## Raportarea nu mai blochează colectorul

Raportul complet de acoperire este calculat de workerul independent
`collection_report`, cu o pauză de 60 de secunde între calcule. Colectorul nu mai
așteaptă această citire a întregului istoric înainte de ciclul următor. Cererile
simultane pentru primul calcul folosesc aceeași operație; nu pornesc copii ale
aceluiași raport. Ulterior, API-ul servește ultimul raport complet din cache.

Interfața arată ora calculului și starea actualizării. Un eșec păstrează ultimul
raport și semnalează eroarea; timestampul nu este înlocuit cu ora cererii. Dacă
primul calcul încă rulează și nu există raport anterior, API-ul răspunde 503 cu
un mesaj de pregătire. Celelalte secțiuni rămân independente. Nu se inventează
contoare zero și nu se schimbă definițiile rezultatelor. Calculul poate rămâne
costisitor pe o bază mare; mutarea lui nu garantează acoperirea tuturor termenelor.

## Instalare și pornire

În Windows, închide aplicația veche, extrage complet versiunea nouă și păstrează
folderul `data` și configurația locală. Deschide `start-windows.cmd` din folderul
care conține `app` și `pyproject.toml`. Deschide `http://127.0.0.1:8000` dacă
browserul nu pornește automat. Nu rula două instanțe pe același `DATA_DIR`.

Cu Python 3.12 și uv, din rădăcina repository-ului:

```bash
uv sync --frozen
uv run --frozen python -m app.desktop
```

În pagina **Oportunități timpurii**, panoul calității colectării arată coada
periodică și obligațiile scadente. Dosarul unui candidat arată starea curentă a
monitorizării, separat de verdictul și observațiile istorice.

## Verificare reproductibilă

```bash
uv run --frozen ruff check app tests
uv run --frozen pytest -q
uv run --frozen pytest -q tests/test_candidate_lifecycle.py
node --check app/static/opportunities.js
uv run --frozen --with playwright playwright install chromium
# Linux cu Chromium instalat în /usr/bin/chromium:
BROWSER_EXECUTABLE=/usr/bin/chromium uv run --frozen --with playwright python tests/browser_audit.py
```

Testele Python folosesc furnizori simulați și baze SQLite reale, izolate.
Scenariile Chromium folosesc date explicite de test; nu sunt dovezi de precizie
pe piață. Dovezile pentru baza și aplicația normală sunt păstrate separat în
`docs/monitoring-evidence/` și explicate mai jos după rulare.

## Servicii, costuri și limite

Această versiune nu adaugă servicii, chei sau abonamente și nu mărește bugetele
API. Colectarea folosește în continuare furnizorii de piață și securitate deja
configurați. Cotațiile Jupiter necesită acces valid la endpointul furnizorului; cheia poate
depinde de endpoint și plan. Un quote de cumpărare real a fost verificat aici.
AI și Telegram rămân opționale și necesită propria configurare. Nu s-au verificat livrări noi
Telegram sau modele AI în această etapă.

Reducerea numărului de reevaluări eligibile nu reprezintă o creștere măsurată a
preciziei. Capacitatea poate rămâne insuficientă pentru toate observațiile;
rapoartele păstrează lipsurile. După pauză nu se observă automat fiecare revenire
de preț. O știre cu contract verificabil sau urmărirea manuală poate relua
monitorizarea; nu se poate măsura riguros rata tuturor oportunităților ratate.

Următorul pas recomandat: păstrarea unei politici stabile și măsurarea
prospectivă a acoperirii la intrare/ieșire și a rezultatelor nete, separat pe
politici și cohorte. Dacă se ratează încă multe termene, ajustarea capacității
sau a admisiei trebuie declarată ca experiment nou, fără reechilibrarea
retroactivă a grupului de control. Nu există dovezi că motorul identifică
predictibil tokenuri de 10x/100x. Tranzacționarea cu bani reali rămâne dezactivată.

## Dovezi pe date reale și starea funcțiilor

Baza normală, păstrată din versiunile anterioare, a fost folosită fără inserarea
manuală a unor tokenuri, semnale, cotații sau profituri. Înainte de modificări,
backupul a fost restaurat într-un dosar separat: **59 de tabele logice și
2.399.283 de rânduri identice**. Comparațiile ulterioare păstrează semnalele,
politicile, observațiile originale, controlul, termenele și rezultatele închise.
Fișierele de calcul financiar și funcțiile de scor sunt neschimbate față de v0.15.

- La prima măsurare: 70.018 candidați cu reevaluarea periodică scadentă, dintre
  care 39.100 intră în pauză prin noua regulă; 30.918 rămân eligibili. Este o
  limitare a monitorizării periodice, nu ștergerea restanțelor sau o creștere
  demonstrată a preciziei.
- Căutarea contractului candidatului vechi #1 a răspuns HTTP 200 în **0,56 s**.
  O căutare textuală costisitoare a răspuns controlat cu 503 după **5,057 s**.
- Raportul de colectare a răspuns HTTP 200 din cache în **0,012 s** și **0,028 s**,
  cu timestampul real al calculului păstrat. Nu se pretinde că raportul a fost
  recalculat la fiecare cerere.
- În browserul normal, candidatul #1 rămâne accesibil prin căutare, cu 9 observații,
  4 semnale și 9 rezultate. Starea lui este „pauză”. Pe desktop și la 390 px nu
  au apărut erori JavaScript sau depășirea lățimii ecranului.
- Conturile manuale rămân la **500 USD / 100 USD virtuali, zero ordine**.

Au fost păstrate separat încercările de validare, inclusiv cele nereușite:

1. **Primul candidat alertat după repornirea inițială:** #84388, semnal #209258,
   politica 22, alertă #5054. Livrare în aplicație confirmată. Observația de intrare
   a fost ratată; toate orizonturile acelui semnal au `missing_forward_entry`,
   iar profitul este `null`. Acest caz nu a fost șters sau înlocuit cu unul bun.
2. O fereastră intermediară de observație a fost întreruptă pentru corecția
   raportării. Nu reprezintă un test complet de performanță.
3. **Prima alertă eligibilă după corecția raportării:** #84492, contract Solana
   `6KTpCZ4MXUrcDEwdurxFbU3mf5SLfnKU6ego654upump`, semnal #209593, politica 24,
   alertă #5058. Alegerea a fost fixată la 16:52:02 UTC, înainte de rezultat.
   Descoperirea, piața, securitatea, scorul, verdictul, stocarea și livrarea în
   aplicație sunt reale. Observațiile ulterioare au actualizat dosarul automat.
   Intrarea estimată de 50 USD a fost acceptată în model, cu cost de numerar
   50,01 USD, comision și impact incluse. La orizontul de cinci minute, observația
   de ieșire a fost colectată, dar nu a trecut toate filtrele de securitate,
   lichiditate, cost sau timestamp: **`exit_unavailable`, profit necunoscut**.
   Aceasta nu dovedește că tokenul este imposibil de vândut pe blockchain.

Fluxul până la urmărirea unui rezultat nefavorabil/necunoscut este demonstrat.
Nu este demonstrată o tranzacție profitabilă, o ieșire Jupiter executabilă sau o
strategie eficientă. A fost stocat și un **quote Jupiter real de cumpărare** pentru
50 USD, cu `contextSlot=459703477`, slippage de 50 bps și traseu AMM. Quote-ul
Jupiter este separat de estimarea de pool; comisionul de conversie și taxa de
rețea din scenariu sunt ipoteze configurate. Încercarea de ieșire Jupiter a fost
oprită de filtrele de risc/lichiditate, fără quote de vânzare acceptat. Nu a fost
construită, semnată sau trimisă o tranzacție on-chain.

Cazul a fost nefavorabil: prețul raportat a trecut de la circa 0,00006917 USD la
intrarea estimată la 0,000001972 USD la observația de ieșire, aproximativ **−97,15%**.
Lichiditatea raportată a scăzut la aproximativ 1.988 USD, iar securitatea nu mai
era complet verificată. Acesta este un randament al prețurilor observate, nu un
profit net realizabil sau o pierdere executată. Sistemul păstrează `pnl_usd=null`.
Aceste exemple sunt date de dezvoltare; politica 24 are testul prospectiv declarat
pentru **22.10.2026, 16:51:23 UTC** (19:51:23 în România). Nu se modifică retroactiv
acest prag pentru a include exemplele favorabile.

| Funcție | Stare și tipul verificării |
| --- | --- |
| Fereastră de fundal, prioritate și protecția obligațiilor | Implementată; teste SQLite și stare reală verificate. Bugetele pot lăsa termene ratate. |
| Securitate rezervată pentru candidați timpurii | Implementată; regresie reprodusă, buget total verificat în teste și alocări reale observate. Nu certifică siguranța tokenului. |
| Dosare și istoricul comprimat | Implementate și verificate pe istoricul real, inclusiv în browser. |
| Căutare după contract exact | Implementată și verificată real; adresele care diferă prin capitalizare rămân distincte. |
| Căutare textuală pe istoricul mare | Parțial: există limită de execuție și eroare controlată; este necesar un index pentru scalare. |
| Raportare de acoperire în fundal și cache explicit | Implementată; verificată în teste, prin API real și interfață. Cache-ul poate fi vechi în timpul recalculării. |
| Recuperarea rezervării workerului la repornire | Implementată; blocarea OS și lease-ul sunt verificate cu SQLite real în teste. Pornirea normală este verificată. |
| Reactivare din documente cu contract verificabil | Implementată; testată cu documente simulate. O nouă știre reală nu a validat această ramură în această etapă. |
| Watchlist și poziții manuale în ambele conturi | Protecții implementate și testate; instanța reală nu are poziții manuale deschise. |
| Alertă în aplicație și observații ulterioare | Implementate și verificate pe un candidat nou real; rezultatul indisponibil rămâne explicit. |
| Profit net executabil și precizia semnalelor | Neverificate statistic. Ieșirea exemplului nu a trecut filtrele; nu se raportează profit zero. |
| Cotații Jupiter | Quote de cumpărare real verificat; ieșire nevalidată deoarece filtrele au respins observația. Nicio execuție on-chain. |
| AI și Telegram | Păstrate; neactivate și neverificate real în această etapă. OpenAI/Telegram necesită cheile/configurația lipsă, iar Ollama serviciul și modelul potrivit. Nu au fost substituite răspunsuri simulate în produs. |
| Base | Descoperire existentă; motorul complet de oportunități rămâne Solana. |

Fișierele JSON și logurile din `monitoring-evidence/` separă probele reale de
testele cu furnizori simulați. Timestampurile tehnice sunt UTC. Capturile sunt
ale instanței normale, fără interceptarea răspunsurilor sau injectarea de date.

## Fișiere modificate

- `app/opportunity_lifecycle.py`: clasificarea monitorizării, protecții și bugetul
  de securitate; fără ștergerea istoricului sau modificarea cohortelor.
- `app/opportunity_sampling.py`, `app/opportunity_rules.py`: ordinea colectării,
  fereastra configurabilă și raportarea distinctă a restanțelor.
- `app/opportunities.py`: metadate în dosare/politici, căutare exactă și limită
  SQL, raportare independentă și cache cu timestamp.
- `app/main.py`: recuperarea lease-ului sub blocarea exclusivă, workerul de raportare
  și endpointul care servește raportul complet din cache.
- `app/static/opportunities.js`: stările de monitorizare, contoare distincte și
  vechimea/starea raportului. Versiunea este actualizată în `app/__init__.py`,
  `app/static/index.html`, `pyproject.toml`, `uv.lock` și `README.md`.
- Teste noi pentru ciclul de viață, identitatea contractelor, repornire și cache;
  auditul Chromium și testul de responsivitate urmăresc noul worker separat.

## Probleme rămase, după prioritate

1. **P0 — validare prospectivă și acoperire:** măsurarea intrărilor/ieșirilor ratate
   pe cohorte stabile și creșterea capacității numai printr-un experiment declarat
   nou. Exemplele de mai sus nu demonstrează precizie, randament sau risc mic.
2. **P1 — scalare:** index pentru căutarea textuală și calcule incrementale pentru
   rapoartele istorice mari. Alte rapoarte inițiale pot fi încă lente; încărcarea
   candidaților și cache-ul de acoperire sunt separate.
3. **P1 — servicii și dovezi suplimentare:** validarea ieșirilor Jupiter pe cazuri compatibile,
   AI cu provider/model disponibil, Telegram cu bot/chat configurate; surse
   fiabile și timestampate pentru walleturi, distribuție și atenție socială.
4. **P2 — extindere și produs public:** validare completă Base, limite de resurse,
   monitorizare operațională și izolare pentru mai mulți utilizatori înainte de
   vânzarea ca serviciu. Aplicația curentă rămâne pentru cercetare personală.

Niciun abonament nou nu este obligatoriu pentru aceste modificări. Bugetele per
ciclu rămân aceleași; eliminarea blocajelor poate crește numărul de cicluri pe oră
și consumul API. Prețul serviciilor opționale depinde de planul furnizorului și nu
a fost verificat aici. AI/Telegram nu au fost activate, iar tranzacțiile reale
rămân dezactivate.

Pentru verificarea stării din PowerShell, cu aplicația pornită:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/healthz'
(Invoke-RestMethod 'http://127.0.0.1:8000/api/opportunities/coverage').report_cache | ConvertTo-Json -Depth 5
Invoke-RestMethod 'http://127.0.0.1:8000/api/opportunities/84492' | ConvertTo-Json -Depth 20
```

Ultimul ID există numai în baza folosită la demonstrație; în baza proprie se
folosește ID-ul dintr-un dosar real. Cheile opționale sunt configurate în mediul
procesului sau prin fișierele de secrete suportate: `JUPITER_API_KEY`,
`PULSE_AI_API_KEY`/`OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN` și `TELEGRAM_CHAT_ID`.
Ollama necesită serviciul local și modelul configurat. Nu introduce valori în Git.

Publicarea concurentă a unui raport nou nu poate combina contoarele unei capturi
cu timestampul alteia: răspunsul API folosește aceeași referință de raport pentru
conținut și data calculului. Regresia a fost reprodusă și verificată separat.


## Verificarea finală

Comanda `uv run --frozen pytest -q` a trecut local: **538 teste, un avertisment
upstream Starlette/httpx, 257,54 secunde**. `ruff check app tests` și verificările
sintactice Node pentru cele trei fișiere JS au trecut. Auditul Chromium are
**30 de scenarii trecute**, cu furnizori simulați și baze SQLite izolate.

Separat, 75 de citiri ale API-ului normal, pe durata schimbării raportului în
fundal, au păstrat identice `generated_at` și data capturii servite. Au fost
observate două versiuni ale raportului; latența maximă în acea probă a fost
1,1676 secunde. Nu este un benchmark de încărcare sau o garanție de latență.
Browserul normal afișează rezultatul `exit_unavailable` și `PnL —` pentru semnalul
209593, inclusiv pe mobil, fără erori JavaScript sau HTTP 5xx în probă.

Ultima politică a instanței după corecția concurentă a timestampului este **25**,
declarată la 21.10.2026, 17:19:51 UTC, cu test prospectiv de la **22.10.2026,
17:19:51 UTC**. Politica 24 și exemplele ei rămân păstrate separat. Datele de
exemplu nu sunt rezultate de test pentru politica 25.

Testele de responsivitate pentru raportare verifică workerul separat; nu mai
așteaptă etapa eliminată din ciclul urgent. Așteptările testului au și timeout,
astfel încât o etapă absentă să producă o eroare, fără blocarea infinită a suitei.

[Dosar real](monitoring-evidence/pipeline-research-desktop.png) ·
[Rezultat păstrat](monitoring-evidence/pipeline-outcomes-desktop.png) ·
[Rezultat pe mobil](monitoring-evidence/pipeline-outcomes-mobile.png)


Verificarea vizuală include atât semnalul original, cât și rezultatul de ieșire
al aceluiași candidat. MFE/MAE observat zero în fereastra nominală de cinci minute
are o singură cotație în acea fereastră; extrema reală rămâne necunoscută. Cotația
ulterioară de ieșire, la 6m55s de la intrare, arată scăderea raportată de 97,15%.
Cazurile cu observații lipsă nu devin tranzacții cu profit zero în rapoarte.

| Criteriu al demonstrației | Dovadă |
| --- | --- |
| Token real descoperit automat | Candidatul #84492, contractul și primul timestamp din `trial3-real-pipeline.json`. |
| Date de piață și securitate colectate | Capturi de furnizor reale, RPC/GoPlus la evaluarea inițială, necunoscute păstrate la ieșire. |
| Features, scoruri și verdict | Semnalul original #209593, politica 24; fără recalculare după rezultat. |
| Stocare | Aceleași ID-uri sunt disponibile în baza normală și prin API. |
| Alertă eligibilă și livrare | Alertă #5058 cu confirmarea clientului din aplicație; nu reprezintă dovada citirii de către om. |
| Observații ulterioare | Trei capturi, inclusiv intrarea estimată și observația de ieșire. |
| Rezultat urmărit | `exit_unavailable`, PnL necunoscut; quote Jupiter real la cumpărare, fără quote de vânzare acceptat. |
| Afișare în dashboard | Textul rezultatului și PnL „—” verificate în browserul normal, desktop și mobil. |

Nu au fost plasate ordine în portofoliile manuale; scenariile de mai sus sunt
experimente virtuale independente. Comenzile, cheile și costurile serviciilor
opționale sunt documentate mai sus. Nu a fost adăugat un serviciu plătit.


CI finală pentru codul `601f00632f69e8bd96104cea4aa138cf4598cbc2` a trecut pe
**Ubuntu și Windows**, inclusiv pornirea nativă și arhivarea/restaurarea din
foldere cu spații. [Rulare și loguri GitHub](https://github.com/Serin15/chatgpt/actions/runs/39642610188).
Ultimele commituri de documentare nu schimbă acel cod testat.
