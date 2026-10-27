# Dovezi audit v0.21.1

Cod verificat: `9ebcf30e7d96300bb14610448346ea0546e0c38b`, pe baza `64636cffdeb6b8d95853580bd8599d32c053a055`. Fișierele de documentație/dovezi se adaugă ulterior; `source-manifest.json` identifică exact sursele, testele, lockul și configurația CI. Datele SQLite, cheile și configurația privată nu sunt incluse.

## Teste controlate, fără furnizori reali

- `pytest-before.txt`: 621 trecute; `pytest-final.txt`: 642 trecute. Include SQLite și subprocessuri reale pe baze temporare, dar răspunsuri de furnizor simulate.
- `browser-before.txt`: 44 scenarii; `browser-final.txt`: 47. Aceste scenarii folosesc furnizori izolați/interceptări; nu sunt dovezi de piață live.
- Fișierele `*-before.txt` pentru regresii păstrează eșecurile reproduse înaintea corecțiilor; fișierele `*-after.txt`/`*-final.txt` păstrează verificările după.
- `ai-evaluation.txt`: validare offline a corpusului, fără rulare de model și fără metrică de precizie.
- `ci-final.json`, `ci-excerpts.txt`: [CI 40455732978](https://github.com/Serin15/chatgpt/actions/runs/40455732978), commitul sursă indicat mai sus; succes pe Linux și Windows. 642 teste pe fiecare OS, 47 scenarii Chromium pe Linux, launcher nativ Windows și backup/restaurare verificate pe baze temporare. Nu reprezintă execuție pe PC-ul utilizatorului sau restore al bazei mari.

## Verificări pe instanța și istoricul reale

- `api-before.json`, `extra-api*.json`, `ranking-search.json`: status și latențe reale, inclusiv timeouturi/503. `extra-api-long.json` arată repetarea routes în 88,646 s și daily în 4,838 s înaintea servirii Jupiter din cache.
- `backup-before.json` / `backup-after.json`: HTTP 500 → 507 explicativ pe același disc insuficient. Nu s-a produs backupul integral; nu există dovadă de restore a bazei mari.
- `export-before.json` / `export-after.json`: export Scanner fără ordine, 14,264 → 0,777 s. Măsurători locale în condiții de sarcină variabilă.
- `routes-final-timing.json` și `routes-final.json`: la rece 503 explicativ rapid, apoi 200 din snapshot în 0,0124 s, calcul de 66,297 s în proces read-only. `routes-profile.txt` explică costul citirii istoricului. Metadata cache face vechimea explicită.
- `integrity.json`: ambele baze existente au trecut `quick_check(1)`.
- `pilot-equivalence.json`: comparație între implementarea veche și cea optimizată pe **aceeași tranzacție SQLite și aceeași oră**; întregul raport identic. `frozen-sources.json` și `preservation-*.json`: regulile, politicile, declarațiile, configurația și conturile manuale originale păstrate; istoricul continuă să crească.
- `live-collection.json`: 163 s, 6 capturi distincte alerte / 7 control, toate cele șase criterii trecute. Observațiile sunt capturate și primite în intervalul măsurării și ferestrele promise.
- `pipeline-candidate.json`, `pipeline-alert.json`, `pipeline-routed-proof.json`: candidat real 197521, semnal 465359, alertă 12369, cotații buy/sell Jupiter și rezultat ulterior legate. Selecție pentru înregistrare nouă, alertă necritică afișată și minimum două observații, fără filtrare după PnL. **Un caz operațional, nu eșantion statistic de succes.** Afișarea în aplicație a fost confirmată la 05:24:55 UTC; nu înseamnă citire umană sau mesaj Telegram.
- `live-ui.json`, `dossier-ui.json`, PNG-urile: Chromium pe API real, fără interceptări. Nouă destinații, layout la 320–1536 px, dosar real. Zero erori JavaScript; răspunsul 507 al backupului și un 503 temporar al pilotului la pregătirea cache-ului sunt păstrate explicit în rezultate.
- `runtime-final.json`, `pilot-final.json`: instanța v0.21.1, opt workers, execuție reală dezactivată, pilotul original păstrat. Sunt capturi la o anumită oră, nu garanție de uptime.
- `dependencies.json` / `dependencies-after.json`: audit PyPI al dependențelor de producție înainte/după actualizarea certifi. Două înregistrări ale aceluiași advisory în rezultatul inițial reprezintă **o vulnerabilitate unică**, nu două vulnerabilități independente. Nu este auditul imaginii OS, al tuturor instrumentelor de dezvoltare sau o dovadă de securitate absolută.
- `ai-status-live.json`: AI dezactivat/neconfigurat; nu există dovadă de generare reală OpenAI/Ollama. Telegram nu a fost trimis. Cotațiile Jupiter observate nu sunt execuții de tranzacții.
- `documents-live.json`: cititorul real de documente, pe SQLite temporar și cu User-Agent-ul aplicației, a extras text de la Anthropic și Circle. Sunt salvate URL, oră, hash și număr de caractere, nu o afiliere confirmată. `api-final.json` păstrează și latențele ultimului eșantion de API real.

## Repetare

După pornirea normală a aplicației, folosind portul afișat de launcher:

```bash
uv run --frozen python -m app.collection_verify --url http://127.0.0.1:8001 --duration 900 --output live-collection.json
uv run --frozen python -m app.routes_verify --url http://127.0.0.1:8001 --duration 900 --output live-routes.json
```

Verificatoarele citesc instanța, nu injectează candidați, nu schimbă praguri și nu plasează ordine. Pot încheia cu criterii incomplete dacă nu apar observații/cotații eligibile în interval; rezultatul incomplet trebuie păstrat. Pilotul existent nu se reactivează, nu se resetează și nu se antedatează pentru verificare.
