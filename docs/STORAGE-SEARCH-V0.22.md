# MemeScope v0.22.0 — backup și citirea istoricului

Backupul poate folosi un disc separat, iar căutarea/clasamentul citesc un index derivat, în loc să parseze toate payloadurile istorice. Raportul global reutilizează aceleași proiecții mici; subiecții încă neactualizați sunt citiți din datele originale. Datele și regulile financiare originale nu sunt rescrise.

## Backup pe alt disc

Variabilele sunt configurate de proprietarul instalării înainte de pornire; API-ul nu acceptă căi de scriere din cereri HTTP.

În PowerShell, în folderul proiectului:

```powershell
# Alege o cale absolută pe un disc existent, cu suficient spațiu.
$env:PULSE_BACKUP_DIR = 'D:\MemeScope Backups'
# Opțional: alt disc pentru copia temporară; implicit folosește destinația.
$env:PULSE_BACKUP_WORK_DIR = 'E:\MemeScope Working'
uv sync --frozen
uv run --frozen python -m app.desktop
```

Linux/macOS:

```bash
export PULSE_BACKUP_DIR=/cale/absoluta/disc-backup/MemeScope
# Opțional; folosește o cale reală, nu copia exemplul ca destinație.
export PULSE_BACKUP_WORK_DIR=/cale/absoluta/disc-temporar/MemeScope
uv run --frozen python -m app.desktop --no-browser
```

Fișierul `.env` nu este încărcat automat la pornirea nativă. Dacă aplicația rulează deja, închide-o înainte de repornirea cu noile variabile. Fără variabile, rămâne comportamentul `data/backups`.

În „Jurnal & rezultate → Stocare” sunt afișate destinația, folderul temporar, spațiul liber și necesarul pe volume. Dacă sunt pe același volum, copia temporară și arhiva sunt bugetate împreună. Pe volume diferite, ambele trebuie să aibă loc suficient. Copia SQLite este eliminată după includerea ei în arhivă, astfel încât folderul temporar păstrează cel mult o bază copiată simultan. ZIP-ul incomplet nu este publicat; backupurile existente rămân păstrate.

Mutarea destinației nu creează spațiu fizic. Backupul întregii baze mari din cloud rămâne blocat dacă niciun volum disponibil nu satisface estimarea conservatoare. Mesajele 507 și 503 pentru capacitate/configurare rămân explicite. Un folder temporar de sistem nu este o copie persistentă independentă a datelor.

## Căutare și rapoarte

- Tabelele `ui_catalog_*` conțin date derivate pentru afișare: nume normalizat Unicode, contract, verdict, scor, timestampuri și câteva câmpuri originale necesare raportului.
- Trigger-ele SQLite înregistrează numai subiecții modificați. Nu decodează JSON și nu apelează servicii externe în tranzacția colectorului.
- Construirea indexului citește loturi într-un snapshot WAL; publicarea folosește o tranzacție scurtă. O revizie schimbată între citire și publicare păstrează subiectul în coadă pentru reluare.
- Căutarea și clasamentul păstrează semantica originală: adrese Solana sensibile la majuscule, căutare Unicode, filtre, paginare și verificarea prospețimii la ora cererii. Un mic rest de actualizări este suprapus direct din sursele originale, fără verdict vechi sau număr parțial de rezultate.
- La prima pornire pe un istoric mare, clasamentul/căutarea pot răspunde temporar 503 până când indexarea inițială este aproape completă. Lista recentă rămâne accesibilă. Detaliile de stare arată progresul; indexul este persistent și nu se reconstruiește integral la fiecare pornire.
- Raportul financiar global citește proiecțiile pentru subiecții actualizați și datele originale pentru cei din coadă, în aceeași tranzacție. Nu așteaptă ca indexul să fie complet pentru a calcula un raport corect. Verificarea prospețimii folosește timestampurile originale și ora calculului.
- Raportul zilnic materializează numai coloanele cohortei folosite efectiv, fără schimbarea ferestrelor sau rezultatelor.
- Manifestul istoriei exclude numai cache-ul derivat `ui_catalog_*`, la fel cum exclude deja metadatele de arhivare. Semnalele, observațiile, politicile, ordinele și rezultatele financiare rămân verificate. Cache-ul poate fi reconstruit din surse.

## Verificări

Testele folosesc SQLite/fișiere/subprocessuri reale pe baze temporare și furnizori simulați. Acoperă backup și restaurare pe destinații cu spații/Unicode, capacitatea ambelor volume, configurații invalide, echivalența căutării și raportului cu implementarea precedentă, arhivele, scrieri SQL native, concurență și modificări intervenite în timpul indexării.

```bash
uv run --frozen ruff check app tests
uv run --frozen pytest -q
uv run --with playwright python tests/browser_audit.py
```

Rezultatele finale, comparațiile pe baza reală și verificarea Windows sunt consemnate separat în dovezile acestei versiuni după finalizarea lor. Testele simulate nu reprezintă validare a profitabilității, generare AI reală sau livrare Telegram.

Pilotul prospectiv, policy 32, soldurile manuale și execuția reală dezactivată sunt păstrate. AI și Telegram nu sunt activate de această versiune.
