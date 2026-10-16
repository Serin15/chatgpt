# Rezultatele etapei v0.11.0

Codul final al etapei este `cc1b9940635c12d0b18dd46ffe094b9de970bbb0`.
Commiturile ulterioare de dovezi/documentație nu schimbă aplicația sau testele.

## Teste cu fixture-uri

- [`before.txt`](before.txt): două lipsuri reproduse înainte de implementare.
- [`health-before.json`](health-before.json): 14 scenarii trecute și unul eșuat
  înaintea corecției detaliilor de sănătate ale feedurilor.
- [`pytest.txt`](pytest.txt): **364 teste trecute**, un avertisment cunoscut de
  depreciere Starlette/httpx, în **84,96s**, pe codul final.
- [`targeted.txt`](targeted.txt): **49 teste trecute** pentru surse, documente,
  descoperire și verificator. Adresele/documentele/cotațiile sunt fixture-uri.
- [`browser.json`](browser.json): **15 scenarii Chromium trecute**, inclusiv
  detaliile erorilor de știri, afișarea fără AI, izolarea erorilor, navigarea,
  cursele între răspunsuri, exportul și mobilul.
- [`ai-offline.json`](ai-offline.json): validarea offline a corpusului existent;
  `model_run=false`. Nu este o generare AI sau o dovadă a calității unui model.

Comenzi executate:

```bash
UV_CACHE_DIR=/workspace/.cache/uv uv sync --frozen
.venv/bin/ruff check app tests
UV_CACHE_DIR=/workspace/.cache/uv uv run --frozen pytest -q
node --check app/static/app.js
node --check app/static/advanced.js
node --check app/static/opportunities.js
UV_CACHE_DIR=/workspace/.cache/uv uv run --with playwright python tests/browser_audit.py
.venv/bin/python -m app.ai_evaluation --output /tmp/memescope-story-ai-offline.json
```

