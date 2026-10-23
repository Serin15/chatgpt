# MemeScope v0.20.0 — research workspace

**Colectare v0.20.0:** [bugete comune de timp, RPC/GoPlus în paralel și amânări explicite](docs/NETWORK-V0.20.md). O cerere neîncepută nu devine eșec de tranzacție; dashboardul arată separat timeouturile și lucrările amânate. Finalizarea în SQLite poate încă depăși intervalul nominal.

**Colectare v0.19.0:** [reevaluări prioritare, urmărirea pozițiilor virtuale și verificare live strictă](docs/COLLECTION-V0.19.md). Tokenurile urmărite pot depăși programarea zilnică de fundal; termenele apropiate sunt executate primele dintre candidații admiși. Dashboardul separă întârzierile prioritare de istoricul de fundal.

**Performanță v0.18.0:** [raport complet în fundal, proces de citire separat și colectare fără așteptări inutile](docs/PERFORMANCE-V0.18.md). Raportul afișează ora snapshotului; rezultatele viitoare sunt recalculate la termen sau când apar observații noi.

**Interfață v0.17.0:** [radar, dosare vizuale, grafice observate și navigație mobilă](docs/UI-V0.17.md). Filtre rapide, comparații 5m/15m/1h, riscuri și rezultate necunoscute explicate. Fără schimbări ale regulilor financiare.

**Monitorizare v0.16.0:** [prioritate pentru candidații timpurii, pauză pentru reevaluările vechi și istoric păstrat](docs/MONITORING-V0.16.md). Observațiile promise și pozițiile virtuale deschise rămân protejate.

**Stocare v0.15.0:** [arhivare fără pierderi, backup verificat prin restaurare și controlul spațiului](docs/STORAGE-V0.15.md). În Windows: oprește aplicația, apoi rulează `archive-windows.cmd`; istoricul rămâne accesibil.

**Colectare și validare v0.14.0:** [securitate reîmprospătată, cotații incrementale în același buget și protocol viitor separat](docs/COLLECTION-V0.14.md).

**Ferestre Jupiter v0.13.3:** [observații corecte, politici vechi păstrate și verificări](docs/JUPITER-V0.13.3.md).

**Audit suplimentar v0.13.2:** [cotații, timestampuri, diagnostice și verificare corectă](docs/AUDIT-V0.13.2.md).

**Corecție interfață v0.13.1:** [panou de stare, navigare și actualizare Windows](docs/UI-V0.13.1.md).

**Observații și măsurare:** [noutăți v0.13, comenzi și limite reale](docs/RESEARCH-V0.13.md).

Cercetare automată pentru tokenuri Solana observate devreme în feedurile publice: descoperire →
date de piață și securitate → filtre → scoruri separate → verdict explicat → alertă → rezultate
paper măsurate ulterior. Dashboardul pornește în **Oportunități timpurii**.

Motorul rulează cât timp aplicația este pornită. Păstrează și candidații respinși, dispăruți și
observațiile eșuate. Nu prezice randamente, nu confirmă automat afilierea unui token și nu execută
tranzacții reale. Un pool recent nu dovedește că tokenul a fost lansat recent.

[Cotații Jupiter v0.9 și verificări](docs/ROUTED-PAPER.md) ·
[Beta Solana v0.10: știri, contracte și bilanț zilnic](docs/BETA-SOLANA.md) ·
[Audit și corecții v0.9.1](docs/AUDIT-V0.9.1.md) ·
[Colectare echilibrată v0.8](docs/COLLECTION.md) ·
[Implementare, verificare live, limite și următorul milestone](docs/LEVEL3.md) ·
[Dovezi executabile](docs/level3-evidence/) · [Deschidere pe Windows](DESCHIDE-APLICATIA.md)

## Pornire pe Windows

