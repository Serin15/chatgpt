# MemeScope v0.16.0 — prioritate pentru descoperirile timpurii

Motorul separă reevaluarea inițială de monitorizarea periodică a candidaților
vechi. După încheierea ferestrei de fundal (implicit **48 de ore de la
înregistrarea în motor**), un candidat fără obligații deschise intră în pauză
pentru colectarea periodică. Dosarul, descoperirea inițială, semnalele, scorurile,
observațiile, rezultatele, politicile și apartenența la control rămân păstrate și
accesibile prin căutare. Pauza nu reprezintă o ieșire reușită sau o pierdere zero.

Nu se elimină rânduri și nu se rescriu termene, grupuri sau rezultate istorice.
Arhivarea fără pierderi din [v0.15](STORAGE-V0.15.md) rămâne disponibilă separat.

## Ce s-a reparat

1. Candidații vechi, cu urmărirea promisă încheiată, erau programați pentru
   reevaluare zilnică fără limită de vârstă. Restanțele creșteau permanent.
2. Locurile rămase după observațiile promise erau alocate exclusiv după
   `next_due`; un candidat vechi putea preceda un token aflat în primele minute
   de urmărire. Acum colectarea inițială, lista personală și referințele recente
   la contract precedă colectarea de fundal.
3. Contorul de restanțe nu diferenția reevaluările periodice în pauză de cele
   încă eligibile. Interfața afișează ambele și păstrează totalul brut.

Regula operațională de 48 de ore nu este optimizată după randamente viitoare.
`background_watch_hours` acceptă 1–168 prin configurația existentă a motorului;
`active_watch_seconds` și bugetele existente rămân respectate. Noua regulă este
inclusă în amprenta codului și în politicile create de acum înainte. Politicile
vechi și granițele lor dezvoltare/testare nu se modifică. Pentru politica nouă
se aplică o nouă declarare prospectivă; datele de dezvoltare nu validează
profitabilitatea viitoare.

## Bugetul verificărilor de securitate

Rularea reală a scos la iveală un al patrulea blocaj: verificările pentru
candidații procesați primii puteau consuma tot bugetul înainte de descoperirile
noi. Se rezervă acum până la `ceil(security_budget / 3)` apeluri pentru
candidații aflați în fereastra activă sau încă fără prima observație. Cu buget de
un singur apel, rezervarea alternează între cicluri. Locurile eliberate pot fi
folosite de candidații procesați ulterior. Unele pot rămâne nefolosite dacă
ultimii candidați nu au nevoie de verificare sau nu au lichiditate suficientă.

Ordinea cotațiilor și termenele observațiilor promise rămân respectate. Nu se
mărește bugetul total și nu se relaxează verificarea de securitate, vechimea
acceptată sau filtrele de lichiditate. Un apel eșuat consumă un loc și lasă
dovezile necunoscute. `status.security_allocation` raportează apelurile încercate
pentru candidații timpurii și pentru ceilalți; nu reprezintă numărul de tokenuri
sigure sau de verificări complete. Schimbarea are propria versiune în politica
înghețată și necesită evaluare prospectivă separată.

## Protecții

- Prima încercare de colectare este obligatorie chiar dacă furnizorul a fost
  indisponibil mai mult de 48 de ore.
- Observațiile de intrare, ieșire, reperele de preț și ieșirile rutate promise
  rămân prioritare, inclusiv când termenul este la șapte zile. Programul periodic
  și limita de vârstă nu le anulează.
- Rezultatele estimate sau rutate încă nerezolvate și intrările rutate în curs
  împiedică punerea în pauză. Termenele deja ratate rămân ratate.
- Lista de urmărire și pozițiile virtuale deschise din ambele conturi sunt
  protejate. Programul periodic și bugetul se respectă în continuare; scannerul
  pozițiilor manuale continuă independent.
- O referință nouă verificată la contract, în documentele deja acceptate de
  modulul de știri, poate relua urmărirea pentru fereastra activă. Se acceptă
  adresa explicită și blockchain-ul corespunzător sau o referință de pool
  calificată. Numele asemănător, dovezile viitoare și cele expirate nu ajung.
  Reluarea nu înseamnă o lansare nouă sau confirmarea unei asocieri oficiale.
- API-urile de stare și dosar sunt read-only pentru această funcție.

`queue.due` continuă să însemne totalul brut de candidați cu `next_due` periodic
scadent. `dispatchable_due` exclude candidații în pauză; `paused_due` păstrează
restul. Observațiile promise pot ocoli programul periodic: numărul lor distinct
este raportat separat prin `promised_due_candidates`, inclusiv partea din afara
cozii periodice. Nu aduna aceste grupuri fără a elimina suprapunerile.

## Instalare și pornire

În Windows, închide aplicația veche, extrage complet versiunea nouă și păstrează
folderul `data` și configurația locală. Deschide `start-windows.cmd` din folderul
care conține `app` și `pyproject.toml`. Deschide `http://127.0.0.1:8000` dacă
browserul nu pornește automat. Nu rula două instanțe pe același `DATA_DIR`.

Cu Python 3.12 și uv, din rădăcina repository-ului:

```bash
uv sync --frozen
uv run --frozen python -m app.desktop
```

În pagina **Oportunități timpurii**, panoul calității colectării arată coada
periodică și obligațiile scadente. Dosarul unui candidat arată starea curentă a
monitorizării, separat de verdictul și observațiile istorice.

## Verificare reproductibilă

```bash
uv run --frozen ruff check app tests
uv run --frozen pytest -q
uv run --frozen pytest -q tests/test_candidate_lifecycle.py
node --check app/static/opportunities.js
uv run --frozen --with playwright playwright install chromium
# Linux cu Chromium instalat în /usr/bin/chromium:
BROWSER_EXECUTABLE=/usr/bin/chromium uv run --frozen --with playwright python tests/browser_audit.py
```

Testele Python folosesc furnizori simulați și baze SQLite reale, izolate.
Scenariile Chromium folosesc date explicite de test; nu sunt dovezi de precizie
pe piață. Dovezile pentru baza și aplicația normală sunt păstrate separat în
`docs/monitoring-evidence/` și explicate mai jos după rulare.

## Servicii, costuri și limite

Această versiune nu adaugă servicii, chei sau abonamente și nu mărește bugetele
API. Colectarea folosește în continuare furnizorii de piață și securitate deja
configurați. Cotațiile Jupiter necesită accesul/cheia furnizorului; AI și Telegram
rămân opționale și necesită propria configurare. Nu s-au verificat livrări noi
Telegram sau modele AI în această etapă.

Reducerea numărului de reevaluări eligibile nu reprezintă o creștere măsurată a
preciziei. Capacitatea poate rămâne insuficientă pentru toate observațiile;
rapoartele păstrează lipsurile. După pauză nu se observă automat fiecare revenire
de preț. O știre cu contract verificabil sau urmărirea manuală poate relua
monitorizarea; nu se poate măsura riguros rata tuturor oportunităților ratate.

Următorul pas recomandat: păstrarea unei politici stabile și măsurarea
prospectivă a acoperirii la intrare/ieșire și a rezultatelor nete, separat pe
politici și cohorte. Dacă se ratează încă multe termene, ajustarea capacității
sau a admisiei trebuie declarată ca experiment nou, fără reechilibrarea
retroactivă a grupului de control. Nu există dovezi că motorul identifică
predictibil tokenuri de 10x/100x. Tranzacționarea cu bani reali rămâne dezactivată.
