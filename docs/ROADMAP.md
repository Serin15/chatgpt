# Produs și milestone-uri

Misiune: identificarea ipotezelor de trading care merită cercetate după risc, lichiditate și costuri.
Nu dezvoltăm un predictor de profit sau copytrading automat.

Stare curentă: [v0.5](V0.5.md) implementează analiza AI opțională cu citări, configurare
Ollama/OpenAI și un set inițial cu două extrase observate și zece scenarii sintetice. Motorul AI
nu a fost încă rulat live; precizia nu este măsurată. [v0.4](V0.4.md) păstrează verificările de
document-contract și evaluările manuale de sursă. Prioritatea este configurarea unui model real,
un set mai mare de anunțuri autentice/false revizuit independent și măsurarea asocierilor false.

## 1. Scanner și laborator paper — implementat

Date reale Solana, filtre cu veto-uri, necunoscute explicite, observații persistente, watchlist,
ranking euristic și scenarii paper. Teste pentru costuri, expunere, pierderi realizate, freshness,
signal timing, atomicitate și eșecuri de furnizori. Interfață în browser și test separat cu fixture.

Acceptare: un mint real produce observații de piață și surse de securitate; lipsa oricărei verificări
obligatorii blochează simularea. Un round-trip la preț neschimbat pierde costurile, iar ieșirile
nevalidabile nu creditează soldul. Nu este dovadă de avantaj de trading.

Clarificare implementată: feed de știri Claude/Anthropic și Trump, surse/dată, potriviri lexicale
cu tokenuri Solana și ordin market virtual manual de $50 într-un cont separat de $500. Se păstrează
știrea în jurnal și se afișează PnL net estimat pentru pozițiile deschise. Asocierile semantice,
verificarea afirmațiilor din articole și alte subiecte virale rămân de dezvoltat.

## 2. Cotații și urmărirea rezultatelor — următorul milestone

Alegerea API-ului Jupiter actual din documentația oficială, quote-only fără semnare; verificarea
cheilor, tierului, rate limits și costurilor înainte de integrare. Quote la intrare și la ieșire,
fee-uri realiste, ATA rent, latență, min-out, lichiditate concentrată și indici de executabilitate.
Un quote rămâne insuficient pentru a garanta execuția.

Înregistrarea automată a ipotezelor și evaluarea forward la orizonturi prestabilite, inclusiv tokenuri
care dispar sau nu mai pot fi vândute. Rularea baselinelor cu aceleași date și costuri. Indicatori
de equity, PnL unrealized incert și drawdown; păstrarea explicită a eșecurilor și lipsurilor de date.

## 3. Wallet intelligence

Inițial monitorizăm adrese alese, fără clasament inventat de „walleturi profitabile”. Alegem un RPC/
indexer cu istoric suficient. Decodăm swapuri, separăm transferuri de intrări/ieșiri și reconstruim
inventarul/cost basis. Validăm PnL pe exemple verificate manual, apoi afișăm eșantionul și acoperirea
istoricului, drawdown, profit factor și dependența de un singur câștigător.

Copyability se testează cu întârzieri și cotații pentru poziții de $2–$10, după costuri. Fără
copytrading real implicit și fără a trata cumpărarea unui wallet drept instrucțiune automată.

## 4. Strategii și AI asistiv

Comparație early discovery / momentum / wallets / combined cu baseline, date out-of-sample și
tokenuri eșuate. Nu optimizăm pe setul de evaluare. Raportăm numărul de observații, perioadele și
incertitudinea; nu afirmăm profitabilitate din scoruri sau câteva trade-uri.

AI asistiv cu citări este implementat opțional, fără limite financiare sau tranzacții calculate
de model. Urmează validarea unui motor real, a costurilor și a calității pe un set separat de test;
cheia se furnizează securizat, niciodată în chat sau fișiere tracked. Interpretarea automată în
fundal se activează ulterior, după măsurarea calității și bugetului.

## 5. Base și alerte

Adaptoare de chain separate, schema comună de observații și aceeași suită de reguli financiare;
riscurile EVM au reguli proprii. Telegram necesită configurarea unui bot și a destinatarului,
deduplicare și limite de alertare. Nicio trimitere externă nu este activată acum.

Execuția reală este un proiect ulterior separat, cu autorizare explicită, signing izolat,
simulation unde este suportată, limite de cheltuieli, confirmări și kill switch.

## Extinderea v0.2 — implementată

Știri crypto generale și surse primare, piață CoinGecko, public book pentru unele active, piețe
raportate, metadata de identitate, experiment manual de $50 și UI PULSE desktop/mobil. Detalii
și limite în [V0.2.md](V0.2.md). Nu confundăm această extindere cu verificarea fundamentelor.

Următoarea prioritate: validarea anunțului original și a contractului, date despre produs, echipă,
tokenomics/vesting și audit; cazuri etichetate manual pentru măsurarea potrivirilor false. Mai apoi,
compararea rezultatelor forward și infrastructură web cu autentificare și monitorizare persistentă.
