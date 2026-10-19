const $ = (id) => document.getElementById(id);
const state = {
  page: "overview",
  account: "news",
  assets: [],
  tokens: [],
  news: [],
  portfolio: null,
  status: null,
  loading: false,
  filter: "all",
  selection: null,
  back: "news",
  sectionErrors: {},
  updated: {},
  performance: null,
  newsArchive: false,
  pendingLoad: false,
  authReady: false,
};
const announcementLabels = {
  identity_mismatch: "Contractul nu corespunde activului selectat",
  identity_unconfirmed: "Identitatea contractului nu poate fi stabilită",
  contract_not_found: "Contractul exact nu a fost găsit",
  chain_mismatch: "Documentul indică un alt chain",
  chain_unconfirmed: "Adresa apare, chain-ul rămâne neconfirmat",
  negative_context: "Context de avertizare sau negare · necesită evaluare",
  address_match_requires_review: "Adresă și chain găsite · emitent de evaluat",
  manual_source_match: "Contract găsit în sursă evaluată manual",
  source_unavailable: "Document necitit · rezultat necunoscut",
  approval_inactive: "Evaluarea sursei a expirat sau a fost retrasă",
  stale: "Rezultat vechi · cere o reverificare",
};
const pageNames = {
  overview: "Privire de ansamblu",
  news: "Inteligență de piață",
  market: "Piața crypto",
  scanner: "Tokenuri emergente",
  portfolio: "Portofoliu virtual",
  journal: "Jurnal & rezultate",
  sources: "Surse & metodologie",
  detail: "Dosar de cercetare",
  advanced: "Cercetare avansată",
  opportunities: "Oportunități timpurii",
};
const categories = {
  launches: "LANSARE / PROIECT",
  listings: "LISTARE",
  public_figures: "PERSOANĂ PUBLICĂ",
  ecosystem: "ECOSISTEM",
};
const decisions = {
  reject: "Respinge",
  monitor: "Monitorizează",
  investigate: "Investighează",
};
const cash = (value) =>
  value === null || value === undefined
    ? "—"
    : new Intl.NumberFormat("ro-RO", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 2,
      }).format(Number(value));
const price = (value) =>
  value === null || value === undefined || !Number.isFinite(Number(value))
    ? "—"
    : new Intl.NumberFormat("ro-RO", { maximumSignificantDigits: 8 }).format(
        Number(value),
      ) + " USD";
