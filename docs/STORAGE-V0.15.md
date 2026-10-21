# MemeScope v0.15.0 — istoric comprimat și restaurare verificabilă

Arhivarea este **compresie fără pierderi în aceeași bază SQLite**, cu ID-urile,
timestampurile, rândurile și indexurile păstrate. Nu șterge candidați respinși,
observații lipsă, tokenuri dispărute, semnale sau rezultate nereușite.
Compresia nu reprezintă un backup independent de disc.

## Utilizare pe Windows

1. Extrage întreaga versiune nouă. Păstrează folderul `data` și configurația.
2. Închide fereastra în care rulează aplicația.
3. Deschide `archive-windows.cmd` din folderul extras. Nu porni simultan aplicația.
4. Așteaptă mesajul de arhivare verificată, apoi pornește `start-windows.cmd`.

Implicit se comprimă observațiile mai vechi de **7 zile**, păstrând întotdeauna
ultima observație/snapshot pentru fiecare subiect în format text. Dacă baza are
mai puțin de 7 zile, poate să nu existe nimic eligibil. Nu se micșorează fereastra
de observații și nu se elimină rânduri pentru a obține spațiu.

În **Jurnal & rezultate → Stocare și arhivarea istoricului → Verifică spațiul**
apar dimensiunea celor două baze, WAL-ul, spațiul reutilizabil, spațiul liber și
backupurile locale. Indicatorul general de stare avertizează sub 1 GiB liber și
raportează eroare sub 512 MiB. Arhivarea este manuală, nu automată.

## Comenzi exacte

Din rădăcina proiectului, cu Python 3.12 și `uv` disponibile:

```bash
uv sync --frozen
uv run --frozen python -m app.storage status --data-dir data
uv run --frozen python -m app.storage verify --data-dir data
# Oprește aplicația înainte de comanda următoare:
uv run --frozen python -m app.storage archive --data-dir data --days 7 --compact
uv run --frozen python -m app.desktop
```

`--days` acceptă 1–3650, implicit 7. Fără `--compact`, paginile eliberate rămân
reutilizabile de SQLite, chiar dacă fișierul nu scade imediat. Cu `--compact`,
SQLite `VACUUM` recuperează fizic spațiul. Operația verifică spațiul pentru copii,
ZIP, compactare și rezerva de 512 MiB, inclusiv volumul temporar folosit de SQLite.
Nu șterge automat backupuri existente. O oprire a colectării lasă observații ratate,
care nu sunt reconstruite din prețurile actuale.

Restaurare într-un **dosar care nu există**, fără suprascrierea datelor curente:

```bash
uv run --frozen python -m app.storage restore --backup "data/backups/NUME-BACKUP.zip" --destination "data-restored"
uv run --frozen python -m app.storage verify --data-dir "data-restored"
uv run --frozen python -m app.research_evaluate --data-dir "data-restored" --day 2026-10-16 --output "restored-report.json"
```

Înlocuiește numele ZIP și ziua cu cele ale bazei tale. `DATA_DIR` selectează datele
atât pentru aplicație, cât și pentru launcherul de arhivare. Aplicația nativă nu
încarcă automat `.env`; variabilele trebuie exportate în mediul procesului.

## Ce verifică operația

- Backup SQLite consistent pentru fiecare cont, ZIP publicat numai după verificări
  SQLite/CRC. O eroare elimină fișierul parțial, fără a elimina backupuri anterioare.
- Restaurare efectivă a backupului, `quick_check` și comparația numărului/hashului
  tuturor rândurilor logice, înainte de compresia originalelor.
- Loturi atomice de maximum 200 de rânduri. Fiecare payload comprimat se citește
  din nou și se compară exact cu originalul înainte de commit.
- Manifest complet înainte/după arhivare și după compactare. Tabelele de cercetare,
  conturile, ordinele, politicile și rezultatele trebuie să fie logic identice.
  Jurnalul nou `storage_archive_runs` este separat de acest manifest.
- Restaurare numai pentru cele două nume de baze acceptate, într-un dosar nou.
  Sunt refuzate fișiere suplimentare, căi relative abuzive, duplicate și symlinkuri.
