# MemeScope v0.24.0 — bilanțul zilnic în fundal

Calculul bilanțului zilnic nu mai ocupă cererea HTTP în timp ce citește istoricul. Aplicația păstrează ultima versiune completă și o actualizează într-un proces separat, cu acces doar pentru citirea bazelor de cercetare. Data descoperirii, regulile financiare, selecțiile inițiale, rezultatele și protocolul pilotului nu sunt modificate.

## Comportament

- O zi fără raport răspunde imediat cu HTTP 202 și `report_state=preparing`. Nu produce totaluri fictive sau PnL zero. Interfața explică starea și verifică automat finalizarea.
- O zi calculată răspunde cu HTTP 200 și raportul complet păstrat. `generated_at` și `report_cache.snapshot_at` sunt data reală a datelor; nu devin ora unei noi cereri sau reporniri.
- Un singur proces calculează bilanțuri, cu cel mult opt zile în memorie/coadă. Cererile duplicate nu pornesc alte calcule. Dacă toate locurile sunt ocupate, o zi nouă primește explicit starea `busy` și poate fi reîncercată.
- Ziua UTC curentă se pregătește automat; zilele trecute se actualizează la cerere. Intervalul normal de actualizare este 45 s după calcul. Erorile folosesc o pauză de 15 s înaintea reîncercării. O zi trecută poate avea rezultate ulterioare; raportul nu pretinde reconstruirea unei stări istorice necunoscute.
- Un calcul eșuat păstrează ultima versiune completă, cu avertisment și tipul erorii. Mesajele arbitrare ale excepțiilor, URL-urile autentificate și cheile nu sunt salvate în diagnostic. Ultima eroare și până la cinci evenimente rămân disponibile după repornire și după recuperare.
- O actualizare întreruptă se reia; un proces anulat este terminat și recuperat. Starea `running` de dinaintea unei opriri nu rămâne blocată permanent.
- Formularul unei oportunități și lista candidaților rămân independente de acest calcul. Bilanțul păstrează panourile deschise la actualizare, iar o generație identică nu reconstruiește conținutul mare. Schimbarea zilei invalidează exportul până când este disponibil raportul corect.

## Stocare și limite

Fișierul `data/daily-reports.sqlite3` conține numai cache și diagnostice reconstruibile. Nu este o bază de ordine, un backup sau o înlocuire a observațiilor originale. Nu este inclus între bazele financiare ale arhivei; după o restaurare poate fi reconstruit. Identitatea sursei și versiunea implementării împiedică reutilizarea unui raport de la alt fișier de bază restaurat prin înlocuire sau de la altă versiune a calculatorului.

Cache-ul păstrează cel mult opt zile și acceptă până la 32 MiB pentru un raport. Un rezultat peste limită este semnalat ca indisponibil; nu este trunchiat și nu înlocuiește ultimul raport complet. Fișierul SQLite poate păstra pagini libere după eliminarea cache-urilor vechi; acestea sunt reutilizabile. Nicio limită a cache-ului nu șterge candidați, observații, ordine sau rezultate din istoricul principal.

În lipsa accesului la fișierul de cache, calculele pot continua în memorie, iar interfața și starea componentelor explică problema de persistență. Un cache corupt poate fi eliminat doar ca fișier derivat, cu aplicația oprită; bazele `research.sqlite3` și `news_paper/research.sqlite3` trebuie păstrate.

Proba pe baza reală a identificat un raport de peste 12 MB; limita inițială de 8 MiB a prototipului a fost corectată înaintea livrării. Nu au fost eliminate rândurile individuale din export pentru a micșora artificial raportul.

## Pornire și verificare

Închide versiunea veche, păstrează `data` și configurația, extrage complet actualizarea și pornește `start-windows.cmd`. Din terminal, în proiect:

```bash
uv sync --frozen
uv run --frozen python -m app.desktop
```

Nu sunt necesare servicii noi, chei API sau abonamente pentru cache și calcule. Procesul de raportare nu construiește servicii externe, nu accesează AI, nu trimite mesaje și nu execută tranzacții.

```bash
uv run --frozen ruff check app tests
uv run --frozen pytest -q
node --check app/static/app.js
node --check app/static/advanced.js
node --check app/static/opportunities.js
uv run --with playwright python tests/browser_audit.py
```

Testele folosesc baze SQLite și procese reale pe date de test, cu furnizori simulați. Acoperă cereri HTTP în timpul unui calcul blocat, deduplicare, coadă limitată, restaurarea cache-ului, refuzul unui cache de la altă bază, erori persistente, date vechi, ceas viitor, cache corupt, anulare și rezultate prea mari/invalide. Verificările browserului separă pregătirea în fundal, raportul vechi, erorile, exportul pentru ziua corectă și panourile păstrate.

## Limite rămase

- Calculele istorice rămân costisitoare; această schimbare scoate calculul din cererea HTTP și îl partajează, fără să modifice formulele sau rezultatele.
- Raportul global și raportul Jupiter folosesc în continuare propriile procese/cache-uri; această persistență nouă privește bilanțul zilnic.
- Un proces care nu termină în 180 s este oprit; problema apare ca eroare și poate fi reîncercată. Un raport păstrat nu devine date live prin simpla afișare.
- Monitorizarea se oprește când PC-ul sau mediul cloud este oprit. Nu reconstruim observații lipsă și nu resetăm pilotul pentru a ascunde intervalele neobservate. Funcționarea 24/7 necesită un proces/găzduire care rămâne pornit.
- Backupul complet al bazei mari necesită în continuare spațiu suplimentar. AI/Telegram rămân opționale și necesită configurare separată. Profitabilitatea nu este demonstrată.