Descarcă [ZIP-ul repository-ului](https://github.com/Serin15/chatgpt/archive/refs/heads/main.zip),
alege **Extrage tot**, apoi deschide `start-windows.cmd` din folderul care conține `app`,
`pyproject.toml` și `uv.lock`. Necesită Python 3.12+ sau uv; launcherul instalează dependențele și
pornește browserul. Păstrează fereastra de comandă deschisă.

Din PowerShell, cu uv instalat și terminalul în folderul proiectului:

```powershell
uv sync --frozen
uv run --frozen python -m app.desktop
```

Pe macOS/Linux, din folderul proiectului:

```bash
bash start-unix.sh
```

Pornire explicită, fără deschiderea browserului:

```bash
uv sync --frozen
uv run --frozen python -m app.desktop --no-browser
```

Dashboardul local este la `http://127.0.0.1:8000`; launcherul poate alege un port liber ulterior.
În mediul cloud, proiectul este în `/workspace/chatgpt`; verificările locale nu reprezintă găzduire publică.

## Ce face Level 3

- Descoperă pooluri Solana din GeckoTerminal și profiluri/expunere plătită DEX Screener. Rotește
  paginile, validează adresele și deduplică după chain/contract. Primul pool devine ancora de preț.
- Colectează preț, lichiditate, tranzacții, volume și contoare de cumpărători raportate de furnizor;
  verifică autoritățile mint/freeze prin RPC și restricțiile raportate de GoPlus.
- Compară observații anterioare pe 5m/15m/1h. Ferestrele fără istoric rămân necunoscute.
- Afișează opt dimensiuni: risc în verificările de securitate, lichiditate de ieșire, participare,
  momentum, wallet intelligence, dovezi narative, condiții de intrare și fiabilitatea datelor.
- Produce `REJECT`, `MONITOR`, `INVESTIGATE` sau `CONSIDER`, cu motive, necunoscute și invalidări.
  Scorurile sunt euristici, fără probabilități de succes.
- Emite alerte în aplicație cu cooldown, deduplicare și confirmare de afișare. Emite avertizare
  critică dacă un candidat alertat este ulterior respins pentru lichiditate/securitate.
- Înregistrează experimente independente de $50, separat de conturile manuale, pe observații
  ulterioare semnalului. Include fee și impact estimat. Lipsa datelor nu devine profit zero.
- Raportează rezultatele la 5m/1h/24h și observațiile lipsă. Grupul fix de comparație este stabilit
  înaintea evaluării și primește capacitate protejată împreună cu alertele. Datele istorice rămân
  separate de cohorta prospectivă; lipsa unei observații nu devine profit zero.
- Colectează separat cotații Jupiter pentru intrarea virtuală și ieșirea ulterioară, cu cantitatea
  exactă primită, conversie USDC/USD observată și costuri înghețate. Eșecurile păstrează PnL
  necunoscut. Cotațiile sunt scenarii paper și nu garantează executarea unor tranzacții.
- Clasifică opțional povești din documente permise cu OpenAI/Ollama. O poveste sau un nume
  asemănător nu reprezintă dovadă că persoana/compania a lansat ori susține moneda.

Praguri inițiale: lichiditate $25.000, impact estimat ≤2%, minimum 10 tranzacții/5m, pool ≤24h,
maximum +30%/5m și +50% față de prima captură pentru alerte de oportunitate. Costul tur-retur
estimat trebuie să fie ≤5%. Nu au fost optimizate pe rezultatele live pentru a declara succes.
Datele de securitate absente/expirate blochează clasificarea ca oportunitate.

Nu există acoperire completă a lansărilor, monitorizare socială globală, audit automat al
contractului sau dovadă că volumul este organic. Base rămâne discovery/cercetare separată;
nu intră în clasamentul automat Level 3. [Limitele complete](docs/LEVEL3.md).

## Configurare și date

Feedurile publice și RPC-ul public funcționează fără chei noi, în limitele furnizorilor. AI și
Telegram sunt opționale, oprite implicit. `.env.example` documentează variabilele; aplicația nativă
nu încarcă automat `.env`. Exportă variabilele înainte de pornire. Nu folosi private keys sau seed
phrases. Nu introduce secrete în Git, chat sau capturi.

```bash
# Exemplu opțional pentru o bază NOUĂ. Pentru o bază existentă folosește pragurile din dashboard.
export OPPORTUNITY_AI_NARRATIVES=1
export PULSE_AI_PROVIDER=ollama
export PULSE_AI_MODEL=numele-exact-al-modelului-instalat
uv run --frozen python -m app.desktop --no-browser
```

Alternativa OpenAI cere `PULSE_AI_PROVIDER=openai`, `PULSE_AI_MODEL` și `PULSE_AI_API_KEY_FILE`
cu un fișier secret exterior repository-ului. Necesită credit API separat. Modelul configurat
trebuie să suporte schema cerută. Erorile nu sunt înlocuite cu analize simulate.

Telegram cere `TELEGRAM_BOT_TOKEN_FILE`, `TELEGRAM_CHAT_ID` și activarea explicită a opțiunii
Telegram în pragurile motorului. Confirmarea API nu dovedește citirea mesajului. Livrarea reală
Telegram nu a fost verificată în acest mediu, în lipsa botului și destinatarului configurate.

`data/research.sqlite3` păstrează universul Level 3 și contul Scanner. Contul Research se află în
`data/news_paper/research.sqlite3`. Solduri inițiale numai pentru baze noi: Scanner $100, Research
$500. Motorul automat nu plasează ordine în aceste conturi. Experimentele independente nu
reprezintă un portofoliu cu buget total limitat.

Pentru actualizare: oprește aplicația, fă backup, păstrează `data` și copiază codul nou. Migrarea
nu șterge istoricul și nu completează prețuri istorice lipsă cu date viitoare. **Backup complet**
din jurnal include ambele baze și toate tabelele Level 3. Restaurează numai cu aplicația oprită,
într-un director de date gol, fără WAL/SHM vechi. Exportul JSON al portofoliului manual nu
înlocuiește backupul SQLite al motorului.

## Funcțiile existente sunt păstrate

Știri crypto și persoane publice, catalog/căutare crypto, dosare cu surse și citate, verificarea
contractului în document, watchlist, listări raportate, wallet activity, paper manual, jurnal,
export și backup. Cotațiile Jupiter sunt disponibile și în scenariile automate separate;
modelul aproximativ de pool este păstrat distinct. Niciunul nu garantează execuția on-chain.
[Descrierea funcțiilor anterioare și auditul v0.6](docs/V0.6-AUDIT.md).

Găzduirea cu autentificare single-owner/HTTPS este păstrată: `compose.yaml`, `Caddyfile` și fișier
secret extern. Necesită domeniu, DNS și server propriu. Testul HTTPS local nu dovedește o
publicare pe internet. Nu expune instanța locală fără configurarea autentificării.

## Verificare

```bash
uv sync --frozen
uv run ruff check app tests
uv run pytest -q
node --check app/static/app.js
node --check app/static/advanced.js
node --check app/static/opportunities.js
```

Browser cu furnizori simulați, baze temporare și Chromium instalat:

```bash
uv run --with playwright python tests/browser_opportunities.py
```

Demonstrație cu **servicii reale**, fără injectarea unui token și fără ordine. `--data-dir` trebuie
să indice un director nou pentru experiment. `--browser` este calea către Chromium instalat;
Python Playwright se adaugă numai pentru verificare:

```bash
uv run --with playwright python -m app.level3_verify \
  --data-dir /tmp/memescope-live-demo --duration 1200 \
  --browser /usr/bin/chromium --output /tmp/memescope-live-result.json
```

Scriptul pornește workerul normal, deschide interfața, verifică alerta și așteaptă un rezultat
paper pe observații ulterioare. Dacă nu apare un candidat eligibil sau serviciile nu răspund,
iese cu cod 1 și criteriile neverificate. Nu reduce filtrele pentru a obține artificial un PASS.
Pe Windows, folosește aceeași comandă pe un singur rând, cu propriile căi de date/browser/output.

Testele cu fixture-uri validează comportamentul. Demonstrația live validează conectarea fluxului;
un eșantion mic nu demonstrează profitabilitate sau identificarea viitoarelor tokenuri 10x/100x.
