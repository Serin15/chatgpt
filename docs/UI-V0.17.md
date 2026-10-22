# MemeScope v0.17.0 — interfața de cercetare

Versiunea reorganizează interfața existentă într-un workspace cu fundal grafit, accente violet,
tipografie mai lizibilă și suprafețe coerente. Datele afișate provin din API-urile aplicației.
Avatarurile cu inițiale sunt elemente de navigare generate local, nu logo-uri oficiale.

## Ce s-a schimbat

- Navigație, titluri, formulare, tabele, știri și portofoliu cu aceeași ierarhie vizuală.
- Radar cu filtre rapide sincronizate cu filtrul complet, căutare prin `/`, număr de rezultate,
  identitate de chain, prioritate și timestamp pentru fiecare candidat.
- Salturi directe la candidați, alerte, bilanț și metodologie. Diagnosticele complete ale
  colectării se deschid separat; secțiunile care eșuează sunt numite în rezumatul vizibil.
- Dosar cu adresă copiabilă, explorer, piața poolului, verdict explicat, preț, lichiditate,
  volum și variație raportată. Închiderea dosarului invalidează cererile întârziate.
- Grafic cu observații reale, puncte izolate, goluri păstrate, timestamp la cursor și control
  prin săgeți, Home și End. Scăderea față de prima observație este colorată distinct.
- Ferestre 5m/15m/1h din caracteristicile deja calculate de motor. Lipsurile rămân
  „Istoric insuficient” sau „—”; nu se completează cu zero.
- Opt scoruri separate, cu sensul riscului de securitate explicat. Motivele pozitive,
  riscurile, necunoscutele și invalidările au secțiuni distincte. Traducerile sunt pentru
  texte fixe ale regulilor; formularea originală rămâne în tooltip și în dovezile JSON.
- Rezultate paper sub formă de carduri, cu stare, orizont, PnL și limitele MFE/MAE. Un PnL
  necunoscut rămâne necunoscut. Istoricul complet este accesibil chiar când lista arată 15 rezultate.
- Pe telefon: listă adaptată în carduri, bară inferioară și meniu cu toate destinațiile,
  focus limitat la meniu, Escape, revenire la butonul care l-a deschis și mișcare redusă.
- Încărcarea, lipsa datelor și timeout-ul au mesaje explicite. Un raport indisponibil nu
  produce patru carduri cu valori fictive și nu elimină accesul la candidați.

## Pornire și actualizare

În Windows, închide fereastra aplicației vechi, extrage noul ZIP și păstrează folderul `data`
al instalării existente. Pentru păstrarea istoricului într-un folder nou, copiază **întregul**
folder `data` după oprirea aplicației. Deschide `start-windows.cmd` din folderul cu `app`,
`pyproject.toml` și `uv.lock`. În browser folosește `Ctrl+F5` pentru reîncărcare completă.

Cu uv instalat, din terminalul deschis în folderul proiectului:

```powershell
uv sync --frozen
uv run --frozen python -m app.desktop
```

Pe Linux/macOS:

```bash
bash start-unix.sh
```

Adresa implicită este `http://127.0.0.1:8000/#opportunities`. Nu este o adresă publică.
Versiunea nu adaugă abonamente, chei API, pachete JavaScript sau costuri de UI. Fonturile,
stilurile și graficele sunt locale; sursele de date păstrează cerințele existente.

## Verificare

Comenzi din rădăcina proiectului:

```bash
uv sync --frozen
uv run --frozen ruff check app tests
uv run --frozen pytest -q
node --check app/static/app.js
node --check app/static/advanced.js
node --check app/static/opportunities.js
uv run --frozen --with playwright python tests/browser_audit.py
uv run --frozen --with playwright python tests/browser_regressions.py
uv run --frozen --with playwright python tests/browser_opportunities.py
uv run --frozen --with playwright python tests/browser_smoke.py
```

Scripturile browser folosesc Chromium. În mediul verificat, executabilul este
`/usr/bin/chromium`, configurabil prin `BROWSER_EXECUTABLE` pentru auditul principal.
Pe alt calculator trebuie instalat un Chromium compatibil și adaptată calea scripturilor.
Aceasta este o cerință de testare, nu de pornire a aplicației în browserul utilizatorului.

Rezultatele și capturile sunt în [dovezile acestei versiuni](ui-v0.17-evidence/).
Testele Python și scenariile browser folosesc furnizori izolați; nu demonstrează servicii externe
sau eficiența semnalelor. Verificarea `live-ui.json` folosește aplicația normală și baza existentă,
fără înlocuirea răspunsurilor sau injectarea unor prețuri. Actualizarea periodică a browserului
a fost dezactivată numai pentru a limita sesiunea de captură.

## Limite confirmate

- Pe baza existentă, cu peste 95.000 de candidați, raportul istoric de performanță poate depăși
  limita de 20 de secunde a cererii. Interfața indică indisponibilitatea și păstrează candidații
  și dosarele accesibile. Optimizarea acelui raport rămâne o sarcină de backend.
- Erorile de colectare și de cotații sunt păstrate și afișate. Noul aspect nu validează
  sursele lipsă, Telegram, un model AI sau posibilitatea efectivă de vânzare.
- Istoricul Speed arată în continuare `exit_unavailable`, cu PnL necunoscut pentru semnalul
  original 209593 la 5m. Prezentarea nouă nu transformă acel caz în succes.
- Testarea vizuală a acestei versiuni folosește Chromium pe Linux, inclusiv viewporturi mobile.
  Nu este o verificare pe un telefon fizic sau pe toate browserele Windows/iOS.
- Nu se adaugă execuție cu bani reali, autentificare comercială sau găzduire SaaS.

## Fișiere principale

| Fișier | Schimbare |
| --- | --- |
| `app/static/workspace.css` | Tema, tipografia, suprafețele, layouturile și stările responsive |
| `app/static/index.html` | Shell, meniul mobil, radarul, filtrele și etichetele |
| `app/static/app.js` | Meniu accesibil, focus, navigare, timeout explicat |
| `app/static/opportunities.js` | Dosar vizual, grafic, ferestre, scoruri și rezultate |
| `tests/browser_audit.py` | Regresii funcționale, mobil, tastatură, lipsuri și timeout |
| `tests/browser_regressions.py` | Acces la jurnal prin noul meniu mobil |
| `app/__init__.py`, `pyproject.toml`, `uv.lock` | Identitatea versiunii 0.17.0 |

Cele 56 de fișiere backend existente, în afara identificatorului versiunii, sunt identice
cu versiunea anterioară. Regulile de scor, politicile istorice, costurile și tranzacțiile
paper nu sunt rescrise pentru această schimbare de interfață.