const compact = (value) =>
  value === null || value === undefined
    ? "—"
    : "$" +
      new Intl.NumberFormat("en-US", {
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(Number(value));
const number = (value) =>
  value === null || value === undefined
    ? "—"
    : Number(value).toLocaleString("en-US", { maximumSignificantDigits: 7 });
const percent = (value) =>
  value === null || value === undefined
    ? "—"
    : `${Number(value) > 0 ? "+" : ""}${Number(value).toFixed(2)}%`;
const date = (value) =>
  value
    ? new Date(value).toLocaleString("ro-RO", { timeZone: "Europe/Bucharest" })
    : "dată neraportată";
const short = (value) =>
  value.startsWith("asset:")
    ? value.slice(6)
    : value.slice(0, 6) + "…" + value.slice(-5);
function node(tag, text, className) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (className) n.className = className;
  return n;
}
function icon(type = "arrow") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("svg-icon");
  const path = document.createElementNS(svg.namespaceURI, "path");
  const paths = {
    arrow: "M5 19L19 5M5 5h14v14",
    refresh: "M20 11a8 8 0 1 0-2 6M20 4v7h-7",
    overview: "M12 3l9 9-9 9-9-9zM12 8l4 4-4 4-4-4z",
    news: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M12 7v5l4 2",
    market: "M3 17l6-6 4 3 8-10M15 4h6v6",
    scanner: "M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14M15 15l6 6",
    opportunities:
      "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M12 7v10M7 12h10M12 10a2 2 0 1 0 0 4 2 2 0 0 0 0-4",
    portfolio: "M3 5h18v15H3zM3 9h18M14 13h4",
    journal: "M4 5h16M4 12h16M4 19h16",
  };
  path.setAttribute("d", paths[type] || paths.arrow);
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", "1.5");
  path.setAttribute("stroke-linecap", "round");
  path.setAttribute("stroke-linejoin", "round");
  svg.append(path);
  return svg;
}
function decorate(n, text) {
  n.textContent = text.replace(/[↗↻]/g, "").trim();
  if (/[↗↻]/.test(text))
    n.append(icon(text.includes("↻") ? "refresh" : "arrow"));
}
function button(text, className, fn) {
  const b = node("button", undefined, className);
  decorate(b, text);
  b.onclick = fn;
  return b;
}
function link(text, url, className) {
  const a = node("a", text, className);
  if (typeof url === "string" && url.startsWith("https://")) a.href = url;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
}
function coin(asset) {
  const box = node("div", undefined, "coin-name");
  const logo = node(
    "span",
    (asset.symbol || "?").slice(0, 1),
    "coin-logo " +
      (["bitcoin", "ethereum", "solana"].includes(asset.asset_id)
        ? asset.asset_id
        : ""),
  );
  const name = node("div");
  name.append(
    node("strong", asset.name || asset.symbol || "Token"),
    node("small", asset.symbol || "Solana"),
  );
  box.append(logo, name);
  return box;
}
let messageTimeout;
function message(text, success = false) {
  clearTimeout(messageTimeout);
  $("message").textContent = text;
  $("message").hidden = !text;
  $("message").className = "toast" + (success ? " success" : "");
  if (text)
    messageTimeout = setTimeout(() => {
      $("message").hidden = true;
    }, 12000);
}
async function api(path, body) {
  const controller = body === undefined ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), 20000) : null;
  try {
    const response = await fetch(
      path,
      body === undefined
        ? { signal: controller.signal }
        : {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...(state.csrf ? { "X-Pulse-CSRF": state.csrf } : {}),
            },
            body: JSON.stringify(body),
          },
    );
    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error("Serverul nu a returnat un răspuns valid.");
    }
    if (!response.ok)
      if (response.status === 401 && data.authentication_required) {
        showLogin();
        throw new Error("Autentificare necesară.");
      }
    if (!response.ok)
      throw new Error(
        typeof data.detail === "string"
          ? data.detail
          : "Cerere invalidă. Verifică datele introduse.",
      );
    return data;
  } finally {
    clearTimeout(timer);
  }
}
function setHealthDetails(open) {
  $("health-details").hidden = !open;
  $("connection").setAttribute("aria-expanded", String(open));
}
function navigate(page) {
  if (!pageNames[page]) return;
  setHealthDetails(false);
  state.page = page;
  for (const p of Object.keys(pageNames)) $("view-" + p).hidden = p !== page;
  document
    .querySelectorAll(".nav-item[data-page]")
    .forEach((b) => b.classList.toggle("active", b.dataset.page === page));
  $("page-name").textContent = pageNames[page];
  if (location.hash !== "#" + page) history.pushState(null, "", "#" + page);
  window.scrollTo({ top: 0, behavior: "instant" });
  if (page === "advanced") renderAdvanced();
  if (page === "opportunities") renderOpportunities();
}
async function action(b, fn) {
  b.disabled = true;
  message("");
  try {
    await fn();
  } catch (error) {
    message(error.message);
  } finally {
    b.disabled = false;
    await load();
  }
}
function empty(target, text) {
  target.append(node("div", text, "empty-state"));
}
function renderOverview() {
  const target = $("overview-news");
  target.replaceChildren();
  for (const article of state.news.slice(0, 4)) {
    const row = node("article", undefined, "mini-story");
    const symbol = node(
      "span",
      article.source_kind === "primary" ? "◇" : "◷",
      "story-symbol",
    );
    const content = node("div");
    content.append(
      node("h3", article.title),
      node("p", `${article.publisher} · ${date(article.published_at)}`),
    );
    row.append(symbol, content, icon());
    row.onclick = () => {
      navigate("news");
      $("news-search").value = "";
      state.filter = "all";
      renderNews();
      document
        .querySelector(`[data-story-id="${article.id}"]`)
        ?.scrollIntoView({ block: "center" });
    };
    target.append(row);
  }
  if (!state.news.length)
    empty(target, "Se colectează știri. Starea surselor rămâne vizibilă.");
  $("market-glance").replaceChildren();
  for (const asset of state.assets
    .filter((a) =>
      ["bitcoin", "ethereum", "solana", "dogecoin"].includes(a.asset_id),
    )
    .slice(0, 4)) {
    const row = node("div", undefined, "glance-row");
    const prices = node("div", undefined, "glance-prices");
    prices.append(
      node("div", price(asset.price_usd)),
      node(
        "small",
        percent(asset.change_24h),
        (asset.change_24h || 0) >= 0 ? "good" : "bad",
      ),
    );
    row.append(coin(asset), prices);
    row.onclick = () =>
      openAsset(asset.asset_id).catch((e) => message(e.message));
    $("market-glance").append(row);
  }
  if (!state.assets.length)
    empty($("market-glance"), "Nicio observație de piață încă.");
}
function renderNews() {
  const query = $("news-search").value.toLowerCase();
  const stories = state.news.filter(
    (a) =>
      (state.filter === "all" ||
        a.category === state.filter ||
        (state.filter === "primary" && a.source_kind === "primary")) &&
      `${a.title} ${a.publisher} ${a.topic_label}`
        .toLowerCase()
        .includes(query),
  );
  $("stories").replaceChildren();
  for (const article of stories.slice(0, 30)) {
    const card = node("article", undefined, "story");
    card.dataset.storyId = article.id;
    const top = node("div", undefined, "story-top");
    top.append(
      node(
        "span",
        article.source_kind === "primary"
          ? "SURSĂ PRIMARĂ"
          : categories[article.category] || "ȘTIRE",
        "category-pill" +
          (article.source_kind === "primary" ? " primary-source" : ""),
      ),
      node("span", article.seen ? "CITIT" : "NECITIT", "new-label"),
    );
    card.append(top);
    const title = link(article.title, article.url, "story-title");
    title.onclick = () => {
      api(`/api/news/${article.id}/seen`, {})
        .then(load)
        .catch((e) => message(e.message));
    };
    card.append(
      title,
      node(
        "p",
        `${article.publisher} · ${date(article.published_at)} · ${article.source_priority === "review_needed" ? "sursă de verificat" : article.source_priority === "primary" ? "sursă primară" : "redacție cunoscută"}`,
        "story-meta",
      ),
      node(
        "div",
        article.brief ||
          "Titlu raportat de sursă; articolul integral nu a fost validat.",
        "story-brief",
      ),
    );
    const documentAnalysis = article.document_analysis;
    if (documentAnalysis?.state === "read") {
      card.append(
        node(
          "p",
          `Pagina sursei a fost citită ${date(documentAnalysis.observed_at)}${documentAnalysis.stale ? " · observație veche" : ""}. Afirmația nu este validată integral.`,
          "story-meta",
        ),
      );
      if (documentAnalysis.excerpt)
        card.append(
          node("blockquote", documentAnalysis.excerpt, "source-excerpt"),
        );
    } else if (documentAnalysis?.error) {
      card.append(
        node(
          "p",
          "Documentul original nu a putut fi citit; titlul rămâne neverificat.",
          "story-warning",
        ),
      );
    }
    const matches = article.matches || [];
    function appendMatch(match, parent) {
      const asset = match.market,
        general = asset.kind === "market_asset";
      const row = node("div", undefined, "story-token");
      const desc = node("div");
      desc.append(node("strong", `${asset.symbol} · ${asset.name}`));
      desc.append(
        node(
          "small",
          general
            ? "Activ menționat / context de ecosistem"
            : asset.news_relation === "primary_document_contract_mention" ||
                asset.origin_topics?.some((t) => t.startsWith("document:"))
              ? "Contract citat în pagina sursei · afiliere neconfirmată"
              : "Asociere ipotetică după nume",
        ),
      );
      if (match.announcement_check)
        desc.append(
          node(
            "small",
            announcementLabels[match.announcement_check.effective_status] ||
              "Relație neconfirmată",
            "warn",
          ),
        );
      if (match.ai_analysis) {
        const a = match.ai_analysis;
        desc.append(
          node(
            "small",
            a.state === "completed"
              ? `AI · ${aiRelations[a.relationship.effective]}${a.stale ? " · analiză veche" : ""}`
              : "AI · analiză nereușită / incompletă",
            "warn",
          ),
        );
      }
      if (!general)
        desc.append(
          node(
            "small",
            match.chronology === "pool_before_article"
              ? "Pool anterior articolului · tokenul nu este confirmat nou"
              : match.chronology === "pool_after_article"
                ? "Pool după articol · data mintului neconfirmată"
                : "Cronologie necunoscută",
          ),
        );
      const b = button("Analizează pentru paper", "secondary", () =>
        action(b, async () => {
          if (general) await openAsset(asset.asset_id, article);
          else await openToken(asset.address, article, true);
        }),
      );
      row.append(desc, b);
      parent.append(row);
    }
    matches.slice(0, 2).forEach((m) => appendMatch(m, card));
    if (matches.length > 2) {
      const details = node("details");
      details.append(node("summary", `Alte ${matches.length - 2} potriviri`));
      matches.slice(2).forEach((m) => appendMatch(m, details));
      card.append(details);
    }
    if (!matches.length)
      card.append(
        node(
          "p",
          "Încă fără activ asociat în datele colectate. Nu presupunem că există un token cumpărabil.",
          "story-warning",
        ),
      );
    card.append(
      node(
        "p",
        article.source_kind === "primary"
          ? "Publicație a sursei primare. Afirmațiile și fundamentele tokenului necesită verificare separată."
          : "Articol nevalidat integral. Afilierea sau susținerea oficială a unui token nu sunt confirmate.",
        "story-warning",
      ),
    );
    $("stories").append(card);
  }
  if (!stories.length)
    empty(
      $("stories"),
      "Nicio știre în filtrul selectat. Nu înlocuim datele lipsă cu exemple.",
    );
  const statuses = Object.values(state.status?.news?.topics || {}),
    errors = statuses.filter((s) => s.state !== "ok");
  $("news-status").textContent =
    `Actualizare periodică: 5 minute · ${state.status?.news?.running ? "căutare în curs" : `${statuses.length - errors.length} surse/subiecte cu răspuns valid`} · ${errors.length ? `${errors.length} surse cu eroare; vezi metodologia` : "metadata și timestamp-uri păstrate"}`;
  $("unread-badge").textContent = state.news.filter((n) => !n.seen).length;
}
function renderAssets() {
  $("asset-rows").replaceChildren();
  const query = $("asset-search").value.toLowerCase();
  for (const asset of state.assets.filter((a) =>
    (a.name + " " + a.symbol + " " + a.asset_id).toLowerCase().includes(query),
  )) {
    const row = node("tr");
    const first = node("td");
    const b = button("", "token-button", () =>
      openAsset(asset.asset_id).catch((e) => message(e.message)),
    );
    b.append(coin(asset));
    first.append(b);
    first.append(
      node(
        "small",
        asset.freshness?.fresh
          ? "Date recente"
          : "DATE EXPIRATE / NEVERIFICATE",
        asset.freshness?.fresh ? "footnote" : "warn",
      ),
    );
    row.append(
      first,
      node("td", price(asset.price_usd)),
      node(
        "td",
        percent(asset.change_24h),
        (asset.change_24h || 0) >= 0 ? "good" : "bad",
      ),
      node("td", compact(asset.volume_24h)),
      node("td", compact(asset.market_cap)),
    );
    const research = node("td");
    research.append(
      button("Deschide dosarul ↗", "text-button", () =>
        openAsset(asset.asset_id).catch((e) => message(e.message)),
      ),
    );
    row.append(research);
    $("asset-rows").append(row);
  }
  $("assets-empty").hidden = state.assets.length > 0;
  const status = state.status?.crypto_market;
  $("market-status").textContent =
    `CoinGecko · ${status?.state === "ok" ? "observat " + date(status.at) : status?.error || "încă neverificat"}`;
}
function renderTokens() {
  $("tokens").replaceChildren();
  const query = $("search").value.toLowerCase();
  for (const token of state.tokens.filter((t) =>
    (t.address + " " + (t.snapshot?.market.symbol || ""))
      .toLowerCase()
      .includes(query),
  )) {
    const m = token.snapshot?.market,
      a = token.snapshot?.analysis,
      row = node("tr"),
      first = node("td");
    const b = button("", "token-button", () =>
      openToken(token.address).catch((e) => message(e.message)),
    );
    b.append(
      node("strong", m?.symbol || "Fără observație"),
      node("small", short(token.address) + (token.watch ? " · watchlist" : "")),
    );
    first.append(b);
    row.append(
      first,
      node("td", a?.scores.research_priority ?? "—"),
      node("td", cash(m?.liquidity_usd)),
      node("td", cash(m?.volume_5m)),
    );
    const decision = node("td");
    decision.append(
      node(
        "span",
        decisions[a?.action] || "Fără date",
        "badge " + (a?.action || "monitor"),
      ),
    );
    row.append(
      decision,
      node(
        "td",
        token.error ||
          (token.age_seconds !== null
            ? `${token.age_seconds}s · observație`
            : "API nevalidat"),
        token.error ? "warn" : "",
      ),
    );
    $("tokens").append(row);
  }
  $("empty").hidden = state.tokens.length > 0;
}
function renderPortfolio() {
  const p = state.portfolio;
  if (!p) return;
  $("cash").textContent = cash(p.cash);
  $("hero-cash").textContent = cash(p.cash);
  $("portfolio-cash").textContent = cash(p.cash);
  $("equity").textContent = cash(p.estimated_equity_usd);
  $("portfolio-equity").textContent = cash(p.estimated_equity_usd);
  $("realized").textContent = cash(p.realized_pnl_usd);
  $("portfolio-realized").textContent = cash(p.realized_pnl_usd);
  $("open-count").textContent = p.positions.filter((x) => !x.closed_at).length;
  $("positions").replaceChildren();
  $("orders").replaceChildren();
  for (const position of p.positions) {
    const row = node("div", undefined, "position"),
      desc = node("div");
    const asset =
      position.kind === "market_asset"
        ? state.assets.find((a) => a.asset_id === position.address.slice(6))
        : state.tokens.find((t) => t.address === position.address)?.snapshot
            ?.market;
    desc.append(
      coin(
        asset || {
          symbol: position.symbol || short(position.address),
          name: position.name || short(position.address),
        },
      ),
      node(
        "p",
        `${position.closed_at ? "Închis" : "Deschis"} · ${date(position.closed_at || position.entry_at)}`,
      ),
      node("code", position.address),
    );
    const figures = node("div", undefined, "numbers");
    figures.append(
      node("div", `Cost intrare: ${cash(position.entry_cost)}`),
      node("div", `Cantitate: ${number(position.quantity)}`),
    );
    if (position.closed_at)
      figures.append(
        node(
          "div",
          `PnL net realizat: ${cash(position.pnl)}`,
          Number(position.pnl) >= 0 ? "good" : "bad",
        ),
      );
    else {
      const v = position.valuation;
      figures.append(
        node(
          "div",
          `PnL net estimat: ${cash(v?.estimated_unrealized_pnl_usd)}`,
          v?.estimated_unrealized_pnl_usd === null
            ? "warn"
            : Number(v?.estimated_unrealized_pnl_usd) >= 0
              ? "good"
              : "bad",
        ),
      );
      if (v) figures.append(node("div", `Observație: ${date(v.observed_at)}`));
      const b = button("Simulează ieșirea", "secondary", () =>
        action(b, async () => {
          await api(
            `/api/paper/positions/${position.id}/sell?account=${p.account}`,
            {},
          );
          message("Ieșire virtuală înregistrată în jurnal.", true);
        }),
      );
      figures.append(b);
    }
    row.append(desc, figures);
    $("positions").append(row);
  }
  if (!p.positions.length)
    empty(
      $("positions"),
      "Portofoliul este pregătit pentru prima ipoteză. Cercetează un activ și decide tu intrarea.",
    );
  for (const order of p.orders) {
    const box = node("article", undefined, "order");
    const top = node("div", undefined, "order-top");
    top.append(
      node("strong", `${order.side.toUpperCase()} · ${short(order.address)}`),
      node(
        "span",
        order.status === "filled" ? "ORDIN SIMULAT" : "RESPINS",
        "badge " + (order.status === "filled" ? "investigate" : "monitor"),
      ),
    );
    box.append(top, node("p", date(order.at)));
    const context = order.details.entry_context;
    if (context?.news_context)
      box.append(
        node(
          "p",
          `Informația de la intrare: ${context.news_context.title} · ${context.news_context.publisher}`,
        ),
      );
    if (context?.thesis)
      box.append(node("p", `Ipoteza mea: ${context.thesis}`));
    if (order.details.reason)
      box.append(node("p", order.details.reason, "warn"));
    if (order.details.pnl !== undefined)
      box.append(
        node(
          "p",
          `Rezultat net realizat: ${cash(order.details.pnl)}`,
          Number(order.details.pnl) >= 0 ? "good" : "bad",
        ),
      );
    const details = node("details");
    details.append(
      node("summary", "Dovezi, costuri și modelul simulării"),
      node("pre", JSON.stringify(order.details, null, 2)),
    );
    box.append(details);
    $("orders").append(box);
  }
  if (!p.orders.length)
    empty(
      $("orders"),
      "Nu există ordine încă. Jurnalul va păstra și încercările respinse.",
    );
}
function renderSources() {
  $("provider-status").replaceChildren();
  const s = state.status;
  if (!s) return;
  const sources = {
    ...s.providers,
    ...s.market_sources,
    coingecko: s.crypto_market,
  };
  for (const [key, label] of Object.entries({
    dex: "DEX Screener",
    rpc: "Solana RPC",
    goplus: "GoPlus",
    coingecko: "CoinGecko",
  })) {
    const item = sources[key];
    const row = node("div", undefined, "provider");
    row.append(
      node("span", label),
      node(
        "span",
        item?.state === "ok"
          ? `HTTP OK · ${date(item.at)}`
          : item?.error || "Neverificat",
        item?.state === "ok" ? "good" : "warn",
      ),
    );
    $("provider-status").append(row);
  }
  for (const [key, item] of Object.entries(s.news.topics || {})) {
    const row = node("div", undefined, "provider");
    row.append(
      node("span", key),
      node(
        "span",
        item.state === "ok"
          ? `${item.headlines} titluri colectate`
          : item.error,
        item.state === "ok" ? "good" : "warn",
      ),
    );
    $("provider-status").append(row);
  }
  const r = s.rules;
  $("rules").textContent =
    `Capital inițial în cont: ${cash(state.portfolio?.initial_balance)}. Alocare per poziție ≤${Number(r.max_allocation) * 100}%, expunere totală la cost ≤${Number(r.max_exposure) * 100}%, pierderi realizate zilnice ≤${Number(r.daily_loss_limit) * 100}% (UTC). DEX: fee presupus ${Number(r.swap_fee) * 100}% + ${cash(r.network_fee_usd)} rețea; lichiditate minimă ${cash(r.min_liquidity)}. Crypto generale: fee presupus ${Number(r.reference_fee) * 100}%, slippage de referință ${Number(r.reference_slippage) * 100}%.`;
}
function renderHealth() {
  const status = state.status || {},
    errors = [];
  const unknown = [];
  const sources = {
    dex: status.providers?.dex,
    rpc: status.providers?.rpc,
    goplus: status.providers?.goplus,
    ...(status.providers || {}),
    ...(status.market_sources || {}),
    coingecko_catalog: status.crypto_market,
    performance: status.performance,
    announcements: status.announcement_analysis,
    opportunity_engine: status.opportunity_engine,
    story_discovery: status.story_discovery,
    routed_quotes: status.routed_quotes,
    ...Object.fromEntries(
      Object.entries(status.news?.topics || {}).map(([k, v]) => [
        "news_" + k,
        v,
      ]),
    ),
    ...Object.fromEntries(
      Object.entries(status.discovery_sources || {}).map(([k, v]) => [
        "discovery_" + k,
        v,
      ]),
    ),
    ...Object.fromEntries(
      Object.entries(status.onchain_sources || {}).map(([k, v]) => [
        "onchain_" + k,
        v,
      ]),
    ),
  };
  if (status.ai_summaries?.configured) sources.ai = status.ai_summaries;
  if (status.jupiter?.mode === "jupiter")
    sources.jupiter = status.jupiter.status;
  if (status.notifications?.telegram_bot_configured)
    sources.telegram = status.notifications.status;
  for (const [name, item] of Object.entries(sources)) {
    if (item?.state === "disabled") continue;
    if (["error", "partial"].includes(item?.state)) errors.push(name);
    else if (
      !["ok", "running"].includes(item?.state) ||
      !item.at ||
      !Number.isFinite(new Date(item.at).getTime()) ||
      new Date(item.at).getTime() > Date.now()
    )
      unknown.push(name);
    else if (
      Date.now() - new Date(item.at).getTime() >
      (name === "announcements"
        ? 3900000
        : name.startsWith("news_")
          ? 660000
          : name.startsWith("discovery_")
          ? 1320000
          : 300000)
    )
      errors.push(name + " · date vechi");
  }
  for (const [name, item] of Object.entries(status.workers || {}))
    if (item.state === "error") errors.push(name);
  const count = errors.length + Object.keys(state.sectionErrors).length;
  $("connection").replaceChildren(
    node(
      "span",
      undefined,
      count || unknown.length ? "live-dot degraded" : "live-dot",
    ),
    document.createTextNode(
      count
        ? `${count} componente cu eroare`
        : unknown.length
          ? `${unknown.length} componente neverificate`
          : "Surse monitorizate",
    ),
  );
  $("connection").title = "Apasă pentru starea fiecărei componente";
  const details = $("health-components");
  details.replaceChildren();
  for (const [name, item] of Object.entries(sources)) {
    const rawNote = item?.error || (item?.errors || []).join("; ");
    const note =
      typeof rawNote === "string" ? rawNote : JSON.stringify(rawNote);
    details.append(
      node(
        "p",
        `${name}: ${errors.includes(name) ? "eroare / date vechi" : unknown.includes(name) ? "neverificat" : item?.state || "neverificat"} · ${date(item?.at)}${note ? " · " + note : ""}`,
        "footnote",
      ),
    );
  }
  $("section-alerts").replaceChildren();
  for (const [key, value] of Object.entries(state.sectionErrors))
    $("section-alerts").append(
      node(
        "p",
        `${pageNames[key] || key}: ${value}. Ultima actualizare reușită: ${date(state.updated[key])}. Datele afișate pot fi vechi.`,
      ),
    );
  if (errors.length)
    $("section-alerts").append(
      node(
        "p",
        "Surse afectate: " +
          errors.join(", ") +
          ". Apasă indicatorul de stare pentru detalii.",
      ),
    );
  $("section-alerts").hidden = !count;
}
async function load() {
  if (state.loading) {
    state.pendingLoad = true;
    return;
  }
  state.loading = true;
  const account = state.account,
    archive = state.newsArchive;
  const requests = {
    status: "/api/status",
    scanner: "/api/tokens",
    news: `/api/news?archive=${archive}`,
    portfolio: `/api/portfolio?account=${account}`,
    market: "/api/assets",
    performance: `/api/performance?account=${account}`,
  };
  const renderers = {
    status: () => {
      renderSources();
      renderAssets();
      renderNews();
    },
    scanner: renderTokens,
    news: () => {
      $("news-count").textContent = state.news.length;
      $("news-count-caption").textContent =
        state.news.filter((a) => a.source_kind === "primary").length +
        " din surse primare";
      renderNews();
    },
    portfolio: () => {
      renderPortfolio();
      renderSources();
    },
    market: renderAssets,
    performance: renderPerformance,
  };
  try {
    await Promise.allSettled(
      Object.entries(requests).map(async ([key, path]) => {
        try {
          const data = await api(path);
          if (
            (key === "portfolio" || key === "performance") &&
            account !== state.account
          )
            return;
          if (key === "news" && archive !== state.newsArchive) return;
          delete state.sectionErrors[key];
          state.updated[key] = new Date().toISOString();
          state[
            { scanner: "tokens", news: "news", market: "assets" }[key] || key
          ] = data;
          renderers[key]();
          renderOverview();
        } catch (error) {
          state.sectionErrors[key] = error.message;
        }
        renderHealth();
      }),
    );
  } finally {
    state.loading = false;
    if (
      state.pendingLoad ||
      account !== state.account ||
      archive !== state.newsArchive
    ) {
      state.pendingLoad = false;
      load();
    }
  }
}
function renderPerformance() {
  const target = $("performance");
  target.replaceChildren();
  const report = state.performance;
  if (!report) {
    empty(target, "Se așteaptă primele măsurători ale contului.");
    return;
  }
  const stats = node("div", undefined, "detail-stats");
  for (const [label, value] of [
    ["REZULTAT REALIZAT", cash(report.realized_pnl_usd)],
    ["RANDAMENT TOTAL ESTIMAT", percent(report.estimated_total_return_pct)],
    [
      "POZIȚII ÎNCHISE / DESCHISE",
      report.closed_trades + " / " + report.open_trades,
    ],
    ["WIN RATE · DOAR ÎNCHISE", percent(report.win_rate_closed_only_pct)],
    ["DRAWDOWN OBSERVAT", percent(report.max_observed_drawdown_pct)],
    ["ÎNCERCĂRI RESPINSE", report.failed_attempts],
  ])
    stats.append(stat(label, value));
  target.append(stats);
  target.append(
    node(
      "p",
      `${report.signals_total} semnale salvate · ${report.signals_without_trade} fără intrare · ${report.observations_total} observații equity · ${report.missing_valuations} evaluări lipsă în fereastra raportului.`,
      "footnote",
    ),
  );
  const c = report.comparison;
  if (c)
    target.append(
      node(
        "p",
        `Perioadă comparabilă: ${date(c.from)} → ${date(c.to)}. Portofoliu ${percent(c.portfolio_return_pct)}; BTC în scenariul cu fee/slippage presupuse ${percent(c.btc_scenario_return_pct)}.`,
        "footnote",
      ),
    );
  else
    target.append(
      node(
        "p",
        "Comparația cu BTC cere cel puțin două observații aliniate și o evaluare curentă completă.",
        "footnote",
      ),
    );
  target.append(node("p", report.note, "footnote"));
  if (report.history_truncated)
    target.append(
      node(
        "p",
        "Graficul și drawdown-ul acoperă fereastra păstrată în raport, nu întregul istoric.",
        "warn",
      ),
    );
}
function detailBase(asset) {
  const target = $("detail");
  target.replaceChildren();
  const heading = node("div", undefined, "detail-heading");
  const title = node("div");
  title.append(
    coin(asset),
    node("h1", asset.name || asset.symbol),
    node(
      "p",
      asset.kind === "market_asset"
        ? `ID CoinGecko: ${asset.asset_id}`
        : `SOLANA · ${asset.address}`,
    ),
  );
  heading.append(title, node("span", "DOSAR DE CERCETARE", "pill"));
  target.append(heading);
  const grid = node("div", undefined, "detail-grid"),
    left = node("div"),
    right = node("div");
  grid.append(left, right);
  target.append(grid);
  return { left, right };
}
function stat(label, value) {
  const s = node("div", undefined, "detail-stat");
  s.append(node("small", label), node("strong", value));
  return s;
}
function drawHistory(container, history) {
  const prices = history
    .map((h) => Number(h.price_usd))
    .filter(Number.isFinite);
  if (prices.length < 2) {
    container.append(
      node(
        "p",
        "Istoricul local se colectează de acum. Nu desenăm un grafic fictiv.",
        "footnote",
      ),
    );
    return;
  }
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 400 100");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Istoric local de preț");
  svg.classList.add("chart");
  const low = Math.min(...prices),
    high = Math.max(...prices),
    range = high - low || 1;
  const line = document.createElementNS(svg.namespaceURI, "polyline");
  line.setAttribute(
    "points",
    prices
      .map(
        (v, i) =>
          `${5 + (i * 390) / (prices.length - 1)},${90 - ((v - low) / range) * 75}`,
      )
      .join(" "),
  );
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", "currentColor");
  line.setAttribute("stroke-width", "2");
  svg.append(line);
  container.append(
    svg,
    node(
      "p",
      "GRAFIC DIN OBSERVAȚII LOCALE · FĂRĂ DATE INVENTATE",
      "chart-label",
    ),
  );
}
function paperForm(right, asset, allowed = true, article = null) {
  const general = asset.kind === "market_asset",
    orderAccount = general ? "news" : state.account;
  const box = node("section", undefined, "panel padded paper-box");
  box.append(
    node("p", "DECIZIE MANUALĂ / PAPER", "eyebrow"),
    node("h2", "Testează ipoteza"),
    node(
      "p",
      general
        ? "Preț de referință sau bid/ask observat. Comisioanele sunt presupuse; nu este un ordin real."
        : "Simulare DEX aproximativă, cu veto-uri de risc și date noi la intrare.",
    ),
  );
  box.append(node("label", "SUMA ORDINULUI · USD"));
  const wrap = node("div", undefined, "order-amount"),
    amount = node("input");
  amount.type = "number";
  amount.min = "2";
  amount.step = ".01";
  amount.value = orderAccount === "news" ? "50" : "5";
  amount.setAttribute("aria-label", "Suma paper în USD");
  wrap.append(amount, node("span", "USD"));
  box.append(wrap);
  box.append(node("label", "DE CE CONSIDERI INTRAREA?"));
  const thesis = node("textarea");
  thesis.placeholder = "Ce informație contează? Ce ar invalida ipoteza?";
  thesis.maxLength = 1000;
  thesis.setAttribute("aria-label", "Ipoteza de intrare");
  box.append(thesis);
  let signalId = null;
  const signal = button("Salvează semnal", "secondary", () =>
    action(signal, async () => {
      const body = {
        account: orderAccount,
        news_id: article?.id || null,
        thesis: thesis.value,
      };
      const endpoint = general
        ? `/api/assets/${asset.asset_id}/signal`
        : `/api/tokens/${asset.address}/signal`;
      buy.disabled = true;
      signalId = null;
      const saved = await api(endpoint, body);
      signalId = saved.id;
      allowed = saved.snapshot?.analysis?.paper_allowed === true;
      signal.textContent = `Semnal #${saved.id} salvat`;
      if (saved.snapshot)
        message(
          `Semnal salvat la prețul ${price(saved.snapshot.market.price_usd)}. ${allowed ? "Datele permit simularea; așteaptă 3 secunde." : "Intrare blocată de dovezile actuale."}`,
          allowed,
        );
      setTimeout(() => {
        if (allowed && signalId === saved.id) buy.disabled = false;
      }, 3000);
    }),
  );
  const buy = button("Simulează intrarea", "primary", async () => {
    await action(buy, async () => {
      if (!signalId) throw new Error("Salvează mai întâi semnalul.");
      const body = general
        ? {
            asset_id: asset.asset_id,
            signal_id: signalId,
            amount_usd: amount.value,
          }
        : {
            address: asset.address,
            signal_id: signalId,
            amount_usd: amount.value,
            account: orderAccount,
          };
      await api(general ? "/api/paper/assets/buy" : "/api/paper/buy", body);
      signalId = null;
      message(
        "Ordin virtual înregistrat. Urmărim rezultatul în portofoliu.",
        true,
      );
      navigate("portfolio");
    });
    buy.disabled = true;
  });
  buy.disabled = true;
  thesis.addEventListener("input", () => {
    signalId = null;
    buy.disabled = true;
    signal.textContent = "Salvează semnal";
  });
  box.append(
    signal,
    buy,
    node(
      "p",
      "Semnalul precedă intrarea cu minimum 3 secunde. Fill-ul folosește date noi și poate fi respins.",
      "footnote",
    ),
  );
  if (!allowed)
    box.append(node("p", "Intrare blocată de verificările actuale.", "warn"));
  right.append(box);
}
async function openAsset(id, article = null) {
  state.back = state.page === "detail" ? state.back : state.page;
  state.selection = { kind: "asset", id, article };
  state.account = "news";
  $("paper-account").value = "news";
  const data = await api(`/api/assets/${encodeURIComponent(id)}`);
  navigate("detail");
  const asset = data.asset;
  const { left, right } = detailBase(asset);
  const pricing = node("section", undefined, "panel padded");
  pricing.append(
    node("p", "PIAȚĂ OBSERVATĂ", "eyebrow"),
    node("h2", "Date și prospețime"),
  );
  pricing.append(
    node(
      "p",
      `Volume și capitalizare: ${date(asset.market_source_updated_at || asset.source_updated_at)}.`,
      "footnote",
    ),
  );
  if (asset.metadata_error)
    pricing.append(
      node("p", `Metadata păstrate din cache: ${asset.metadata_error}`, "warn"),
    );
  const stats = node("div", undefined, "detail-stats");
  stats.append(
    stat("PREȚ USD", price(asset.price_usd)),
    stat("VARIAȚIE 24H", percent(asset.change_24h)),
    stat("VOLUM 24H", compact(asset.volume_24h)),
    stat("CAPITALIZARE", compact(asset.market_cap)),
  );
  pricing.append(
    stats,
    node(
      "p",
      `${asset.book ? "Preț mid Coinbase L1; volume/capitalizare CoinGecko" : "Preț de referință CoinGecko"} · sursa de preț actualizată ${date(asset.source_updated_at)}. Acest activ nu este prezentat drept lansare nouă.`,
    ),
  );
  drawHistory(
    pricing,
    data.history.filter((h) => !h.book),
  );
  left.append(pricing);
  if (article) {
    const context = node("section", undefined, "panel padded");
    context.append(
      node("p", "INFORMAȚIA CARE A GENERAT IPOTEZA", "eyebrow"),
      link(article.title, article.url, "story-title"),
      node("p", `${article.publisher} · ${date(article.published_at)}`),
      node(
        "p",
        "Menționarea activului / contextul de ecosistem nu confirmă o recomandare sau o susținere oficială.",
      ),
    );
    left.append(context);
  }
  const research = node("section", undefined, "panel padded");
  research.append(node("h2", "Documente și identitate raportate"));
  research.append(
    node(
      "p",
      "Nu clasificăm proiectul ca solid doar pentru că are preț, volum sau un nume cunoscut.",
      "footnote",
    ),
  );
  const documents = node("div");
  const profileButton = button(
    "Verifică documentele și identitatea",
    "secondary",
    () =>
      action(profileButton, async () => {
        const profile = await api(`/api/assets/${id}/profile`);
        documents.replaceChildren();
        for (const doc of profile.documents) {
          const row = link("", doc.url, "venue");
          row.append(
            node("strong", doc.label),
            node("small", new URL(doc.url).hostname),
            icon(),
          );
          documents.append(row);
        }
        documents.append(
          node(
            "p",
            "Linkuri și contracte declarate în CoinGecko. Nu sunt validări independente de produs, echipă sau audit.",
            "footnote",
          ),
        );
        if (Object.keys(profile.contracts).length)
          documents.append(
            node(
              "pre",
              JSON.stringify(profile.contracts, null, 2),
              "history-row",
            ),
          );
      }),
  );
  research.append(profileButton, documents);
  if (asset.watch) {
    const unwatch = button("Scoate din watchlist crypto", "text-button", () =>
      action(unwatch, async () => {
        await api(`/api/assets/${id}/unwatch`, {});
        await openAsset(id, article);
      }),
    );
    research.append(unwatch);
  }
  left.append(research);
  const venues = node("section", undefined, "panel padded");
  venues.append(
    node("h2", "Unde există tranzacționare?"),
    node(
      "p",
      "Piețe raportate de furnizor. Nu confirmă accesul înainte de o listare viitoare.",
    ),
  );
  const list = node("div"),
    b = button("Verifică piețele raportate ↗", "secondary", () =>
      action(b, async () => {
        const result = await api(`/api/assets/${id}/venues`);
        list.replaceChildren();
        for (const v of result.venues) {
          const row = link("", v.url, "venue");
          const desc = node("div");
          desc.append(
            node("strong", v.name),
            node("small", `${v.pair} · CoinGecko · ${date(v.observed_at)}`),
          );
          row.append(desc, icon());
          list.append(row);
        }
        if (!result.venues.length)
          empty(
            list,
            "Nu am primit o piață validă. Nu inventăm un loc de cumpărare.",
          );
      }),
    );
  venues.append(b, list);
  left.append(venues);
  await renderAnnouncements(
    left,
    asset.address,
    data.case.announcements,
    article,
  );
  await renderAI(left, asset.address, article);
  await renderFundamentals(left, asset.address);
  await renderCase(left, asset.address, data.case);
  paperForm(right, asset, asset.freshness?.fresh !== false, article);
  await load();
}
async function openToken(address, article = null, refresh = false) {
  state.back = state.page === "detail" ? state.back : state.page;
  state.selection = { kind: "token", id: address, article };
  if (article) {
    state.account = "news";
    $("paper-account").value = "news";
  }
  if (refresh) await api("/api/tokens", { address });
  const data = await api(`/api/tokens/${address}`);
  navigate("detail");
  const market = data.latest.market,
    analysis = data.latest.analysis;
  const { left, right } = detailBase(market);
  const panel = node("section", undefined, "panel padded");
  panel.append(node("h2", "Piață și identitate"));
  const stats = node("div", undefined, "detail-stats");
  stats.append(
    stat("PREȚ OBSERVAT", "$" + number(market.price_usd)),
    stat("LICHIDITATE RAPORTATĂ", cash(market.liquidity_usd)),
  );
  panel.append(
    stats,
    node(
      "p",
      `Pool ${market.dex} · creat ${date(market.pool_created_at)} · observație ${date(market.observed_at)}`,
    ),
    node("p", "Data creării mintului și afilierea oficială sunt neconfirmate."),
  );
  const links = node("div", undefined, "detail-links");
  links.append(
    link(
      "Piața raportată ↗",
      `https://dexscreener.com/solana/${encodeURIComponent(market.pair_address)}`,
    ),
    link(
      "Explorer / contract ↗",
      `https://solscan.io/token/${encodeURIComponent(address)}`,
    ),
  );
  panel.append(links);
  left.append(panel);
  if (article) {
    const context = node("section", undefined, "panel padded");
    context.append(
      node("h2", "Știrea de la începutul ipotezei"),
      link(article.title, article.url, "story-title"),
      node(
        "p",
        "Asociere ipotetică după nume. Nu dovedește că evenimentul a creat tokenul.",
      ),
    );
    left.append(context);
  }
  const risks = node("section", undefined, "panel padded");
  risks.append(node("h2", "Dovezi și veto-uri"));
  for (const [name, items, cls] of [
    ["Veto-uri", analysis.critical, "bad"],
    ["Observații RPC", analysis.positive, "good"],
    ["Necunoscute", analysis.unknown, "warn"],
    ["Limite", analysis.warnings, "warn"],
  ]) {
    if (!items.length) continue;
    risks.append(node("h3", name, cls));
    const list = node("ul");
    items.forEach((i) => list.append(node("li", i)));
    risks.append(list);
  }
  const refreshButton = button("Actualizează dovezile ↻", "secondary", () =>
    action(refreshButton, async () => {
      await api(`/api/tokens/${address}/refresh`, {});
      await openToken(address, article);
    }),
  );
  risks.append(refreshButton);
  if (data.watch) {
    const unwatch = button("Scoate din watchlist", "text-button", () =>
      action(unwatch, async () => {
        await api(`/api/tokens/${address}/unwatch`, {});
        await openToken(address, article);
      }),
    );
    risks.append(unwatch);
  }
  left.append(risks);
  const scores = node("section", undefined, "panel padded");
  scores.append(node("h2", "Scoruri de cercetare"));
  for (const [key, label] of Object.entries({
    security_risk: "Risc total de securitate",
    activity: "Activitate",
    momentum: "Momentum",
    liquidity_exit: "Lichiditate / ieșire",
    research_priority: "Prioritate research",
  })) {
    const row = node("div", undefined, "score-row");
    row.append(
      node("span", label),
      node(
        "strong",
        analysis.scores[key] === null
          ? "necuantificat"
          : analysis.scores[key] + "/100",
      ),
    );
    scores.append(row);
  }
  left.append(scores);
  await renderAnnouncements(left, address, null, article);
  await renderAI(left, address, article);
  await renderFundamentals(left, address);
  await renderCase(left, address);
  paperForm(right, market, analysis.paper_allowed, article);
  await load();
}
document.addEventListener("click", (event) => {
  const b = event.target.closest("[data-page]");
  if (b) {
    event.preventDefault();
    navigate(b.dataset.page);
  }
});
$("news-filters").onclick = (event) => {
  const b = event.target.closest("[data-filter]");
  if (!b) return;
  state.filter = b.dataset.filter;
  document
    .querySelectorAll("[data-filter]")
    .forEach((x) => x.classList.toggle("active", x === b));
  renderNews();
};
$("news-search").oninput = renderNews;
$("asset-search").oninput = renderAssets;
$("search").oninput = renderTokens;
$("news-button").onclick = () =>
  action($("news-button"), async () => {
    await api("/api/news/refresh", {});
  });
