# MemeScope v0.13.1 — panoul de stare și navigarea

Panoul global „Starea componentelor” rămânea deschis după schimbarea secțiunii.
Lista nelimitată împingea pagina sub ecran și lăsa impresia că toate butoanele
arată aceeași pagină. Trei regresii Chromium au reprodus comportamentul înainte
de corecție; celelalte 20 de scenarii continuau să treacă.

## Corecție

- Orice navigare validă închide panoul și sincronizează `aria-expanded`.
- Buton explicit „Închide”, disponibil și când lista componentelor este lungă.
- Panou de maximum jumătate de ecran, plafonat la 420 px; lista se derulează în
  interior, iar titlul și butonul rămân vizibile.
- Reîmprospătarea stării păstrează alegerea deschis/închis. Avertismentele
  compacte și detaliile erorilor rămân disponibile.

Schimbările funcționale sunt în `app/static/app.js`, `index.html` și `style.css`.
`tests/browser_audit.py` adaugă navigarea prin toate cele nouă secțiuni, limitele
pe desktop/mobil și închiderea explicită inclusiv după refresh. Versiunea este
actualizată în `app/__init__.py`, `pyproject.toml`, `uv.lock` și README; fără
schimbări de dependențe.

## Mesajul routed_quotes

`Rejected: Verificările de securitate sunt expirate.` este un refuz al unei
simulări Jupiter: timestampul verificării nu trece regula de prospețime.
Regula respinge atât date prea vechi, cât și timestampuri viitoare. Captura de
pe PC nu conține timestampurile tokenului și nu stabilește care caz a intervenit.
Corecția interfeței nu pretinde că repară sursa acestui refuz.

`app/opportunity_routes.py`, `app/jupiter.py` și `app/paper.py` sunt identice cu
v0.13.0. Nu se relaxează filtre, nu se reiau rezultate terminale și nu se schimbă
politici, costuri sau ordine: [comparație de fișiere](health-panel-evidence/unchanged-execution.json). Avertismentul rămâne vizibil și nu împiedică
navigarea ori accesul la știri.

## Verificări

```bash
uv sync --frozen
uv run --frozen ruff check app tests
node --check app/static/app.js
uv run --frozen pytest -q tests/test_api.py
uv run --frozen --with playwright python tests/browser_audit.py
```

Local: 6 teste API trecute, 23/23 scenarii browser trecute, Ruff/Node/diff trecute.
Aceste teste folosesc furnizori izolați și baze temporare. Dovezile sunt în
[health-panel-evidence](health-panel-evidence/).

Codul corecției: `3cade889b88e4c32b959210f74b2eb46c09b61e6`.
[Rularea CI completă Windows/Linux](https://github.com/Serin15/chatgpt/actions/runs/39262191716)
verifică același cod; commiturile ulterioare de documentație nu schimbă aplicația.

Separat, verificarea browserului pe instanța normală v0.13.1, fără interceptări
sau date injectate, a trecut toate cele nouă navigări. Înălțime panou: 420 px
pe desktop și la 390×844; fără overflow pe mobil sau erori JavaScript. Starea
Jupiter era `partial`, iar avertismentul a rămas accesibil. Nu s-au executat
tranzacții reale sau ordine manuale. Hashurile istoricului anterior sunt intacte. [Captură desktop](screenshots/memescope-health-panel-desktop.png) și [mobil](screenshots/memescope-health-panel-mobile.png).

## Actualizare Windows

Pentru a vedea pagina imediat în versiunea veche, apasă din nou indicatorul de
stare din dreapta sus: acesta închide panoul.

Oprește aplicația veche și salvează `data` și `.env` dacă există. Extrage ZIP-ul
nou integral, copiază datele în noul director și pornește `start-windows.cmd`.
Folosește adresa afișată de launcher și apasă `Ctrl+F5` în browser. Verifică
versiunea `v0.13.1` din stânga jos; modificarea din cloud nu actualizează PC-ul.
