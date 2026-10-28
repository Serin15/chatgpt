# MemeScope v0.26.0 — backup offline verificat și accesul la surse

## Ce rezolvă această versiune

Backupul online existent păstrează o copie SQLite intermediară și o arhivă ZIP.
Pentru istoricul mare, estimarea conservatoare depășea spațiul disponibil. Noul
mod offline comprimă direct fișierele bazelor blocate și restaurează câte o bază
într-un director de verificare. Nu șterge istoricul, nu compactează bazele și nu
reduce rezerva de 512 MiB. Backupul online nu este modificat.

`python -m app.offline_backup` este o comandă administrativă locală. Aplicația
trebuie închisă înainte de execuție. Nu există un endpoint HTTP care să accepte
căi arbitrare de scriere.

## Cum este verificat

1. Sunt necesare ambele baze existente; o cale greșită nu creează un istoric gol.
2. Este obținut lockul aplicației. O instanță pornită împiedică operația offline.
3. Paginile WAL comise sunt integrate prin checkpoint SQLite. Tranzacțiile
   `IMMEDIATE` blochează alți scriitori în timpul comprimării; un checkpoint
   ocupat sau o modificare concurentă opresc operația.
4. Ieșirea ZIP are un buget maxim, calculat din spațiul liber, rezerva de 512 MiB
   și spațiul necesar verificării dacă se folosește același volum. Limita se aplică
   fiecărei scrieri, iar spațiul liber este reverificat periodic.
5. Fiecare fișier este hashuit SHA-256 în timp ce este comprimat. Dimensiunea,
   identitatea și data modificării sursei sunt controlate.
6. Fiecare bază este restaurată efectiv în directorul de verificare. Sunt verificate
   CRC-ul ZIP, dimensiunea, SHA-256 față de sursa blocată și `PRAGMA quick_check(1)`.
   Se păstrează cel mult o bază restaurată simultan.
7. Arhiva `.zip` este publicată numai după verificarea ambelor baze. Un eșec elimină
   ieșirea provizorie; backupurile precedente și bazele originale rămân păstrate.

ZIP-ul conține exact `research.sqlite3` și `news_paper/research.sqlite3`, compatibile
cu restaurarea existentă din `app.storage`. Metadatele cu hashuri sunt în comentariul
ZIP. Fișierele `.env`, cheile API și cache-ul derivat separat nu sunt incluse.

Planul de spațiu nu garantează că datele se vor comprima suficient. Câmpul
`compression_fit_is_unverified` descrie această incertitudine la preflight;
`restoration_verified: true` apare numai după comprimarea și restaurarea reușite.

## Windows

Închide MemeScope și deschide PowerShell în folderul proiectului. Alege o cale
absolută pe un disc real. Exemplul de mai jos nu presupune că ai un disc D:

```powershell
uv sync --frozen
uv run --frozen python -m app.offline_backup --destination 'D:\MemeScope Backups' --plan
uv run --frozen python -m app.offline_backup --destination 'D:\MemeScope Backups'
```

Opțional, `--work-dir 'E:\MemeScope Work'` folosește alt volum pentru verificare.
Acesta trebuie să poată păstra cea mai mare bază restaurată, plus rezerva. Cu
destinația și verificarea pe același volum, sunt bugetate simultan arhiva și acea bază.

Sunt respectate și variabilele administrative existente `PULSE_BACKUP_DIR` și
`PULSE_BACKUP_WORK_DIR`; argumentele explicite au prioritate. `.env` nu este
încărcat automat. `--max-archive-mib` poate restrânge bugetul; nu poate elimina
rezerva sau mări capacitatea fizică disponibilă.

La final sunt afișate calea arhivei, dimensiunea, hashurile și rezultatul verificării.
Pornește apoi aplicația cu `start-windows.cmd`.
Pentru un director de date personalizat, păstrează variabila `DATA_DIR` a instalării
sau precizează explicit `--data-dir` cu acea cale.

## Linux / proba din cloud

