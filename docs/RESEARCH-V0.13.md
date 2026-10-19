# MemeScope v0.13 — observații și măsurare

Această etapă corectează colectarea și evaluarea candidaților. Nu adaugă ordine
reale, nu modifică pragurile de selecție și nu demonstrează profitabilitate.

## Ce s-a schimbat

- Calitatea colectării separă încercările de cotațiile utilizabile. Un preț
  necesită același contract și pool, identitate de sursă declarată live,
  timestampuri valide în intervalul cerut și prospețimea politicii originale.
  Lipsurile, răspunsurile vechi, viitoare sau din alt pool nu cresc contorul.
  O cotație utilizabilă nu dovedește securitatea ori executabilitatea ordinului.
- Politicile noi îngheață `forward_quote_window_version=2`. O cotație preluată
  înaintea ferestrei nu mai consumă observația programată dacă prelucrarea se
  termină după deschiderea ei. Următoarea cotație efectivă sau încercare eșuată
  din interval devine prima observație. Un eșec real nu este înlocuit cu un
  rezultat ulterior favorabil. Termenele și costurile rămân neschimbate.
  Politicile vechi păstrează alegerea primului rând și rezultatele lor.
  Această regulă nouă privește modelul de pool și reperele de preț; Jupiter
  păstrează separat politica și selecția strictă existente. Alinierea ferestrei
  Jupiter necesită propria politică nouă și validare, fără rescriere istorică.
- Bilanțul zilnic include o comparație separată a prețurilor față de cotația
  cunoscută la primul semnal. Sunt păstrați candidații respinși, lipsurile și
  lichiditatea zero. Se arată observații/total, variația medie și numărul
  variațiilor de cel puțin +100% sau −80% la orizontul observat. Nu sunt maxime
  intraperioadă, probabilități, profit după costuri sau dovada vânzării.
- Comparația rămâne separată pe politică, orizont și cohortă. Controlul exclude
  selecțiile suprapuse. Exportul JSON conține ID-urile observațiilor, valorile
  și stările individuale, inclusiv necunoscutele. Raportarea este numai în citire.
- Verificatorul documentar nu mai acceptă dovezi de pool în modul implicit care
  cere contract direct și nu mai acceptă confirmări de afișare datate în viitor.
- Interogarea acoperirii proiectează o singură dată câmpurile necesare fiecărei
  observații pentru alerte/control, fără să recitească integral payloadul pentru
  fiecare câmp. Nu șterge date și nu schimbă rezultatele raportate.

Codul principal este în `app/price_research.py`, `app/daily_research.py`,
`app/opportunity_sampling.py`, `app/opportunity_outcomes.py`,
`app/opportunities.py`, `app/story_verify.py` și `app/static/opportunities.js`.
Testele dedicate sunt în `tests/test_price_research.py`,
`tests/test_observation_sampling.py`, `tests/test_story_verify.py` și auditul Chromium.

## Instalare și verificare

Windows: oprește aplicația, salvează integral `data` și `.env` dacă există,
extrage proiectul complet, copiază datele în noul director și deschide
`start-windows.cmd`. Modificarea din cloud nu actualizează automat PC-ul.

Din directorul proiectului, Windows sau Linux:

```bash
uv sync --frozen
uv run --frozen python -m app.desktop
uv run --frozen pytest -q
uv run --frozen ruff check app tests
node --check app/static/opportunities.js
uv run --frozen --with playwright python tests/browser_audit.py
```

Auditul Chromium cere un browser instalat, implicit `/usr/bin/chromium` pe Linux;
pe alt sistem setează `BROWSER_EXECUTABLE`. Pentru pornire fără browser:

```bash
uv run --frozen python -m app.desktop --no-browser
uv run --frozen python -m app.research_evaluate --data-dir data --day 2026-10-18 --output cohort.json
uv run --frozen python -m app.story_verify --duration 900 --output story.json
uv run --frozen python -m app.story_verify --duration 900 --evidence-kind market_reference --output market-reference.json
```

Verificatorul nu injectează știri, ordine sau confirmări de livrare. Codul 1
înseamnă criterii incomplete. Detaliile verificărilor efective sunt în
[research-evidence/RESULTS.md](research-evidence/RESULTS.md).

## Limite și servicii

Nicio cheie, dependență sau subscripție nouă. Cost incremental de abonament:
$0; infrastructura și limitele furnizorilor existenți rămân valabile. Corecția
nu mărește bugetele configurate; observațiile neconsumate pot fi preluate din nou
în bugetul normal. Telegram și OpenAI necesită propriile credențiale și validare
reală; Ollama necesită serviciu și model instalat. Nu au fost activate aici.

Legătura live pentru o știre nouă eligibilă → candidat → alertă → outcome
rămâne de demonstrat pe aceeași dovadă. Un test cu fixture-uri sau o alertă din
feedul de pool nu completează acest criteriu. Universul de descoperire este
parțial; pauzele de colectare și prețurile lipsă nu pot fi reconstruite din
prețurile curente. Compararea unor eșantioane cu acoperire inegală nu dovedește
că selecția bate piața.

Se păstrează cutoff-ul `2026-10-18T00:00:00Z`. Politicile noi declarate după
acesta rămân neatribuite. Următoarea etapă este colectarea susținută și un
protocol prospectiv separat, declarat înaintea datelor sale de test, fără
optimizarea pragurilor pe rezultatele deja văzute.
