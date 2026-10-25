# Dovezi pilot v0.21.0

- `activation.json`: declarația creată înaintea noilor înscrieri, cu început/sfârșit,
  politica 32 și hash. Această activare este în baza cloud, nu pe PC-ul utilizatorului.
- `pytest-final.txt`: 621 teste locale trecute, furnizori/ceasuri controlați,
  SQLite și subprocess reale. Un avertisment Starlette/httpx deja existent.
- `browser-final.txt`: 44 scenarii Chromium cu furnizori izolați, inclusiv activare,
  export, eroare cu bilanț păstrat, rezultate necunoscute și mobil.
- `live-pilot.json`: verificator read-only pe instanța normală. Toate cele șapte
  criterii au trecut în 938s. Primul candidat ales fără filtrare după rezultat
  este 163457, respins la prima evaluare, și este păstrat cu observațiile ulterioare.
- `live-summary.json`: 284 înscrieri, 280 prime evaluări, 10 alerte de oportunitate
  și o avertizare de risc la snapshot. Trei scenarii pool selectate sunt mature:
  două evaluate și unul indisponibil. Cele 19 scenarii de control mature au toate
  rezultatul net necunoscut. Diferența de acoperire împiedică o concluzie de avantaj.
- `live-ui.json`, `pilot-*.png`: instanță normală, fără interceptare de răspunsuri;
  export cu aceeași declarație, nouă destinații, 50 candidați afișați, fără erori JS
  sau HTTP 5xx și fără overflow la 320/390/768/1536px. Fus Europe/Bucharest.
- `preservation-*.json`: configurație, politici/declarații 1–32, exemplul Speed și
  conturile manuale păstrate. Nu conțin baze de date sau chei.
- `frozen-source-preservation.json`: 13 surse de colectare/scoring/cost/evaluare
  identice cu v0.20.1. Studiul nu a creat o politică financiară nouă.
- `source-manifest.json`: sursele/testele din commitul de cod
  `2f77e2b3483315b5f1c483c26256dbaddef75b5a`, declarația neschimbată și checksum verificat.

Verificarea nativă Windows/Linux și logurile originale:
[CI run 40206582614](https://github.com/Serin15/chatgpt/actions/runs/40206582614).
Adăugarea ulterioară a documentației și dovezilor nu modifică sursele testate.

PASS-ul verifică începerea fluxului, stocarea și numărarea corectă a rezultatelor
necunoscute. Nu înseamnă că pilotul de 30 de zile s-a încheiat, că un ordin a fost
executat sau că selecția este profitabilă. Nu s-au trimis mesaje Telegram și nu
s-au plasat ordine în registrele manuale ori pe blockchain.
