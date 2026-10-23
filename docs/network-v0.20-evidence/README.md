# Dovezi v0.20.0

JSON-urile păstrează timpi UTC; capturile finale folosesc Europe/Bucharest. Nu sunt incluse
chei, baze de date sau tranzacții reale. Rulările nu modifică praguri pentru a obține alerte.

## Teste izolate

- `initial-fault-regressions.txt`: trei defecte reproduse înainte de modificare: securitate
  blocată, discovery blocat și o cotație pornită deși nu mai exista timp disponibil.
- `security-overlap-regression.txt`: testul cu barieră arată că citirile erau secvențiale;
  după corecție, RPC și GoPlus se suprapun.
- `promotion-lookup-regression.txt`: planul SQL parcurgea rețeaua, nu contractul cerut.
- `development-counter-regression.txt`: caz suplimentar găsit în timpul dezvoltării;
  contorul consuma un slot chiar dacă bugetul de timp nu admitea cererea.
- `pytest.txt`: 594 teste trecute pe codul final; un avertisment Starlette/httpx existent.
- `fault-tests.txt` / `focused-tests.txt`: fault injection, SQLite real și anularea taskurilor.
- `browser-audit.json`: 41 scenarii Chromium, cu furnizori și date sintetice izolate.

## Date reale

- `initial-query-profile.json`: 60 citiri de promovări au consumat 22,34s înainte de index;
  citirea istoricelor a consumat 0,013s în aceeași profilare locală.
- `lookup-comparison.json`: comparație pe aceeași tranzacție read-only și aceiași candidați.
  Vechiul index pe rețea este forțat cu `INDEXED BY`; noua cale caută direct contractul.
  131.640 pool-uri, 12,68s versus 0,000394s, rezultate/hashuri identice. Cache-ul, discul
  și încărcarea influențează timpii; nu extrapolăm acest raport la viteza întregii aplicații.
- `live-before-index.json`: prima rulare cu bugetele noi, înaintea corecției indexului.
  Prima stare vine din rularea v0.19 anterioară și nu este un ciclu nou. Inițial aplicația
  nu rula în mediul cloud; acest lucru nu descrie starea PC-ului utilizatorului.
  HTTP 503 inițial pentru raport înseamnă pregătirea explicită a cache-ului, nu un HTTP 500.
- `live-after-index.json`: trei cicluri finale, 60 observații fiecare, 56 candidați noi;
  22,72s / 55,41s / 22,43s. Un ciclu are erori de surse și amânare explicită a cotațiilor.
  Cererile de verificare au rămas accesibile. Nu este o garanție de performanță permanentă.
- `live-collection.json`: verificatorul strict a trecut în 96s; două capturi distincte
  pentru alerte, șase pentru control, în propriul interval și în ferestrele originale.
- `alert-selected-before-outcome.json`: alegerea alertei 7794 înainte de rezultat.
  Dosarul final din prima rulare păstrează evaluarea estimativă de 5 minute, cu pierdere
  aproximativ 5,56 USD, nu fill real sau dovadă de profit. Exemplul negativ nu este șters.
- `first-candidate-before-outcome.json`: primul candidat eligibil înregistrat după pornirea
  monitorului, indiferent de verdict sau de rezultat.
- `live-ui.json` și PNG-uri: dashboardul final real, 50 rânduri, dosarul candidatului
  123058 cu rezultatul ulterior, fără erori JS/HTTP 5xx în verificarea UI finală și fără
  depășirea lățimii la 320/390/768/1536px. Nu sunt dispozitive mobile fizice.

## Istoric și reguli

- `preservation-before.json` / `preservation-after.json`: politici și declarații 1–30
  identice, configurație neschimbată, vechiul semnal și rezultat Speed neschimbate,
  solduri manuale 100/500 USD și zero ordine. Numărul rândurilor istorice nu a scăzut;
  rezultatele pending se pot finaliza în mod normal pe observații ulterioare.
- `financial-sources.json`: nouă fișiere de costuri, scoruri, cotații și rezultate sunt
  identice cu v0.19, inclusiv `opportunity_routes.py` și `opportunity_outcomes.py`.
- `source-sha256.json`: sursele finale și hashul motorului corespund politicii 31.
  Indexul din `discovery.py` este o optimizare cu rezultate echivalente; nu schimbă politica
  semnalelor sau declarația prospectivă din 23 octombrie, 21:18:33 Europe/Bucharest.

Faulturile API sunt testate prin furnizori izolați, nu prin defectarea serviciilor publice.
Serviciile reale verifică funcționarea normală și erorile întâlnite natural. Nu sunt validate
din nou AI plătit, livrarea Telegram sau profitabilitatea selecției în această etapă.
