# MemeScope v0.21.0 — pilot Solana de 30 de zile

Pilotul fixează înaintea colectării o perioadă de 30 × 24h și politica curentă.
Înscrie numai tokenuri Solana nou înregistrate în motor în acea perioadă. Nu atribuie
istoricul vechi noului studiu și nu pretinde acoperirea tuturor lansărilor din piață.

## Activare și folosire

Din folderul proiectului:

```bash
uv sync --frozen
uv run --frozen python -m app.desktop
```

Windows: oprește aplicația veche, păstrează întregul `data` și configurația locală,
pornește noul `start-windows.cmd`, apoi reîncarcă browserul cu `Ctrl+F5`.

În **Oportunități timpurii → Pilot 30 zile**, apasă **Începe pilotul de 30 de zile**.
Fiecare bază locală își are propriul pilot: activarea în cloud nu activează automat
baza de pe PC. Pilotul pornește printr-o cerere explicită și nu activează AI,
Telegram sau tranzacții. Nu sunt necesare pachete, chei sau abonamente noi.

Prima activare păstrează începutul, sfârșitul, politica și hashul protocolului.
Apăsările repetate returnează aceeași declarație. Nu există buton de resetare;
triggerii SQLite refuză UPDATE/DELETE ale declarației. Nu se mută declarațiile
anterioare development/test. Dacă testarea politicii inițiale nu a început încă,
comparația așteaptă și acel termen original.

Colectorul funcționează cât timp procesul și mașina sunt pornite. Treizeci de zile
calendaristice nu reprezintă dovada colectării neîntrerupte. Găzduirea permanentă,
spațiul de stocare, backupurile și disponibilitatea furnizorilor rămân necesare.

## Ce arată bilanțul

- Toate înregistrările noi, eligibilitatea, primele evaluări, alertele și afișările.
- Motivele pentru care un token nu intră în comparația politicii inițiale: lipsă de
  evaluare, schimbare de politică, sursă neconfirmată sau înscriere neprospectivă.
  Tokenul rămâne numărat în univers, inclusiv când este respins sau dispare.
- Mediana/p95 ale timpului înregistrare → evaluare, descoperire în sursă → alertă,
  alertă → afișare și semnal/primă alertă → observație eligibilă pentru intrarea paper.
  Sunt timpi de primire, nu latențe de execuție pe exchange. Intrările refuzate sau
  neobservate păstrează o latență necunoscută.
- Rezultatele nete după costurile originale pentru pool și Jupiter, separat.
  Nu se inventează PnL pentru lipsa unei cotații, o intrare respinsă sau o ieșire indisponibilă.
- Comparație între selecțiile de la prima evaluare și controlul prospectiv fără
  suprapunere. Se păstrează și întregul univers cu prime evaluări eligibile analizei.
- Urmărire descriptivă separată pentru prima alertă necritică a fiecărui token,
  inclusiv când alerta apare după prima evaluare. Repetările și upgrade-urile nu
  dublează această cohortă. Nu este un control sincronizat la momentul alertei.
- Punctualitatea observațiilor pentru alerte și control, cu verificarea identității,
  sursei, ferestrei originale și prospețimii prin validatorul existent de preț.
- Export JSON cu protocolul, data generării și rezultatele vizibile.

Comparația principală folosește numai orizonturi ajunse la termenul conservator:
`semnal + fereastra de intrare + orizont + fereastra de ieșire`. Aceeași regulă se
aplică tuturor grupurilor, independent de rezultat. Cu ferestre standard de 180s,
orizontul 5m intră în comparație după 660s de la semnal. Rezultatele mai rapide nu
fac să pară complet un grup în care celelalte tokenuri încă sunt în așteptare.

Prima evaluare și alerta ulterioară sunt distincte. O alertă nouă nu transformă
retroactiv prima evaluare respinsă într-o selecție. Modificarea regulilor produce
o altă politică; candidații ei rămân numărați, dar nu sunt amestecați cu politica
fixată la început. Nu se optimizează automat praguri pe datele pilotului.

Mediile sunt condiționate de rezultatele evaluate. Raportul păstrează numărul de
rezultate necunoscute și limite descriptive de sensibilitate. Corelațiile dintre
tokenuri și acoperirea inegală limitează interpretarea. Experimentele independente
nu sunt un portofoliu cu un singur buget; nu se deduce un drawdown de portofoliu.

## Stocare, API și izolare

`app/pilot.py` adaugă tabela `pilot_study` și un index pe chain/data înregistrării.
Nu rescrie semnale, costuri, rezultate, solduri sau programări. Calculul pilotului
folosește procesul de citire existent al rapoartelor, cu SQLite read-only. Un eșec al
pilotului nu elimină raportul de performanță existent. HTTP servește snapshotul
complet; afișează separat pregătirea, datele vechi și erorile, păstrând ultimul
bilanț afișat când actualizarea eșuează. Candidații continuă să fie accesibili.

- `POST /api/opportunities/pilot/start`: activare idempotentă.
- `GET /api/opportunities/pilot`: declarație și ultimul bilanț complet.

Ambele păstrează autentificarea existentă; POST păstrează protecția CSRF. Găzduirea
existentă este single-owner. Nu au fost introduse conturi multiple sau plăți.

## Verificare

```bash
uv run --frozen ruff check app tests
uv run --frozen pytest -q
node --check app/static/app.js
node --check app/static/advanced.js
node --check app/static/opportunities.js
BROWSER_EXECUTABLE=/usr/bin/chromium uv run --frozen --with playwright python tests/browser_audit.py
uv run --frozen python -m app.pilot_verify --url http://127.0.0.1:8000 --duration 1200 --output data/pilot-check.json
```

Folosește portul afișat de launcher. Verificatorul pilotului este read-only și cere
un pilot deja activat. Alege primul candidat disponibil fără filtrare după rezultat,
urmărește observația ulterioară și așteaptă grupuri mature selectate/control. Lipsa
unui grup eligibil în acea rulare rămâne criteriu neverificat; nu relaxează regulile.
Un PASS confirmă începutul fluxului, nu finalizarea celor 30 de zile sau profitabilitatea.

Testele folosesc ceasuri și furnizori controlați, baze SQLite reale și un subprocess
real de citire. Verifică limitele exacte, lipsa datelor viitoare, pierderi și ieșiri
necunoscute, controlul distinct, alertele ulterioare, idempotenta, autentificarea,
CSRF, exportul și layoutul mobil. Dovezile cu servicii reale sunt păstrate separat.

## Pornirea pilotului din acest mediu

Declarație în cloud: **25 octombrie 2026, 17:09:53 → 24 noiembrie 2026, 17:09:53**,
în Europe/Bucharest. Politica este **32**, iar declarațiile anterioare sunt păstrate.
Aceasta este o perioadă începută; cele 30 de zile nu au fost încă observate.

Înaintea unei beta comerciale mai sunt necesare evaluarea pilotului și feedback
de la utilizatori reali, operare continuă, conturi separate pentru varianta online,
costuri măsurate și drepturi de utilizare comercială a datelor. Produsul nu este
declarat pregătit pentru vânzare pe baza pornirii acestui pilot.
