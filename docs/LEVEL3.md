# MemeScope Level 3 — implementare și limite

v0.9.0, 15 octombrie 2026. [Cotații rutate](ROUTED-PAPER.md) · [Colectare prospectivă](COLLECTION.md). Obiectiv: un flux automat, explicabil și măsurabil, cu tranzacții reale
dezactivate. Nu atribuim un procent arbitrar de „precizie” sau finalizare.

## Arhitectură și persistență

`Service.run_intelligence` pornește `Opportunities.run` în workerul supravegheat existent. Ciclul
rotește paginile `new_pools` Solana, citește latest profiles și feedul separat de boosts plătite,
apoi îmbogățește candidații fără intervenție manuală. Baza SQLite păstrează configurația,
politicile, lease-ul workerului, prima captură, observațiile, semnalele, alertele și rezultatele.
Restarturile nu șterg candidați, alerte sau rezultate nereușite.

Deduplicarea candidatului folosește `(chain,contract)`, păstrând și poolurile brute. Poolul inițial
rămâne ancora pentru observații, pentru a nu selecta ulterior perechea cu performanță mai bună.
Tokenurile quote/infrastructură cunoscute sunt păstrate cu excluderea explicită. Celelalte adrese
valide sunt înregistrate înaintea filtrelor, inclusiv tokenuri care nu sunt memecoinuri. Nu avem
clasificare semantică verificată a tuturor proiectelor.

Datele din versiunile vechi fără prima captură sunt marcate `imported_from_cache`; prețul inițial
rămâne necunoscut. `first_seen_at`, crearea raportată a poolului și lansarea tokenului sunt câmpuri
diferite. Ultima rămâne necunoscută când lipsește o dovadă. Feedurile sunt parțiale și părtinitoare;
boosturile sunt expunere plătită, nu cerere organică demonstrată.

Ciclul țintește 60s între începuturi. Bugetele implicite sunt 60 de observații și 8 verificări de
securitate/ciclu. Jumătate din capacitate protejează în mod egal termenele alertelor și controlului,
cu împrumutarea locurilor nefolosite. O treime îmbogățește capturi noi; restul urmărește alte
termene și verificări periodice. Candidații respinși sunt reobservați mai rar; cei indisponibili
au backoff limitat. Dashboardul arată coada și întârzierile. Un timeout nu oprește API-ul web.
Nu există capacitate sau latență garantată pe RPC/API-uri publice.

## Dovezi, scoruri și filtre

`opportunity_sources.py` citește aceeași pereche prin DEX Screener/GeckoTerminal. Numărul raportat
de buyers/sellers este separat de numărul tranzacțiilor și de identitățile dintr-un eșantion RPC.
Scorurile folosesc numai observații recepționate înaintea semnalului. Comparațiile 5m/15m/1h cer
un punct anterior suficient de vechi; două ferestre mobile de cinci minute comparate nu se
suprapun. Datele care lipsesc nu devin creștere zero.

| Dimensiune | Calcul și limită |
| --- | --- |
| Security risk | Privilegii RPC, program/extensii SPL acceptate și raport GoPlus. 100 pentru restricții critice cunoscute, 0 pentru trecerea verificărilor limitate, null pentru necunoscut. 0 nu înseamnă lipsa tuturor riscurilor. |
| Exit liquidity | Raportare la pragul de lichiditate și modelul de cost/impact pentru suma configurată; fără garantarea unei rute de ieșire. |
| Participation quality | Contoare de tranzacții, buyers raportate și, opțional, evenimente din eșantion. Plafoane diferite după calitatea sursei; fără dovada volumului organic. |
| Early momentum | Variație 5m, vechimea poolului și extensia față de prima captură. Un pool nou poate aparține unui token vechi. |
| Wallet intelligence | Evenimente de sold din walleturi urmărite. Scorul rămâne null fără o metodă validată de calitate/cost basis. |
| Narrative/social evidence | Mențiuni exacte de contract și chain în documente citite; gazde de publicare și recurență. Gazdele distincte nu demonstrează independență editorială. |
| Entry attractiveness | Combinație transparentă momentum/lichiditate/participare; extensia excesivă anulează scorul de intrare. |
| Data reliability | Disponibilitatea surselor și istoricul observat, fără probabilități calibrate. Ora recepției nu garantează ora ultimului trade în upstream. |

