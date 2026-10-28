# Dovezi pentru interfața v0.25.0

Datele de test din capturile comparative sunt **fictive**, furnizate explicit de
`tests.browser_fixture`. Nu sunt rezultate financiare sau semnale reale.

| Verificare | Fișier |
| --- | --- |
| Afișare înainte de corecții, nouă secțiuni la șase lățimi | [before-layout.json](before-layout.json) |
| Panouri extinse: dovezi tăiate și regiuni inaccesibile la tastatură | [before-expanded.json](before-expanded.json) |
| Afișare după corecții, fără depășiri de pagină sau comenzi tăiate în matricea examinată | [after-layout.json](after-layout.json) |
| 56 de scenarii de regresie Chromium | [browser-regressions.json](browser-regressions.json) |
| 19 scenarii UI, inclusiv matricea de șapte lățimi și axe | [browser-interface.json](browser-interface.json) |
| 707 teste unitare/de integrare | [pytest.txt](pytest.txt) |
| Aplicație cu istoric real, fără interceptări HTTP sau acțiuni financiare | [live-ui.json](live-ui.json) |
| Politici, declarații și conturi păstrate | [preservation.json](preservation.json) |
| Hash-uri ale fișierelor și verificarea celor 23 de module de cercetare/financiare nemodificate | [source-manifest.json](source-manifest.json) |

Capturi comparative pe telefon:

- Piața înainte: [before-market-390.png](before-market-390.png).
- Piața după: [release-market-390.png](release-market-390.png).
- Ansamblu înainte: [before-overview-390.png](before-overview-390.png).
- Ansamblu după: [release-overview-390.png](release-overview-390.png).

Cele șapte fișiere `browser-*.txt` consemnează fluxurile suplimentare cu furnizori
simulați. Testul AI simulează transportul modelului; testele de ordine folosesc
exclusiv portofolii temporare. Verificarea axe selectează regulile WCAG A/AA și nu
înlocuiește evaluarea manuală cu tehnologii asistive.

`live-ui.json` folosește datele păstrate ale aplicației v0.25.0. Nu confirmă cereri
crypto noi: proxy-ul cloud blochează în continuare aceste destinații. Niciun clic
de test nu a plasat ordine în portofoliile reale ale aplicației.
