# Dovezi pentru fluxul manual v0.23.0

Cod verificat: `08de9bfa5cf4ace3322466a66508ba5447f2c0da`. Fișierele din acest folder sunt rezultate de verificare, nu date demonstrative afișate ca live în aplicație.

## Furnizori reali, ordine exclusiv virtuale

- `live-paper-initial.json`: prima probă, 27 octombrie 2026, 16:00:00–16:00:11 UTC. Instanța sursă rula încă v0.22.0; fluxul nou a rulat în baza temporară cu noul cod. Șase criterii trecute, rezultat virtual net −0.51398676456313959406276592 USD.
- `live-paper-release.json`: repetare după pornirea sursei pe v0.23.0, 16:06:21–16:06:40 UTC. Șase criterii trecute, rezultat virtual net −0.50014465434043322867258939 USD. Include snapshotul nou, estimările, ordinul de intrare, ieșirea și portofoliul temporar.
- Ambele probe au ales primul candidat INVESTIGATE disponibil în momentul solicitării. Nu s-au repetat încercări pe alți candidați până la obținerea unui rezultat pozitiv și nu s-au relaxat praguri. Tokenurile existau deja în universul sursei; acestea nu sunt probe de descoperire în timp real a unor lansări noi.
- `live-ui.json`: Chromium pe aplicația reală v0.23.0, fără interceptarea furnizorilor. Formularul, textul și focusul s-au păstrat la refresh; lățimile 320/390/768/1440 px au încăput; zero erori JavaScript și zero POST-uri financiare. A fost editată doar o schiță locală nesalvată.
- `preservation.json`: configurația, politicile și declarațiile originale, două înregistrări istorice fixe și registrele Scanner/News au rămas identice; numărul înregistrărilor istorice nu a scăzut. Soldurile de producție sunt 100/500 USD, fără ordine create în ele de această verificare.
- `financial-sources.json`: fișierele incluse în amprenta financiară sunt identice cu versiunea anterioară; pilotul și formulele sale nu au fost modificate.

Date reale înseamnă răspunsuri API/RPC colectate atunci, nu swapuri executate, sellability demonstrată sau date independente auditate. Cele două rezultate nu estimează profitabilitatea ori probabilitatea de succes.

## Furnizori simulați, SQLite și browser reale

- `focused-tests.txt`: 28 de teste noi de integrare/regresie, toate trecute, pe baze temporare cu furnizori simulați.
- `pytest.txt`: suita finală completă, **690 de teste trecute**, 529,52 s, cu un avertisment existent de depreciere Starlette/httpx. Ruff, verificarea sintaxei celor trei fișiere JavaScript și `git diff --check` au trecut.
- `browser.txt`: 52 de scenarii Chromium trecute cu furnizori simulați. Trei scenarii noi verifică păstrarea formularului/focusului și 320 px; erori/expirare; refuz de risc, conturi separate, intrare și ieșire după costuri. Scenariul de expirare scurtă simulează și răspunsul HTTP; parcursul de cumpărare/vânzare folosește API-ul real al aplicației de test.

CI pentru cod: [40537269078](https://github.com/Serin15/chatgpt/actions/runs/40537269078), **succes pe Linux și Windows**. Au trecut suitele pytest, verificările JavaScript, Chromium pe Linux și pornirea Windows/arhivarea/restaurarea din dosare cu spații pe baze temporare. `ci.json` conține starea finală a joburilor și pașilor. `source-manifest.json` conține amprentele fișierelor aplicației, testelor și configurației verificate; eventualele commituri ulterioare de dovezi nu schimbă acest cod. Backupul complet al bazei reale mari rămâne neverificat din lipsă de spațiu, distinct de proba Windows pe baze mici.

Regresia inițială a fost reprodusă înaintea implementării: solicitarea noului flux returna HTTP 404 și testul parcursului eșua. Testele de acum verifică și valori extreme, modificarea sumei după salvare, prețul nou față de observația inițială, expirarea, încercări duplicate, lipsa furnizorilor, un REJECT ulterior și lipsa fallbackului Jupiter.
