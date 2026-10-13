# Verificare milestone 1

Executat în mediul cloud pe 13 octombrie 2026:

- Scriptul de instalare salvat: `uv sync --frozen`, Ruff și pytest; exit 0, **53 teste trecute**.
- `node --check app/static/app.js`: exit 0.
- Browser smoke izolat cu răspunsuri simulate: scanare → semnal → așteptare → intrare paper →
  ieșire → PnL net. Desktop și viewport mobil de 390px, fără erori JavaScript.
- Browser pe aplicația cu surse reale: dashboard încărcat, tabel populat și layout mobil fără
  overflow al paginii. Captura este un artefact local, nu un deployment public.
- `.venv/bin/python -m app.smoke`: exit 0. Discovery a returnat 12 adrese Solana valide; wrapped
  SOL a furnizat un preț și lichiditate, RPC și GoPlus au răspuns și verificările de bază au trecut.
  Wrapped SOL a fost folosit numai ca probă de infrastructură, fără ordine și fără inserare ca
  memecoin în baza aplicației.
- Server pornit/restartat cu instrucțiunile documentate. Health, token detail și istoric HTTP 200;
  observațiile SQLite au supraviețuit restartului, soldul paper a rămas $100, cu 0 ordine în baza
  reală. Round-trip-urile din teste au folosit numai baze temporare.

Suita acoperă veto-uri de securitate, extensii nesuportate, date lipsă/expirate, parsing de API,
semnale vechi/prea noi, comisioane și break-even, alocare/exposure, pierderi realizate zilnice,
reutilizare de semnale, ordine concurente, lichiditate zero, cache inutilizabil la eșec și CSRF origin.

Un warning de deprecation din Starlette TestClient/httpx apare în teste; testele se execută și
trec. Nu am ascuns warningul sau dezactivat assertions.

Nu s-au verificat: quotes de swap, tranzacții on-chain, memecoin profitability, wallet skill,
backtest, Base, AI sau Telegram. Nu s-a publicat mediul și nu s-a testat restaurarea într-un task
nou. Configurația draft salvează `install_script`, `start_skill` și domeniile personalizate;
publicarea se face de utilizator în setările mediului. La validarea inițială nu se făcuse commit/push GitHub.

## Clarificarea fluxului de știri și ordinul virtual de $50

Verificare ulterioară în aceeași zi: **66 teste trecute**, inclusiv parsing RSS, eliminarea
titlurilor cu „100x”/„price prediction”, deduplicare, cronologia poolului, respingerea asocierilor
neînregistrate, păstrarea articolului original în jurnal și separarea conturilor.

Browser test izolat: titlu → token posibil asociat → semnal → ordin manual de $50 → ieșire și PnL.
Debitul simulat a fost $50,01, soldul contului test „Știri” a devenit $449,99, contul test „Scanner”
a rămas $100. La preț neschimbat round-trip-ul a pierdut costurile. Acestea sunt rezultate din
fixtures, nu o tranzacție pe piață sau dovadă de profitabilitate.

Google News RSS și DEX search au răspuns live pentru ambele subiecte. După restart, aplicația a
afișat titluri colectate și potriviri de tokenuri, fără erori JavaScript; viewport mobil 390px fără
overflow. Contul real al aplicației „Scanner” a rămas $100, iar noul cont fictiv „Știri” a fost
inițializat cu $500; ambele aveau 0 ordine. Nu am plasat un ordin în locul utilizatorului.

Verificarea integrală a articolelor și cauzalitatea știre–token nu sunt implementate. Toate
articolele păstrează `article_verified=false` și potrivirile `lexical_hypothesis`. Nu afirmăm că
poolurile găsite sunt tokenuri noi. Nu există notificări în afara aplicației sau Telegram.