```bash
uv run --frozen python -m app.offline_backup --work-dir /tmp/memescope-backup-verify --plan
# După închiderea aplicației:
uv run --frozen python -m app.offline_backup --work-dir /tmp/memescope-backup-verify
```

În această probă, `/tmp` este folosit numai pentru copiile temporare restaurate.
Arhiva este păstrată în `data/backups`. O copie în același mediu nu este un backup
independent împotriva pierderii acelui mediu; trebuie copiată și pe un disc/serviciu
separat. Comanda raportează explicit `independent_offsite_backup_verified: false`.

## Teste și dovezi

**Probă pe istoricul real:** 11.035.508.736 octeți de baze SQLite au produs o
arhivă de 1.364.363.273 octeți, în **417,63 s**. Ambele baze au fost restaurate
și verificate SHA-256/SQLite înainte de publicarea ZIP-ului. Bugetul de ieșire
a fost 1.782.018.048 octeți, cu rezerva de 512 MiB păstrată; directorul temporar
a fost curățat. Nu a fost folosită o bază sintetică pentru acest rezultat.

Arhiva reală este păstrată local în `data/backups`; nu este introdusă în Git sau
în ZIP-ul public al codului. Backupurile precedente sunt păstrate. Cele opt controale
de păstrare a configurației, politicilor, declarațiilor, înregistrărilor de referință
și conturilor manuale au trecut. Cele 23 de module de cercetare/financiare verificate
sunt identice cu versiunea v0.25.0.

Metoda online continuă să ceară conservator aproximativ 22,60 GB pentru acest istoric.
Noua metodă nu declară că această rezervă încape pe volumul mic: folosește un mod
offline distinct, comprimare efectiv limitată și verificare pe volumul temporar separat.
După backup rămâne sub 1 GB liber pe volumul aplicației; este necesară în continuare
mutarea unei copii pe stocare persistentă separată și rezolvarea capacității pe termen lung.

- **720 teste pytest trecute**, 305,09 s; un avertisment existent Starlette/httpx.
- **24 teste dedicate backupului trecute**, 7,77 s: fișiere SQLite/ZIP și restaurări
  reale în directoare temporare. Limitele de disc/identitățile volumelor sunt simulate
  acolo unde este indicat în test.
- Testul browserului pentru regresii, export și backup online a trecut cu furnizori
  simulați și portofolii temporare.
- Proba cu baza mare, verificarea păstrării datelor și accesul API sunt consemnate în
  [backup-v0.26-evidence](backup-v0.26-evidence/README.md).

```bash
uv run --frozen pytest -q
uv run --frozen pytest -q tests/test_offline_backup.py tests/test_backup_api.py tests/test_backup_destination.py
uv run --frozen ruff check app tests
```

Execuția nativă Windows a acestei versiuni nu este verificată în cloud; testele
locale au rulat pe Linux. Nu au fost activate AI plătit, Telegram sau tranzacții reale.

## Sursele live: blocajul rămas

În verificarea acestei versiuni, DexScreener, GeckoTerminal, CoinGecko și GitHub API
au fost refuzate de proxy cu 403 la conectare, înainte de un răspuns al serviciilor.
Politica activă are numai presetul pentru pachete și zero domenii personalizate.
Draftul salvat conține deja domeniile necesare; salvarea draftului nu le aplică.

În setările mediului cloud trebuie revizuite și salvate regulile, apoi publicat
mediul prin **Save → Publish**. După activare, se reverifică accesul efectiv și
colectarea normală. O conexiune refuzată nu este dovada unei chei API greșite.

Cu aplicația pornită și accesul restabilit, verificatorul existent se poate executa
pe portul afișat de instalarea respectivă, de exemplu:

```powershell
uv run --frozen python -m app.collection_verify --url http://127.0.0.1:8000 --duration 180 --output collection-live.json
```

Această comandă citește colectarea normală, fără injectare de candidați sau schimbări
de praguri. Dacă nu există suficiente observații proaspete, rezultatul rămâne incomplet.
Răspunsurile istorice și lipsurile nu sunt transformate în verificări live reușite.
