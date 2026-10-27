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
- Raportul zilnic selectează numai coloanele cohortei folosite efectiv și permite optimizatorului SQLite să aleagă planul, fără schimbarea ferestrelor sau rezultatelor.
- Manifestul istoriei exclude numai cache-ul derivat `ui_catalog_*`, la fel cum exclude deja metadatele de arhivare. Semnalele, observațiile, politicile, ordinele și rezultatele financiare rămân verificate. Cache-ul poate fi reconstruit din surse.

## Verificări

Testele folosesc SQLite/fișiere/subprocessuri reale pe baze temporare și furnizori simulați. Acoperă backup și restaurare pe destinații cu spații/Unicode, capacitatea ambelor volume, configurații invalide, echivalența căutării și raportului cu implementarea precedentă, arhivele, scrieri SQL native, concurență și modificări intervenite în timpul indexării.

```bash
uv run --frozen ruff check app tests
uv run --frozen pytest -q
uv run --with playwright python tests/browser_audit.py
```

Local: **662 teste pytest trecute**, 272,21 s, un avertisment existent de depreciere Starlette/httpx; **49 scenarii Chromium trecute** cu furnizori controlați. Ruff și verificarea sintaxei celor trei fișiere JavaScript au trecut. Testele simulate nu reprezintă validare a profitabilității, generare AI reală sau livrare Telegram.

CI pentru codul final: [40465684548](https://github.com/Serin15/chatgpt/actions/runs/40465684548), commit `7115eca8741c7c491b9697a0ddf59881c7b67ee0`: **succes pe Linux și Windows**, 662 teste pe fiecare sistem, 49 scenarii Chromium pe Linux, pornire Windows și arhivare/restaurare din foldere cu spații pe baze temporare. Extrasele logurilor și metadata joburilor sunt în folderul de dovezi.

## Măsurare pe baza reală

Comparația finală folosește aceeași tranzacție SQLite și aceeași oră pentru fiecare metodă. Toate cele șase rezultate complete sunt identice cu versiunea v0.21.1, inclusiv câmpurile financiare și rezultatele necunoscute. Valorile sunt timpi interni pe acest mediu, nu garanții pentru alte calculatoare.

| Operație | Metoda veche | Metoda nouă |
|---|---:|---:|
| Clasament, 5 rezultate | 9,22 s | 0,81 s |
| Căutare fără rezultat | 10,29 s | 0,22 s |
| Filtru CONSIDER | 7,67 s | 0,18 s |
| Candidați recenți | 0,55 s | 0,62 s |
| Calcul global complet | 78,54 s | 65,85 s |
| Bilanț zilnic | 5,50 s | 5,76 s |

Pentru compararea rezultatului complet al căutării vechi s-a dezactivat **numai în procesul verificatorului** limita ei de execuție de 5 s. Endpointul vechi real răspundea 503 după aproximativ 5 s; limita din motorul original este păstrată. Căutarea nouă din aplicație nu folosește acel proces verificator.

Ultimul eșantion HTTP pe instanța normală: clasament 0,83 s, căutare 0,19 s și filtru de verdict 0,19 s, toate 200. Bilanțul zilnic a durat 13,20 s în acel eșantion; în testul de sarcină a ajuns la 29,78 s. Calculul global rămâne costisitor, iar snapshotul său poate fi vechi în timpul recalculării; interfața arată explicit aceste informații. Nu declarăm rezolvate toate limitele de performanță ale istoricului mare.

O încercare cu materializare SQL forțată a produs o regresie a bilanțului zilnic: 4,06 → 116,48 s. A fost depistată pe baza reală și eliminată înaintea versiunii finale. Logul încercării este păstrat separat de verificarea finală. Un alt defect depistat în helperul nou de backup, parcurgerea fără oprire a părinților unui volum inexistent, a fost reprodus într-un subprocess izolat cu timeout și corectat prin respingere explicită.

## Verificări live și limite

- Indexarea inițială a ajuns automat la **198.820 candidați**; progresul este păstrat, iar după restart indexul este reutilizat. Semnalele noi continuă să fie colectate.
- Verificatorul colectării normale a trecut toate cele șase criterii în **111 s**, cu **3 capturi distincte pentru alerte și 5 pentru control**, primite în intervalul verificării și în ferestrele promise. Nu au fost injectați candidați sau modificate praguri.
- Chromium pe API real, fără interceptări: 50 candidați afișați, nouă destinații, zero erori JavaScript, fără depășire orizontală la 320/390/768/1536 px. Singurul răspuns 5xx observat în acea verificare a fost 507 al backupului mare, așteptat din cauza capacității.
- Backup și restaurare verificate pe **două volume reale diferite**, cu baze mici sintetice, CRC valid și istoric restaurat identic. Acest test verifică funcționarea destinației/folderului temporar separat; nu este backupul bazei mari din producție.
- În captura finală, volumul aplicației avea aproximativ **2,73 GiB liberi**, iar backupul colocat necesita conservator **20,23 GiB**. Backupul și restaurarea întregului istoric real rămân blocate de capacitate; `/tmp` nu este o destinație persistentă și nu rezolvă lipsa unui volum adecvat. Pe PC se calculează capacitatea pentru baza și discurile locale.
- Verificarea de păstrare confirmă politicile și declarațiile originale, configurația, semnalul/rezultatul de referință și conturile manuale Scanner $100 / News $500, cu zero ordine. Cele 20 de fișiere verificate pentru reguli/colectare/executare sunt identice cu baza v0.21.1; hashul motorului rămâne `cc2e2c6499bbd495b8c28aa38f76d366efb9785e50336a54cd262da62bda9251`.

[Dovezi și comenzi de repetare](storage-search-v0.22-evidence/). Fișierele principale modificate: `app/storage.py` și `app/maintenance.py` pentru volume; `app/opportunity_catalog.py`, `app/main.py` și `app/performance_reporting.py` pentru proiecții/citire; `app/daily_research.py` pentru coloanele citite; interfața, versiunea/lockul, `.env.example` și testele de regresie.

Pilotul prospectiv, policy 32, soldurile manuale și execuția reală dezactivată sunt păstrate. AI și Telegram nu sunt activate de această versiune.
