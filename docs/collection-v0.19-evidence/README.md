# Dovezi v0.19.0

Datele și orele din JSON sunt UTC. Acest director nu conține chei sau baze de date.

## Teste izolate

- `original-regressions.txt`: cele nouă cazuri inițiale eșuate înaintea corecțiilor,
  incluzând lipsa noilor diagnostice. Furnizori izolați, SQLite real.
- `original-checker-regressions.txt`: verificatorul accepta istoric și capturi dublate.
- `repeated-quote-regression.txt` și `custom-cadence-regression.txt`: cazuri limită
  suplimentare reproduse în timpul dezvoltării; nu sunt prezentate ca defecte ale v0.18.
- `pytest.txt`: 579 teste trecute pe sursele finale, un avertisment Starlette/httpx existent.
- `focused-tests.txt`: cele 19 cazuri noi de programare/verificare.
- `browser-audit.json`: 40 scenarii Chromium cu furnizori izolați și SQLite temporar.
  Numerele sintetice folosite pentru layout nu sunt măsurători ale pieței.

## Servicii și observații reale

- `live-run-policy29.json`: aproximativ opt minute de funcționare normală; API-uri reale,
  browser real, fără introducerea unui candidat, praguri modificate sau ordine manuale.
  Politica 29 precede corecția pentru intervale personalizate peste 900s. Prima stare
  încărcată din baza de date provine din rularea precedentă și nu este numărată ca nou ciclu.
- `live-summary-policy29.json`: șase cicluri noi, 111 candidați, 360 observații;
  timpul de 62,55–114,67s arată că întârzierile API/capacitatea rămân o limitare.
- `first-alert-before-outcome.json`: alerta 6798 a fost aleasă înainte de rezultat.
  Ultimul dosar din rularea completă păstrează rezultatul `exit_unavailable`, cu PnL null.
  Nu este o demonstrație de profit, de imposibilitate a vânzării pe chain sau de fill real.
- `first-candidate-after-monitor-start.json`: primul candidat eligibil înregistrat după
  pornirea monitorului; păstrat indiferent de verdict. Nu este selectat după randament.
- `live-collection-policy29.json`: verificatorul cu deduplicare după timpul cotației,
  aplicat înaintea repornirii finale; 221s, trei capturi pentru alerte și zece pentru control.
- `live-collection-policy30.json`: verificare după repornirea cu sursele finale, la portul
  8001; 147s, patru capturi pentru alerte și douăsprezece pentru control. Criteriile sunt
  observații capturate/primite în timpul rulării și în ferestrele originale, nu filluri reușite.
- `live-ui-policy30.json`: dashboard real, primul token nou îmbogățit sub politica finală,
  declarația holdout, dosarul istoric păstrat, zero JS/HTTP 5xx și dimensiuni mobile.
- `desktop.png`, `research.png`, `mobile.png`: capturi ale interfeței reale finale.

## Păstrarea datelor

- `preservation-before.json` / `preservation-after.json`: politicile și declarațiile
  originale 1–28 au aceleași hashuri; configurația, semnalul și rezultatul negativ Speed
  păstrat, precum și ambele conturi manuale nu s-au modificat. Numărul rândurilor istorice
  nu a scăzut. Politicile 29 și 30 sunt adăugate, nu înlocuiesc declarațiile anterioare.
  Rezultatele care erau pending se pot finaliza normal pe observații ulterioare.
- `financial-source-preservation.json`: nouă fișiere de scoruri, costuri, cotații,
  rezultate și evaluare sunt identice cu v0.18.
- `source-sha256.json`: hashurile surselor finale; hashul motorului coincide cu politica 30.

Testele locale nu validează un telefon fizic, profitabilitatea, livrarea Telegram sau
funcționarea unui abonament AI. Corecțiile pentru poziții virtuale și reactivarea după
documente sunt verificate cu fixture-uri; conturile utilizatorului nu primesc ordine de test.