Prima rulare CI pe `032ef0793cfea676889a8ee44d668c48a316d44e` a trecut 363 teste
pe Windows și Ubuntu, inclusiv launcherul Windows nativ; ulterior s-a adăugat o
regresie pentru prioritatea titlurilor memecoin și s-au corectat detaliile de
sănătate în UI. Rularea finală este
[38899739744](https://github.com/Serin15/chatgpt/actions/runs/38899739744).
Starea ei finală și numărul efectiv de teste sunt în [`ci.json`](ci.json).

## Verificări pe date și servicii reale

[`feeds-live.json`](feeds-live.json) păstrează rezultatul real al noilor feeduri
accesibile: **10 titluri** pentru interogarea memecoinurilor și **un articol**
din RSS Solana în fereastra acceptată de două zile. Acesta din urmă era mai vechi
de 24h; nu a fost prezentat ca dovadă narativă proaspătă.

[`migration.json`](migration.json): migrare pe o copie consistentă cu **2.998
candidați**, fără worker și fără cereri externe. Toate cele **49 de tabele
existente** au păstrat numărul de rânduri și hashul conținutului. Noua tabelă este
`story_pool_lookups`. Șase cereri API reprezentative au răspuns HTTP 200.
Backupurile SQLite consistente rămân în afara Git, în
`/workspace/backups/memescope-story-before/`; copia verificată este separată de
baza activă.

[`running.json`](running.json): versiunea nouă rulează pe aceeași bază activă,
cu **3.242 candidați**, 13.333 observații și 218 alerte la captură, nu toate produse
de această versiune. Setările sunt identice celor de dinaintea restartului.
Conturile Research/Scanner rămân **$500/$100 și zero ordine**. Cei cinci workeri
sunt porniți. Politica 5 păstrează cutoff-ul **18 octombrie 2026, 00:00 UTC
(03:00 în România)**; semnalele/politicile vechi nu sunt rescrise.

[`browser-live.json`](browser-live.json): browser Chromium pe instanța reală,
fără interceptări/mock-uri. Panoul arată știri memecoin înaintea celor generale,
erorile `news_decrypt`/`news_cointelegraph` sunt vizibile în detalii, nu apar
erori JavaScript și nu există overflow orizontal la 390 px.
[Captură desktop](../screenshots/memescope-story-discovery.png),
[mobil](../screenshots/memescope-story-mobile.png).

[`package.json`](package.json): arhiva codului final a fost descărcată efectiv,
verificată prin CRC și comparată cu toate cele 270 de fișiere Git. A pornit din
alt director, într-o cale cu spații, `#` și diacritice, cu DATA_DIR nou izolat,
identitatea corectă, cinci workeri și API-urile noi HTTP 200. Instanța de probă
a fost oprită explicit și închiderea portului verificată; instanța principală
rămâne pornită. Pachetul nu schimbă versiunile dependențelor.

## Ce NU a fost demonstrat live

[`live.json`](live.json) este o probă de **90s** exclusiv prin GET pe motorul
normal. [`live-final.json`](live-final.json) este o captură ulterioară pe codul
final. **Nu s-a observat o știre recentă cu adresă Solana exactă.** La captura
bazei erau 52 de documente indexate, zero mențiuni eligibile de contract și zero
căutări documentare de pool. Numărul total de candidați nu demonstrează noua
rută de descoperire din știri.

Verificatorul a ieșit corect cu codul **1** și toate cele șapte criterii ale
noii rute au rămas **neverificate**, fără erori de transport ale verificatorului.
Nu am injectat un articol/token, nu am relaxat filtrele și nu am produs o
confirmare de livrare pentru a forța succesul. Fluxul pozitiv complet al noii
legături este verificat **doar cu fixture-uri**, de la document la alertă;
verificarea outcome-urilor păstrează mecanismul existent și regresiile lui.

[`network.json`](network.json): Decrypt și Cointelegraph sunt refuzate de
proxy-ul cloud; diagnosticul Decrypt confirmă **ProxyError 403 Forbidden**.
Adaptoarele lor au fost testate cu fixture-uri și **nu sunt declarate funcționale
live**. Configurația pregătită adaugă doar `decrypt.co` și `cointelegraph.com`
la domeniile deja salvate, păstrând celelalte reguli și secretele existente.
Salvarea draftului nu aplică și nu publică politica: sunt necesare revizuirea,
salvarea și publicarea ei din setările mediului. Nici accesul deblocat nu
garantează că următorul articol va conține o adresă sau va produce o alertă.

Titlurile repetate/sindicalizate între publicații pot rămâne în feed. Domeniile
diferite nu sunt considerate dovada independenței editoriale, iar titlurile
necitite nu primesc o asociere de contract sau un bonus de scor doar după nume.

## Starea funcțiilor și următorii pași

| Funcție | Stare verificabilă |
| --- | --- |
| Interogare memecoin și feed RSS Solana | Implementate și verificate pe surse reale. |
| Decrypt/Cointelegraph, feed și citire document | Implementate; fixture-uri trecute, acces live blocat de proxy. |
| Link Pump.fun explicit, chain, contexte contradictorii | Implementate și verificate cu fixture-uri. Nu s-a citit Pump.fun prin HTTP. |
| Document → pool → candidat → semnal/alertă | Implementat și verificat cu fixture-uri; asocierea pozitivă reală rămâne neverificată. |
| Retry persistent, refuz date invalide/vechi, păstrare adrese fără pool | Implementate și verificate cu fixture-uri, inclusiv restart și erori parțiale. |
| Știri, prioritizare și starea surselor în dashboard | Verificate în browser pe date reale și în regresii. |
| Outcomes și execuție paper | Mecanismul financiar existent este păstrat; regresiile trec. Outcome-ul noii rute documentare nu este verificat live. |
| Holdout și avantaj predictiv | Cutoff păstrat; nu există încă o evaluare suficientă pe date noi sau profitabilitate demonstrată. |

Fișiere principale: `app/story_discovery.py` (coadă și legătura cu pool-urile),
`story_verify.py` (probă read-only), `news.py` (surse, timeouturi și interogare),
`announcements.py` (linkuri de mint și prioritizarea documentelor),
`story_evidence.py` (proveniență și feed), `opportunities.py` (conectare și
fingerprint), `main.py` (stări/API), `app/static/*` (interfață), cele trei fișiere
noi de teste, `test_story_evidence.py` și `browser_audit.py` (regresii). Versiunea
este actualizată în `app/__init__.py`, `pyproject.toml` și `uv.lock`.

Priorități: **1)** deblocarea surselor și prima asociere reală verificabilă,
**2)** colector pornit suficient timp pentru alertă și outcome pe aceeași dovadă,
**3)** evaluare prospectivă cu eșantion, costuri și lipsuri raportate. Holderi,
deployer, AI semantic, deduplicare editorială și produs public multi-user rămân
etape separate. Nu s-a executat nicio tranzacție reală și nu s-a cumpărat niciun
serviciu ori abonament.
