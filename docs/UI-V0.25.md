# MemeScope v0.25.0 — verificarea și corectarea interfeței

Interfața a fost verificată în Chromium, atât cu furnizori simulați și baze temporare,
cât și pe aplicația pornită cu istoricul real. Corecțiile vizează afișarea și comenzile
interfeței; scoringul, regulile financiare și protocolul pilotului nu au fost modificate.

## Probleme reproduse și corectate

| Problemă observată | Corecție și verificare |
| --- | --- |
| La 320 px, pagina de ansamblu avea 350 px, iar portofoliul 351 px. | Grilele permit micșorarea și împachetarea valorilor; acțiunile principale se așază pe rânduri. Verificare inclusiv cu sume foarte mari. |
| Pe telefon, cercetarea și coloanele din piață/scanner necesitau derulare laterală fără o indicație clară. | Aceste tabele devin carduri etichetate la maximum 600 px. Acțiunile și toate valorile rămân în lățimea ecranului. |
| Dovezile extinse din alerte ajungeau la 927 px și erau tăiate în interiorul panoului. | Limite de lățime pentru copii, împachetarea JSON-ului, derulare pentru conținutul lung. |
| Rapoartele derulabile și unele blocuri tehnice nu puteau primi focus de la tastatură. | Regiuni etichetate cu `tabindex`, contur vizibil și focus pentru rezumatele panourilor. |
| Butonul de pornire a pilotului folosea aspectul implicit al browserului și avea numai aproximativ 20 px înălțime. | Stilul principal și o înălțime de minimum 44 px. Nu a fost activat sau resetat pilotul real. |
| Căutarea fără potriviri lăsa tabele goale dacă existau alte active în bază. | Mesaj distinct pentru zero potriviri și revenire corectă când se șterge căutarea. |
| Știrile și activele din privirea de ansamblu erau containere accesibile numai prin clic. | Linkuri reale, utilizabile cu Tab și Enter. |
| Panoul „Pulsul pieței” era ascuns pe ecrane mici. | Rămâne prezent în fluxul paginii. |
| Erorile dispăreau automat după 12 secunde și nu puteau fi închise explicit. | Mesajele de eroare rămân până la închidere sau o nouă acțiune; textul lung se derulează. Confirmările de succes păstrează închiderea automată. |
| Actualizarea globală se oprea la prima eroare și nu reîncărca radarul vizibil. | Cereri independente, rezultate parțiale păstrate, radarul/secțiunea avansată reîncărcate când sunt deschise. |
| Listele mari de surse defecte ocupau excesiv ecranul. | Rezumat extensibil cu lista completă și acces la starea componentelor. Deschiderea și focusul sunt păstrate la actualizare. Numărul erorilor nu este redus. |
| Formularele și comenzile aveau etichete, dimensiuni și contrast neuniforme. | Etichete vizibile pentru rețele/orizont, borduri mai clare, fonturi de formular de 16 px pe telefon, stări de așteptare și butoane consistente. |

## Ce a fost verificat

- **707 teste pytest trecute**, în 387,08 secunde; un avertisment existent Starlette/httpx.
- **56 de scenarii Chromium existente trecute**: filtre, navigare, dosare, rapoarte,
  întârzieri, erori, conturi separate și ordine exclusiv virtuale în baze temporare.
- **19 scenarii noi trecute** în `tests/browser_interface.py`, inclusiv nouă pagini la
  **320, 390, 600, 768, 1024, 1440 și 1920 px**, sume mari, erori lungi,
  căutări fără rezultate, focus și actualizare parțială.
- Verificarea automatizată **axe-core 4.14.0** nu a raportat încălcări ale regulilor
  WCAG A/AA selectate în cele **20 de combinații**: zece vederi, panouri extinse,
  desktop și telefon. Acesta este un control automat, nu o certificare de accesibilitate.
- Cele șapte scripturi suplimentare de browser au trecut: `smoke`, `regressions`,
  `advanced`, `ai`, `announcements`, `opportunities`, `slow_news`.
  Scriptul vechi pentru autentificare a fost adaptat să deschidă meniul mobil înainte
  de a apăsa o destinație din sertar.
- Ruff, verificarea sintaxei celor trei fișiere JavaScript și `git diff --check`: trecute.

**Aplicație cu istoric real, fără interceptări HTTP:** nouă secțiuni la șapte lățimi
(63 de verificări), plus deschiderea unui candidat păstrat și dosarul său la patru
lățimi. Fără erori JavaScript și fără ordine sau alte acțiuni financiare în browser.
Verificările de păstrare confirmă soldurile, ordinele, pozițiile, politicile originale,
declarațiile și înregistrările istorice de control. Politica pilotului rămâne 32.

Inventarul include controalele repetate din rânduri și numai stările efectiv afișate;
nu înseamnă că fiecare serviciu extern a fost apelat în contul real. Dovezile și
capturile comparative sunt în [ui-v0.25-evidence](ui-v0.25-evidence/README.md).

## Reproducerea verificărilor

Din folderul proiectului, cu Python 3.12+, uv și Chromium instalate:

```bash
uv sync --frozen
uv run --frozen pytest -q
uv run --frozen ruff check app tests
node --check app/static/app.js
node --check app/static/advanced.js
node --check app/static/opportunities.js
uv run --with playwright python tests/browser_audit.py
uv run --with playwright python tests/browser_interface.py
```

Scripturile acceptă `BROWSER_EXECUTABLE`; implicit folosesc `/usr/bin/chromium`.
Pentru axe, instalează separat `axe-core@4.14.0` într-un director de unelte și setează
`BROWSER_AXE_PATH` la fișierul său `axe.min.js`. Workflow-ul CI execută acum și acest
audit; axe nu devine o dependență a aplicației.

## Actualizare și pornire

Închide aplicația veche. Copiază fișierele noii versiuni peste instalarea actuală,
păstrând `data` și configurația existentă. Arhiva codului nu conține baza ta de date.

Pe Windows, deschide `start-windows.cmd`. Alternativ, din PowerShell în folderul proiectului:

```powershell
uv sync --frozen
uv run --frozen python -m app.desktop
```

În browser, folosește `Ctrl+F5`; versiunea din bara laterală trebuie să fie **v0.25.0**.
Pe Linux/macOS: `bash start-unix.sh`. Verificarea din cloud a folosit portul intern 8001;
acesta nu este o adresă de acces pentru calculatorul utilizatorului.

## Limite rămase

- Testele de interfață cu AI, Telegram, documente, cotații și ordine folosesc furnizori
  simulați, marcați explicit. Nu au fost trimise mesaje Telegram sau cereri AI plătite.
- În instanța cloud, accesul efectiv la API-urile crypto și GitHub API rămâne blocat
  de proxy. Datele păstrate și erorile rămân vizibile; această verificare vizuală nu
  confirmă colectarea live sau profitabilitatea.
- Execuția nativă Windows a versiunii v0.25.0 nu a fost verificată în această sesiune.
  Rezultatele locale sunt din Chromium/Linux.
- Spațiul pentru backupul complet al bazei mari rămâne insuficient. Mesajul este
  lizibil; interfața nu transformă lipsa spațiului într-un backup reușit.
