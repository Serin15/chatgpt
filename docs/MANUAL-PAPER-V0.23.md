# MemeScope v0.23.0 — din oportunitate în portofoliul virtual

Dosarul unui candidat Solana poate deschide acum un ordin manual în contul virtual ales. Decizia păstrează observația afișată, verdictul, scorurile, motivele, datele descoperirii și semnalele originale. Prețul și verificările de securitate sunt colectate din nou la salvarea deciziei și la intrare. Nicio tranzacție reală nu este construită sau trimisă.

## Folosire

1. În **Oportunități timpurii**, deschide dosarul unui candidat și **Portofoliul meu · ordin virtual**.
2. Alege contul, suma și ipoteza; apasă **Salvează decizia și verifică datele**.
3. Citește prețul nou, riscurile și estimarea costurilor pentru suma aleasă. Așteaptă minimum trei secunde, apoi apasă **Cumpără virtual**.
4. Portofoliul afișează poziția, proveniența deciziei și un buton pentru redeschiderea oportunității. **Simulează ieșirea** colectează date noi; dacă ieșirea nu poate fi simulată, poziția rămâne deschisă.
5. Jurnalul păstrează ipoteza, dovezile, costurile și rezultatul net. Semnalele originale nu sunt rescrise cu informații apărute ulterior.

Contul **News** începe cu 500 USD, **Scanner** cu suma configurată, implicit 100 USD. Suma implicită de 50 USD nu schimbă limitele: alocarea implicită de 20% include costurile; un ordin de 50 USD în Scanner este refuzat. Conturile existente nu sunt resetate și nu primesc bani suplimentari.

O schimbare a contului, sumei sau ipotezei invalidează decizia pregătită în formular. Serverul verifică și suma, expirarea, întârzierea minimă, folosirea unică a semnalului, soldul, expunerea și pierderile zilnice. Actualizarea automată a dosarului păstrează formularul și observația aleasă, inclusiv focusul câmpului editat. Un verdict REJECT apărut ulterior blochează și o decizie deja pregătită.

Base, candidații excluși și observațiile neevaluate/respinse nu primesc această intrare. Căderea furnizorilor nu produce ordine la prețul din cache. În modul Jupiter, lipsa unei rute/chei nu produce fallback la modelul de pool. Estimarea preliminară de pool nu este prezentată drept cotație Jupiter sau execuție garantată.

## Separarea de studiul automat

Ordinele manuale folosesc tabelele existente `signals`, `positions`, `orders` și soldul contului ales. Legătura este salvată atomic în `signals.evidence.opportunity_context`, apoi copiată în dovezile ordinului de implementarea existentă.

Experimentele automate independente de 50 USD, rezultatele lor și pilotul nu devin poziții ale contului manual. Noua funcție nu schimbă formulele financiare, pragurile, declarațiile, ferestrele studiului sau prețurile istorice. Fișierele incluse în amprenta financiară a motorului sunt păstrate; amprenta rămâne `cc2e2c6499bbd495b8c28aa38f76d366efb9785e50336a54cd262da62bda9251`.

## Instalare și pornire

În Windows: extrage complet arhiva, păstrează dosarul tău `data` și configurația existentă, apoi pornește `start-windows.cmd`. Închide instanța veche înainte de înlocuirea fișierelor.

Din terminalul deschis în proiect, cu Python 3.12+ și `uv`:

```bash
uv sync --frozen
uv run --frozen python -m app.desktop
```

Nu sunt necesare chei AI sau Telegram pentru noul flux manual. Modul implicit folosește prețuri DEX Screener, verificări RPC Solana/GoPlus și o simulare de pool cu comisioane/rețea presupuse. Accesul și limitele API depind de furnizori. Jupiter rămâne opțional, cu acces API valid și `PAPER_SOLANA_EXECUTION=jupiter`. Modul pool nu produce costuri de blockchain sau tranzacții pe chain; aplicația nu necesită wallet ori cheie privată.

## Verificare reproductibilă

```bash
uv run --frozen ruff check app tests
uv run --frozen pytest -q
node --check app/static/app.js
node --check app/static/advanced.js
node --check app/static/opportunities.js
uv run --with playwright python tests/browser_audit.py
```

Testele unitare/de integrare folosesc SQLite real în directoare temporare și furnizori simulați. Acoperă proveniența, prețul nou, costurile, intrare/ieșire, risc nou după pregătire, lipsa datelor, conturi separate, sume invalide, duplicate, expirare și păstrarea tabelelor studiului. Chromium verifică și formularul la actualizare, focusul, 320 px, erori API, expirare și parcursul complet. Aceste teste nu sunt dovezi de predicție sau de execuție on-chain.

