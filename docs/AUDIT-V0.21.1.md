# Audit MemeScope v0.21.1 — 27 octombrie 2026

Au fost inspectate codul, launcherul, dependențele, bazele SQLite existente, API-ul și interfața. Auditul a produs corecții și teste de regresie. Nu demonstrează absența tuturor bugurilor și nu demonstrează profitabilitate.

## Probleme reproduse și reparate

| Problemă | Dovadă înainte | Corecție și verificare |
|---|---|---|
| Backupul eșua cu HTTP 500 când discul nu putea ține copia și arhiva | POST real `/api/backup`: 500 în 0,018 s; cinci cazuri de regresie eșuau | HTTP 507 cu mesaj și capacitate necesară; panoul Stocare arată deficitul. Lockul refuză cereri simultane cu 409. Erorile de disc sunt sanitizate, arhivele vechi păstrate. POST real după: 507 în 0,013 s. |
| Starea discului putea fi „ok” deși backupul complet nu încăpea | Status și test cu spațiu disponibil între rezerva minimă și capacitatea necesară | Aceeași estimare pentru status, capacitate și preflight, incluzând WAL; fișierele WAL dispărute între citiri nu produc excepții. |
| Exportul manual citea și decomprima snapshoturi fără legătură | Contul Scanner fără ordine: 14,264 s. Regresie pe codul anterior: 1 eșec/1 succes | Selectare SQL numai a snapshoturilor referite. Aceeași bază, export real după: 0,777 s, fără ordine sau snapshoturi fabricate. Timpi locali, nu garanție generală. |
| Cauza unei căderi dispărea după recuperarea workerului | Status real vechi: 4 reporniri fără cauze păstrate; test cu eșec urmat de recuperare reproduce pierderea | `app/workers.py`: tip, dată și ultimele cinci erori păstrate în memorie și afișate în detalii; logging fără mesaj arbitrar, cale sau cheie. Istoricul nu persistă după oprirea aplicației. Cauzele vechi nu pot fi reconstruite. |
| Launcherul accepta metadate cu mod de execuție nesigur sau necunoscut | Patru regresii eșuau pentru `true`, `null`, șir și număr | Refolosirea unui server cere explicit `live_execution is False`, pe lângă identitate, versiune și instanță. Verificare defensivă; metadatele nu sunt autentificare criptografică. |
| Certifi conținea un trust anchor revocat | pip-audit: PYSEC-2026-4320 / GHSA-6q48-6c7w-9gw2 în certifi 2026.7.22 | Lock actualizat numai la certifi 2026.10.23; auditul dependențelor de producție nu mai raportează vulnerabilități cunoscute la data verificării. TLS rămâne activ. |
| Raportul pilot citea payloaduri mari și rezultate neutilizate | Profil pe baza reală | Proiecții SQL restrânse la subiecții și câmpurile analizate. Aceeași tranzacție de citire, aceeași oră: 30,856 → 14,965 s; rapoartele întregi au același SHA-256 `e73370918fd4954503eb01f19f38a8a3c8aa0caf440e72247ded0929857b8cd2`. |
| Raportul Jupiter depășea limita de 20 s a interfeței | Cerere reală: 88,646 s; profil: 804.000 rezultate și multă parsare JSON; trei regresii eșuau | Calcul separat în proces SQLite read-only, cu limită de 180 s și oprire la anulare. API-ul servește ultimul snapshot complet, cu oră, vechime și erori de actualizare. Pe baza reală: calcul inițial 66,297 s în fundal, apoi răspuns 200 în 0,0124 s; la rece răspunde imediat 503 explicativ. Calculul istoric rămâne costisitor, dar nu mai ține cererea HTTP deschisă. |

## Teste și limitele dovezilor

