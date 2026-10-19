# Verificare v0.13 — observații, rapoarte și concurență

Datele reale, fixture-urile și simulările financiare sunt separate mai jos.
Această etapă nu declară aplicația completă sau profitabilă.

## Cod și teste izolate

Implementarea finală: `452d332cf97f4630fe81fdf0b3a45685745d84a2`.
Commiturile ulterioare de documentație/dovezi nu schimbă aplicația sau testele.

- `.venv/bin/pytest -q`: **426 passed**, un avertisment de deprecare din
  Starlette/httpx; [ieșire integrală](pytest.txt). Nu s-au apelat servicii externe.
- `.venv/bin/ruff check app tests`, `git diff --check` și `node --check` pentru
  cele trei fișiere JavaScript: trecute.
- Audit Chromium: **20/20** scenarii cu furnizori izolați,
  [browser.json](browser.json). Include separarea prețurilor de încercări,
  tabelele noi și lățimea de 390 px. Nu constituie dovadă de piață reală.
- Corpus AI: 12 cazuri validate structural; `model_run=false`. Nu s-a măsurat
  precizia unui model și nu s-a apelat un model real în această etapă.

Validarea inițială CI [39245535279](https://github.com/Serin15/chatgpt/actions/runs/39245535279)
a trecut pentru implementarea inițială `c1cfb28`. Logurile oficiale descărcate după
încheiere confirmă **416 passed** pe Windows (779,91s) și Ubuntu (68,74s),
**19/19** scenarii Chromium pe Linux și pornirea launcherului nativ Windows
dintr-un director cu spații. Metadatele inițiale sunt în [ci-initial.json](ci-initial.json). Verificarea continuă
a identificat apoi blocarea stocării și problema de precizie a ceasului, descrise mai jos.

Validarea finală CI [39258455505](https://github.com/Serin15/chatgpt/actions/runs/39258455505)
a trecut pentru codul `452d332`. Logurile oficiale descărcate confirmă **426 passed**
pe Windows (**576,81s**) și Ubuntu (**69,84s**), **20/20** scenarii Chromium și
pornirea nativă Windows dintr-un director cu spații. Metadatele și pașii sunt în
[ci.json](ci.json). Verificarea intermediară a corecției de ceas, cu 424 teste,
se păstrează în [ci-clock.json](ci-clock.json).

Regresiile au fost reproduse înainte de remediere:

| Problemă | Dovadă înainte | Rezultatul corecției |
| --- | --- | --- |
| Încercările erau afișate ca observații utile; lipsea comparația prețurilor | [9 teste eșuate](price-before.txt) | Prețuri valide și stări necunoscute separate; include respinse și lichiditate zero |
| Cotația preluată înaintea ferestrei consuma observația | [2 teste eșuate](window-before.txt) | Politică nouă v2; jobul așteaptă cotația din interval; un eșec real rămâne eșec |
| Verificatorul confunda pool-ul cu contractul direct și accepta receipt viitor | [2 teste eșuate](verifier-before.txt) | Tip de dovadă explicit și receipt în intervalul real |
| Refreshurile simultane recalculau repetat raportul mare | [2 teste eșuate](concurrency-before.txt) | Un calcul în desfășurare, copii independente, eroare transmisă și recuperare la cererea următoare |
| Stocarea sincronă din colector bloca răspunsurile API | [4 teste eșuate](responsiveness-before.txt) și [stack real](blocking-stack-before.txt) | Persistare, istoric, outcomes și acoperire în fundal; oprirea așteaptă scrierea înainte de eliberarea lease-ului |
| Scannerul vechi citea arhiva pe firul principal | [1 test eșuat](scanner-before.txt) și stack real | Aceeași citire în fundal, fără ștergerea sau filtrarea istoricului |
| Rapoartele zilnice simultane se recalculau și istoricul se încărca în paralel | [regresie API](daily-concurrency-before.txt), [regresie browser](history-browser-before.txt) | Calcul comun pe aceeași zi; date diferite independente; candidații apar înaintea rapoartelor grele |
| Windows respingea uneori date proaspete din cauza ceasurilor diferite | [eșec CI real](clock-windows-failure.json), [reproducere deterministă](service-clock-before.txt) | Un singur ceas UTC; cazurile realmente viitoare rămân blocate |

Nu există cache de rapoarte istorice: o cerere nouă, după terminarea celei
anterioare, citește date noi. Cererile simultane împart numai calculul curent.
Testele includ succes, eroare, mutarea rezultatului de către apelant și o nouă
cerere după eroare. Niciun test nu modifică istoricul real al utilizatorului.

Testele de răspuns verifică trei stadii de colectare și scannerul vechi cu
stocare întârziată, plus anularea în timpul scrierii. Cele cinci cazuri au trecut
([responsiveness-after.txt](responsiveness-after.txt)). Cele trei regresii ale
ceasului includ o captură sănătoasă, un preț viitor și securitate viitoare;
viitorul nu este tolerat. Testele sănătoase de screening folosesc și ele UTC,
fără să depindă de diferențele întâmplătoare dintre ceasurile Windows.

## Verificări cu date reale

- [live-state.json](live-state.json): v0.13.0, cele cinci servicii în execuție,
  `live_execution=false`, cele 13 topicuri de știri în starea `ok`. Portofoliile
  manuale Research/Scanner au rămas la $500/$100, cu zero ordine.
- [browser-live.json](browser-live.json): browser normal, fără interceptări,
  afișează raportul stocat din 18 octombrie, cele trei orizonturi și șase rânduri
  de comparație politică/cohortă. Panourile de performanță și Jupiter s-au
  afișat și ele; zero erori pe componente, JS/API și fără overflow la 390 px.
- [live-window.json](live-window.json): job real **91202**, candidat **41806**,
  semnal **93896**, control cu verdict **MONITOR**. Cotația 165014 a fost
  înregistrată la `11:25:20.397 UTC`, dar primită la `11:25:19.856 UTC`, înainte
  de termenul `11:25:20.032 UTC`. Cotația 165074, primită la
  `11:26:19.682 UTC`, a devenit observația valabilă. Outcome-ul de pool la 5m a
  fost evaluat ulterior, cu costurile înghețate. Acesta este un singur scenariu
  virtual cu date de furnizor, nu un swap executat, o alertă din știri sau o
  demonstrație de profitabilitate. Nu s-au injectat observații/tokenuri.
- [preservation.json](preservation.json): toate cele **88.191 semnale** existente
  la verificarea inițială, cele nouă politici și configurația păstrează aceleași
  hashuri. Semnalele noi se adaugă; cele vechi nu sunt rescrise. SQLite
  `PRAGMA quick_check` pe ambele baze reale a răspuns `ok`: [integrity-final.json](integrity-final.json).

Prima verificare a interfeței a expus timeout-uri și acumularea cererilor grele.
Instanțele intermediare ale acestei sarcini au fost oprite și repornite pe
aceleași date, cu backup consistent anterior. Unele cereri de citire au depășit
oprirea normală și au necesitat oprirea procesului intermediar. Nu s-au înlocuit
baze/WAL-uri și nu s-au resetat conturi. Verificările de integritate și
păstrare de mai sus sunt ulterioare acestor opriri.

## Răspuns în timpul colectării

O verificare extinsă a depășit timeout-ul configurat de 15s pentru verificarea
API. Stackurile reale au arătat salvarea snapshoturilor și citirea arhivei de
către scanner pe event loop. Testele unitare inițiale și un dashboard încărcat
o dată nu fuseseră suficiente pentru a surprinde această problemă periodică.

Cu un prag diagnostic de 0,5s, înainte de corecție au eșuat 24/208 probe;
după primele 20s au eșuat 12/180. După mutarea colectării în fundal, monitorizarea
a identificat și scannerul vechi, remediat separat. O verificare ulterioară pe
pornirea normală a înregistrat **685/685 probe fără eroare în șase minute**, cu
timeout 2s și maxim observat aproximativ **0,653s**, în timp ce dashboardul și
furnizorii reali funcționau. [responsiveness-live.json](responsiveness-live.json)
conține intervalele, numitorii și pragurile. Pragurile diferă; nu comparăm direct
ratele de eșec și nu extrapolăm aceste minute la o garanție 24/7.

După corecția ceasului UTC, alt interval de șase minute a avut **două timeout-uri
la 669 probe**, cu limita strictă de 2s. Repetarea cu limita inițială de 15s a
avut **619/619 probe reușite**, maxim **8,888s**. Aceste rezultate arată că mai
există latențe ocazionale; nu susținem dispariția completă a întârzierilor.

Verificarea pe baza reală a găsit apoi un timeout al bilanțului zilei curente,
care nu apărea cu fixture-urile mici. Cererile identice împart acum un calcul;
interfața încarcă mai întâi candidații, apoi pe rând bilanțul, performanța și
Jupiter. Rapoartele zilelor diferite rămân independente. JSON-ul bilanțului se
encodează în workerul endpointului, evitând blocarea event loop-ului. Pentru
răspunsul de 4.786.211 octeți, serializarea a scăzut de la 0,301s la 0,033s,
cu exact aceiași octeți; aceasta nu este o accelerare de zece ori a întregului
raport. [report-serialization.json](report-serialization.json).

Pe backupul consistent al zilei de 19 octombrie, cu 5.699 candidați, raportul
întreg este identic după optimizarea proiecției JSON, 2,162s înainte și 1,979s
după: [today-report-equivalence.json](today-report-equivalence.json). Browserul
real a încărcat apoi ziua curentă și ziua de 18 octombrie, fără interceptări,
erori API/JS sau overflow mobil. Aceasta este o verificare concretă de pornire
și afișare, fără garanție pentru toate dimensiunile viitoare ale bazei. O monitorizare
separată a codului final `452d332`, timp de șase minute cu limita 15s, a avut
**662/662 probe reușite**, maxim **0,924s**, în timpul colectării și verificărilor
UI. Intervalele anterioare mai lente sunt păstrate în același fișier.

Windows CI intermediar a identificat un refuz 409 pentru un ordin virtual
valid, cu 419 teste trecute și unul eșuat. Reproducerea a arătat că `time.time()`
putea fi puțin în urma capturii UTC, iar screeningul o marca drept viitoare.
Service, dosarul tokenului și smoke check folosesc acum UTC. Nu s-au schimbat
formulele financiare, pragurile de risc sau acceptarea datelor viitoare.

## Acoperire și comparații

Export numai în citire al backupului consistent făcut înaintea actualizării:
[price-reference-summary.json](price-reference-summary.json). Cohorta UTC din
18 octombrie are 1.590 candidați și 1.589 prime evaluări. Candidatul fără prima
evaluare rămâne numărat separat, fără preț/semnal inventat.

| Orizont față de primul semnal | Prețuri utilizabile / prime evaluări | Restul |
| --- | --- | --- |
| 5m | 72 / 1.589 | 1.455 fără observație în interval; 62 cotații prea timpurii |
| 1h | 57 / 1.589 | 1.479 fără observație; 53 cotații prea timpurii |
| 24h | 0 / 1.589 | 1.587 lipsă; două încă în așteptare |

În politica 5/cohorta test, la 5m sunt 38/53 prețuri observate pentru selecții
și 15/297 pentru controlul fără suprapunere. Acoperirea redusă și inegală
împiedică o concluzie de superioritate. Variațiile de preț nu includ costuri,
nu dovedesc cumpărarea/vânzarea și nu sunt PnL. O lipsă nu înseamnă zero pierdere.
Pragurile +100%/−80% numără variația la orizontul observat, nu maxime/minime
neobservate. Nu s-a optimizat niciun prag pe aceste rezultate.

[daily-equivalence.json](daily-equivalence.json) confirmă egalitatea întregului
raport zilnic anterior după eliminarea singurului câmp nou, `price_references`,
pe aceeași bază și același ceas. [performance-equivalence.json](performance-equivalence.json)
confirmă egalitatea raportului general anterior după optimizarea extracției JSON.

Măsurători secvențiale pe backup: raportul general 9,37 → 5,27s, fără timpul
colectării; interogarea nouă de prețuri pentru acoperire 36,09 → 1,22s, cu
aceleași stări raportate ([coverage-latency.json](coverage-latency.json)).
Pe baza reală oprită, raportul general a durat 6,42s, iar interogarea prețurilor
1,14s. După repornire, HTTP-ul raportului general a durat 2,54s și acoperirea
4,42s în verificarea finală. Cache-ul sistemului, concurența și datele diferite
afectează aceste măsurători; nu reprezintă o garanție de latență.

## Starea funcțiilor

| Funcție | Stare și limită |
| --- | --- |
| Descoperire Solana, îmbogățire, filtre și scoruri explicate | Implementate; colectare și semnale reale observate. Feedurile nu acoperă toate lansările |
| Cotații utile și ferestre v2 pentru pool/repere | Implementate; regresii izolate și secvență reală verificată |
| Comparații de preț pe politică/cohortă, inclusiv respinse | Implementate și verificate pe istoricul real; fără afirmații de execuție/profit |
| Rapoarte, export JSON, concurență și UI mobil | Implementate; teste izolate și UI real verificat |
| Alertare în aplicație | Există și este observată în UI real; un receipt dovedește afișarea, nu citirea umană |
| Paper pool cu costuri înghețate | Implementat; outcome real de furnizor, simulare de execuție; acoperire incompletă |
| Jupiter | Adaptor existent, separat de pool; regula nouă a ferestrelor necesită aliniere prin propria politică și validare. Nu s-a modificat execuția lui aici |
| Știre recentă → token nou → alertă → outcome | Implementare pozitivă testată cu fixture-uri; **neverificată live integral** |
| Verificarea emitentului oficial | Necesită dovezi exacte și surse suficiente; un link de pool ori un nume nu confirmă emitentul |
| AI OpenAI/Ollama | Integrări existente; **neverificate cu modele reale în această etapă**. Corpusul structural nu dovedește precizia |
| Telegram | Integrare existentă; **livrare reală neverificată**, bot/chat/activare lipsă. Nu s-au trimis mesaje |
| Wallet intelligence și Base | Rămân parțiale; nu s-a extins/reauditat acoperirea aici. Base nu intră în clasamentul automat Solana |
| Găzduire publică/autentificare | Implementare existentă pentru un singur proprietar; fără deployment public validat în această etapă |
| Avantaj predictiv, profitabilitate și oportunități ratate globale | **Nedemonstrate**; univers parțial, lipsuri, eșantioane corelate și acoperire inegală |

## Blocaje și priorități

1. **Dovadă documentară recentă eligibilă și întregul lanț pentru același token.**
   Cele două verificări finale de 60s, contract direct și referință de piață,
   au ieșit cu cod 1, toate cele șapte criterii false și `errors=[]`:
   [story-direct.json](story-direct.json), [story-market.json](story-market.json).
   Nu au existat contracte eligibile în catalog. Nu s-au introdus articole vechi,
   fabricat receipts sau relaxat filtre ca să treacă verificarea.
2. **Alinierea ferestrei Jupiter**, cu politică nouă înghețată, compatibilitate
   istorică explicită și validare GET-only pe serviciu. Rezultatele vechi rămân.
3. **Colectare susținută și reducerea lipsurilor**, măsurate pe selecție și control,
   apoi un protocol prospectiv separat declarat înaintea datelor sale de test.
   Cutoff-ul original `2026-10-18T00:00:00Z` se păstrează. Politicile declarate
   ulterior rămân neatribuite; istoricul nu este relabelat după rezultate.
4. **Operare de durată:** creșterea bazei este încă o limită, aproximativ 2 GB.
   Arhivarea/compactarea trebuie să păstreze toate semnalele și outcome-urile.
   Gazda trebuie să rămână pornită; nu s-a livrat găzduire 24/7 publică aici.
5. **Servicii opționale:** OpenAI necesită cheie `PULSE_AI_API_KEY`, credit API
   și model disponibil; Ollama necesită serviciu și model instalat. Telegram
   necesită `TELEGRAM_BOT_TOKEN`, chat ID și activare explicită înaintea trimiterii.
   `JUPITER_API_KEY` poate fi cerută dacă accesul public este refuzat. Publicarea
   cere domeniu, HTTPS și autentificare configurate. Nicio cheie nouă ori
   subscripție nu a fost folosită/cumpărată; cost incremental de abonament $0.

Comenzile exacte de instalare, pornire, teste și verificare sunt în
[RESEARCH-V0.13.md](../RESEARCH-V0.13.md). Cheile și bazele de date nu intră în Git.