Rezultate finale: **690 teste trecute** local, **52 scenarii Chromium trecute**, Ruff și sintaxa JavaScript verificate. [CI 40537269078](https://github.com/Serin15/chatgpt/actions/runs/40537269078) a trecut pe Linux și Windows, inclusiv pornirea Windows și arhivarea/restaurarea din dosare cu spații, pe baze temporare.

Cu o instanță MemeScope deja pornită în modul paper pool, verificarea cu furnizori reali este:

```bash
uv run --frozen python -m app.opportunity_paper_verify --url http://127.0.0.1:8000 --output manual-paper-live.json
```

Comanda citește numai prin GET din instanța sursă. Alege primul candidat INVESTIGATE din clasament, fără încercarea altor tokenuri până când unul reușește, și copiază dovezile acestuia într-o bază temporară. Colectează cotații/securitate reale, încearcă un ordin virtual de 50 USD și ieșirea, apoi șterge baza temporară. Contul temporar începe cu 500 USD și limitele implicite; proba nu reproduce setările personalizate ale conturilor utilizatorului. Nu creează ordine în conturile utilizatorului, nu trimite mesaje, nu activează AI și nu declară profitabilitate. Fiecare blocaj păstrează criteriul neverificat; pragurile nu sunt relaxate pentru a obține un rezultat favorabil.

Proba inițială din **27 octombrie 2026, 16:00:00–16:00:11 UTC**, pe candidatul existent `206089`, contract Solana `Bgw1fG9hCVKupMd59dMwKyK9968rkJ8LyFabuMZ3N1Nv`, a trecut toate cele șase verificări: decizie, intrare, ieșire, proveniență, rezultat net și conturi de producție neschimbate. Prețul nou DEX Screener la pregătire a fost `0.00003187 USD`; cotația și verificările de securitate au fost colectate la aproximativ 16:00:05 UTC. Rezultatul virtual net a fost **−0.51398676456313959406276592 USD**. Candidatul fusese descoperit anterior probei; proba nu pretinde o descoperire nouă sau o tranzacție executabilă garantată.

După repornirea instanței pe v0.23.0, proba din **16:06:21–16:06:40 UTC** a ales candidatul `206026`, contract Solana `ZT8rLXRskyNqAh13NCLyHNgLSBqzyXFwQkaRr6HbvYL`. A trecut aceleași șase verificări, cu rezultat virtual net **−0.50014465434043322867258939 USD**. Două probe scurte, pe candidați aleși manual/din clasament, nu măsoară avantajul statistic al motorului și nu înlocuiesc grupul de control.

Dovezile și separarea testelor reale de cele simulate sunt în [manual-paper-v0.23-evidence](manual-paper-v0.23-evidence/README.md).

## Fișierele schimbate

| Fișiere | Rol |
| --- | --- |
| `app/opportunity_paper.py` | Leagă observația aleasă de decizia manuală, calculează estimarea preliminară și verifică veto-urile ulterioare. |
| `app/main.py`, `app/service.py` | Endpoint pentru pregătire, context atomic în semnalul existent, verificare înaintea ordinului, proveniență în portofoliu. |
| `app/static/opportunities.js` | Formular, cont/sumă/ipoteză, costuri, expirare, invalidarea modificărilor, păstrarea formularului și focusului la refresh. |
| `app/static/app.js`, `app/static/workspace.css` | Proveniență și redeschiderea dosarului din portofoliu, context în jurnal, stiluri responsive. |
| `app/opportunity_paper_verify.py` | Verificare cu furnizori reali într-un cont temporar, fără ordine în instanța sursă. |
| `tests/test_opportunity_paper.py`, `tests/browser_audit.py` | Regresii API/financiare și parcursul în Chromium cu furnizori simulați. |
| `app/__init__.py`, `app/static/index.html`, `pyproject.toml`, `uv.lock` | Versiune 0.23.0 și actualizarea referințelor statice; fără schimbarea dependențelor. |
| `README.md`, acest document și dovezile | Instrucțiuni și rezultate verificabile. |

## Limite rămase

- Simularea de pool deduce rezerve din lichiditatea USD. Nu dovedește vânzarea efectivă, structura exactă a poolului sau absența taxelor ascunse. Necunoscutele motorului rămân în dosar.
- Rezultatele manuale și cele automate nu constituie profitabilitate demonstrată. Pilotul prospectiv trebuie încheiat și evaluat după protocol.
- Backupul complet al bazei reale mari necesită spațiu suplimentar; configurarea destinației externe există deja. Rapoartele istorice pot rămâne lente.
- Analizele AI reale, Telegram, găzduirea publică și conturile separate pentru clienți necesită configurare/validare distinctă.