`REJECT`: restricții critice, lichiditate insuficientă sau scădere USD mare a lichidității.
`MONITOR`: verificări incomplete, pool prea vechi/necunoscut, activitate insuficientă sau extensie.
`INVESTIGATE`: filtrele trec, pool recent, activitate și costuri în limite, fără extensie excesivă.
`CONSIDER`: și istoric ≥10m, comparație 5m ne-supravapusă cu accelerare de volum, lichiditate
păstrată, participare suficientă, date suficiente și fără flaguri de suspiciune active.
Niciun verdict nu reprezintă un ordin sau o probabilitate de câștig.

Euristicile disting observații de suspiciuni: dezechilibru de tranzacții, turnover foarte mare,
cantități repetitive, concentrare în eșantion, mai multe walleturi în același slot, concentrare de
token accounts și scădere USD a lichidității. Ultima poate proveni și din reevaluarea rezervelor;
nu o numim retragere LP confirmată. Un singur flag nu declară manipulare. Nu avem detecție
exhaustivă de bundle-uri, wash trading, proprietari beneficiari, echipe/deployer sau promovare
coordonată. Eșantionarea RPC este opțională și dezactivată implicit.

## Narațiuni, AI și walleturi

Poveștile din sursele permise sunt citite și clasificate opțional de AI în categorii, cu citări
literale. Modelul nu are voie să transforme un nume comun în afiliere. Mențiunile de contract
nu confirmă emiterea, endorsementul sau adevărul afirmațiilor. Verificarea semantică automată a
relațiilor pozitive rămâne blocată de gate-ul conservator v2 existent.

OpenAI și Ollama folosesc integrarea reală existentă; limita zilnică include încercările de
generare eșuate. Clasificarea automată este separată de dosarele manuale și nu blochează ciclul
de piață. Erorile de citire/model sunt afișate și au backoff; nu se înlocuiesc cu text demonstrativ.
AI este oprit implicit. Fără metrici sociale timestamped autorizate, creșterea socială și
comunitățile rămân necunoscute. RSS nu înlocuiește o măsurare X/Telegram/Discord.

Cel mult un wallet Solana configurat este actualizat în fundal/ciclu, prin rotație. Transferurile
și swap-candidates sunt etichetate separat. Nu este implementat un scor validat de „smart money”,
PnL istoric al walletului sau un detector complet de tranzacții ale deployerului. Base are adaptoare
de citire și teste proprii, dar nu este promovat în pipeline-ul automat Solana.

## Alerte și urmărire

Alertele conțin contract/chain, nume, orele descoperirii/datelor, preț/lichiditate, schimbările
măsurate, flaguri, scoruri, explicații, extensie, costuri orientative, invalidări și linkuri.
Semnalul și outboxul sunt salvate atomic. Cooldown implicit 1h, cu excepția upgrade-ului la
CONSIDER și a unei avertizări critice de risc. Schimbarea configurației nu produce automat
aceeași alertă din nou. Istoricul API este paginat; dashboardul permite încărcarea alertelor vechi.

Confirmarea în aplicație se face după randarea alertei pe pagina activă; nu înseamnă că utilizatorul
a citit-o. Starea „citită” se marchează explicit. Telegram cere chei și activare; outboxul trimite
cel mult un mesaj/ciclu, validează message ID și destinatarul din răspuns. O trimitere cu rezultat
ambiguu sau întreruptă nu este repetată automat. Nu putem promite exact-once printr-o rețea externă.

Fiecare primă evaluare și fiecare semnal nou are scenarii independente la orizonturile configurate.
Intrarea folosește **prima încercare observată** după minimum 3s, în fereastra implicită de 180s;
nu cel mai bun preț. Ieșirea folosește prima încercare după intrare + orizont, în încă 180s.
Durata efectivă poate fi mai mare decât orizontul și este raportată. Un răspuns incomplet sau un
filtru respins nu este o ieșire reușită. Observațiile lipsă, dispariția unui pool și imposibilitatea
confirmată de vânzare sunt stări diferite.

