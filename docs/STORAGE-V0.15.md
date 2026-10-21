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
SQL JSON1 folosesc `archive_text(payload)` numai pentru BLOB-uri. JSON-ul text
folosește calea nativă SQLite; clasarea ultimei observații rămâne nativă, deoarece
arhivarea păstrează acest rând în text. Pentru scripturi SQLite externe:

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
| `app/daily_research.py`, `app/price_research.py`, `app/opportunity_outcomes.py`, `app/opportunity_sampling.py` | JSON1 decodează numai payloadurile binare; textul și clasarea ultimei observații păstrează calea nativă SQLite |
| `app/static/app.js`, `app/static/index.html` | Panou de stocare și avertizare în starea generală |
| `archive-windows.cmd` | Mentenanță cu backup/restaurare verificată din Windows |
| `tests/test_storage.py`, `tests/browser_audit.py`, `.github/workflows/checks.yml` | SQLite/ZIP/lock, erori, UI desktop/mobil și launcher nativ Windows |

Nu sunt necesare API-uri, chei, abonamente sau dependențe noi pentru arhivare.
Costul este local: CPU, I/O și spațiu temporar, plus locul păstrat de backupuri.
Costurile și cerințele surselor crypto/AI rămân cele din README. Nicio tranzacție
reală nu este disponibilă sau executată de acest flux.

## Verificări

Codul aplicației/testelor: `b27f4070b7a49367a68af4f94e91de230e8ad085`.
Modificările ulterioare din această livrare documentează verificările.

- **502 teste unitare/de integrare trecute**, 98,12 secunde local; un avertisment
  existent de deprecare Starlette/httpx. [pytest.txt](storage-evidence/pytest.txt).
- **28/28 scenarii Chromium trecute**, cu baze temporare și furnizori izolați:
  [browser.json](storage-evidence/browser.json).
- Ruff, sintaxa celor trei fișiere JS, `uv sync --frozen` și `git diff --check`:
  trecute. Nu există dependențe noi.
- Aplicația obișnuită, cu date reale: panoul stocării, dosarul candidatului 1
  (inclusiv 7 observații comprimate), desktop/mobil, fără interceptări/stare
  injectată, fără erori JS sau HTTP 500 în verificare. Conturi manuale $500/$100,
  zero ordine: [browser-live.json](storage-evidence/browser-live.json).
- După repararea blocării, **10 confirmări normale de alertă cu HTTP 200** și
  zero `database is locked` în fereastra observată:
  [backlog-live.json](storage-evidence/backlog-live.json). Acesta este un eșantion,
  nu o garanție că toate condițiile viitoare au fost testate.
- Semnalele, politicile, configurația și protocolul inițial sunt verificate și
  după reluarea colectării:
  [after-restart-preservation.json](storage-evidence/after-restart-preservation.json).
