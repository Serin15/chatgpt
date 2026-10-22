# MemeScope v0.19.0 — reevaluări prioritare și verificare live

Această versiune repară programarea colectării. Obiectivul este să obținem observații
ulterioare pentru candidați și pozițiile virtuale, cu termenele și lipsurile vizibile.
Nu demonstrează că scorurile anticipează creșteri de preț sau că sistemul este profitabil.

## Probleme reproduse înaintea modificărilor

- Un token vechi din watchlist sau dintr-unul dintre cele două portofolii virtuale putea
  primi următoarea verificare peste 24 de ore. Eticheta `manual_watch` nu modifica această
  cadență. O poziție adăugată între timp nu scurta programarea zilnică existentă.
- Observațiile promise puteau ocupa și toate locurile rămase după alocarea protejată,
  înaintea reevaluărilor active. Un token recent putea rămâne fără o a doua observație.
- Alternarea grupurilor de alerte/control determina și ordinea execuției: o observație cu
  termen apropiat putea ajunge după una cu termen mai îndepărtat.
- Verificatorul live putea accepta observații mai vechi decât propria pornire și putea
  număra două joburi servite de aceeași captură drept două observații distincte.

Regresiile și lipsa noilor diagnostice au fost reproduse în testele salvate în
[directorul de dovezi](collection-v0.19-evidence/). Sunt teste cu furnizori izolați și SQLite
real, separate de verificarea cu API-urile publice.

## Comportamentul nou

1. Alertele și controlul păstrează alocarea echilibrată protejată. Descoperirile păstrează
   rezerva existentă. Înaintea observațiilor promise suplimentare, până la
   `max(1, floor(observation_budget / 6))` locuri rămase sunt rezervate cercetării active.
   La bugetul standard de 60 sunt până la 10 locuri. Locurile nefolosite sunt împrumutate.
   Pentru bugete mici sau cerere excesivă nu există garanția servirii fiecărei categorii.
2. Watchlistul, pozițiile virtuale deschise și referințele documentate recente pot scurta
   o programare zilnică. Se folosește un termen efectiv calculat, fără rescrierea istoriei.
   Încercările eșuate păstrează backofful. O asemănare de nume nu reactivează un token.
3. După alegerea candidaților unici, execuția începe cu cel mai apropiat termen al unui job
   deja scadent. Orizonturile viitoare nu sunt aduse înainte și nu sunt prelungite.
4. Fiecare ciclu salvează `collection_plan`: versiune, buget, candidați admiși, categorii și
   primul termen scadent. Inclusiv observațiile fără preț păstrează categoria colectării.
5. Dashboardul separă întârzierea tokenurilor recente/urmărite de coada de fundal și de
   istoricul în pauză. Prospețimea încercării nu este prezentată drept preț executabil.
   Timestampurile viitoare/invalide sunt raportate separat.
6. Verificatorul acceptă doar cotații capturate și primite în timpul propriei rulări,
   în ferestrele originale ale joburilor. Acumulează dovezile între citiri și numără
   capturile distincte, păstrând separat fazele entry/exit/checkpoint.

## Instalare și pornire

Din folderul proiectului:

```bash
uv sync --frozen
uv run --frozen python -m app.desktop
```

Pe Windows: închide instanța veche, păstrează întregul folder `data` și configurația locală
în versiunea nouă, apoi deschide `start-windows.cmd`. În browser, `Ctrl+F5` reîncarcă
fișierele interfeței. Adresa implicită este `http://127.0.0.1:8000/#opportunities`;
launcherul afișează portul ales dacă cel implicit este ocupat.

Nu sunt necesare biblioteci, chei sau abonamente noi pentru această modificare. Se folosesc
integrările și configurația existente; limitele și tarifele furnizorilor rămân aplicabile.
Bugetele de observații, securitate și cotații Jupiter nu au fost mărite. Execuția cu bani
reali rămâne dezactivată. AI și Telegram nu sunt activate de acest release.

## Verificare reproductibilă

```bash
uv run --frozen ruff check app tests
uv run --frozen pytest -q
node --check app/static/app.js
node --check app/static/advanced.js
node --check app/static/opportunities.js
BROWSER_EXECUTABLE=/usr/bin/chromium uv run --frozen --with playwright python tests/browser_audit.py
uv run --frozen python -m app.collection_verify --url http://127.0.0.1:8000 --duration 600 --output data/collection-check.json
```