Fee-ul presupus este 0,3%/sens, costul rețelei $0,01/sens, impactul este aproximat printr-un pool
constant-product echilibrat; nu este un swap Jupiter sau o verificare on-chain a vânzării.
v0.9 adaugă un scenariu independent cu cotații Jupiter la intrare și la ieșirea ulterioară,
fără modificarea modelului de pool sau a rezultatelor lui. Conversia USDC/USD folosește L1
observat Kraken/Coinbase, iar fee-urile de conversie și rețea rămân presupuneri înghețate.
Prețuri și lichidități reale, execuție simulată: `execution_verified=false`. Politica păstrează
pragurile, costurile, ferestrele și hashurile codului. Dacă implementarea costurilor se schimbă,
un rezultat vechi neevaluat nu este recalculat tacit cu noua formulă.

MFE/MAE sunt extreme numai în observațiile disponibile până la orizont. Raportul include numărul
punctelor și golurile; extrema reale dintre ele rămân necunoscute. Pozițiile independente de $50
nu reprezintă un cont cu capital limitat. Jurnalul manual existent rămâne separat.

## Evaluare și limite statistice

Rapoartele arată universul descoperit, candidații fără evaluare, filtrele, deciziile inițiale,
alertele, scenariile evaluate, indisponibile și în așteptare. Rezultatele selectate la prima
evaluare sunt separate de alertele ulterioare; o decizie viitoare nu rescrie cohorta inițială.
Baseline-ul de 20% folosește hashul contractului și nu randamentul ulterior. Sunt raportate și
politicile distincte, pentru a nu ascunde schimbările de reguli.

`test_from` trebuie declarat în viitor. Ferestrele de development care ating perioada test sunt
eliminate din acea comparație. Implicit datele sunt **unassigned**, nu un holdout inventat.
Diagnosticele pe semnale sunt exploratorii; nu optimizăm praguri și nu pretindem validare pe
același eșantion. Intervalele Wilson presupun observații independente; tokenurile corelate pot
încălca această ipoteză.

Colectarea prioritizată a alertelor produce acoperire inegală față de tokenurile respinse.
Multe experimente din universul complet pot rămâne fără observație de intrare/ieșire. Păstrarea
lor previne ștergerea eșecurilor, dar nu elimină singură biasul de lipsă a datelor. Comparațiile
actuale nu demonstrează superioritate statistică. Oportunitățile ratate global și tokenurile
confirmat nevandabile rămân null; un univers parțial nu permite calculul lor onest.

## Verificare și dovezi

Comenzile de instalare și pornire sunt în README. Dovezile exacte, cu timestamp-uri și contracte
publice, sunt în [level3-evidence](level3-evidence/). Bazele live izolate nu sunt introduse în Git.
Niciun ordin real sau ordin în conturile manuale ale utilizatorului nu a fost executat.

Testele unitare/de integrare folosesc explicit fixture-uri HTTP/RPC. Testele browser folosesc
Chromium real cu furnizori simulați. Scriptul `app.level3_verify` folosește workerul normal și
servicii publice reale, fără injectarea unui token, schimbarea pragurilor sau date istorice
completate artificial. Cere un rezultat paper efectiv evaluat, nu simpla stare „date lipsă”.

Starea exactă a acceptanței și a modelului local este consemnată în `RESULTS.md` și fișierele JSON
din directorul de dovezi. O demonstrație de conectivitate nu demonstrează profitabilitate.

## Servicii, chei și costuri

