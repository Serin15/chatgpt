# Verificare UI v0.17.0

- `pytest-final.log`: **538 teste Python trecute**, un avertisment existent Starlette/httpx.
- `browser-audit-final.json`: **38 scenarii Chromium trecute**, cu surse izolate. Include
  focusul meniului mobil, toate destinațiile, stări de eroare, filtre, cereri întârziate,
  controlul graficului din tastatură, observații lipsă și explicația timeoutului.
- `browser-regressions.json`, `browser-opportunities.log`, `browser-smoke.log`: scenariile
  anterioare de știri, dosar, paper trading, jurnal, export și backup, cu date de test.
- `live-ui.json` și PNG-urile: aplicația normală, versiunea **0.17.0**, verificată pe
  **22 octombrie 2026**, cu datele existente. Fără răspunsuri înlocuite și fără prețuri injectate.
  50 de candidați afișați, 30 de știri, zero erori JavaScript și zero HTTP 5xx în sesiune.
  Fără depășire orizontală a paginii la 320, 390, 768 și 1536 px.
- Raportul istoric **nu a răspuns în limita de 20 secunde a browserului**. Cardurile nu au
  primit valori inventate; indisponibilitatea apare explicit. `pass: true` din verificarea UI
  privește funcționarea și lizibilitatea interfeței, nu disponibilitatea tuturor API-urilor.
- Semnalul original Speed 209593 păstrează `exit_unavailable` la 5m și PnL necunoscut.
  Cele două conturi manuale au rămas $500/$100 virtuali și zero ordine în această sesiune.
- `backend-preservation.json`: cele 56 de fișiere backend, exceptând identificatorul versiunii,
  sunt identice cu versiunea precedentă. Politica 25 din 21 octombrie a rămas ultima politică
  după repornire. Execuția reală rămâne dezactivată.
- `ui-source-sha256.json`: identifică exact fișierele de interfață verificate.

Capturi: `radar-desktop.png`, `radar-mobile.png`, `research-desktop.png`,
`research-mobile.png`, `evidence-desktop.png`, `navigation-mobile.png`, `news-desktop.png`.
Prețurile și orele sunt observații din acea sesiune, nu cotații actuale garantate.
