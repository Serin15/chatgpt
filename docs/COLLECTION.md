# v0.8 — colectare prospectivă și grup fix de comparație

15 octombrie 2026. Această actualizare rezolvă programarea observațiilor și măsurarea acoperirii.
Nu modifică pragurile financiare pentru oportunități și nu adaugă tranzacții reale.

## Problema reprodusă

După aproximativ zece ore de rulare, vechiul colector avea peste 10.000 de candidați, aproape
10.000 scadenți și peste 3.600 încă neîmbogățiți. Mii de prime evaluări fără alertă ajunseseră la
`missing_forward_entry`. Alertele aveau prioritate; grupul determinist de 20% exista în raport,
dar nu beneficia de aceeași urmărire în colector. Comparația rezultatelor avea acoperire inegală.

[Fotografia înaintea modificării](collection-evidence/before.json) este din baza reală, nu din
fixture-uri. Nu completăm lipsurile istorice cu prețuri actuale.

## Ce s-a schimbat

- Fiecare candidat primește la înregistrare apartenența la un grup determinist de comparație:
  `int(sha256(contract)[:8],16) % 5 == 0`. Apartenența nu depinde de scor, preț ulterior, verdict
  sau succes. Aproximativ 20% în așteptare, fără garanția unui procent exact în eșantioane mici.
- Înscrierea este persistentă și precede evaluarea. Candidații existenți la migrare sunt `legacy`,
  separat de înscrierile `prospective`. Nu pretindem că vechiul istoric a fost colectat echilibrat.
- Fiecare semnal are o sarcină de observare a intrării, cu început și termen-limită înghețate.
  După o intrare modelabilă, fiecare orizont primește o sarcină de ieșire pornind de la ora
  efectivă a primei observații de intrare. Un orizont de 24h nu ocupă un loc în fiecare minut.
- Jumătate din bugetul unui ciclu protejează follow-up-ul alertelor și al controlului, alternând
  între grupuri după termenul cel mai apropiat. Capacitatea nefolosită poate fi împrumutată.
  Un token din ambele grupuri consumă o singură observație; suprapunerea este raportată.
- Controlul primește și repere de preț la orizonturile configurate, pornind de la prima descoperire,
  chiar dacă intrarea paper este respinsă. Acestea păstrează preț/lichiditate fără a inventa un fill
  sau un profit și sunt raportate separat de intrări/ieșiri. Nu reconstruim astfel repere istorice lipsă.
- O treime din buget permite îmbogățirea descoperirilor noi. Restul poate prelua alte termene și
  observații de fundal. Sarcinile de follow-up pot depăși `next_due` al verificării periodice;
  un token respins nu trebuie să aștepte cinci minute pentru o fereastră de intrare de trei minute.
- După fereastra activă implicită de 15 minute, verificarea periodică devine zilnică. Tokenurile
  și încercările eșuate rămân în bază. Sarcinile de ieșire programate separat continuă la orizontul
  promis, inclusiv pentru semnale vechi recuperate la migrare. Watchlistul și pozițiile manuale
  rămân urmărite de workerul existent.
- Presetul nou are 60 observații/ciclu, grupate în cereri de maximum 30 adrese. Numai vechiul
  preset complet neschimbat de 30 este migrat automat la 60. O configurație personalizată este
  păstrată. Pragurile de risc, suma virtuală și costurile nu sunt relaxate. Bugetul se poate
  modifica din interfață, între 1 și 100; nu reprezintă o capacitate garantată a furnizorilor.

Datele brute, prețurile inițiale, semnalele și politicile vechi nu sunt rescrise. Migrarea pe o
copie reală a bazei de 279 MB a durat sub o secundă în acest mediu; hashurile tabelelor cu
semnale, rezultate și ordine au rămas identice: [dovadă](collection-evidence/migration.json).
Dimensiunea sau timpul nu sunt garanții pentru alte sisteme.

## Ce înseamnă cifrele din dashboard

**Calitatea colectării** arată separat, pentru candidații înscriși prospectiv:

- ferestre cu o încercare de observare în interval;
- termene ratate;
- sarcini încă în așteptare;
- motive precum cotație indisponibilă, securitate insuficientă, filtru de lichiditate/risc,
  cotație preluată înaintea ferestrei sau colectare terminată după termen.

