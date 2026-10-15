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
2. În Downloads, click dreapta pe arhiva ZIP și alege **Extrage tot...**, apoi **Extrage**.
   Deschide folderul extras `chatgpt-main`. În același folder trebuie să vezi `app`,
   `pyproject.toml`, `uv.lock` și `start-windows.cmd`. Nu porni scriptul din fereastra arhivei ZIP
   și nu copia doar fișierul `.cmd`; aplicația are nevoie de întregul pachet.
3. Dublu clic pe `start-windows.cmd`. Scriptul folosește `uv`; dacă lipsește, îl instalează prin pip.
4. Browserul se deschide automat când serverul este gata. Păstrează fereastra de comandă deschisă.

Dacă browserul nu se deschide automat, introdu `localhost:8000` în bara de adresă. Dacă portul
este ocupat, launcherul alege următorul port disponibil și îl afișează în fereastra de comandă.

### Eroarea „No module named 'app'”

Dacă apare și `--no-dev has no effect when used outside of a project`, `uv` nu a găsit proiectul
în directorul de pornire. Acest lucru se poate întâmpla dacă scriptul este deschis direct din ZIP
sau dacă ai copiat numai `.cmd`. Nu este o problemă care cere reinstalarea Python.

Extrage întreaga arhivă și pornește scriptul lângă folderul `app` și `pyproject.toml`. Launcherul
actualizat verifică fișierele înainte să ruleze `uv` și afișează pașii de extragere dacă lipsesc.
El transmite explicit directorul aplicației către `uv`, inclusiv pentru căi cu spații.

## macOS / Linux

Instalează `uv` folosind https://docs.astral.sh/uv/getting-started/installation/ dacă lipsește.
Deschide Terminal în directorul dezarhivat și rulează:

```bash
bash start-unix.sh
```

Browserul se deschide automat când aplicația este gata. Păstrează Terminalul deschis.

## Ce faci în aplicație

1. Aplicația deschide **Oportunități timpurii**. Motorul colectează automat candidați Solana cât timp
   fereastra de comandă rămâne deschisă. Primele date pot întârzia sau sursele pot fi indisponibile.
2. Apasă **Cercetează** pentru motive, scoruri, riscuri și observații ulterioare. Alertele apar numai
   dacă regulile sunt îndeplinite; un candidat respins rămâne în istoric.
3. Experimentele automate de $50 sunt separate de conturile manuale. Rezultatele apar după
   orizonturile viitoare; datele lipsă rămân necunoscute. Nu se execută tranzacții reale.
4. Pentru un ordin virtual manual, deschide **Inteligență de piață**, alege **Analizează pentru paper**,
   citește datele și salvează semnalul. **Simulează intrarea** cere verificări valide. Contul Research
   pornește cu $500 fictivi numai dacă baza este nouă.

Oprești serverul cu `Ctrl+C`. Nu este necesar un wallet sau bani reali. Pentru cerințe și limite,
vezi `README.md`. Pachetul nu reprezintă un site public; interfața se servește pe calculatorul tău.

## Actualizare dintr-o versiune anterioară

Închide fereastra de comandă a aplicației. Fă o copie de siguranță a directorului `data`, apoi
copiază fișierele noii versiuni peste folderul anterior, păstrând `data`. Pornește din nou
`start-windows.cmd`. Nu porni două versiuni pe același director de date.

Din v0.3, dacă launcherul găsește o versiune veche încă pornită, cere închiderea acelei ferestre
înainte de a continua. Nu reseta contul. După actualizarea curentă, în bara laterală apare **v0.8 · L3**.

Analiza AI se configurează în dosarul unei monede, la **Ce spune știrea, de fapt?**.
Alege Ollama local și numele exact din `ollama list`, apoi salvează și testează conexiunea.
Ollama și modelul se instalează separat; aplicația nu le descarcă automat.
Alternativa OpenAI API cere credit API și `PULSE_AI_API_KEY` în mediul procesului pornit de launcher.
Nu trimite cheia în chat. Instrucțiuni și limite: [v0.5](docs/V0.5.md).
Din **Jurnal & rezultate** poți descărca un backup consistent al ambelor conturi și un export JSON
al experimentului selectat. Soldurile de pe PC sunt cele din propriul director `data`; arhiva
GitHub nu include conturile instanței cloud.
