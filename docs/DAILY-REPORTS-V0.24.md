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

Fișierul `data/daily-reports.sqlite3` conține cache reconstruibil și diagnostice operaționale. Nu este o bază de ordine, un backup sau o înlocuire a observațiilor originale. Nu este inclus între bazele financiare ale arhivei; rapoartele se pot recalcula după restaurare, iar istoricul diagnosticelor din cache nu face parte din backupul financiar. Identitatea sursei și versiunea implementării împiedică reutilizarea unui raport de la alt fișier de bază restaurat prin înlocuire sau de la altă versiune a calculatorului. Persistența între reporniri privește aceeași sursă și versiune a calculatorului; invalidarea lor impune reconstruirea cache-ului.

Cache-ul păstrează cel mult opt zile și acceptă până la 32 MiB pentru un raport. Un rezultat peste limită este semnalat ca indisponibil; nu este trunchiat și nu înlocuiește ultimul raport complet. Fișierul SQLite poate păstra pagini libere după eliminarea cache-urilor vechi; acestea sunt reutilizabile. Nicio limită a cache-ului nu șterge candidați, observații, ordine sau rezultate din istoricul principal.

În lipsa accesului la fișierul de cache, calculele pot continua în memorie, iar interfața și starea componentelor explică problema de persistență. Un cache corupt poate fi eliminat doar ca fișier derivat, cu aplicația oprită; bazele `research.sqlite3` și `news_paper/research.sqlite3` trebuie păstrate.

Proba pe baza reală a identificat un raport de peste 12 MB; limita inițială de 8 MiB a prototipului a fost corectată înaintea livrării. Nu au fost eliminate rândurile individuale din export pentru a micșora artificial raportul.

Răspunsul complet JSON se pregătește o singură dată pentru fiecare generație. Cererile reutilizează aceiași octeți imuabili și actualizează numai metadatele mici de prospețime. Programarea periodică nu copiază raportul; decodarea și pregătirea volumului mare sunt separate de bucla asincronă principală. Proba sub încărcare a prins și corectat o cerere de 21 s în prototipul care încă făcea copii complete prea des.

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

## Rezultate verificate

- **707 teste trecute local**, 396,72 s; un avertisment existent Starlette/httpx. După închiderea explicită a unei conexiuni din fixture înaintea înlocuirii fișierului, au fost repetate și trecute cele **17 teste specifice**. Codul aplicației este identic cu cel al suitei complete.
- **56 scenarii Chromium trecute** cu furnizori simulați; Ruff, cele trei verificări JavaScript și `git diff --check` trecute.
- Calculul original, nemodificat, pe baza reală: **20,13 s** pentru 27 octombrie și **33,33 s** pentru 26 octombrie, în condițiile înregistrate în dovadă. Acestea sunt timpi de calcul; noul calcul continuă în fundal.
- Pe codul final, **10 cereri HTTP** pentru rapoarte complete de aproximativ 11,5–16,9 MB: mediană **0,125 s**, maxim **0,295 s**. O zi încă necalculată a răspuns cu HTTP 202 în **0,026 s**. Timpii nu reprezintă o garanție pentru orice volum/hardware.
- Comparația integrală, cu același ceas și același snapshot SQLite: toate câmpurile raportului vechi și nou identice. Răspunsurile HTTP finale au fost comparate integral și cu versiunile persistate, inclusiv rândurile individuale.
- După oprirea și repornirea procesului real: HTTP 200 în **0,239 s**, aceeași dată `generated_at`, aceeași amprentă a conținutului. Ora repornirii nu a devenit data raportului.
- Chromium pe aplicația reală, fără interceptarea datelor: zero erori JavaScript, panoul de lectură păstrat, fără depășire orizontală la 320/390/768/1440 px. Exportul descărcat efectiv a avut **19.278.762 bytes și 45.387 rânduri individuale**.
- Politicile 1–32, declarațiile, configurația, înregistrările istorice fixe și conturile de 100/500 USD au rămas păstrate. Nicio tranzacție manuală nu a fost creată în baza reală. Formulele și fișierele raportului financiar original sunt neschimbate.

Dovezi: [daily-reports-v0.24-evidence](daily-reports-v0.24-evidence/README.md).

### Blocaj extern de verificare

În sesiunea acestei livrări, mediul cloud activ permite doar domeniile presetului de pachete. Proxyul refuză conexiunile către `api.github.com` și sursele crypto cu **403 Forbidden / ProxyError**. Configurația draft conține deja domeniile necesare, dar lista nu este activă în mediul care rulează. Este necesară verificarea și salvarea draftului în setările mediului, apoi **Publish**, urmată de retestarea accesului. Nicio cheie nouă nu a fost cerută și politica nu a fost ocolită.

Codul a fost trimis în repository, dar rezultatul CI și verificarea nativă Windows **v0.24.0 rămân neconfirmate aici** până când accesul este restabilit. Succesul Windows al v0.23.0 nu este folosit ca dovadă pentru noua versiune. Verificările pe baza reală descrise mai sus folosesc istoricul stocat; nu sunt declarate drept o verificare a unor cotații crypto live noi în această sesiune.

## Limite rămase

- Calculele istorice rămân costisitoare; această schimbare scoate calculul din cererea HTTP și îl partajează, fără să modifice formulele sau rezultatele.
- Raportul global și raportul Jupiter folosesc în continuare propriile procese/cache-uri; această persistență nouă privește bilanțul zilnic.
- Un proces care nu termină în 180 s este oprit; problema apare ca eroare și poate fi reîncercată. Un raport păstrat nu devine date live prin simpla afișare.
- Persistența diagnosticelor depinde de posibilitatea scrierii cache-ului. În cazul unei probleme de disc, copia din memorie poate continua, cu avertisment, dar nu poate garanta păstrarea noului diagnostic după oprire.
- Monitorizarea se oprește când PC-ul sau mediul cloud este oprit. Nu reconstruim observații lipsă și nu resetăm pilotul pentru a ascunde intervalele neobservate. Funcționarea 24/7 necesită un proces/găzduire care rămâne pornit.
- Backupul complet al bazei mari necesită în continuare spațiu suplimentar. AI/Telegram rămân opționale și necesită configurare separată. Profitabilitatea nu este demonstrată.