O încercare observată nu este un fill valid și nu înseamnă profit. Un răspuns HTTP reușit cu date
incomplete poate duce la `entry_unavailable`. Un preț preluat înaintea ferestrei nu este folosit
ca un fill ulterior valid. O fereastră fără observație rămâne `missing_forward_entry/exit`,
cu PnL null. Nu reîncercăm la cel mai favorabil preț pentru a îmbunătăți un rezultat.

Rata acoperirii folosește încercările observate și termenele deja ratate. Ferestrele încă viitoare
nu intră ca eșecuri sau succese. Endpointul arată și termenele expirate când workerul este oprit,
fără a modifica baza printr-un GET. Un termen nepreluat nu ne spune singur dacă a fost o pauză,
o lipsă de capacitate sau altă problemă; eticheta păstrează această incertitudine.

Comparația paper prospectivă este separată de rapoartele istorice. Include controlul respins,
rezultatele indisponibile și tokenurile care apar și printre alerte. Mărimea universului înscris
și numărul candidaților fără prima observație sunt vizibile. În API, `groups` reprezintă toate
sarcinile operaționale, `prospective_groups` numai cohorta nouă, iar `legacy_groups` termenele
istorice recuperate. Dashboardul folosește cohorta nouă pentru această comparație.

## Verificare executabilă

Instalarea rămâne aceeași:

```bash
uv sync --frozen
uv run python -m app.desktop
```

Pentru o probă izolată, din folderul repository-ului, într-un terminal separat:

```bash
DATA_DIR=/tmp/memescope-collection-demo uv run python -m uvicorn app.main:app \
  --host 127.0.0.1 --port 8766
```

Alege un director nou. Pe Windows/PowerShell, setează `$env:DATA_DIR` înainte de aceeași comandă,
pe un singur rând. În alt terminal:

```bash
uv run python -m app.collection_verify --url http://127.0.0.1:8766 \
  --duration 900 --output /tmp/collection-proof.json
```

Verificatorul citește numai API-ul: identitatea aplicației, tranzacții reale dezactivate,
înscrierea prospectivă, exemple reale de prețuri în fereastră în ambele grupuri, o observație
ulterioară de ieșire și un reper ulterior de preț în control. Nu injectează tokenuri, nu schimbă praguri, nu trimite mesaje Telegram și
nu plasează ordine. Dacă datele necesare nu apar în interval, produce `complete=false` și exit 1.
Nu este o dovadă de profitabilitate sau o garanție de livrare sub orice încărcare.

```bash
uv run ruff check app tests
uv run pytest -q
node --check app/static/opportunities.js
uv run --with playwright python tests/browser_opportunities.py
```

Testele unitare/de integrare folosesc fixture-uri explicite. Verificarea browserului folosește
Chromium real și date simulate. Probele din [collection-evidence](collection-evidence/) sunt
separate: API-uri reale, migrare pe copia bazei reale și teste simulate.

## Chei și costuri

Această actualizare nu cere o cheie sau un abonament nou. Proba folosește API-urile publice
existente; rate limits și indisponibilitatea lor pot reduce acoperirea. Un RPC dedicat este
opțional, cu costul planului ales. AI și Telegram rămân opționale. Bugetul mai mare poate
crește traficul și dimensiunea bazei. [Servicii și estimarea costurilor](LEVEL3.md) descrie
cerințele existente; nu a fost cumpărat sau activat automat un serviciu plătit.

## Limite rămase și următorul pas

Acoperirea verificată într-un eșantion scurt nu este un SLA. Dacă noile descoperiri și termenele
depășesc bugetul sau API-urile nu răspund, pot exista în continuare lipsuri, acum măsurate explicit.
Reverificarea rară a tokenurilor vechi poate rata mișcări între observații; nu pretindem o serie
completă sau detectarea tuturor oportunităților. Feedurile rămân un univers parțial.

Păstrează politica și colectează date prospective suficiente înainte de comparații statistice.
1h/24h necesită trecerea reală a timpului. Pasul următor este simularea intrării/ieșirii cu cotații
rutate unde există suport, apoi o evaluare pe o perioadă de test declarată în avans. Acest update
nu demonstrează identificarea unor viitoare 10x/100x și nu repară retrospectiv datele lipsă.