$("market-button").onclick = () =>
  action($("market-button"), async () => {
    await api("/api/assets/refresh", {});
  });
$("scan-button").onclick = () =>
  action($("scan-button"), async () => {
    await api("/api/scan", {});
  });
$("refresh-all").onclick = () =>
  action($("refresh-all"), async () => {
    await api("/api/assets/refresh", {});
    await api("/api/news/refresh", {});
  });
$("connection").onclick = () => {
  setHealthDetails($("health-details").hidden);
};
$("health-close").onclick = () => {
  setHealthDetails(false);
  $("connection").focus();
};
$("add-form").onsubmit = (event) => {
  event.preventDefault();
  const b = event.currentTarget.querySelector("button");
  action(b, async () => {
    const address = $("address").value.trim();
    await api("/api/tokens", { address });
    $("address").value = "";
    await openToken(address);
  });
};
$("paper-account").onchange = async () => {
  state.account = $("paper-account").value;
  state.portfolio = null;
  state.performance = null;
  for (const id of [
    "cash",
    "hero-cash",
    "portfolio-cash",
    "equity",
    "portfolio-equity",
    "realized",
    "portfolio-realized",
  ])
    $(id).textContent = "—";
  $("positions").replaceChildren();
  await load();
};
$("detail-back").onclick = () =>
  navigate(state.back === "detail" ? "news" : state.back);
