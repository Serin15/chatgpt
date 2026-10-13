const $ = (id) => document.getElementById(id);
let tokens = [], selected = null, loading = false, newsContext = null;
let activeAccount = 'news';
const labels = {reject: 'Respinge', monitor: 'Monitorizează', investigate: 'Investighează'};
const money = (v) => v === null || v === undefined ? '—' : new Intl.NumberFormat('ro-RO', {style:'currency', currency:'USD', maximumFractionDigits:2}).format(Number(v));
const price = (v) => Number(v).toLocaleString('en-US', {maximumSignificantDigits:6});
const stamp = (v) => v ? new Date(v).toLocaleString('ro-RO', {timeZone:'Europe/Bucharest'}) : '—';
const short = (v) => v.slice(0,6) + '…' + v.slice(-5);
function el(tag, text, cls) {const node = document.createElement(tag); if(text !== undefined) node.textContent = text; if(cls) node.className = cls; return node;}
function message(text) {$('message').textContent = text; $('message').hidden = !text;}
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const data = await response.json();
  if(!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Cerere invalidă. Verifică adresa și câmpurile.');
  return data;
}
async function action(button, fn) {
  button.disabled = true; message('');
  try {await fn();} catch(error) {message(error.message);} finally {button.disabled = false; await load();}
}
function renderTokens() {
  const query = $('search').value.toLowerCase();
  $('tokens').replaceChildren();
  for(const token of tokens.filter(t => (t.address + (t.snapshot?.market.symbol || '') + (t.snapshot?.market.name || '')).toLowerCase().includes(query))) {
    const row = el('tr'), snapshot = token.snapshot, market = snapshot?.market, analysis = snapshot?.analysis;
    const first = el('td'), button = el('button', undefined, 'token-button');
    button.append(el('strong', market?.symbol || 'În așteptare'), el('small', short(token.address) + (token.watch ? ' · watchlist' : ' · profil')));
    button.onclick = () => {newsContext = null; showDetails(token.address).catch(e => message(e.message));}; first.append(button); row.append(first);
    row.append(el('td', analysis?.scores.research_priority ?? '—', 'score'), el('td', money(market?.liquidity_usd)), el('td', money(market?.volume_5m)));
    row.append(el('td', market?.change_5m === null || market?.change_5m === undefined ? '—' : `${market.change_5m > 0 ? '+' : ''}${market.change_5m}%`, market?.change_5m > 0 ? 'good' : ''));
    const decision = el('td'); decision.append(el('span', analysis ? labels[analysis.action] : 'Fără date', `badge ${analysis?.action || 'monitor'}`)); row.append(decision);
    row.append(el('td', token.error || (snapshot ? `${token.age_seconds}s · ${token.age_seconds > 120 ? 'expirat' : 'observație API'}` : 'API nevalidat'), token.error ? 'bad' : ''));
    $('tokens').append(row);
  }
  $('empty').hidden = tokens.length > 0;
}
function renderPortfolio(portfolio) {
  $('cash').textContent = money(portfolio.cash); $('positions').replaceChildren(); $('orders').replaceChildren();
  if(!portfolio.positions.length) $('positions').append(el('p', 'Nicio poziție simulată. Deschide un candidat pentru a înregistra un semnal.', 'source-note'));
  for(const p of portfolio.positions) {
    const row = el('div', undefined, 'position'), desc = el('div');
    const symbol = tokens.find(t => t.address === p.address)?.snapshot?.market.symbol;
    desc.append(el('strong', symbol || short(p.address)), el('p', p.closed_at ? `Închis · ${stamp(p.closed_at)}` : `Deschis · ${stamp(p.entry_at)}`), el('code', short(p.address)));
    const figures = el('div', undefined, 'numbers'); figures.append(el('div', `Cost intrare: ${money(p.entry_cost)}`), el('div', `Cantitate: ${price(p.quantity)}`));
    if(p.closed_at) figures.append(el('div', `PnL net realizat: ${money(p.pnl)}`, Number(p.pnl) >= 0 ? 'good' : 'bad'));
    else {
      const v = p.valuation;
      if(v?.estimated_unrealized_pnl_usd !== null && v?.estimated_unrealized_pnl_usd !== undefined) figures.append(el('div', `PnL net estimat la ieșire: ${money(v.estimated_unrealized_pnl_usd)}`, Number(v.estimated_unrealized_pnl_usd) >= 0 ? 'good' : 'bad'));
      else figures.append(el('div', 'PnL de ieșire: necunoscut', 'warn'));
      if(v) figures.append(el('div', `Observație: ${stamp(v.observed_at)}`));
      const button = el('button', 'Simulează ieșirea'); button.onclick = () => action(button, async () => {await api(`/api/paper/positions/${p.id}/sell?account=${portfolio.account}`, {});}); figures.append(button);
    }
    row.append(desc, figures); $('positions').append(row);
  }
  for(const order of portfolio.orders) {
    const block = el('div', undefined, 'order');
    block.append(el('div', `${stamp(order.at)} · ${order.side.toUpperCase()} · ${short(order.address)} · ${order.status === 'filled' ? 'SIMULAT' : 'RESPINS'}`, order.status === 'filled' ? 'good' : 'warn'));
    if(order.details.reason) block.append(el('div', order.details.reason));
    const context = order.details.entry_context?.news_context;
    if(context) block.append(el('div', `Ipoteză din știre: ${context.title} · ${context.publisher} · ${stamp(context.published_at)} · asociere neconfirmată`));
    const details = el('details'); details.append(el('summary', 'Ipoteze și dovezi'), el('pre', JSON.stringify(order.details, null, 2))); block.append(details); $('orders').append(block);
  }
}
function renderNews(stories, status) {
  $('stories').replaceChildren();
  const states = Object.entries(status.topics).map(([topic, state]) => `${topic}: ${state.state === 'ok' ? `${state.headlines} titluri / ${state.candidates} potriviri` : state.error}`);
  $('news-status').textContent = `${status.running ? 'Căutare în curs…' : 'Verificare la fiecare 5 minute'} · ${states.join(' · ') || 'Surse încă neverificate'}`;
  if(!stories.length) {const empty = el('div', undefined, 'empty'); empty.append(el('h3', 'Încă nu avem știri colectate.'), el('p', 'Pornește căutarea sau verifică starea surselor. Nu afișăm exemple drept știri reale.')); $('stories').append(empty);}
  for(const story of stories.slice(0,12)) {
    const card = el('article', undefined, 'story');
    card.append(el('p', `${story.topic_label} · ${story.publisher} · ${stamp(story.published_at)}`, 'eyebrow'));
    const link = el('a', story.title, 'story-title'); link.href = story.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; card.append(link);
    card.append(el('p', 'Titlu raportat de sursă; articolul integral nu a fost validat. Nu inferăm probabilități de profit.', 'source-note'));
    if(!story.matches.length) card.append(el('p', 'Niciun token Solana asociat după nume în rezultatele verificate. Aceasta nu dovedește că nu există.', 'source-note'));
    for(const match of story.matches) {
      const m = match.market, row = el('div', undefined, 'story-token'), desc = el('div');
      desc.append(el('strong', `${m.symbol} · ${m.name}`), el('code', m.address));
      desc.append(el('p', `Asociere ipotetică după nume · ${match.chronology === 'pool_before_article' ? 'pool existent înainte de articol' : match.chronology === 'pool_after_article' ? 'pool creat după articol' : 'cronologie necunoscută'}`));
      desc.append(el('p', `Lichiditate raportată ${money(m.liquidity_usd)} · pool ${stamp(m.pool_created_at)} · token creation / afiliere oficială: neconfirmate`));
      const button = el('button', 'Analizează pentru paper'); button.onclick = () => action(button, async () => {
        activeAccount = 'news'; $('paper-account').value = 'news'; newsContext = story;
        await api('/api/tokens', {address:m.address}); await load(); await showDetails(m.address);
      });
      row.append(desc, button); card.append(row);
    }
    $('stories').append(card);
  }
}
async function load() {
  if(loading) return; loading = true;
  const requestedAccount = activeAccount;
  try {
    const [status, list, portfolio, stories] = await Promise.all([api('/api/status'), api('/api/tokens'), api(`/api/portfolio?account=${requestedAccount}`), api('/api/news')]);
    if(requestedAccount !== activeAccount) return;
    tokens = list; $('count').textContent = list.length; $('eligible').textContent = list.filter(t => t.snapshot?.analysis.paper_allowed).length;
    $('last-scan').textContent = status.scanner.last_completed_at ? new Date(status.scanner.last_completed_at).toLocaleTimeString('ro-RO', {timeZone:'Europe/Bucharest'}) : '—';
    $('scan-state').textContent = status.scanner.running ? 'Scanare în curs…' : status.scanner.error || 'Scanner periodic activ';
    $('provider-status').replaceChildren();
    for(const [key, label] of [['dex','DEX Screener'], ['rpc','Solana RPC'], ['goplus','GoPlus']]) {
      const state = status.providers[key], row = el('div', undefined, 'provider');
      const age = state ? Math.round((Date.now()-Date.parse(state.at))/1000) : null;
      row.append(el('span', label), el('span', !state ? 'NEVERIFICAT' : state.state === 'ok' ? `HTTP OK · ${age}s` : state.error, state?.state === 'ok' && age < 120 ? 'good' : 'warn'));
      $('provider-status').append(row);
    }
    const r = {...status.rules, initial_balance:portfolio.initial_balance};
    $('rules').textContent = `Capital ${money(r.initial_balance)}; alocare ≤${Number(r.max_allocation)*100}%, expunere la cost ≤${Number(r.max_exposure)*100}%. Lichiditate ≥${money(r.min_liquidity)}, impact ≤${Number(r.max_price_impact)*100}%, swap ${Number(r.swap_fee)*100}%, rețea estimată ${money(r.network_fee_usd)} pe sens. Pierderi realizate zilnic ≤${Number(r.daily_loss_limit)*100}% (UTC).`;
    renderTokens(); renderPortfolio(portfolio); renderNews(stories, status.news);
  } catch(error) {message(error.message);} finally {loading = false; if(requestedAccount !== activeAccount) load();}
}
async function showDetails(address) {
  selected = address;
  const data = await api(`/api/tokens/${encodeURIComponent(address)}`);
  if(selected !== address) return;
  const current = data.latest, market = current.market, analysis = current.analysis;
  const panel = $('detail'); panel.replaceChildren(); panel.hidden = false;
  const heading = el('div', undefined, 'section-title'), title = el('div'); title.append(el('p', 'DOSAR TOKEN · OBSERVAȚII API', 'eyebrow'), el('h2', `${market.symbol} · ${market.name}`));
  const refresh = el('button', 'Actualizează dovezile'); refresh.onclick = () => action(refresh, async () => {await api(`/api/tokens/${address}/refresh`, {}); await load(); await showDetails(address);}); heading.append(title, refresh); panel.append(heading, el('p', address, 'address'));
  const grid = el('div', undefined, 'detail-content'), left = el('div'), right = el('div');
  const links = el('div', undefined, 'detail-links');
  for(const [label, url] of [['DEX Screener', `https://dexscreener.com/solana/${encodeURIComponent(market.pair_address)}`], ['Solscan', `https://solscan.io/token/${encodeURIComponent(address)}`]]) {
    const a = el('a', label + ' ↗'); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; links.append(a);
  }
  left.append(links, el('p', `Preț observat: $${price(market.price_usd)} · pool: ${market.dex} · observație ${stamp(market.observed_at)}`));
  if(newsContext) {left.append(el('h3', 'Știrea care a generat ipoteza'), el('p', newsContext.title), el('p', `${newsContext.publisher} · ${stamp(newsContext.published_at)}. Legătura cu tokenul este neconfirmată.`));}
  if(data.watch) {const unwatch = el('button', 'Scoate din watchlist'); unwatch.onclick = () => action(unwatch, async () => {await api(`/api/tokens/${address}/unwatch`, {}); await showDetails(address);}); left.append(unwatch);}
  left.append(el('p', market.pool_created_at ? `Pool creat: ${stamp(market.pool_created_at)}. Aceasta nu este data creării tokenului.` : 'Vârsta poolului/tokenului: necunoscută.'));
  for(const [label, items, cls] of [['Veto-uri', analysis.critical, 'bad'], ['Fapte RPC', analysis.positive, 'good'], ['Necunoscute', analysis.unknown, 'warn'], ['Limite de interpretare', analysis.warnings, 'warn']]) {
    if(!items.length) continue; left.append(el('h3', label, cls)); const list = el('ul'); items.forEach(item => list.append(el('li', item))); left.append(list);
  }
  right.append(el('h3', 'Scoruri explicabile'));
  const scoreLabels = {security_risk:'Risc securitate (mare = risc)', liquidity_exit:'Lichiditate / ieșire', activity:'Activitate', momentum:'Momentum', data_completeness:'Completitudine verificări MVP', research_priority:'Prioritate cercetare', wallet_quality:'Calitate wallet', copyability:'Copyability'};
  for(const [key, label] of Object.entries(scoreLabels)) {const row = el('div', undefined, 'score-row'); row.append(el('span', label), el('strong', analysis.scores[key] === null ? 'necunoscut' : `${analysis.scores[key]}/100`)); right.append(row);}
  const paper = el('div', undefined, 'paper-box'); paper.append(el('h3', `Market order virtual · cont ${activeAccount === 'news' ? 'Știri' : 'Scanner'}`), el('p', '1. Salvează ipoteza. 2. Așteaptă minimum 3 secunde. 3. Plasează manual ordinul market simulat cu date noi. Poate fi respins.'));
  const controls = el('div', undefined, 'paper-controls'), amount = el('input'); amount.type = 'number'; amount.min = '2'; amount.max = '100'; amount.step = '.01'; amount.value = activeAccount === 'news' ? '50' : '5'; amount.setAttribute('aria-label', 'Suma paper în USD');
  const signal = el('button', 'Salvează semnal'), buy = el('button', 'Simulează intrarea'); buy.disabled = true; let signalId = null;
  const orderAccount = activeAccount, orderNewsId = newsContext?.id || null;
  signal.onclick = () => action(signal, async () => {const saved = await api(`/api/tokens/${address}/signal`, {account:orderAccount, news_id:orderNewsId}); signalId = saved.id; signal.textContent = `Semnal #${saved.id}`; setTimeout(() => {if(analysis.paper_allowed) buy.disabled = false;}, 3000);});
  buy.onclick = async () => {await action(buy, async () => {await api('/api/paper/buy', {address, amount_usd:amount.value, signal_id:signalId, account:orderAccount}); signalId = null;}); buy.disabled = true;};
  controls.append(amount, signal, buy); paper.append(controls); if(!analysis.paper_allowed) paper.append(el('p', 'Intrare blocată de verificările actuale.', 'warn')); right.append(paper);
  right.append(el('h3', 'Ultimele observații — istoric local'));
  for(const h of data.history.slice(0, 8)) right.append(el('div', `${stamp(h.at)} · $${price(h.market.price_usd)} · LP ${money(h.market.liquidity_usd)}`, 'history-row'));
  grid.append(left, right); panel.append(grid); panel.scrollIntoView({behavior:'smooth', block:'start'});
}
$('search').addEventListener('input', renderTokens);
$('add-form').addEventListener('submit', (event) => {event.preventDefault(); newsContext = null; const button = event.currentTarget.querySelector('button'); const address = $('address').value.trim(); action(button, async () => {await api('/api/tokens', {address}); $('address').value = ''; await load(); await showDetails(address);});});
$('scan-button').onclick = () => action($('scan-button'), async () => {await api('/api/scan', {});});
$('news-button').onclick = () => action($('news-button'), async () => {await api('/api/news/refresh', {});});
$('paper-account').onchange = async () => {activeAccount = $('paper-account').value; await load(); if(selected) await showDetails(selected);};
load(); setInterval(load, 15000);