| Serviciu | Cerință / cost operațional |
| --- | --- |
| DEX Screener, GeckoTerminal | Endpointuri publice folosite fără cheie/abonament nou. Limite, indisponibilități și termeni ai furnizorului; fără SLA. Univers incomplet. |
| Solana RPC | Endpoint public implicit; opțional URL HTTPS propriu. Default până la 8 verificări mint/ciclu, în plus wallet/sample dacă sunt activate. Un abonament dedicat poate fi necesar la volum mai mare; tarif ales de utilizator. |
| GoPlus | Raport terț; `GOPLUS_ACCESS_TOKEN` dacă furnizorul îl cere. Lipsa raportului nu este tratată ca securitate validată. |
| Știri | RSS și citirea documentelor permise, fără serviciu plătit nou. Nu este un API Anthropic LLM sau Circle financiar. |
| Ollama | Serviciu și model instalat local, fără taxă API per cerere. Consumă RAM/CPU/GPU, energie sau timpul instanței cloud. Modelul ales și calitatea lui contează. |
| OpenAI | Opțional, cheie proprie și credit API separat de ChatGPT. Cost = input tokens × tarif input + output tokens × tarif output, la tarifele modelului ales. Implicit maximum 20 cereri/zi când AI este configurat; limita nu garantează un plafon monetar. Fără cheie nu pretindem verificare live. |
| Telegram | Bot token și chat ID proprii, plus activare explicită. Fără abonament nou introdus de cod; condițiile și limitele Telegram se aplică. Livrare live neverificată fără aceste date. |
| Jupiter | Cotații automate paper separate, implicit maximum 4 încercări/ciclu, și modul manual opțional. Acces fără cheie observat în acest mediu, fără garanție; 401/403 cere `JUPITER_API_KEY_FILE` sau binding securizat. FX necesită acces la `api.kraken.com`; nu se presupune paritate USD. |
| Social / holders / istoric complet | Furnizori autorizați, chei și eventual planuri plătite încă neconfigurate. Nu sunt simulate. |
| Găzduire | PC local sau instanță proprie, stocare și, dacă public, domeniu/HTTPS. Niciun abonament cloud nu este cumpărat automat. |

La 60s, un buget plin de 60 observații/ciclu înseamnă teoretic până la 86.400 observații/zi;
cererile sunt grupate, nu un HTTP call per observație. Bugetul nu garantează această capacitate.
Păstrarea întregului univers crește baza și backupurile; dimensionează discul și verifică coada.
Nu ștergem automat tokenurile pierzătoare pentru a reduce spațiul sau îmbunătăți statisticile.

## Fișiere și responsabilități

- `app/opportunities.py`: orchestrare, lease, coadă, persistență, semnale și outbox.
- `app/opportunity_sources.py`: cotații pe poolul ancorat, participare eșantionată, walleturi.
- `app/opportunity_rules.py`: configurație, features, costuri și decizii explicabile.
- `app/opportunity_outcomes.py`: observații viitoare, scenarii înghețate, cohorte și rapoarte.
- `app/opportunity_sampling.py`: înscriere prospectivă, grup fix, termene, repere de preț și acoperire.
- `app/opportunity_routes.py`, `app/jupiter.py`: cotații forward, costuri înghețate, FX și eșecuri fără fallback la pool.
- `app/narratives.py`, `app/ai_research.py`: surse/contracte, clasificare cu citări și erori reale.
- `app/discovery.py`: prima captură păstrată, surse suplimentare etichetate.
- `app/analysis.py`, `app/models.py`: filtre separate și buyers/sellers raportate opționale.
- `app/service.py`, `app/main.py`: workerul existent și API-uri autentificate/CSRF existente.
- `app/static/opportunities.js`, `app.js`, `advanced.js`, `index.html`, `style.css`: dashboard,
  paginare, detalii, alerte și afișare rezilientă.
- `app/level3_verify.py`, `app/collection_verify.py`, `app/routes_verify.py`, `tests/test_opportunities.py`,
  `tests/test_observation_sampling.py`, `tests/browser_opportunities.py`:
  verificare live separată de testele simulate; fixture-ul și regresiile vechi sunt păstrate.
- `.env.example`, `pyproject.toml`, `uv.lock`, workflow CI și documentație: configurare/versionare.

## Următorul milestone recomandat

**Un experiment prospectiv cu acoperire și costuri mai bine măsurate**, înainte de Base sau noi
integrări. Colectarea echilibrată și controlul prestabilit sunt implementate în v0.8; acoperirea
trebuie măsurată în continuare. Cotațiile entry/exit sunt adăugate în v0.9, cu limitele din
documentația lor. Prioritatea 1: RPC stabil și dimensionarea capacității. Prioritatea 2:
holdout declarat în avans, mai multe săptămâni de observații, costuri
și eșecuri incluse, estimarea incertitudinii fără selecția retrospectivă a pragurilor. Prioritatea 3:
metrici de holders/walleturi și surse sociale autorizate, apoi validare Base pe aceleași criterii.
Niciun calendar sau eșantion mic nu garantează un avantaj. Nu există dovadă pentru 10x/100x.
