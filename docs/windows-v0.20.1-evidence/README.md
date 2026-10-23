# Dovezi v0.20.1

- `windows-before.txt`: eșecurile reale din CI Windows pentru v0.20.0,
  [run 40004797820](https://github.com/Serin15/chatgpt/actions/runs/40004797820).
- `regressions-before.txt`: trei reproduceri locale cu ceas controlat, înainte de corecție.
- `pytest.txt`: 600 teste locale trecute; API-urile sunt izolate. Timerele,
  anulările, stocarea și orchestrarea testate sunt reale.
- `browser.txt`: 41 scenarii Chromium cu furnizori izolați și bază temporară.
- Verificarea nativă Windows/Linux: [run 40010975346](https://github.com/Serin15/chatgpt/actions/runs/40010975346),
  pentru același cod și aceleași teste identificate în `source-manifest.json`.
  Rezultatul și logurile originale se consultă direct în acel run.
- `live-run.json`: opt minute de observație a workerului normal, cu furnizori publici,
  fără injecții de candidați sau schimbări ale pragurilor. Păstrează snapshotul de la
  terminarea monitorului; unele rezultate erau încă în așteptare atunci.
- `first-*-at-selection.json`: candidatul și alerta alese înainte de rezultatul ulterior.
- `live-followup.json` și `live-summary.json`: citire ulterioară a aceleiași alerte;
  rezultatul estimativ de cinci minute este `exit_unavailable`, cu `pnl_usd: null`.
  Semnalul original și payloadul alertei sunt identice cu snapshotul inițial.
- `live-collection.json`: verificator strict, care numără doar capturi de piață
  efectuate și primite în propria rulare și în ferestrele originale.
- `release-ui.json`, `release-*.png`: browser conectat la serverul normal, în
  Europe/Bucharest, fără interceptarea răspunsurilor. Confirmă nouă destinații,
  dosarul și lățimile observate; nu reprezintă teste pe telefoane fizice.
- `preservation-*.json`: hashuri ale configurației, declarațiilor și exemplului
  istoric, plus ambele registre manuale. Nu conțin chei sau baze de date.
- `financial-source-preservation.json`: surse financiare identice cu v0.20.0.
- `source-manifest.json`: hashuri ale surselor și testelor din commitul de cod
  `7e933369d0acb330114e3acca9e9c9a117f69646`, plus politica 32 și propria declarație.
  Adăugarea ulterioară a documentației nu modifică aceste surse.

Rularea live verifică funcționarea colectării, afișarea și urmărirea unui candidat,
nu calitatea predictivă sau profitabilitatea. Confirmarea în aplicație este
distinctă de Telegram și de executarea unui ordin. Nu s-au plasat ordine reale
sau ordine în registrele virtuale manuale.