Ultima comandă necesită o instanță pornită care colectează date reale. Face doar cereri GET;
nu introduce candidați, nu modifică praguri și nu cumpără. Returnează cod 1 dacă intervalul
nu oferă toate dovezile necesare, chiar dacă în baza istorică există exemple mai vechi.
Capturile recente nu garantează intrări sau ieșiri economice; acestea au propriile filtre.

## Rezultate și limite

**579 teste Python și 40 de scenarii Chromium au trecut local.** Sunt incluse cadența
watchlistului și ambelor portofolii, reactualizarea după o referință documentată, refuzul
asocierii după nume, rezervarea capacității sub încărcare, ordinea termenelor, backofful și
refuzul dovezilor istorice/dublate. Testele de browser folosesc furnizori izolați, nu piața live.

Dovezile live și rezultatul urmăririi unei alerte sunt salvate separat în directorul de dovezi.
Valorile de acolo descriu intervalul măsurat și nu constituie estimări de randament viitor.

În rularea inițială, șase cicluri noi au înregistrat **111 candidați și 360 de observații**,
cu câte 10 locuri de reevaluare activă în fiecare ciclu. Starea inițială păstrată din rularea
precedentă este exclusă din aceste totaluri. Ciclurile au durat 62,55–114,67s; întârzierea
nu este declarată eliminată. Acest interval a inclus și verificări locale concurente.

Alerta reală **6798**, pentru candidatul **109064 / kimchi**, a fost aleasă înaintea
rezultatului ulterior, fără filtrare după câștig. Semnalul este din `2026-10-22T21:11:47Z`,
iar livrarea în aplicație este înregistrată la `21:12:32Z`. Intrarea estimată a fost observată
la `21:12:38Z`, pentru un cost virtual total de 50,01 USD. La evaluarea de 5 minute, observația
de ieșire a fost respinsă de filtrele modelului: **`exit_unavailable`, PnL necunoscut**.
Aceasta nu dovedește imposibilitatea vânzării pe blockchain. Un singur preț în interval nu
permite cunoașterea extremelor reale, chiar dacă extrema observată este zero.

După verificarea suplimentară a intervalelor personalizate mai lungi de 900s, aplicația a
fost repornită cu sursele finale. **Politica 30** corespunde hashului surselor livrate.
Verificatorul strict a confirmat toate cele șase criterii în **147s**, folosind **4 capturi
distincte pentru alerte și 12 pentru control**, toate capturate în propria rulare.
Dashboardul real a afișat 50 de rânduri și istoricul alertei păstrate, fără erori JavaScript
sau HTTP 5xx în verificarea UI finală; nu a depășit lățimea la 320/390/768/1536px.

Declarația prospectivă nouă este `2026-10-22T21:20:42Z`, cu testul de la
`2026-10-23T21:20:42Z`. Declarațiile 1–29 sunt păstrate; nu sunt mutate pentru a obține
rezultate favorabile. Soldurile manuale au rămas 100 USD și 500 USD, cu zero ordine.
În cloud, launcherul final a ales portul **8001**; dovezile finale folosesc acel port.
Folosește portul afișat de launcher și în comanda de verificare.

- Coada de fundal nu este ștearsă și nu este declarată rezolvată. API-urile și verificările
  lente pot încă depăși intervalul nominal de 60s și pot produce termene ratate.
- Testele locale verifică Linux/Chromium și dimensiuni mobile, nu dispozitive fizice.
  Rezultatul Windows al versiunii precedente nu validează automat această versiune.
- Corectarea cadenței pentru poziții virtuale este verificată pe SQLite izolat; conturile
  utilizatorului nu primesc ordine de test.
- Formulele de preț/cost, pragurile, contractele, clasificarea lansărilor și evaluarea
  financiară nu sunt modificate. Dispariția unui token sau lipsa unei ieșiri rămâne necunoscută.
- Noua programare primește o politică și un holdout prospectiv proprii. Politicile,
  declarațiile și rezultatele originale rămân păstrate; testul nu este mutat retrospectiv.

Următorul pas: măsurarea acoperirii și a termenelor ratate pe un interval mai lung, apoi
evaluarea selecției după costuri pe holdoutul declarat, cu grupul de control și incertitudine.
Îmbunătățirea clasificării/narațiunilor se validează separat înainte de alte schimbări de praguri.