- Lock OS pe durata aplicației/mentenanței, pe Windows și Linux. Se eliberează și la
  terminarea procesului. Nu se înlocuiește baza unui proces activ.

## Format și compatibilitate

Doar `snapshots.market/security/analysis` și `opportunity_observations.payload`
sunt eligibile. Payloadurile suficient de mari devin BLOB-uri zlib versionate,
cu lungimea originală și SHA-256. JSON-ul nu este reserializat: precizia prețurilor,
textele, ordinea câmpurilor și dovezile originale rămân identice. Limita de citire
este 16 MiB/payload; valorile mai mari rămân text. Coruperea produce eroare,
nu date absente sau PnL zero.

Conexiunile aplicației și exportatorului read-only decodează valorile. Interogările
SQL JSON1 folosesc `archive_text(payload)`. Pentru scripturi SQLite externe:

```python
import sqlite3
from app.archive_codec import configure
with sqlite3.connect("data/research.sqlite3") as db:
    configure(db)
    row = db.execute("SELECT payload FROM opportunity_observations WHERE id=?", (1,)).fetchone()
```

Nu rula o versiune anterioară pe o bază deja comprimată. Pentru revenire există
backupul creat înaintea arhivării; restaurează-l într-un dosar nou. La găzduire,
folosește un singur proces al aplicației pentru același `DATA_DIR`.

`paper.py`, `jupiter.py`, `opportunity_routes.py` și regulile de scor sunt păstrate.
Sursa de execuție Jupiter rămâne `0ad33d6b40cd23f133078fa9e78f42008cfaec7776d463299872c3fa3b04e3f7`.
Schimbarea citirilor SQL schimbă amprenta motorului: noile semnale primesc o politică
și o declarație prospectivă distincte. Protocoalele, cutoff-urile și rezultatele
istorice nu sunt rescrise și nu demonstrează performanța unei politici noi.

## Fișiere și costuri

| Fișiere | Schimbare |
| --- | --- |
| `app/archive_codec.py` | Codec verificat, citiri SQLite și funcție SQL; cache de o valoare per conexiune |
| `app/storage.py` | Capacitate, manifeste, arhivare, compactare și restaurare offline |
| `app/runtime_lock.py`, `app/main.py` | Excludere între aplicație și mentenanță; endpoint capacitate și avertizare de spațiu |
| `app/maintenance.py` | Backup atomic, verificări SQLite/ZIP și spațiu înaintea copierii |
| `app/store.py`, `app/research_evaluate.py` | Citirea arhivei în aplicație și exportul offline |
| `app/daily_research.py`, `app/price_research.py`, `app/opportunity_outcomes.py`, `app/opportunity_sampling.py`, `app/opportunities.py` | JSON1 decodează istoricul înaintea extragerii câmpurilor |
| `app/static/app.js`, `app/static/index.html` | Panou de stocare și avertizare în starea generală |
| `archive-windows.cmd` | Mentenanță cu backup/restaurare verificată din Windows |
| `tests/test_storage.py`, `tests/browser_audit.py`, `.github/workflows/checks.yml` | SQLite/ZIP/lock, erori, UI desktop/mobil și launcher nativ Windows |

Nu sunt necesare API-uri, chei, abonamente sau dependențe noi pentru arhivare.
Costul este local: CPU, I/O și spațiu temporar, plus locul păstrat de backupuri.
Costurile și cerințele surselor crypto/AI rămân cele din README. Nicio tranzacție
reală nu este disponibilă sau executată de acest flux.

## Verificări

Dovezile versiunii sunt în `storage-evidence/`. Testele de piață din suită folosesc
furnizori simulați; SQLite, ZIP, compresia și restaurarea sunt reale. Verificarea
separată pe baza cloud folosește istoricul colectat efectiv, fără cotații inventate.

```bash
uv run --frozen pytest -q
uv run --frozen ruff check app tests
uv run --frozen --with playwright python tests/browser_audit.py
```

Limitări păstrate: arhivarea nu oprește creșterea tuturor tabelelor, backupul local
nu protejează la pierderea discului, iar compactarea întrerupe colectarea. Pentru
următoarea etapă: colectare prospectivă cu politica fixată, raport de completitudine
și rezultate după costuri. Nu există încă dovadă statistică pentru 10x/100x.
