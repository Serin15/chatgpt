# Dovezi v0.12 — 19 octombrie 2026

## Teste izolate, fără dovadă de profitabilitate

[`pytest.txt`](pytest.txt): **397 teste trecute**, un avertisment cunoscut de
depreciere Starlette/httpx, în 62,56s pe Linux. Ruff, verificarea sintactică a
celor trei fișiere JavaScript și `git diff --check` trec.
[`browser.json`](browser.json): **17 scenarii Chromium trecute**, cu furnizori
izolați, inclusiv dovezi de pool, relatări repetate, comparație pe politici/cohorte
și mobil. CI Windows/Ubuntu se raportează separat după terminarea rulării.

[`coverage-before.txt`](coverage-before.txt) reproduce pe codul v0.11 original
cele trei lipsuri: articol relevant dincolo de primele zece, colectare dependentă
de limita UI și titluri repetate afișate separat. Noul test de grupare păstrează
documentele cu adrese distincte separate. [`new-regressions-before.txt`](new-regressions-before.txt)
arată și validările lipsă găsite în implementarea intermediară a referințelor și
a protocolului. [`export-before.txt`](export-before.txt) reproduce suprascrierea
prin hard link într-o bază de test; [`export-after.txt`](export-after.txt) verifică
remedierea. Acestea sunt fixture-uri, nu defecte observate pe fonduri reale.

[`ai-offline.json`](ai-offline.json) validează numai corpusul: `model_run=false`.
Nu s-a măsurat precizia generării OpenAI/Ollama în această etapă.

## Date și servicii reale

[`sources-access.json`](sources-access.json): GET-urile reale către feedurile
Decrypt și Cointelegraph au răspuns HTTP 200 pe 19 octombrie. Nu s-a ocolit
proxy-ul și nu s-au schimbat certificatele TLS. Vechea observație de blocare din
raportul v0.11 rămâne istorică, nu descrie accesul actual.

[`historical-pool-reference.json`](historical-pool-reference.json): document real
Decrypt și răspuns DEX Screener actual, cu timestampuri/hashuri. Linkul identifică
pool-ul `G2UuRbmVDzDFP4qyoBJrSKBXSi7d6V4bPP9tHPs36y4b` și mintul
`nxPqZ4F7ux8Vph5NFu25rEP6Kx9Gr1U6Fmj36Rjpump`. Cotația este un alt token,
nu SOL/USDC/USDT: `qualifies_for_discovery=false`. Articolul vechi nu a fost
injectat în baza principală și nu constituie o oportunitate nouă verificată.

[`story-live-final.json`](story-live-final.json) și
[`market-story-final.json`](market-story-final.json): probe read-only de circa
71s pe instanța normală, pentru mențiuni directe și referințe de pool, cu zero
erori de transport la rularea finală. **Niciuna nu a completat cele șapte criterii.**
Nu exista un lookup documentar eligibil: toate criteriile noii rute rămân
neverificate live. Nu s-a trimis o confirmare sau alertă artificială pentru a
schimba rezultatul. Fereastra scurtă nu dovedește absența globală a oportunităților.

Primele probe întâlniseră un timeout la agregarea istoricului. În
[`report-equivalence.json`](report-equivalence.json), același backup consistent
cu 37.485 candidați, 81.683 semnale și 147.553 observații a produs rapoarte
identice înainte/după optimizarea citirii JSON: **22,987s → 8,206s**. S-a folosit
aceeași oră fixată și acces SQLite read-only. [`latency-before.json`](latency-before.json)
arată un GET real de 18,814s înainte; [`latency-after.json`](latency-after.json),
un GET HTTP 200 în 5,528s după. Aceste latențe sunt observații locale, nu un SLA.
Verificatorul citește acum agregatul o dată, separat de pollingul dovezilor.

[`preservation.json`](preservation.json): hashurile tuturor semnalelor/politicilor
anterioare, setarea motorului și registrele financiare comparate sunt identice.
Backupurile complete ale ambelor baze sunt în afara Git. Conturile păstrează
$500/$100 și zero ordine manuale. Noile politici se adaugă; cele vechi nu se
rescriu. Nu s-au schimbat formulele de fill, adaptorul Jupiter sau pragurile
configurate.

[`browser-live.json`](browser-live.json): Chromium pe aplicația reală, fără
interceptări, arată 50 candidați în pagină, comparația din 18 octombrie pe politica
5/test și politicile ulterioare/neatribuite, zero erori JS/API, fără overflow la
390 px, cinci workeri porniți și `live_execution=false`.

## Evaluare offline pe observații reale

[`holdout-2026-10-18.json`](holdout-2026-10-18.json) este o captură read-only,
anterioară restartului: 1.590 candidați, 1.587 prime evaluări, 53 selecții inițiale.
Politica 5 fusese declarată înaintea cutoff-ului din 18 octombrie. Rezultatele
paper se bazează pe observații reale, însă fill-urile sunt simulate.

La 5 minute, în modelul de pool sunt evaluate 28/53 selecții și 1/297 controale
fără suprapunere. Mediile nete evaluate sunt $4,95 și −$22,74; **25 și 296 de
rezultate rămân necunoscute**. În modelul Jupiter sunt evaluate 13/53 selecții și
0/297 controale; la 24h nu există rezultate evaluate. Compararea mediilor nu
rezolvă lipsurile sau diferențele dintre grupuri. Nu este dovada unui avantaj
predictiv, a unor tranzacții executabile sau a profitabilității. Nu s-au reglat
pragurile după acest eșantion și nu s-a mutat cutoff-ul vechi.

## Stare și blocaje, în ordinea priorității

| Funcție | Stare |
| --- | --- |
| Acces feeduri și colectare documente | Implementate, probe reale reușite; acoperire parțială, limite publice. |
| Grupare titluri pentru afișare | Implementată, fixture-uri/browser verificate; nu stabilește independența surselor. |
| Link DEX → pool → mint | Implementat, verificare reală de componentă și fixture-uri; cazul real avea cotație nesuportată. |
| Document recent → candidat nou → alertă → outcome | Implementat și testat cu fixture-uri; verificare pozitivă live incompletă, lipsește dovada eligibilă. |
| Raport per politică/test/control și export read-only | Implementate; evaluate pe observații reale și afișate în browser. |
| Avantaj statistic și randamente viitoare | Nedemonstrate; acoperire foarte inegală, lipsuri și eșantioane insuficiente. |
| Colectare permanentă și 1h/24h fără pauze | Parțială; necesită proces/gazdă pornită, surse disponibile și timp efectiv. |
| AI semantic, social growth, holder/deployer complet | Nu sunt finalizate/verificate de această etapă; vezi auditul și limitările existente. |
| Telegram și lansare publică | Necesită servicii/configurare distincte; nu s-au trimis mesaje sau făcut deployment. |

Fișierele principale și comenzile sunt explicate în
[RESEARCH-V0.12.md](../RESEARCH-V0.12.md). Urmează colectarea prospectivă susținută,
prima dovadă documentară eligibilă și un protocol nou declarat înaintea datelor
sale, păstrând istoricul și lipsurile existente.