- CI nativ Linux/Windows: [39550431631](https://github.com/Serin15/chatgpt/actions/runs/39550431631).
  Rezultatul curent este păstrat în `storage-evidence/ci.json`; o rulare încă în
  curs nu reprezintă validare Windows. Include launcherul de arhivare într-o
  cale cu spații și verificarea restaurării.

Dovezile versiunii sunt în `storage-evidence/`. Testele de piață din suită folosesc
furnizori simulați; SQLite, ZIP, compresia și restaurarea sunt reale. Verificarea
separată pe baza cloud folosește istoricul colectat efectiv, fără cotații inventate.

### Verificare pe baza reală, 21 octombrie 2026

- Rulare offline cu `--days 3 --compact`, separat de valoarea implicită de 7 zile.
  Baza principală: **3.845.509.120 → 3.514.163.200 bytes**, reducere de
  **331.345.920 bytes / 8,62%**. Nu este o estimare pentru alte baze.
- **128.071 snapshoturi și 128.558 observații** comprimate. Manifestele celor
  **59 de tabele de cercetare/conturi**, însumând **2.108.190 de rânduri**, sunt
  identice logic înainte/după. Jurnalul nou de arhivare este verificat separat.
- Sunt păstrate inclusiv **183.375 semnale**, **17 politici**, **108.174 experimente
  Jupiter**, **324.522 rezultate Jupiter** și zero ordine în conturile manuale.
- Backupul inițial de 341.242.669 bytes a fost restaurat și comparat înaintea
  compresiei. Un backup ulterior al bazei comprimate, de **625.837.061 bytes**,
  a fost de asemenea restaurat într-un dosar nou: toate rândurile logice și
  metadatele arhivării sunt identice.
- Raportul cohortei **16 octombrie, 13.660 de candidați**, este identic integral
  înainte/după, exceptând `generated_at`. Hashul raportului normalizat este în
  [report-equivalence.json](storage-evidence/report-equivalence.json).
- Verificarea inițială pe baza mare a identificat o regresie de viteză în accesul
  necondiționat prin Python. A fost reprodusă printr-un test care refuză decoderul
  pe JSON text și corectată: numai BLOB-urile traversează decoderul. Pe 5.000 de
  observații reale, aceeași extragere a durat 0,145 s prin decoder necondiționat,
  0,052 s nativ și 0,047 s condițional. Sunt măsurători locale, nu garanții.
  Două cereri reale de clasare după corecție au returnat câte 50 de candidați în
  **2,71 s și 1,89 s**.
- La recuperarea după oprire, recalcularea a până la 2.000 de rezultate păstra
  blocarea de scriere între calcule; confirmări ale alertelor au răspuns HTTP 500
  cu `database is locked`. Regresia este reprodusă separat în
  [backlog-before.txt](storage-evidence/backlog-before.txt). Expirarea joburilor
  se confirmă acum separat, apoi fiecare rezultat și joburile lui se confirmă
  atomic înaintea următorului calcul. Formulele, ferestrele și selecția observației
  sunt identice AST după eliminarea apelurilor suplimentare de commit:
  [outcome-compatibility.json](storage-evidence/outcome-compatibility.json).

Backupurile sunt păstrate pe același volum în această verificare și ocupă separat
967.079.730 bytes. Economia din fișierul bazei **nu este economie netă pe disc**
după adăugarea acestor copii. Mută copii verificate pe alt disc pentru protecție
independentă; aplicația nu elimină automat niciun backup.

```bash
uv run --frozen pytest -q
uv run --frozen ruff check app tests
uv run --frozen --with playwright python tests/browser_audit.py
```

Limitări păstrate: arhivarea nu oprește creșterea tuturor tabelelor, backupul local
nu protejează la pierderea discului, iar compactarea întrerupe colectarea. Pentru
următoarea etapă: colectare prospectivă cu politica fixată, raport de completitudine
și rezultate după costuri. Nu există încă dovadă statistică pentru 10x/100x.

## Starea funcțiilor și ce rămâne

| Funcție | Stare |
| --- | --- |
| Compresie fără pierderi, compactare și integritatea istoricului | Implementate și verificate pe baza reală Linux |
| Backup și restaurare, înainte și după compresie | Implementate și verificate prin restaurarea efectivă a ambelor baze |
| Dosare, rapoarte vechi și export read-only pe date comprimate | Implementate și verificate, inclusiv pe cohorta reală de 13.660 candidați |
| Capacitate, avertizare de spațiu și UI mobil | Implementate și verificate |
| Cale SQL nativă pentru text; decoder numai pentru BLOB | Implementată și verificată prin regresie și măsurători reale |
| Eliberarea blocării între calculele rezultatelor | Implementată, regresie trecută și confirmări HTTP 200 observate în aplicație |
| Launcher de arhivare nativ Windows | Implementat; rezultatul CI stabilește verificarea nativă, separat de Linux |
| Arhivare/eliminare automată a backupurilor | Neimplementată; operația este manuală, fără ștergeri automate |
| Avantaj predictiv și rezultate pe testul viitor | Neverificate; necesită timp și date prospective suficiente |

Priorități rămase:

1. **Completitudinea colectării.** Snapshotul de stare păstrează aproximativ
   61.000 de reevaluări de fundal restante, cu bugete API limitate. Toți candidații
   noi din acel snapshot au o primă observație, dar aceasta nu garantează
   follow-up sau ieșiri la timp. Arhivarea nu repară această capacitate de colectare.
   Urmează evaluarea duratei monitorizării active și a bugetelor, fără eliminarea
   candidaților nereușiți din istoric sau din comparații.
2. **Test prospectiv și rapoarte mari.** Politica finală 20 este declarată la
   21 octombrie 05:34:30 UTC; testul ei începe la **22 octombrie 05:34:30 UTC
   (08:34 în România)**. Protocoalele 17–19 rămân intacte. Păstrează politica
   fixată și colectarea pornită; nu modifica cutoff-ul pentru a obține rezultate.
   Rapoartele globale pot rămâne costisitoare pe istoricul mare; următoarea
   optimizare trebuie să păstreze toți numitorii și proveniența datelor.
3. **Backup pe alt volum.** Copiile locale sunt verificate, dar nu protejează la
   pierderea întregului disc. Nu s-a configurat o destinație externă și nu s-au
   șters copii pentru a afișa artificial mai mult spațiu liber.
