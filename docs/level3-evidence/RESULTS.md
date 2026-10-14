# Rezultate verificate — 14 octombrie 2026

Codul este modificat efectiv; acesta este registrul de dovezi, nu o estimare de profitabilitate.
Toate tranzacțiile reale sunt dezactivate. Bazele existente au fost păstrate; testele folosesc
baze izolate și nu plasează ordine în conturile manuale ale utilizatorului.

## Acceptanță live dintr-o bază nouă

Comandă executată, cu API-uri reale, Chromium real și fără injectare de tokenuri:

```bash
UV_CACHE_DIR=/workspace/.cache/uv uv run --with playwright python -m app.level3_verify \
  --data-dir /workspace/memescope-level3-fresh --duration 1200 \
  --browser /usr/bin/chromium --output /tmp/memescope-level3-fresh.json
```

[Rezultatul integral](live-fresh.json), capturat la `2026-10-14T17:38:10.381633+00:00`,
după 502s. Workerul a descoperit **205 tokenuri**, dintre care 36 încă fără prima evaluare.
Au existat 6 alerte: 5 de oportunitate și 1 de risc; toate 6 au confirmare de afișare în aplicație.
Nicio livrare Telegram nu este declarată verificată.

Exemplul ales de script pentru acceptanță este **MEMEOS / SOL**, contract
`5q5pEZZwhkuazS4rGa66LcNotdsnUE9KcJ7xQmXSpump`. Alegerea scriptului preferă cel mai recent
experiment evaluat, fără a sorta după randament.

| Criteriu | Dovadă reală |
| --- | --- |
| 1. Descoperire automată | Prima captură `17:29:53.029612 UTC`, din feedul public. |
| 2. Piață și securitate | Observațiile includ poolul ancorat, preț/lichiditate, RPC și GoPlus. |
| 3. Features și scoruri | Opt dimensiuni calculate; necunoscutele rămân null. |
| 4. Verdict explicat | `INVESTIGATE`, scor de clasament 72, la `17:31:03.796624 UTC`, cu riscuri și invalidări. |
| 5. Persistență | Semnalul 130 și observațiile sunt în SQLite; payloadurile sunt în JSON-ul atașat. |
| 6. Alertă și livrare | Confirmare de afișare `17:31:05.032601 UTC`, produsă de dashboard. Nu confirmă citirea umană. |
| 7. Observații ulterioare | Intrare modelată `17:32:51.081097 UTC`, ieșire `17:37:56.123469 UTC`; 305s durată efectivă. |
| 8. Dashboard | Browserul a afișat contractul, semnalele și secțiunea cu rezultatele păstrate. |

Scenariul de $50 a avut **−$11,97 net** după fee și impact estimate. Acesta este un fill
constant-product modelat pe observații reale, nu o tranzacție on-chain și nu o cotație Jupiter.
Captura nu dovedește afilierea sau calitatea proiectului.

La orizontul 5m, candidații selectați chiar la prima evaluare aveau 4 experimente: 2 evaluate
(1 pozitiv, 1 negativ), 1 intrare indisponibilă, 1 în așteptare. Suma netă a celor două evaluate:
**−$10,03**. În întregul subset cu primă evaluare: 169 experimente, 5 evaluate și 164 încă
incomplete/indisponibile; suma celor 5 evaluate este **−$13,30**. Lipsurile nu sunt completate
cu zero. Acoperirea redusă și eșantionul mic interzic concluzii despre un avantaj statistic.
Rezultatele de mai târziu pot diferi; fișierul păstrează exact momentul raportării.

[Proba cu istoric continuat](live-continued.json) și [proba după restart](live-after-restart.json)
păstrează și alte rezultate observate. Nu au fost șterse încercările nereușite pentru a obține PASS.
Prima variantă a verificatorului accepta greșit o stare terminală fără intrare; această regulă
este corectată: acum cere explicit `state=evaluated`. Artefactul acelei verificări slabe nu este
prezentat ca dovadă de acceptanță.

## AI real și erori reale

[Ollama automat](ollama-narratives.json): `pulse-qwen7b-audit:latest`, generări reale pentru
documente CoinDesk, cu citări verificate literal. La captură: 3 analize finalizate și 1 răspuns
respins pentru schemă/citări nevalide. Nu am relaxat validarea pentru a-l accepta.
Clasificările și traducerile sunt interpretări AI; corectitudinea semantică nu este demonstrată.
Nicio afiliere pozitivă de token nu a fost inventată. OpenAI live rămâne neverificat, fără cheie
și credit API în acest mediu.

`corpus-structure-only.json` este **validare offline a structurii**: 12 cazuri, 2 extrase observate
și 10 sintetice. `model_run=false`; nu reprezintă o măsurare nouă de precizie AI.

## Teste simulate, separat

```bash
uv run ruff check app tests
uv run pytest -q
node --check app/static/app.js
node --check app/static/advanced.js
node --check app/static/opportunities.js
```

[pytest.txt](pytest.txt): **244 passed**, un warning upstream Starlette/TestClient despre httpx.
[lint.txt](lint.txt): Ruff fără erori. Verificările Node au exit code 0.
Testele unitare/de integrare HTTP/RPC sunt fixture-uri explicite, nu acces live.

