# Dovezi v0.24.0

Codul aplicației: `d0b1aa5fe216b9dfa25dce6289b6f3e90cb04941`. Commitul `072e1d7fd3c249ad11b2768bbe156e376669fde4` schimbă numai închiderea conexiunii SQLite dintr-un test înaintea înlocuirii fișierului pe Windows; cele 17 teste specifice au fost repetate. Fișierele aplicației sunt identice. `source-manifest.json` identifică versiunile și amprentele livrate.

## Date reale stocate, fără furnizori simulați

| Fișier | Ce demonstrează |
| --- | --- |
| `baseline.json` | Timpii calculatorului original pe baza reală: 20,13/33,33 s. Serviciul HTTP nu era pornit la începutul sesiunii; măsurarea a folosit direct cititorul original, numai în citire. |
| `equivalence.json` | Un ceas fix și un snapshot SQLite comun în verificatorul extern; toate câmpurile vechi/noi identice. Ceasul aplicației și semnalele de producție nu au fost modificate. Timpii celor două citiri diferă din cauza încărcării/cache-ului; nu reprezintă o optimizare a formulelor. |
| `prototype-http.json` | Prototipul a avut încă o cerere de 21 s. Copierea inutilă a raportului a fost investigată și eliminată; această încercare nu este prezentată drept rezultat final. |
| `http.json` | 10 cereri finale, mediană 0,125 s și maxim 0,295 s; HTTP 202 rapid pentru o zi fără raport. Conținutul complet al fiecărui răspuns comparabil coincide cu snapshotul de pe disc. |
| `restart.json` | Proces real oprit și repornit: raport complet servit în 0,239 s, cu dată și conținut identice. |
| `live-ui.json` | Chromium pe instanța reală, fără interceptare: panouri păstrate, patru lățimi fără overflow, zero erori JS, export real de 19 MB cu 45.387 rânduri. |
| `preservation.json`, `source-preservation.json` | Politici/declarații/configurație și registre financiare păstrate, fără ștergerea istoricului; fișierele motorului și formulelor raportului neschimbate. |

Rapoartele sunt despre cohortele descoperite și rezultatele cunoscute la momentul calculului. Aceste măsurări nu sunt tranzacții reale, nu demonstrează profitabilitate și nu compensează intervalele fără observații.

## Teste cu furnizori simulați

- `pytest.txt`: 707 teste trecute; SQLite, fișiere și procese reale pe baze temporare, fără a modifica registrele utilizatorului.
- `focused-tests.txt`: 17 teste ale cache-ului, repetate după corecția închiderii conexiunii din fixture.
- `browser.txt`: 56 scenarii Chromium trecute; răspunsuri și furnizori controlați. Acestea sunt separate de verificarea instanței reale de mai sus.

## Neverificat din cauza unui blocaj extern

`external-blocker.json` descrie refuzul proxyului pentru API-ul GitHub și sursele crypto. Lista de domenii există în draft, însă nu este aplicată mediului activ. CI nativ Windows al v0.24.0 și cotațiile live noi rămân neconfirmate în această sesiune; rezultatele din versiunile anterioare nu sunt reutilizate pentru a pretinde succesul lor. După Save/Publish în setările mediului, trebuie reluate cererile refuzate.
