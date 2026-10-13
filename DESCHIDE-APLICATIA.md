# Deschide aplicația pe calculatorul tău

Arhiva conține aplicația, nu doar o captură. Dezarhivează întregul director înainte să o pornești.
La prima pornire sunt descărcate dependențele; ai nevoie de internet. Datele și banii virtuali se
păstrează în directorul `data` creat local. Nu sunt incluse secrete sau istoricul instanței cloud.

Din GitHub: deschide repository-ul `Serin15/chatgpt`, selectează branch-ul `main`, apoi
**Code → Download ZIP**. Arhiva GitHub se extrage de regulă într-un director `chatgpt-main`;
fișierul `start-windows.cmd` se află direct în acel director.

## Windows

1. Instalează Python de pe https://www.python.org/downloads/ dacă nu îl ai. Păstrează Python
   launcher activat în instalator; Python 3.12+ este o alegere potrivită.
2. Dezarhivează pachetul și deschide directorul `chatgpt-main` (sau `memecoin-research` pentru
   pachetul local).
3. Dublu clic pe `start-windows.cmd`. Scriptul folosește `uv`; dacă lipsește, îl instalează prin pip.
4. Browserul se deschide automat când serverul este gata. Păstrează fereastra de comandă deschisă.

Dacă browserul nu se deschide automat, introdu `localhost:8000` în bara de adresă. Dacă portul
este ocupat, launcherul alege următorul port disponibil și îl afișează în fereastra de comandă.

## macOS / Linux

Instalează `uv` folosind https://docs.astral.sh/uv/getting-started/installation/ dacă lipsește.
Deschide Terminal în directorul dezarhivat și rulează:

```bash
bash start-unix.sh
```

Browserul se deschide automat când aplicația este gata. Păstrează Terminalul deschis.

## Ce faci în aplicație

1. Deschide secțiunea **Știri & tokenuri** și apasă **Caută știri** dacă feedul încă se încarcă.
2. Alege **Analizează pentru paper** lângă un token.
3. Citește datele, salvează semnalul și plasează manual ordinul virtual de $50 dacă verificările
   permit simularea. Contul **Știri** pornește cu $500 fictivi.

Oprești serverul cu `Ctrl+C`. Nu este necesar un wallet sau bani reali. Pentru cerințe și limite,
vezi `README.md`. Pachetul nu reprezintă un site public; interfața se servește pe calculatorul tău.