[Browser tests](browser-tests.json): 7 scripturi trecute cu Chromium real și furnizori simulați:
`browser_opportunities`, `browser_smoke`, `browser_regressions`, `browser_advanced`, `browser_ai`,
`browser_announcements`, `browser_slow_news`. Verifică inclusiv 390px, login/CSRF, știri lente,
dosare, ordine virtuale numai în fixture-uri, paginare/filtrare, receipt-uri și rezultate Level 3.

Regresii noi: descoperire automată până la outbox, prima captură imuabilă, pooluri duplicate,
token dispărut/respins păstrat, cooldown/restart, date lipsă fără profit zero, ferestre fără
look-ahead, model de cost înghețat, clasificare conservatoare, recuperare după timeout,
promovare plătită etichetată, avertizare de risc, quote fără schimbarea poolului, prioritate de
reobservare, clasament fără date expirate, Telegram cu destinatar verificat și fără retry ambiguu,
separarea cohortelor viitoare și protecție contra blocării clasificării narative.

## Instalare și găzduire

[HTTPS container](https-container.json): imagine construită cu dependențele fixate, pornită nonroot
UID 10001, filesystem read-only cu directoare temporare/data separate, TLS verificat cu o CA
locală generată, autentificare, cookie Secure/HttpOnly, CSRF și logout. Zero ordine.
Acesta nu este un deployment pe un domeniu public.

[Pornire pe baza existentă](production-startup.json): v0.7.0, cinci workeri supravegheați,
Research $500 / Scanner $100, zero ordine, migrare fără resetarea datelor. AI rămâne oprit în
instanța principală până este configurat de utilizator; proba Ollama a rulat izolat.
Instrucțiuni exacte de instalare/configurare/costuri: [README](../../README.md), [LEVEL3](../LEVEL3.md).

## Stare pe funcție și blocaje rămase

| Funcție | Stare | Limită / următorul pas |
| --- | --- | --- |
| Pipeline Solana discovery → alert → outcome | Implementat și verificat live | Acoperire parțială și polling, fără latență garantată. |
| RPC mint/freeze + GoPlus + lichiditate | Implementat și verificat live | Screening limitat, nu audit complet sau vânzare demonstrată. |
| Features temporale, scoruri, extensie | Implementat; live și teste izolate | Euristici fără avantaj predictiv demonstrat. |
| Alerte în aplicație / cooldown / dedup / risc | Implementat; afișare verificată live, cazurile-limită prin teste | Receipt nu înseamnă citire umană. |
| Scenarii forward după costuri | Implementat și verificat live | Constant-product estimat, incompletele rămân în raport. |
| Evaluare / baseline / holdout viitor | Implementat; rapoarte live, separare testată izolat | Holdout suficient și comparație echilibrată încă nedemonstrate. |
| Știri și clasificare Ollama | Implementat și generare verificată live | Erori reale respinse; acuratețe semantică nevalidată. |
| OpenAI | Implementat, neverificat live | Cheie proprie, model disponibil, credit API. |
| Asociere narativă cu tokenul | Implementat conservator; teste de evidență | Nu există probă de afiliere pentru tokenul demo; rămâne neconfirmată. |
| Social growth / comunități / holder growth | Parțial: câmpuri explicite necunoscute | Lipsesc surse timestamped autorizate și acoperire la nivel de proprietar. |
| Activitate suspectă / distribuție | Euristici și eșantionare implementate | Acoperirea RPC și clasificarea globală nu sunt demonstrate; vezi proba on-chain separată. |
| Wallet intelligence | Parțial | Citire/refresh Solana implementate; fără wallet real configurat, scor/calitate/istoric complet nevalidate. |
| Base | Parțial | Adaptoare de discovery/citire existente; exclus din rankingul automat până la validare suficientă. |
| Telegram automat | Implementat, testat cu mock, neverificat live | Lipsesc bot token și chat ID; nu s-au trimis mesaje reale. |
| Jupiter | Fluxul manual existent; Level 3 nu îl folosește | Cheie API și verificare reală a rutelor/costurilor înainte de integrare în evaluarea automată. |
| Dashboard și mobile | Implementat; browser real cu date live și fixture-uri | Istoricul este păstrat, cu limită de 1000 observații în graficul unui dosar. |
| Windows launcher | Logică existentă păstrată; verificare CI separată | Starea CI și testul arhivei sunt în artefactele dedicate când sunt disponibile. |
| Hosted/auth | Test local HTTPS real trecut | Domeniu/DNS/ACME public încă neconfigurate. |

Prioritatea 1: surse stabile și acoperire forward echilibrată inclusiv pentru un control stabilit
în avans; ieșiri reale cotabile pentru simulare, costuri și eșecuri. Prioritatea 2: perioadă test
prospectivă suficientă, cu mostre/intervale de incertitudine și politici înghețate. Prioritatea 3:
holders/social/walleturi autorizate și Base. Nu avem dovezi că motorul identifică viitoare 10x/100x.
