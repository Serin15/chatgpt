# MemeScope v0.11.0 — de la știre la candidat

Etapa conectează documentele din știri la motorul Solana existent. Tranzacțiile reale
rămân dezactivate. Mențiunea unui contract nu confirmă emitentul, susținerea unei
persoane, o listare ori un randament viitor.

## Ce s-a reparat și implementat

Două lipsuri au fost reproduse înaintea modificării: un contract dintr-un document
nu devenea candidat dacă nu apărea în feedurile de pool-uri; un link explicit
`pump.fun/coin/<mint>` nu era extras. Testele de regresie verifică acum ambele cazuri.
Linkurile DEX către pool-uri nu sunt tratate ca adrese de token, iar domeniile
asemănătoare și referințele devnet sunt refuzate.

`StoryDiscovery` păstrează în SQLite adresele cu mențiune exactă, chain Solana
neambiguu și document curent. Caută cel mult trei piețe pe ciclu, concurent, cu
timeout de opt secunde. Contractul, adresa pool-ului, prețul, lichiditatea și
prospețimea cotației sunt validate înaintea trimiterii către `Discovery.save` și
motorul normal de risc/scoruri/alerte/outcomes. Nu există o scurtătură peste filtre.

Prima dovadă și prima captură nu sunt rescrise. Adresele fără piață rămân în
`story_pool_lookups`, cu rezultat necunoscut și reîncercări după 5, 10, 20, 40, apoi
60 de minute. Întreruperile păstrează o rezervare de 60s; nu există retry nelimitat
în aceeași cerere. O adresă fără pool validat nu este încă un candidat evaluabil
în universul pool-urilor; numitorul separat al adreselor documentare este vizibil.
Lipsa pieței nu este o dovadă de imposibilitate a vânzării ori un rezultat zero.

Eliminarea unei mențiuni în timpul cotației împiedică folosirea dovezii vechi.
Dovezile expirate sunt păstrate; o știre nouă poate redeschide căutarea, păstrând
prima dovadă. Recitirea aceluiași conținut nu resetează backoff-ul. Un candidat deja
cunoscut nu cere o cotație suplimentară pentru această legătură; o știre nouă îl
reprogramează pentru cercetare în bugetul existent, fără a-i rescrie primul semnal.

Catalogul are acum și Decrypt/Cointelegraph, ca redacții fără relație de emitent
aprobată. Feedul Solana și o interogare dedicată memecoinurilor completează știrile
existente. Feedurile directe acceptă numai articole pe domeniul lor exact. Citirea
documentelor rămâne HTTPS, fără redirecturi, maximum 2 MB și trei documente per
refresh. Documentele necitite preced recitirile orare; știrile cu termeni memecoin
au prioritate în acest grup, fără ca titlul să demonstreze o asociere. Timeout-ul
unui feed este explicit și nu împiedică salvarea știrilor celorlalte surse.

Panoul „Știri, contracte și dovezi” afișează numărul adreselor, pool-urile găsite,
candidații existenți, erorile, expirările și așteptările. Știrile cu adrese sunt
afișate înaintea celor fără legături; apoi sunt prioritizate titlurile despre
memecoinuri, inclusiv cele al căror document rămâne necitit, cu eticheta explicită
de selecție după titlu. Starea acestei componente apare și în
indicatorul general de sănătate. API-ul narativ include ultimele 20 de căutări,
cu proveniență și candidat dacă există; GET-urile nu modifică această coadă.

Verificarea în browser pe date reale a mai reprodus o eroare: feedurile defecte
măreau contorul de probleme, dar lipseau din detaliile de sănătate. Acum fiecare
feed apare ca `news_<sursă>`, cu eroare și moment, fără dublarea contorului;
fereastra de prospețime rămâne de 11 minute pentru știri. Regresia este inclusă
în cele 15 scenarii Chromium.

## Instalare și pornire

Pe Windows: închide aplicația veche, fă backup întregului folder `data`, extrage
arhiva nouă într-un folder nou, copiază `data` acolo și rulează `start-windows.cmd`.
Din PowerShell, în folderul care conține `pyproject.toml`:

```powershell
uv sync --frozen
uv run --frozen python -m app.desktop
```

În cloud/Linux, din `/workspace/chatgpt`:

```bash
UV_CACHE_DIR=/workspace/.cache/uv uv sync --frozen
.venv/bin/python -m app.desktop --no-browser
```

Nu sunt necesare chei API noi. Se folosesc feeduri publice și cotațiile deja
integrate. Accesul public, limitele și dreptul de redistribuire comercială nu sunt
garantate. AI și Telegram rămân opționale, fără apeluri plătite ori mesaje trimise
de această etapă. Costul incremental al codului este zero abonamente noi; nu este
o estimare a costului găzduirii sau al licențelor pentru vânzare publică.

## Verificare reproductibilă

```bash
uv run --frozen ruff check app tests
uv run --frozen pytest -q
node --check app/static/app.js
node --check app/static/opportunities.js
uv run --with playwright python tests/browser_audit.py
uv run --frozen python -m app.story_verify --url http://127.0.0.1:8000 --duration 900 --output /tmp/story-live.json
```

Ultima comandă citește doar API-ul unei instanțe normale deja pornite, fără a
injecta știri, tokenuri, cote, ordine sau confirmări de livrare. Pe Windows
folosește `--output story-live.json`. Pentru browser este necesar Chromium;
`BROWSER_EXECUTABLE` permite alegerea căii. `story_verify` nu verifică randarea
browserului: aceasta se verifică separat. O alertă poate primi confirmarea de
afișare prin dashboardul normal; comanda nu o falsifică.

Verificatorul cere pe același candidat: document cu adresă, descoperire din
document, observații de piață/securitate, semnal cu dovada originală, alertă,
confirmarea afișării și rezultat ulterior evaluat. Codul de ieșire este **1** dacă
lipsește un criteriu, inclusiv când nu a apărut o știre eligibilă. Urmărește cele
mai recente 20 de căutări, apoi candidatul ales; nu demonstrează acoperire globală.
Rezultatele pool și Jupiter rămân modele separate, cu costurile și lipsurile lor.

## Dovezi și limite

Rezultatele efective și blocajele ultimei rulări sunt păstrate în
[`story-evidence/`](story-evidence/). Testele cu fixture-uri sunt distincte de
feedurile, baza existentă și browserul verificate pe date reale. Raportul beta
anterior rămâne în [BETA-SOLANA.md](BETA-SOLANA.md); nu este o verificare live a
noii legături document–descoperire.

O știre recentă reală despre un memecoin, cu contract exact și alertă/outcome pe
același candidat, trebuie observată fără injectare pentru a demonstra capătul
narativ al fluxului. Adaptoarele implementate și testele simulate nu satisfac
singure acest criteriu. Numele asemănătoare, titlurile RSS și simpla existență a
unui cont social rămân ipoteze. Nu sunt introduse măsurători sociale globale sau
o detecție automată completă a promovării plătite/sindicalizării editoriale.

Politicile și semnalele istorice sunt păstrate. Fingerprintul motorului include
acum și colectarea știrilor/documentelor, astfel încât regulile noi nu sunt
prezentate drept același experiment cu cele vechi. Cutoff-ul prospectiv existent
nu este mutat și datele fără declarație validă nu devin retroactiv holdout.

Prioritatea următoare rămâne obținerea unor surse accesibile și suficient de
specifice pentru tokenuri, urmată de colectare prospectivă susținută. Nu este
demonstrată predicția unui 10x/100x sau profitabilitatea strategiei.
