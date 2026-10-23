# MemeScope v0.20.1 — bugete de timp consecvente pe Windows

Verificarea nativă a versiunii 0.20.0 a încheiat cu 592 teste trecute și două
eșuate pe Windows; verificarea Linux a trecut. Am investigat eșecurile, fără să
mărim limitele sau să eliminăm aserțiunile care le-au detectat.

## Problema și corecția

Un timer asyncio poate expira înainte ca un ceas monotonic cu rezoluție mai mică
să raporteze întreaga durată alocată. Calculul exclusiv din timpul măsurat lăsa
un rest de câteva milisecunde, care putea admite încă o cerere către o sursă blocată.

`CollectionBudget` folosește acum contextul `asyncio.timeout` pentru a distinge
expirarea propriului timer de un `TimeoutError` primit mai devreme de la furnizor:

- Un timer expirat consumă cel puțin durata alocată lui. Bugetul opțional comun,
  termenul ciclului și termenul comun al discovery nu se redeschid din cauza
  rezoluției ceasului.
- Un timeout propriu al furnizorului consumă doar timpul măsurat. Alte surse pot
  fi încercate dacă există timp; eșecul nu devine aprobare de securitate.
- Operațiile opționale concurente rezervă timpul înainte să pornească. Anularea
  eliberează rezervarea și așteaptă curățarea operației, fără taskuri detașate.
- Diagnosticul păstrează separat timpul măsurat, timpul contabilizat, rezervările,
  timeouturile colectorului și timeouturile furnizorilor.

Nu se schimbă intervalele configurate, numărul de cereri permis, pragurile financiare,
costurile, ferestrele de evaluare sau istoricul. SQLite poate depăși în continuare
intervalul nominal: limita controlează așteptările cooperative, nu întrerupe scrierile.

## Instalare și pornire

Windows: închide aplicația veche, păstrează folderul `data` și configurația locală,
apoi rulează `start-windows.cmd` din noua versiune. Reîncarcă browserul cu `Ctrl+F5`.
Folosește portul afișat de launcher.

Din directorul proiectului, pe Linux sau Windows cu uv instalat:

```bash
uv sync --frozen
uv run --frozen python -m app.desktop
```

Nu sunt necesare chei, pachete sau abonamente noi. Telegram, AI și tranzacțiile reale
nu sunt activate de această actualizare.

## Verificări reproductibile

```bash
uv run --frozen ruff check app tests
uv run --frozen pytest -q
node --check app/static/app.js
node --check app/static/advanced.js
node --check app/static/opportunities.js
BROWSER_EXECUTABLE=/usr/bin/chromium uv run --frozen --with playwright python tests/browser_audit.py
uv run --frozen python -m app.collection_verify --url http://127.0.0.1:8000 --duration 600 --output data/collection-check.json
```

Regresiile folosesc timere și anulări asyncio reale, cu ceasul de contabilizare
controlat. Înainte de corecție, cele trei cazuri pentru bugetul opțional, ciclul
complet și grupul discovery eșuau. Testele păstrează și cazul unui furnizor care
aruncă imediat `TimeoutError`, rezervarea concurentă și eliberarea după anulare.
Acestea sunt teste cu surse controlate, nu dovada unei indisponibilități reale a API-urilor.

**600 teste Python au trecut local în 154,05s**, cu un avertisment de depreciere
Starlette/httpx deja existent. **41 de scenarii Chromium au trecut**, cu furnizori
izolați. Ruff și verificarea sintaxei celor trei fișiere JavaScript au trecut.
[Dovezile de regresie și testare](windows-v0.20.1-evidence/) separă eșecurile inițiale
de rezultatele corectate. Verificarea nativă Windows/Linux și observațiile cu surse
reale se raportează separat; nu sunt deduse din testele locale. Un preț colectat sau o alertă
livrată nu demonstrează profitabilitatea selecției.

Verificarea nativă Windows/Linux este publică în
[CI run 40010975346](https://github.com/Serin15/chatgpt/actions/runs/40010975346),
pentru commitul de cod `7e933369d0acb330114e3acca9e9c9a117f69646`. Jobul Windows
include launcherul și arhivarea/restaurarea din directoare cu spații în nume.
Commitul ulterior conține doar documentație și dovezi; hashurile tuturor surselor,
testelor și configurației CI sunt identice cu commitul verificat.

## Rulare cu surse reale

Motorul normal a parcurs șapte cicluri observate, cu **420 de observații și 123 de
candidați nou înregistrați**, fără injecții de candidați sau modificarea pragurilor.
Duratele au fost între 37,59s și 56,55s. Acesta este un eșantion local scurt, nu
o garanție de latență. Verificatorul strict a trecut toate cele șase criterii în
215s: cinci capturi distincte pentru alerte și 12 pentru control, capturate și
primite în propria rulare și în ferestrele originale.

Alerta 7832 / candidatul 124123 / semnalul 303857 a fost aleasă înainte de rezultat.
Contract Solana: `3HV7xnV8uDmBne5xkRZAvUyj4dwLZss3vrEhHyMTxz8i`.
Verdictul original `INVESTIGATE` și payloadul alertei au rămas identice după observațiile
ulterioare. Alerta a primit confirmarea afișării în aplicație la **23 octombrie 2026,
22:22:37, Europe/Bucharest**. Nu a fost trimisă pe Telegram.

În experimentul estimativ independent de pool, prima observație eligibilă pentru intrare
a venit după 57s, pentru un cost virtual de 50,01 USD. La evaluarea de cinci minute,
prima observație de ieșire nu a trecut filtrele; starea este **`exit_unavailable`,
cu PnL necunoscut**, nu zero și nu profit. Acesta nu este un ordin executat sau dovada
că tokenul nu poate fi vândut pe nicio piață. Un preț public disponibil nu confirmă
singur o ieșire economic posibilă. Rezultatul și toate observațiile sunt păstrate.

Browserul a afișat dosarul și această stare ulterioară. Navigarea prin toate cele nouă
secțiuni a funcționat fără erori JavaScript sau HTTP 5xx în această rulare. Dosarul nu
a depășit lățimea viewportului la 320/390/768/1536px. Aceste verificări folosesc Chromium,
nu un telefon fizic.

Hashurile confirmă păstrarea configurației, politicilor și declarațiilor 1–31, a
exemplului istoric Speed și a ambelor registre manuale: solduri 100/500 USD, zero
ordine. Politica 32 corespunde surselor instalate și are testarea viitoare declarată
din **24 octombrie 2026, 22:20:37, Europe/Bucharest**. Declarațiile anterioare nu au
fost mutate. Sursele modelelor de cost și evaluare financiară sunt identice cu v0.20.0.

## Ce urmează

Măsurarea prospectivă a acoperirii și a rezultatelor după costuri rămâne necesară.
Coada istorică, ferestrele ratate și ieșirile necunoscute rămân vizibile; această
corecție nu recuperează observații care nu au fost colectate la timp.
