# Verificare v0.13 — observații, rapoarte și concurență

Datele reale, fixture-urile și simulările financiare sunt separate mai jos.
Această etapă nu declară aplicația completă sau profitabilă.

## Cod și teste izolate

Implementarea finală: `c1cfb28d5369c76d2c13458e22507e11856cb4c8`.
Commiturile ulterioare de documentație/dovezi nu schimbă aplicația sau testele.

- `.venv/bin/pytest -q`: **416 passed**, un avertisment de deprecare din
  Starlette/httpx; [ieșire integrală](pytest.txt). Nu s-au apelat servicii externe.
- `.venv/bin/ruff check app tests`, `git diff --check` și `node --check` pentru
  cele trei fișiere JavaScript: trecute.
- Audit Chromium: **19/19** scenarii cu furnizori izolați,
  [browser.json](browser.json). Include separarea prețurilor de încercări,
  tabelele noi și lățimea de 390 px. Nu constituie dovadă de piață reală.
- Corpus AI: 12 cazuri validate structural; `model_run=false`. Nu s-a măsurat
  precizia unui model și nu s-a apelat un model real în această etapă.

CI oficial [39245535279](https://github.com/Serin15/chatgpt/actions/runs/39245535279)
a trecut pentru commitul final al aplicației. Logurile oficiale descărcate după
încheiere confirmă **416 passed** pe Windows (779,91s) și Ubuntu (68,74s),
**19/19** scenarii Chromium pe Linux și pornirea launcherului nativ Windows
dintr-un director cu spații. Metadatele și liniile extrase sunt în [ci.json](ci.json).

Regresiile au fost reproduse înainte de remediere:

| Problemă | Dovadă înainte | Rezultatul corecției |
| --- | --- | --- |
| Încercările erau afișate ca observații utile; lipsea comparația prețurilor | [9 teste eșuate](price-before.txt) | Prețuri valide și stări necunoscute separate; include respinse și lichiditate zero |
| Cotația preluată înaintea ferestrei consuma observația | [2 teste eșuate](window-before.txt) | Politică nouă v2; jobul așteaptă cotația din interval; un eșec real rămâne eșec |
| Verificatorul confunda pool-ul cu contractul direct și accepta receipt viitor | [2 teste eșuate](verifier-before.txt) | Tip de dovadă explicit și receipt în intervalul real |
| Refreshurile simultane recalculau repetat raportul mare | [2 teste eșuate](concurrency-before.txt) | Un calcul în desfășurare, copii independente, eroare transmisă și recuperare la cererea următoare |

Nu există cache de rapoarte istorice: o cerere nouă, după terminarea celei
anterioare, citește date noi. Cererile simultane împart numai calculul curent.
Testele includ succes, eroare, mutarea rezultatului de către apelant și o nouă
cerere după eroare. Niciun test nu modifică istoricul real al utilizatorului.

## Verificări cu date reale

- [live-state.json](live-state.json): v0.13.0, cele cinci servicii în execuție,
  `live_execution=false`, cele 13 topicuri de știri în starea `ok`. Portofoliile
  manuale Research/Scanner au rămas la $500/$100, cu zero ordine.
- [browser-live.json](browser-live.json): browser normal, fără interceptări,
  afișează raportul stocat din 18 octombrie, cele trei orizonturi și șase rânduri
  de comparație politică/cohortă; zero erori JS/API, fără overflow la 390 px.
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
  `PRAGMA quick_check` pe baza reală a răspuns `ok`.

Prima verificare a interfeței a expus timeout-uri și acumularea cererilor grele.
Instanțele intermediare ale acestei sarcini au fost oprite și repornite pe
aceleași date, cu backup consistent anterior. Unele cereri de citire au depășit
oprirea normală și au necesitat oprirea procesului intermediar. Nu s-au înlocuit
baze/WAL-uri și nu s-au resetat conturi. Verificările de integritate și
păstrare de mai sus sunt ulterioare acestor opriri.

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
