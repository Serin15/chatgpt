# Surse și verificare — 13 octombrie 2026

Actualizare v0.5: adaptoare HTTP pentru Ollama local (`/api/chat`, JSON schema, fără streaming)
și OpenAI (`/v1/responses`, Structured Outputs, `store=false`). Ambele sunt testate cu transport
simulat; niciun model local instalat și nicio cheie API disponibile aici, deci fără validare live
sau preț curent confirmat. Încercările de citire a documentației OpenAI/Ollama din acest cloud
au eșuat. Am verificat ulterior, pe 14 octombrie 2026, câmpurile protocolului în sursele oficiale:

- [OpenAI Responses create](https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response_create_params.py): input, text, store și max_output_tokens.
- [OpenAI JSON schema format](https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response_format_text_json_schema_config_param.py): name, schema, type=json_schema și strict.
- [Ollama request/response types](https://github.com/ollama/ollama-python/blob/main/ollama/_types.py): messages, format JSON schema, stream, options și done.

Aceste surse au răspuns HTTP 200; nu validează accesul la un anumit model, o generare reală sau
tarifele/limitele actuale ale contului. Vezi [limitele](V0.5.md).
Două pagini Solana/Kraken au fost citite live pentru extrasele setului de evaluare. Restul de zece
cazuri sunt sintetice; nu reprezintă anunțuri reale ale companiilor folosite ca surse de fixture.

Extinderea [v0.4](V0.4.md) separă citirea documentului de verificarea relației cu emitentul.
Catalogul include cele trei surse existente, `solana.com`, `www.anthropic.com` și
`developers.circle.com`. Ultimele două au fost declarate în draftul de rețea, dar accesul cloud
a rămas blocat cu `ProxyError` în probe; nu sunt declarate integrări live validate.
Pagina Solana Sync Native a fost citită live și adresa wrapped SOL a fost găsită; verificarea
a rămas neconfirmată pentru chain în contextul extras și nu a produs afiliere oficială.

Actualizare 14 octombrie: [v0.3](V0.3.md) adaugă căutare CoinGecko și citate din documente
Ethereum Foundation/Kraken/CoinDesk. Citirea documentului verifică prezența textului, fără
verificare automată a afirmației. Nu sunt necesare chei sau domenii noi. Deduplicarea știrilor
curente este după URL normalizat, cu păstrarea subiectelor și ID-urilor istorice.

Extinderea crypto generală v0.2, sursele actuale CoinGecko/Coinbase/RSS și limitele lor sunt
documentate în [V0.2.md](V0.2.md). Secțiunile de mai jos păstrează cercetarea primului milestone.

Repository-ul `Serin15/chatgpt` era gol, fără commituri sau branch remote `main`, la începutul
implementării. Nu a existat cod anterior de reutilizat. La prima validare, codul acestui milestone
era disponibil doar local. Nu am solicitat tokenuri GitHub: autentificarea HTTPS existentă a
permis citirea repository-ului.

## Alegerea surselor

| Sursă | Contract și autentificare | Limite/istoric/cost | Probe |
| --- | --- | --- | --- |
| [DEX Screener API](https://docs.dexscreener.com/api/reference) | `GET /token-profiles/latest/v1`, `GET /token-pairs/v1/solana/{mint}`; fără cheie în probe | Referința specifică 60 requests/min pentru profiluri; clientul limitează toate cererile DEX la aproximativ 54/min. Nu avem istoric de trades/OHLC complet din aceste endpointuri | Profiluri live și date de pool/preț/volum obținute; cazurile fără lichiditate sunt respinse |
| [GoPlus Solana Beta](https://docs.gopluslabs.io/reference/token-security-api-for-solana-beta) | `/api/v1/solana/token_security?contract_addresses=...`; Bearer opțional, SDK oficial confirmat | [Overview](https://docs.gopluslabs.io/reference/api-overview) descrie servicii gratuite. Quota exactă per cont/tier nu a fost confirmată; pacing ≤29/min, retry 429. Snapshot de securitate, nu istoric complet | Cod API 1 și avertismente interpretate pe token real; autentificare suplimentară necerută |
| [Solana RPC](https://solana.com/docs/rpc/http/getaccountinfo) | HTTPS `getAccountInfo`, `jsonParsed`, commitment `confirmed` | [RPC endpoints](https://solana.com/docs/references/clusters): rate limits publice pot varia; nu sunt destinate producției. Nu garantează arhivă completă | Program owner, mint/freeze authorities și metadata extensions citite live |
| [Base network](https://docs.base.org/base-chain/network-information) | Documentație consultată, RPC public descris | Nu este selectat/instalat încă; indexarea și istoricul trebuie alese la milestone-ul Base | Documentație HTTP 200; niciun scanner Base sau swap validat |
| [Jupiter docs](https://docs.jup.ag/) | Necesită alegerea unui API de quote actual înainte de integrare | Vechiul URL `/docs/api` a returnat 404; nu am presupus că vechile endpointuri, chei sau planuri rămân valabile | Doar indexul documentației a fost accesat; quotes/execution neintegrate |

SDK oficial GoPlus inspectat:
[GoPlusSecurity/goplus-sdk-python](https://github.com/GoPlusSecurity/goplus-sdk-python),
HEAD `ea1a80e33f1804c59632d18cee12102ffa367671` la inspectare. Solana `getAccountInfo` a fost
consultat și în [repository-ul oficial de documentație](https://github.com/solana-foundation/solana-com).
Nu există dependență runtime de aceste clone de cercetare.

Primele cereri au eșuat cu proxy 403 sau refuz legat de user agent. După salvarea domeniilor necesare,
clientul cu identificatorul `MemecoinResearch/0.1` a obținut răspunsuri live. Nu am dezactivat TLS,
verificarea certificatelor sau hashurile pachetelor.

## Costuri și utilizare

Milestone-ul a folosit endpointuri read-only fără abonamente API noi sau tranzacții on-chain.
Nu s-au consumat fonduri de trading. Hosting-ul rămâne dependent de planul cloud al utilizatorului;
nu a fost verificat un cost lunar al platformei. Quota, disponibilitatea și prețurile furnizorilor
trebuie reverificate înainte de monitorizare permanentă la scară mai mare.

[DEX Screener API Terms](https://docs.dexscreener.com/api/api-terms-and-conditions), consultate:
permit utilizări comerciale/necomerciale cu restricții privind concurența directă, revânzarea și
punerea API-ului la dispoziția terților. Aplicația este construită ca tool personal, fără endpoint
public de revânzare a datelor. Termenii GoPlus pentru redistribuire și planurile unui indexer de
wallet nu au fost confirmați; nu sunt presupuse drepturi comerciale de redistribuire.

Nu alegem încă un indexer plătit. Profitul unui wallet nu poate fi calculat corect doar din
snapshoturi de preț sau din transferurile recente: trebuie tranzacții complete, cost basis,
prețuri la momentul tranzacției, decodare swap, fee-uri și transferuri externe.

## Știri și asocierea cu tokenuri

Google News RSS (`https://news.google.com/rss/search`) a fost probat live cu cereri HTTPS,
fără cheie API. Căutările pentru subiectele Claude/Anthropic și Trump sunt limitate la știri recente;
se rețin până la 10 titluri per subiect și 6 tokenuri per subiect, cu deduplicare după link și subiect.
RSS-ul BBC Technology a răspuns de asemenea HTTP 200 în cercetare, dar nu este folosit de aplicație.
Nu avem un contract de disponibilitate/quota pentru Google News RSS sau un istoric complet de știri.
Aplicația stochează metadata și linkuri pentru uz personal; nu reproduce articolele integrale.

DEX Screener `GET /latest/dex/search?q=...` a returnat live tokenuri Solana pentru Claude și Trump.
Potrivirea este lexicală, nu AI și nu dovadă de cauzalitate. Titlul și identitatea publicației sunt
cele raportate de feed, fără validarea articolului integral. Scorul de oportunitate nu primește
puncte suplimentare doar pentru că există o știre cu un nume asemănător.

## Domenii în configurația draft

`api.dexscreener.com`, `docs.dexscreener.com`, `api.gopluslabs.io`, `docs.gopluslabs.io`,
`api.mainnet-beta.solana.com`, `solana.com`, `docs.base.org`, `docs.jup.ag`,
`198140802-files.gitbook.io` (fișierul OpenAPI atașat documentației DEX; accesul nu a fost confirmat).
S-au adăugat ulterior `news.google.com` și `feeds.bbci.co.uk` pentru probele de știri.
Preseturile existente pentru package managers/GitHub au fost păstrate. Nu sunt declarate secrete.

Salvarea configurației este distinctă de aplicarea sa la runtime și de publicare. Probe live
reușite descriu această instanță; nu reprezintă validare într-un task nou sau publicare pe GitHub.
