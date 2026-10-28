# Dovezi v0.26.0 — backup real și acces API

| Verificare | Dovezi |
| --- | --- |
| Acces HTTPS real la DexScreener, GeckoTerminal, CoinGecko și GitHub API | [initial-check.json](initial-check.json): toate patru refuzate de proxy cu 403; nu sunt erori API de autentificare confirmate |
| Preflight înaintea arhivei mari | [real-plan.json](real-plan.json): buget de ieșire limitat și volum separat pentru restaurare |
| Backupul întregului istoric, fără mock-uri | [real-backup.json](real-backup.json), [real-backup-timing.json](real-backup-timing.json), [progres](real-backup-progress.txt) |
| Backup online conservator, aceeași bază | [online-comparison.json](online-comparison.json): refuz corect din cauza capacității |
| Politici, declarații, conturi și înregistrări de referință | [preservation.json](preservation.json): toate cele opt controale trecute |
| Fișierele de cercetare și cele financiare păstrate | [source-preservation.json](source-preservation.json): 23 de fișiere identice cu v0.25.0 |
| Teste complete | [pytest.txt](pytest.txt): 720 trecute |
| Teste dedicate backupului | [focused.txt](focused.txt): 24 trecute |
| Export/backup online și erori în browser | [browser-regressions.txt](browser-regressions.txt): furnizori simulați, baze temporare |
| Repornire și browser pe istoricul real | [live-restart.json](live-restart.json): v0.26.0, 50 candidați, zero erori JavaScript, avertismentul de spațiu păstrat |

Arhiva reală are **1.364.363.273 octeți**, pentru **11.035.508.736 octeți** de baze.
SHA-256: `e4a7431fda7ab562655e72136d907e86edd7b229b38062caec7faf4c79816ec5`.
Ambele baze au fost restaurate temporar și comparate cu hashurile calculate din
sursele SQLite blocate. Apoi au trecut verificarea SQLite și au fost eliminate
numai copiile temporare de verificare. Întreaga operație: **417,63 s**.

ZIP-ul privat rămâne în `data/backups`, exclus din Git. Acest folder nu este o copie
independentă în alt mediu: `independent_offsite_backup_verified` este explicit fals.
Nu există o verificare nativă Windows pentru această versiune în această sesiune.
Sursele crypto live și performanța financiară nu sunt validate de backup.

Eșantionul de compresie din verificarea inițială a fost doar o investigație de
fezabilitate. Acceptarea backupului se bazează pe arhiva completă și restaurările
efective, nu pe extrapolarea acelui eșantion.
