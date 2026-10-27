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

## Teste și limitele dovezilor

- Înainte: **621 teste pytest trecute**. După: **639 trecute**, 227,75 s; un avertisment existent de depreciere Starlette/httpx. Sunt teste unitare și de integrare cu SQLite temporar, furnizori controlați și răspunsuri simulate, nu validare universală a furnizorilor reali.
- Chromium: **46 verificări trecute**, cu răspunsuri controlate; inclusiv concurență, timeout, navigare, layout mobil, erori recuperate și backup 507.
- Ruff, sintaxa celor trei fișiere JavaScript și `git diff --check`: trecute.
- Pe date reale: ambele baze SQLite au trecut `PRAGMA quick_check(1)`; API-urile de sănătate, status, candidați recenți, pilot, performanță cache, colectare, portofolii, știri, active și wallets au răspuns 200 în eșantion. O sută de știri au avut o sută de URL-uri canonice distincte; aceasta nu dovedește deduplicarea întregului univers.
- Păstrare verificată: toate politicile și declarațiile originale, configurația, semnalul și observația inițială de referință, conturile manuale Scanner $100 și News $500, zero ordine. Numărul înregistrărilor a continuat să crească prin colectarea normală.
- Cele 15 surse financiare/de colectare înghețate sunt identice cu versiunea precedentă. Policy 32 și declarația pilotului 25 octombrie–24 noiembrie rămân neschimbate; hashul motorului este `cc2e2c6499bbd495b8c28aa38f76d366efb9785e50336a54cd262da62bda9251`.
- Windows nativ și dovezile live suplimentare vor fi consemnate după încheierea verificărilor curente; rezultatele locale nu sunt prezentate ca rezultate Windows.

## Ce rămâne, în ordinea impactului

1. **Capacitate pentru backupul bazei reale.** La măsurare erau aproximativ 2,96 GiB liberi; estimarea conservatoare cerea 19,83 GiB, deficit 16,87 GiB. Backupul și restaurarea întregului istoric nu au putut fi rulate pe acest disc. Backup/restore pe baze mici este testat, dar nu substituie copia producției. Nu s-a șters istoric și nu s-a pornit arhivarea fără backup verificat. Valorile exacte se recitesc în panoul Stocare.
2. **Costul interogărilor pe istoric mare.** Clasament: 11,27 s în eșantion; filtrul CONSIDER: 8,30 s. Căutarea fără rezultat în tot istoricul atinge limita SQL de 5 s și răspunde 503 cu îndrumarea de a folosi contractul exact. Rapoartele routes și daily au depășit timeoutul clientului de 30 s. Aceste limite rămân în audit; nu sunt declarate reparate prin optimizarea pilotului. O schimbare a surselor motorului înghețat necesită un protocol nou, fără amestecarea rezultatelor pilotului existent.
3. **AI real și livrare externă.** AI este dezactivat/neconfigurat; nu s-au consumat credite și nu s-a demonstrat generare OpenAI/Ollama în această sesiune. Telegram nu are bot/destinație configurate; nu s-au trimis mesaje. Testele simulate ale adaptoarelor nu reprezintă livrare sau analiză reală.
4. **Acoperire și dovezi fundamentale/sociale.** Feedurile nu acoperă toate lansările; afilierea, holderii, deblocările, auditul și promovarea organică rămân necunoscute când nu există surse suficiente. Base este discovery separat, nu motor Level 3 validat integral. Wallet intelligence și corelarea narativă nu garantează identitatea persoanelor sau intenția lor.
5. **Validare economică și produs public.** Pilotul prospectiv trebuie să ajungă la maturitate, cu lipsuri și costuri raportate. Cotațiile Jupiter sunt simulări, fără swapuri executate. Nu există încă dovadă statistică de avantaj, nici validare SaaS cu mai mulți utilizatori, facturare și operare publică.

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

Fișierele modificate sunt `app/{desktop,main,maintenance,pilot,storage,workers}.py`, versiunea pachetului și lockul, `app/static/{app.js,index.html}`, teste de backup/export/diagnostic/pilot/launcher și auditul de browser. Dovezile vor fi publicate în `docs/audit-v0.21.1-evidence/`.
