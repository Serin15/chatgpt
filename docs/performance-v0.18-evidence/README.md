# Dovezi v0.18.0

Datele și timpii sunt din 22 octombrie 2026. Timestampurile JSON sunt UTC;
interfața afișează Europe/Bucharest. Un rezultat al benchmarkului nu este o garanție de latență.

## Aplicație normală și date reale

- `before-endpoints.json`: raportul vechi nu a răspuns în 21 secunde.
- `before-query-timings.json`: profilarea citirilor mari, fără scriere în istoricul original.
- `report-equivalence.json`: aceeași tranzacție de citire, ceas înghețat, SHA-256 identic,
  zero diferențe în raportul agregat. 79,07s pentru vechiul calcul și 34,16s pentru cel nou.
- `final-start.json`: pregătire inițială HTTP 503 explicată în 0,30s; candidați HTTP 200 în 2,06s.
- `live-performance.json`, `live-summary.json`: 25 răspunsuri 200 din cache, mediană 10,9ms,
  maxim 204ms; trei cicluri complete, 60 observații/ciclu, 53 candidați noi în total, zero
  erori ale motorului în acele cicluri. Recalculările complete au durat 29,23s și 45,93s.
  Cache-ul este etichetat; aceste durate nu sunt înlocuite cu timpul mic de servire HTTP.
- `new-real-candidate.json`: primul candidat ingested după repornire care a primit un semnal
  baseline sub politica nouă; verdictul său este **REJECT**. Nu a fost selectat după randament.
- `live-ui.json` și PNG-uri: versiunea 0.18.0, fără înlocuirea răspunsurilor sau injectarea
  prețurilor. Indicatori compleți și ora snapshotului vizibile, zero erori JavaScript/HTTP 5xx,
  fără depășire orizontală la 320/390/768/1536 px. Actualizarea periodică a browserului a fost
  dezactivată numai pentru o sesiune finită de captură. Testul nu a plasat ordine.

## Teste izolate

- `pytest-final.log`: **560 teste Python trecute**, un avertisment existent Starlette/httpx.
- `browser-final.json`: **39 scenarii Chromium trecute**, cu furnizori și date izolate.
- `parallel-reproduction.json`: dependențe controlate prin evenimente; reproduce așteptarea
  secvențială și demonstrează pornirea suprapusă, cu aceleași două cereri și aceeași precedență.
- `outcome-selection-tests.log`: include backlogul sintetic de peste 2.000 de rezultate viitoare,
  actualizarea extremelor la observații noi și închiderea la termen, plus regresiile existente.
- `process-final-tests.log`: proces Python real, date fixture, conexiuni doar pentru citire,
  căi cu spații/Unicode/# și anulare. Nu reprezintă verificare nativă pe Windows sau date live.

## Păstrare

- `financial-preservation.json`: fișierele financiare enumerate sunt identice cu v0.17.0.
  Bucla efectivă de evaluare a rezultatelor are AST identic; s-a schimbat selecția lucrărilor.
- `post-release-preservation.json`: toate politicile/protocoalele până la 27 au rămas identice,
  configurația este identică, iar rezultatul original Speed 209593/300s este identic.
  Portofoliile manuale au rămas $100/$500 virtuali și zero ordine.
- Politica nouă este **28**, declarată înaintea semnalelor sale. Testul prospectiv începe la
  **23 octombrie 2026, 15:59:36 UTC**. Nu s-a modificat retrospectiv protocolul politicii 25.
- `source-sha256.json`: identifică fișierele sursă verificate.

La ultimul ciclu existau încă **27.102** reevaluări periodice eligibile scadente și **67.697**
în pauză, din totalul brut 94.799. Coada nu a fost resetată. Promisiunile și observațiile ratate
rămân contabilizate separat. Cele trei cicluri nu dovedesc eliminarea backlogului sau profitabilitate.