document.querySelectorAll(".nav-item[data-page]").forEach((b) => {
  const span = b.querySelector("span");
  if (span) span.replaceChildren(icon(b.dataset.page));
});
document.querySelectorAll("button").forEach((b) => {
  if (/[↗↻]/.test(b.textContent)) decorate(b, b.textContent);
});
navigate(
  pageNames[location.hash.slice(1)] && location.hash !== "#detail"
    ? location.hash.slice(1)
    : "opportunities",
);
startApplication();
setInterval(load, 15000);
setInterval(() => {
  if (
    state.page === "opportunities" &&
    !document.body.classList.contains("locked")
  )
    renderOpportunities();
}, 15000);

let fieldCounter = 0;
function inputField(parent, label, type = "text") {
  const id = "field-" + ++fieldCounter,
    l = node("label", label),
    input = type === "textarea" ? node("textarea") : node("input");
  if (type !== "textarea") input.type = type;
  input.id = id;
  l.htmlFor = id;
  input.setAttribute("aria-label", label);
  parent.append(l, input);
  return input;
}
const aiRelations = {
  issuer_announcement: "Ipoteză: anunț de emitere a tokenului",
  listing_announcement: "Ipoteză: anunț de listare",
  unrelated_or_namesake: "Eveniment separat sau nume asemănător",
  contradicted: "Afiliere negată sau avertizare în document",
  insufficient_evidence: "Dovezi insuficiente pentru asociere",
};
async function renderAI(parent, address, article) {
  const box = node("section", undefined, "panel padded ai-panel");
  parent.append(box);
  const endpoint = `/api/research/${encodeURIComponent(address)}/ai`;
  try {
    const data = await api(
      endpoint + (article ? `?news_id=${article.id}` : ""),
    );
    box.append(
      node("p", "INTERPRETARE CU SURSE", "eyebrow"),
      node("h2", "Ce spune știrea, de fapt?"),
    );
    box.append(
      node(
        "p",
        "AI explică documentul în română și propune întrebări de cercetare. Citările sunt controlate ca text; sensul și adevărul afirmațiilor cer evaluare. Ordinele paper rămân decizia ta.",
        "footnote",
      ),
    );
    const stateText = node("p", undefined, "footnote");
    const showStatus = (s) => {
      stateText.textContent = `${s.provider === "disabled" ? "AI oprit" : `${s.provider} · ${s.model}`} · ${s.requests_today}/${s.daily_request_limit} încercări azi (UTC). ${s.error || (s.state === "ok" ? "Conexiune testată; vezi rezultatul fiecărei analize." : "Disponibilitatea motorului nu este testată.")}`;
      if (s.configuration_error)
        stateText.textContent += " " + s.configuration_error;
    };
    showStatus(data.status);
    box.append(stateText);
    const setup = node("details", undefined, "ai-setup");
    setup.open = !data.status.configured;
    setup.append(node("summary", "Configurează motorul AI"));
    const configForm = node("form", undefined, "evidence-form");
    const provider = node("select");
    provider.setAttribute("aria-label", "Motor AI");
    for (const [value, title] of Object.entries({
      disabled: "Oprit",
      ollama: "Ollama pe acest PC",
      openai: "OpenAI API",
    })) {
      const o = node("option", title);
      o.value = value;
      provider.append(o);
    }
    provider.value = data.status.provider;
    const model = inputField(configForm, "Numele exact al modelului AI");
    model.value = data.status.model;
    model.placeholder = "Numele din ollama list sau din contul API";
    configForm.prepend(provider);
    const limit = inputField(
      configForm,
      "Limită de încercări AI pe zi (UTC)",
      "number",
    );
    limit.min = "1";
    limit.max = "1000";
    limit.value = data.status.daily_request_limit;
    const save = button("Salvează configurația AI", "secondary", () => {});
    save.type = "submit";
    configForm.onsubmit = (e) => {
      e.preventDefault();
      action(save, async () => {
        const s = await api("/api/ai/config", {
          provider: provider.value,
          model: model.value.trim(),
          daily_request_limit: Number(limit.value),
        });
        showStatus(s);
        message(
          "Configurație salvată. Testează conexiunea înainte de analiză.",
          true,
        );
      });
    };
    const connect = button("Testează conexiunea AI", "secondary", () =>
      action(connect, async () => {
        const s = await api("/api/ai/connection", {});
        showStatus(s);
        message(
          "Motorul și modelul răspund. Generarea și calitatea se verifică separat prin analize.",
          true,
        );
      }),
    );
    configForm.append(save, connect);
    if (data.status.environment_override) {
      for (const el of [provider, model, limit, save]) el.disabled = true;
      configForm.append(
        node(
          "p",
          "Configurația este stabilită prin variabilele de mediu.",
          "footnote",
        ),
      );
    }
    setup.append(
      configForm,
      node(
        "p",
        "Ollama trebuie instalat separat, cu un model disponibil, la portul local 11434. OpenAI cere PULSE_AI_API_KEY în mediul procesului și credit API separat; cheia nu se introduce aici sau în chat. API-ul primește documentul public și identitatea activului, fără portofoliu sau notițele tale. Limita de cereri nu reprezintă un plafon monetar.",
        "footnote",
      ),
    );
    box.append(setup);
    const form = node("form", undefined, "evidence-form ai-form");
    const url = inputField(
      form,
      "Document pentru analiza AI (URL HTTPS)",
      "url",
    );
    url.required = true;
    url.value =
      article?.url || data.history[0]?.payload?.bundle?.sources?.[0]?.url || "";
    const chain = node("select");
    chain.setAttribute("aria-label", "Chain pentru analiza AI");
    for (const value of [
      "",
      "solana",
      "ethereum",
      "base",
      "polygon",
      "bsc",
      "arbitrum",
      "avalanche",
    ]) {
      const o = node("option", value || "Fără contract ales / monedă nativă");
      o.value = value;
      chain.append(o);
    }
    form.append(chain);
    const contract = inputField(form, "Contract pentru analiza AI (opțional)");
    if (!address.startsWith("asset:")) {
      chain.value = "solana";
      chain.disabled = true;
      contract.value = address;
      contract.readOnly = true;
    }
    const run = button("Analizează documentul cu AI", "primary", () => {});
    run.type = "submit";
    const results = node("div", undefined, "ai-results");
    const draw = (history) => {
      results.replaceChildren();
      if (!history.length) {
        empty(
          results,
          "Nicio analiză AI pentru acest context. Nu afișăm o interpretare simulată.",
        );
        return;
      }
      for (const r of history.slice(0, 3)) {
        const p = r.payload,
          row = node("article", undefined, "evidence-item ai-result");
        row.append(
          node(
            "p",
            `${date(r.at)} · ${p.config.provider} / ${p.config.model}${r.stale ? " · mai veche de 24h; cere o analiză nouă" : ""}`,
            "footnote",
          ),
        );
        if (r.state !== "completed") {
          row.append(
            node(
              "p",
              p.error || "Analiză nefinalizată; rezultatul este necunoscut.",
              "warn",
            ),
          );
          results.append(row);
          continue;
        }
        row.append(
          node(
            "strong",
            aiRelations[p.relationship.effective] || p.relationship.effective,
          ),
        );
        const statement = (s) => {
          row.append(node("p", s.text_ro));
          for (const c of s.citations) {
            const source = p.bundle.sources.find((s) => s.id === c.source_id);
            row.append(node("blockquote", c.quote, "ai-citation"));
            if (source)
              row.append(
                link(
                  `${source.publisher || source.id} · sursa citatului ↗`,
                  source.url,
                  "text-button",
                ),
              );
          }
        };
        statement(p.interpretation.event_summary);
        statement(p.interpretation.relationship_reason);
        for (const reason of p.relationship.limitations)
          row.append(node("p", reason, "warn"));
        const facts = node("details");
        facts.append(node("summary", "Afirmații relatate și citările lor"));
        const factsBody = node("div");
        for (const fact of p.interpretation.facts) {
          factsBody.append(node("p", fact.text_ro));
          for (const c of fact.citations)
            factsBody.append(node("blockquote", c.quote, "ai-citation"));
        }
        facts.append(factsBody);
        row.append(facts);
        for (const [label, values] of [
          ["Ce trebuie cercetat", p.interpretation.research_questions],
          ["Riscuri și limite", p.interpretation.risks],
        ]) {
          row.append(node("h3", label));
          const list = node("ul");
          for (const value of values) list.append(node("li", value));
          row.append(list);
        }
        const source = p.bundle.sources[0];
        row.append(
          node(
            "p",
            `Document observat ${date(source.observed_at)} · publicare declarată ${date(source.published_at_reported)}${source.truncated ? " · text parțial trimis modelului" : ""}. Afilierea, fundamentele și randamentul nu sunt validate de această analiză.`,
            "footnote",
          ),
        );
        results.append(row);
      }
    };
    draw(data.history);
    form.onsubmit = (e) => {
      e.preventDefault();
      action(run, async () => {
        run.textContent = "AI citește documentul…";
        try {
          const r = await api(endpoint, {
            source_url: url.value.trim(),
            news_id: article?.id || null,
            chain: chain.value || null,
            contract: contract.value.trim() || null,
          });
          const fresh = await api(
            endpoint + (article ? `?news_id=${article.id}` : ""),
          );
          draw(fresh.history);
          showStatus(fresh.status);
          if (r.state !== "completed")
            throw new Error(r.payload.error || "Analiza nu s-a finalizat.");
          message(
            "Analiză salvată cu sursele folosite. Un semnal nou va captura această interpretare.",
            true,
          );
        } finally {
          run.textContent = "Analizează documentul cu AI";
        }
      });
    };
    form.append(run);
    box.append(form, results);
  } catch (error) {
    box.append(node("p", error.message, "warn"));
  }
}
async function renderAnnouncements(parent, address, provided, article) {
  const box = node("section", undefined, "panel padded announcement-panel");
  parent.append(box);
  let retained = null;
  async function draw(data) {
    box.replaceChildren();
    box.append(
      node("p", "SURSĂ ORIGINALĂ / CONTRACT", "eyebrow"),
      node("h2", "Ce legătură are anunțul cu moneda?"),
      node("p", data.note, "footnote"),
    );
    if (article)
      box.append(
        node(
          "p",
          `Verificarea se leagă numai de știrea: ${article.title}`,
          "footnote",
        ),
      );
    const checks = article
      ? data.checks.filter((c) => c.news_id === article.id)
      : data.checks;
    for (const check of checks.slice(0, 5)) {
      const p = check.payload,
        row = node("article", undefined, "evidence-item announcement-result");
      row.append(
        node(
          "strong",
          announcementLabels[check.effective_status] || check.effective_status,
        ),
        node(
          "p",
          `${date(check.at)} · ${p.chain} · ${p.relationship === "listing" ? "relație de listare" : p.relationship === "issuer" ? "relație cu emitentul, evaluată manual" : "relație neconfirmată"}`,
        ),
        node("code", p.contract),
        link("Documentul verificat ↗", p.source_url),
      );
      if (p.document)
        row.append(
          node(
            "p",
            `${p.document.publisher} · ${p.document.title || "titlu neraportat"}`,
          ),
          node(
            "p",
            `Document observat: ${date(p.document.observed_at)}. Data publicării raportată de pagină: ${date(p.document.published_at_reported)}.`,
            "footnote",
          ),
        );
      if (p.observations?.excerpt)
        row.append(node("blockquote", p.observations.excerpt));
      if (p.observations)
        row.append(
          node(
            "p",
            `Contract exact: ${p.observations.exact_contract_found ? "găsit" : "negăsit"}. Chain-uri raportate în context: ${p.observations.networks_reported.join(", ") || "necunoscute"}.`,
            "footnote",
          ),
        );
      if (p.observations?.text_truncated)
        row.append(
          node(
            "p",
            "Text extras parțial; rezultatul poate fi incomplet.",
            "warn",
          ),
        );
      if (p.error) row.append(node("p", p.error, "warn"));
      row.append(
        node(
          "p",
          "Nu confirmă susținerea unei persoane, adevărul integral al anunțului sau calitatea investiției.",
          "footnote",
        ),
      );
      box.append(row);
    }
    if (!checks.length)
      box.append(
        node(
          "p",
          "Nu există încă o verificare a documentului pentru acest context. Potrivirea de nume rămâne o ipoteză.",
          "footnote",
        ),
      );
    for (const approval of data.approvals) {
      const p = approval.payload,
        row = node("article", undefined, "evidence-item");
      row.append(
        node("strong", `${p.publisher} · ${p.host}`),
        node(
          "p",
          `${p.relation === "listing" ? "Listare" : "Emitent"} · ${p.chain} · ${approval.active ? "evaluare manuală activă" : approval.revoked_at ? "evaluare retrasă" : "evaluare expirată"}`,
        ),
        node("code", p.contract),
        node("p", p.reviewer_note),
        link("Justificarea evaluării ↗", p.proof_url),
      );
      if (approval.active) {
        const revoke = button("Retrage evaluarea sursei", "text-button", () =>
          action(revoke, async () => {
            const result = await api(
              `/api/research/${encodeURIComponent(address)}/source-approvals/${approval.id}/revoke`,
              {},
            );
            await draw(result.announcements);
          }),
        );
        row.append(revoke);
      }
      box.append(row);
    }
    const catalog = node("details");
    catalog.append(
      node("summary", "Surse acceptate pentru citirea documentelor"),
    );
    for (const source of data.sources)
      catalog.append(
        node(
          "p",
          `${source.publisher} · ${source.host} · ${source.kind === "editorial" ? "redacție; nu poate fi aprobată ca emitent" : "sursă primară; relația cu moneda cere evaluare"}. Acces: ${source.status?.state === "ok" ? "citire reușită la " + date(source.status.at) : source.status?.state === "error" ? "indisponibil la ultima cerere" : "încă neverificat"}.`,
          "footnote",
        ),
      );
    box.append(catalog);
    const form = node("form", undefined, "evidence-form");
    const url = inputField(form, "URL-ul anunțului original", "url");
    url.required = true;
    const chain = node("select");
    chain.setAttribute("aria-label", "Chain pentru verificarea anunțului");
    chain.required = true;
    const chooseChain = node("option", "Alege chain-ul contractului");
    chooseChain.value = "";
    chooseChain.disabled = true;
    chain.append(chooseChain);
    for (const key of [
      "solana",
      "ethereum",
      "base",
      "polygon",
      "bsc",
      "arbitrum",
      "avalanche",
    ]) {
      const option = node("option", key);
      option.value = key;
      chain.append(option);
    }
    form.append(chain);
    const contract = inputField(form, "Contractul exact de verificat");
    contract.required = true;
    const general = address.startsWith("asset:");
    if (!general) {
      contract.value = address;
      contract.readOnly = true;
      chain.value = "solana";
      chain.disabled = true;
    }
    if (retained) {
      url.value = retained.source_url;
      chain.value = retained.chain;
      contract.value = retained.contract;
    } else if (
      article &&
      data.sources.some((s) => new URL(article.url).hostname === s.host)
    )
      url.value = article.url;
    const body = () => ({
      source_url: url.value.trim(),
      chain: chain.value,
      contract: contract.value.trim(),
      news_id: article?.id || null,
    });
    if (general) {
      const loadContracts = button(
        "Încarcă contractele raportate",
        "secondary",
        () =>
          action(loadContracts, async () => {
            const profile = await api(
              `/api/assets/${address.slice(6)}/profile`,
            );
            const mapping = {
              ethereum: "ethereum",
              base: "base",
              "polygon-pos": "polygon",
              "binance-smart-chain": "bsc",
              "arbitrum-one": "arbitrum",
              avalanche: "avalanche",
              solana: "solana",
            };
            const found = Object.entries(profile.contracts).filter(
              ([k, v]) => mapping[k] && v,
            );
            choices.replaceChildren();
            for (const [key, value] of found) {
              const select = button(
                `${mapping[key]} · ${short(value)}`,
                "text-button",
                () => {
                  chain.value = mapping[key];
                  contract.value = value;
                },
              );
              select.type = "button";
              choices.append(select);
            }
            if (!found.length)
              choices.append(
                node(
                  "p",
                  "Nu avem un contract raportat pentru acest activ. O monedă nativă, precum BTC, nu primește un contract inventat.",
                  "footnote",
                ),
              );
          }),
      );
      const choices = node("div", undefined, "panel-actions");
      loadContracts.type = "button";
      form.append(loadContracts, choices);
    }
    form.append(
      node(
        "p",
        "Folosește pagina originală din catalog. Un link Google News sau un nume asemănător nu confirmă emitentul.",
        "footnote",
      ),
    );
    const verify = button(
      "Verifică anunțul și contractul",
      "primary",
      () => {},
    );
    verify.type = "submit";
    form.append(verify);
    form.onsubmit = (event) => {
      event.preventDefault();
      action(verify, async () => {
        retained = body();
        const result = await api(
          `/api/research/${encodeURIComponent(address)}/verify-announcement`,
          retained,
        );
        const dossier = await api(
          `/api/research/${encodeURIComponent(address)}`,
        );
        await draw(dossier.announcements);
        message(
          announcementLabels[result.effective_status] ||
            "Verificare înregistrată.",
        );
      });
    };
    const approvalDetails = node("details");
    approvalDetails.append(
      node("summary", "Evaluează manual relația sursei cu această monedă"),
    );
    const relation = node("select");
    relation.setAttribute("aria-label", "Relația sursei");
    for (const [value, label] of [
      ["issuer", "Anunț al emitentului"],
      ["listing", "Anunț de listare al pieței"],
    ]) {
      const option = node("option", label);
      option.value = value;
      relation.append(option);
    }
    approvalDetails.append(relation);
    const proof = inputField(
      approvalDetails,
      "Link de justificare pentru identitatea sursei",
      "url",
    );
    const note = inputField(
      approvalDetails,
      "Cum ai verificat relația cu emitentul sau piața?",
      "textarea",
    );
    const ack = node("input");
    ack.type = "checkbox";
    ack.setAttribute("aria-label", "Am verificat manual identitatea sursei");
    const ackLabel = node("label", undefined, "archive-control");
    ackLabel.append(
      ack,
      document.createTextNode(
        "Am verificat manual identitatea sursei și relația cu acest contract. Numele și prezența adresei în pagină nu sunt suficiente.",
      ),
    );
    approvalDetails.append(ackLabel);
    const approve = button("Salvează evaluarea sursei", "secondary", () =>
      action(approve, async () => {
        if (!form.reportValidity()) return;
        if (!ack.checked)
          throw new Error(
            "Evaluarea sursei cere verificarea manuală a identității și relației.",
          );
        retained = body();
        const result = await api(
          `/api/research/${encodeURIComponent(address)}/source-approvals`,
          {
            ...retained,
            relation: relation.value,
            proof_url: proof.value.trim(),
            reviewer_note: note.value,
            reviewed: true,
          },
        );
        await draw(result.announcements);
        message(
          "Evaluare manuală salvată. Reverifică documentul și creează un semnal nou pentru dosarul actualizat.",
          true,
        );
      }),
    );
    approve.type = "button";
    approvalDetails.append(approve);
    form.append(approvalDetails);
    box.append(form);
  }
  try {
    await draw(
      provided ||
        (await api(`/api/research/${encodeURIComponent(address)}`))
          .announcements,
    );
  } catch (error) {
    box.append(node("p", error.message, "warn"));
  }
}
async function renderCase(parent, address, provided) {
  const box = node("section", undefined, "panel padded evidence-panel");
  parent.append(box);
  async function draw(data) {
    box.replaceChildren();
    box.append(node("h2", "Dosar cu dovezi"), node("p", data.note, "footnote"));
    for (const check of data.checks) {
      const row = node("div", undefined, "check-row");
      row.append(
        node("span", check.label),
        node(
          "span",
          {
            unknown: "NECUNOSCUT",
            supported_manual: "SUSȚINUT · MANUAL",
            disputed: "CONTESTAT",
          }[check.status] || check.status,
        ),
      );
      box.append(row);
    }
    for (const record of data.evidence) {
      const e = record.payload,
        row = node("article", undefined, "evidence-item");
      row.append(
        node("strong", e.claim),
        node(
          "p",
          `${e.category} · ${record.revoked_at ? "RETRAS" : e.status + " · evaluare manuală"} · ${date(record.at)}`,
        ),
        node("p", e.reviewer_note),
      );
      if (e.source_url) row.append(link("Sursa citată ↗", e.source_url));
      if (e.excerpt) row.append(node("blockquote", e.excerpt));
      if (e.contract)
        row.append(node("code", (e.chain || "") + " · " + e.contract));
      if (!record.revoked_at) {
        const revoke = button("Retrage evaluarea", "text-button", () =>
          action(revoke, async () => {
            const updated = await api(
              `/api/research/${encodeURIComponent(address)}/evidence/${record.id}/revoke`,
              {},
            );
            await draw(updated);
          }),
        );
        row.append(revoke);
      }
      box.append(row);
    }
    const form = node("form", undefined, "evidence-form"),
      category = node("select"),
      status = node("select"),
      chain = node("select");
    for (const [key, label] of Object.entries({
      identity: "Identitate / contract",
      announcement: "Anunț original",
      product: "Produs",
      team: "Echipă",
      tokenomics: "Tokenomics / vesting",
      audit: "Audit",
      liquidity: "Lichiditate",
      distribution: "Distribuție / concentrare",
      unlocks: "Deblocări / vesting",
      contract_risk: "Riscuri on-chain",
    })) {
      const o = node("option", label);
      o.value = key;
      category.append(o);
    }
    category.setAttribute("aria-label", "Tipul dovezii");
    for (const [key, label] of Object.entries({
      unknown: "Necunoscut",
      supported: "Susținut de dovezi · evaluare manuală",
      disputed: "Contestat · evaluare manuală",
    })) {
      const o = node("option", label);
      o.value = key;
      status.append(o);
    }
    status.setAttribute("aria-label", "Starea evaluării");
    form.append(category, status);
    const claim = inputField(form, "Afirmația evaluată", "textarea");
    claim.required = true;
    claim.maxLength = 1000;
    const url = inputField(form, "URL public al sursei", "url"),
      excerpt = inputField(form, "Citat din document", "textarea"),
      note = inputField(form, "Motivul evaluării manuale", "textarea"),
      issuer = inputField(form, "Emitent / autor"),
      published = inputField(
        form,
        "Data publicării · ora calculatorului",
        "datetime-local",
      );
    for (const key of [
      "",
      "solana",
      "ethereum",
      "base",
      "polygon",
      "bsc",
      "arbitrum",
      "avalanche",
      "bitcoin",
      "other",
    ]) {
      const o = node("option", key || "Chain necunoscut");
      o.value = key;
      chain.append(o);
    }
    chain.setAttribute("aria-label", "Chain");
    form.append(chain);
    const contract = inputField(
      form,
      "Contract / mint · gol pentru monedă nativă",
    );
    const sourceResult = node("p", undefined, "footnote"),
      sourceButton = button("Compară citatul în document", "secondary", () =>
        action(sourceButton, async () => {
          const result = await api("/api/research/source", {
            url: url.value,
            excerpt: excerpt.value,
          });
          sourceResult.textContent =
            (result.excerpt_found ? "Citat găsit. " : "Citat negăsit. ") +
            result.note +
            " " +
            date(result.observed_at);
        }),
      );
    sourceButton.type = "button";
    form.append(sourceButton, sourceResult);
    const save = button("Salvează dovada", "primary", () => {});
    save.type = "submit";
    form.append(save);
    form.onsubmit = (event) => {
      event.preventDefault();
      action(save, async () => {
        const body = {
          category: category.value,
          status: status.value,
          claim: claim.value,
          source_url: url.value || null,
          excerpt: excerpt.value,
          reviewer_note: note.value,
          issuer: issuer.value,
          chain: chain.value || null,
          contract: contract.value,
          published_at: published.value
            ? new Date(published.value).toISOString()
            : null,
        };
        const result = await api(
          `/api/research/${encodeURIComponent(address)}/evidence`,
          body,
        );
        await draw(result);
        message(
          "Dovadă și evaluare manuală salvate. Creează un semnal nou pentru a captura dosarul actualizat.",
          true,
        );
      });
    };
    box.append(form);
  }
  try {
    await draw(
      provided || (await api(`/api/research/${encodeURIComponent(address)}`)),
    );
  } catch (error) {
    box.append(node("p", error.message, "warn"));
  }
}
window.addEventListener("hashchange", () => {
  const page = location.hash.slice(1);
  if (pageNames[page] && (page !== "detail" || state.selection)) navigate(page);
});
window.addEventListener("popstate", () => {
  const page = location.hash.slice(1);
  navigate(
    pageNames[page] && (page !== "detail" || state.selection)
      ? page
      : "overview",
  );
});
$("news-archive").onchange = () => {
  state.newsArchive = $("news-archive").checked;
  load();
};
$("asset-discovery-form").onsubmit = (event) => {
  event.preventDefault();
  const b = event.currentTarget.querySelector("button");
  action(b, async () => {
    const results = await api(
      "/api/assets/search?q=" +
        encodeURIComponent($("asset-query").value.trim()),
    );
    const target = $("asset-search-results");
    target.replaceChildren();
    for (const asset of results) {
      const row = node("div", undefined, "venue");
      row.append(coin(asset));
      const watch = button("Urmărește și deschide", "secondary", () =>
        action(watch, async () => {
          await api("/api/assets/watch", { asset_id: asset.asset_id });
          await openAsset(asset.asset_id);
        }),
      );
      row.append(watch);
      target.append(row);
    }
    if (!results.length) empty(target, "Niciun activ identificat.");
  });
};
$("export-button").onclick = () => {
  const a = node("a");
  a.href = "/api/export?account=" + state.account;
  a.download = "pulse-" + state.account + ".json";
  a.click();
};
$("backup-button").onclick = () =>
  action($("backup-button"), async () => {
    const response = await fetch("/api/backup", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(state.csrf ? { "X-Pulse-CSRF": state.csrf } : {}),
      },
      body: "{}",
    });
    if (!response.ok) throw new Error("Backupul nu a putut fi creat.");
    const url = URL.createObjectURL(await response.blob()),
      a = node("a");
    a.href = url;
    a.download =
      "pulse-backup-" + new Date().toISOString().slice(0, 10) + ".zip";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    message(
      "Backup complet pentru ambele conturi, fără resetarea datelor.",
      true,
    );
  });