- Înainte: **621 teste pytest trecute**. Final: **642 trecute**, 286,90 s; un avertisment existent de depreciere Starlette/httpx. Sunt teste unitare și de integrare cu SQLite temporar, furnizori controlați și răspunsuri simulate, nu validare universală a furnizorilor reali. Cititorul Jupiter a fost verificat și ca subprocess real pe baza fixture, cu rezultat identic și istoric nemodificat.
- Chromium: **47 verificări trecute**, cu răspunsuri controlate; inclusiv concurență, timeout, navigare, layout mobil, erori recuperate, snapshot Jupiter și backup 507.
- Ruff, sintaxa celor trei fișiere JavaScript și `git diff --check`: trecute.
- Pe date reale: ambele baze SQLite au trecut `PRAGMA quick_check(1)`; API-urile de sănătate, status, candidați recenți, pilot, performanță cache, colectare, portofolii, știri, active și wallets au răspuns 200 în eșantion. O sută de știri au avut o sută de URL-uri canonice distincte; aceasta nu dovedește deduplicarea întregului univers.
- Păstrare verificată: toate politicile și declarațiile originale, configurația, semnalul și observația inițială de referință, conturile manuale Scanner $100 și News $500, zero ordine. Numărul înregistrărilor a continuat să crească prin colectarea normală.
- Cele 15 surse financiare/de colectare înghețate sunt identice cu versiunea precedentă. Policy 32 și declarația pilotului 25 octombrie–24 noiembrie rămân neschimbate; hashul motorului este `cc2e2c6499bbd495b8c28aa38f76d366efb9785e50336a54cd262da62bda9251`.
- Browser pe API real, fără interceptare: 50 candidați afișați, nouă destinații accesibile, zero erori JavaScript, fără depășire orizontală la 320/390/768/1536 px. Mesajul backupului 507 și deficitul sunt lizibile. A fost observat și un 503 temporar la pregătirea raportului pilot după restart; raportul a devenit disponibil la actualizarea următoare. Nu este prezentat drept răspuns 200.
- Verificare live strictă a colectării: **6 capturi distincte pentru alerte și 7 pentru control**, în 163 s; prețurile au fost capturate și primite în intervalul verificării și în ferestrele promise. Include ieșire ulterioară și checkpoint pentru control. Nicio injecție de candidați sau modificare de praguri.
- Evaluarea offline AI a validat structura a 12 cazuri (2 extrase observate, 10 sintetice); `model_run=false`, precizia AI nemăsurată. Nu este test OpenAI/Ollama live.
- Cititorul de documente, cu User-Agent-ul aplicației, a extras live text din `https://www.anthropic.com/news` (942 caractere) și pagina Circle `https://developers.circle.com/stablecoins/usdc-contract-addresses` (5.403 caractere), fără redirecturi sau TLS dezactivat. Nu s-a confirmat afilierea vreunui token. Aceste domenii sunt surse documentare, nu apeluri către un model Anthropic sau un serviciu financiar Circle.
- CI pentru codul final: [run 40455732978](https://github.com/Serin15/chatgpt/actions/runs/40455732978), commit `9ebcf30e7d96300bb14610448346ea0546e0c38b`: **succes pe Linux și Windows**. Linux: 642 teste în 134,34 s și 47 scenarii Chromium; Windows: 642 teste în 1.064,35 s, launcher pornit din folder cu spații și arhivare cu restaurare verificată pe baze temporare. `ci-final.json` și `ci-excerpts.txt` păstrează rezultatele reale. Nu este restaurarea bazei mari din cloud.

## Demonstrație reală a fluxului

Caz observat în timpul auditului, selectat pentru candidat nou, alertă necritică afișată și minimum două observații, **fără selecție după PnL**: candidatul `197521`, contract Solana `HQBT7S7Ncqwto3fXK8RVQ2GoA2RyaGoVXBASpCVWRhWB`, eticheta furnizorului `.AiTown / SOL`. Afilierea oficială rămâne neconfirmată.

1. Descoperire GeckoTerminal: **05:08:27 UTC**, înregistrare **05:08:29 UTC**. Vârsta raportată a poolului nu este data lansării tokenului.
2. Prima observație de piață/securitate: semnal `465359`, **05:09:02 UTC**, policy 32. Filtre trecute, verdict `INVESTIGATE`, scoruri, costuri, necunoscute și invalidări păstrate.
3. Alertă `12369`, generată automat și înregistrată la aceeași oră. Afișare în aplicație confirmată prin receipt **05:24:55 UTC**; nu dovedește citire umană și nu este livrare Telegram. Întârzierea de afișare rămâne vizibilă.
4. Cinci observații reale păstrate în captura dosarului. Intrare pool virtuală **05:09:44 UTC**, ieșire **05:15:34 UTC**, rezultat 300 s evaluat după costuri. Ferestrele de 1h/24h încă în așteptare în captură; nu sunt completate cu zero.
5. **Jupiter live:** `app.routes_verify.assess` confirmă toate cele patru criterii: observație reală legată, cotație buy cu contextSlot valid, cotație sell ulterioară pe cantitatea exactă și PnL net legat de aceleași tentative/politică. Sunt cotații observate, nu swapuri executate. Accesul fără cheie a funcționat pentru acest caz; nu este garantat pentru toate tokenurile sau în viitor.
6. Dosarul a fost deschis în Chromium pe API real; contractul, verdictul și secțiunea Jupiter sunt afișate, inclusiv la 390 px, fără erori JavaScript. Capturile sunt în folderul de dovezi.

Este o demonstrație operațională cu **un caz**, nu un test statistic reprezentativ și nu o dovadă de profitabilitate. Candidatul și majoritatea cotațiilor provin din colectarea normală pe regulile financiare înghețate, identice înainte și după corecțiile acestui audit.

## Ce rămâne, în ordinea impactului

1. **Capacitate pentru backupul bazei reale.** La măsurare erau aproximativ 2,96 GiB liberi; estimarea conservatoare cerea 19,83 GiB, deficit 16,87 GiB. Backupul și restaurarea întregului istoric nu au putut fi rulate pe acest disc. Backup/restore pe baze mici este testat, dar nu substituie copia producției. Nu s-a șters istoric și nu s-a pornit arhivarea fără backup verificat. Valorile exacte se recitesc în panoul Stocare.
2. **Costul interogărilor pe istoric mare.** Clasament: 11,27 s în eșantion; filtrul CONSIDER: 8,30 s. Căutarea fără rezultat în tot istoricul atinge limita SQL de 5 s și răspunde 503 cu îndrumarea de a folosi contractul exact. Daily a depășit inițial 30 s sub sarcină, iar repetarea a durat 4,84 s; variabilitatea nu este declarată reparată. Raportul global poate fi vechi cât timp se recalculează; snapshotul, data și starea sunt explicite. Jupiter este servit acum din cache, dar calculul său complet rămâne costisitor. O schimbare a surselor motorului înghețat necesită un protocol nou, fără amestecarea rezultatelor pilotului existent; optimizările strict de raportare pot rămâne separate, ca în acest audit.
3. **AI real și livrare externă.** AI este dezactivat/neconfigurat; nu s-au consumat credite și nu s-a demonstrat generare OpenAI/Ollama în această sesiune. Serviciul local Ollama pe `127.0.0.1:11434/api/tags` nu a fost accesibil; nu s-a cerut generare sau descărcare de model. Telegram nu are bot/destinație configurate; nu s-au trimis mesaje. Testele simulate ale adaptoarelor nu reprezintă livrare sau analiză reală.
4. **Acoperire și dovezi fundamentale/sociale.** Feedurile nu acoperă toate lansările; afilierea, holderii, deblocările, auditul și promovarea organică rămân necunoscute când nu există surse suficiente. Base este discovery separat, nu motor Level 3 validat integral. Wallet intelligence și corelarea narativă nu garantează identitatea persoanelor sau intenția lor.
5. **Validare economică și produs public.** Pilotul prospectiv trebuie să ajungă la maturitate, cu lipsuri și costuri raportate. Cotațiile Jupiter sunt simulări, fără swapuri executate. Nu există încă dovadă statistică de avantaj, nici validare SaaS cu mai mulți utilizatori, facturare și operare publică.

## Starea funcțiilor

| Funcție | Stare și dovadă |
|---|---|
| Descoperire Solana, îmbogățire, filtre, scoruri, verdict, SQLite | Implementate și verificate live pe eșantion; feeduri parțiale, nu toate lansările |
| Alerte în aplicație și receipt | Implementate și verificate live; afișarea cere aplicație/browser active, nu dovadă de citire |
| Observații ulterioare, grup de control, rezultate pool | Implementate și verificate live; lipsurile rămân în numitori, model estimativ |
| Cotații automate Jupiter și rezultat net legat de tentative | Implementate și verificate live pe cazul documentat; `execution_verified=false` |
| Ordine manuale paper | Implementate, verificate pe fixture cu costuri și respingeri; niciun ordin plasat în conturile reale ale utilizatorului în audit |
| Raport pilot/global și raport Jupiter în fundal | Implementate și verificate local/live; cache și costul calculului afișate, pilot încă în colectare |
| Știri și surse documentare Anthropic/Circle | Implementate, răspunsuri live și fixture verificate în eșantion; accesul poate varia. Sunt surse de documente, nu integrare cu modelul Anthropic |
| Analiză OpenAI/Ollama | Implementată și testată cu mockuri; generarea reală blocată de configurația lipsă în această sesiune |
| Asociere oficială, analiză fundamentală, narațiuni/social | Parțiale: cer dovezi/contract/chain; clasificarea și sursele absente rămân necunoscute; nu există verificare universală sau flux social global |
| Wallet intelligence / activitate suspectă | Parțiale și testate pe fixture; eșantioanele/euristicile nu dovedesc identitatea sau manipularea |
| Base | Discovery separat și răspuns API real verificat; Level 3 complet și inteligență wallet on-chain nevalidate integral |
| Telegram | Implementat/testat cu mockuri, livrarea reală blocată de bot token/chat id lipsă; zero mesaje trimise |
| Backup, restore, arhivare | Implementate/testate pe baze temporare; lipsa spațiului real și mesajul 507 verificate; backupul complet al bazei mari blocat de capacitate |
| Autentificare single-owner / HTTPS | Implementate și testate local cu fixture; deployment public și scenariu multiuser nevalidate |
| Windows | Implementat și verificat nativ în CI: 642 teste, launcher și arhivare/restore din foldere cu spații; bazele CI sunt temporare |

## Comenzi reproductibile

Din folderul extras al proiectului, cu Python 3.12 și uv:

```bash
uv sync --frozen
uv run --frozen ruff check app tests
uv run --frozen pytest -q
node --check app/static/app.js
node --check app/static/advanced.js
node --check app/static/opportunities.js
uv run --with playwright playwright install chromium
# Linux cu Chromium deja instalat: BROWSER_EXECUTABLE=/usr/bin/chromium
uv run --with playwright python tests/browser_audit.py
uv run --frozen python -m app.desktop --no-browser
```

Windows: `start-windows.cmd`, după „Extrage tot”, în folderul cu `app`, `pyproject.toml`, `uv.lock`. Pentru actualizare păstrează `data` și configurația; nu suprascrie o bază activă. Portul implicit este 8000, iar launcherul poate alege următorul liber. În cloud instanța verificată rulează pe `http://127.0.0.1:8001`.

Feedurile publice nu cer chei noi, dar au rate limits. OpenAI necesită cheie și facturare API; Ollama necesită serviciu/model și resurse locale; Telegram necesită bot token și chat id. Jupiter/RPC premium pot cere cont conform planului furnizorului. Nu s-au cumpărat abonamente și nu au fost estimate costuri fără tarife și volum verificate. Nu folosi seed phrases/private keys; tranzacțiile reale rămân dezactivate.

Fișierele modificate sunt `app/{desktop,main,maintenance,pilot,storage,workers,performance_cache,performance_worker}.py`, versiunea pachetului și lockul, `app/static/{app.js,opportunities.js,index.html}`, teste de backup/export/diagnostic/pilot/launcher/cache Jupiter și auditul de browser. Dovezi: [audit-v0.21.1-evidence](audit-v0.21.1-evidence/).
