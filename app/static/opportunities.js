/* Level 3: persistent discovery, immutable evidence and independent paper outcomes. */
const opportunityView = {
  loading: false,
  pendingRefresh: false,
  errors: {},
  pages: 1,
  queryKey: null,
  candidateRequest: 0,
  detailRequest: 0,
  config: null,
  items: [],
  cursor: null,
  selection: null,
  alerts: [],
  alertCursor: null,
  alertArchiveLoaded: false,
  alertsShown: 20,
  dailyDay: null,
  dailyRequest: 0,
  daily: null,
  dailyRetry: null,
  paperDraft: null,
};
const opportunityLabels = {
  security_risk: "Risc în verificările disponibile",
  exit_liquidity: "Lichiditate de ieșire",
  market_participation_quality: "Participare observată",
  early_momentum: "Momentum timpuriu",
  wallet_intelligence: "Dovezi wallet",
  narrative_social_evidence: "Dovezi narative / sociale",
  entry_attractiveness: "Condiții de intrare",
  data_reliability: "Fiabilitatea datelor",
};
function enginePill(text, verdict) {
  return node(
    "span",
    text,
    "pill engine-" + (verdict || "unknown").toLowerCase(),
  );
}
const verdictDescriptions = {
  CONSIDER: "De luat în calcul pentru cercetare; fără recomandare de cumpărare",
  INVESTIGATE: "Necesită cercetare suplimentară",
  MONITOR: "De urmărit; condiții insuficiente pentru următorul pas",
  REJECT: "Respins de regulile curente",
  PENDING: "Date sau evaluare în așteptare",
};
// Translate fixed rule text only; unrecognized source statements retain their original wording.
const researchTranslations = {
  "Small-position estimated round trip passes liquidity and impact limits.": "Intrarea și ieșirea estimate pentru o poziție mică respectă limitele modelului de lichiditate și impact.",
  "Small-position modeled entry/exit unavailable.": "Intrarea sau ieșirea modelată pentru o poziție mică nu este disponibilă.",
  "Price already exceeds the configured extension threshold; avoid chasing.": "Prețul a depășit deja pragul configurat de creștere; există risc de intrare târzie.",
  "Large observed USD liquidity decline; requires recheck.": "S-a observat o scădere mare a lichidității în USD; este necesară reverificarea.",
  "Unique buyer identities are not independently validated; provider counters and transaction counts do not prove organic participation.": "Identitățile cumpărătorilor unici nu sunt validate independent. Contoarele furnizorului și numărul tranzacțiilor nu dovedesc participare organică.",
  "Owner-level holder growth unavailable.": "Creșterea numărului de deținători la nivel de proprietar nu este disponibilă.",
  "No corroborated contract-specific narrative; name matches remain uncertain.": "Nu există o narațiune coroborată pentru acest contract. Potrivirile de nume rămân incerte.",
  "Contract-specific sources contain negative or contradictory context; issuer claims require independent review.": "Sursele asociate contractului conțin context negativ sau contradictoriu. Afirmațiile emitentului necesită verificare independentă.",
  "No reliable monitored-wallet accumulation evidence.": "Nu există dovezi fiabile de acumulare din walleturile urmărite.",
  "Wash trading, developer identity, LP ownership and sellability are not proven by aggregate data.": "Datele agregate nu confirmă absența wash tradingului, identitatea dezvoltatorului, proprietatea LP sau posibilitatea vânzării.",
  "Pool API freshness uses receipt time; an upstream trade timestamp is not supplied by these endpoints.": "Prospețimea răspunsului API folosește ora primirii. Aceste endpointuri nu furnizează ora tranzacției din sursa inițială.",
  "Fresh security screening, reported activity and recent pool age support further research.": "Verificările recente de securitate, activitatea raportată și vârsta mică a poolului susțin cercetarea suplimentară.",
  "Observed history and non-overlapping five-minute windows support liquidity retention and reported or sampled participation.": "Istoricul observat și ferestrele de cinci minute fără suprapunere susțin menținerea lichidității și participarea raportată sau eșantionată.",
  "Recent transaction counts unavailable.": "Numărul tranzacțiilor recente nu este disponibil.",
  "Pool creation timestamp unavailable; early status is unconfirmed.": "Momentul creării poolului nu este disponibil; stadiul timpuriu rămâne neconfirmat.",
  "New privileged authority or transfer restriction": "Apare o autoritate privilegiată sau o restricție nouă asupra transferurilor.",
  "Liquidity decline or unavailable exit quote": "Scade lichiditatea sau nu se mai poate obține o cotație de ieșire.",
  "Fresh evidence no longer available": "Dovezile recente nu mai sunt disponibile.",
  "Momentum becomes excessively extended": "Creșterea prețului depășește pragul de extensie configurat.",
  "Contradictory contract/source evidence": "Apar contradicții între contract și surse.",
};
function candidateAvatar(contract, symbol) {
  const avatar = node("span", (symbol || "?").replace(/[^\p{L}\p{N}]/gu, "").slice(0, 2).toUpperCase() || "?", "candidate-avatar");
  let hue = 0;
  for (const char of contract) hue = (hue * 31 + char.charCodeAt(0)) % 360;
  avatar.style.setProperty("--token-hue", hue);
  avatar.setAttribute("aria-hidden", "true");
  return avatar;
}
function syncVerdictFilters() {
  document.querySelectorAll("[data-verdict]").forEach(b => {
    const selected = b.dataset.verdict === $("engine-verdict").value;
    b.classList.toggle("active", selected);
    b.setAttribute("aria-pressed", String(selected));
  });
}
function engineStat(label, value, note) {
  const n = node("article", undefined, "panel padded engine-stat");
  n.append(
    node("span", label, "eyebrow"),
    node("strong", String(value ?? "—")),
    node("small", note || "", "footnote"),
  );
  return n;
}
function renderCandidateRows() {
  const root = $("engine-rows");
  root.replaceChildren();
  const items = opportunityView.items;
  $("engine-visible-count").textContent = items.length.toLocaleString("ro-RO");
  for (const c of items) {
    const m = c.latest?.market || {},
      d = c.latest?.decision,
      f = c.latest?.features || {},
      row = node("tr");
    const name = node("td");
    const identity = node("div", undefined, "candidate-identity"), identityText = node("div");
    identityText.append(
      node("strong", m.symbol || c.discovery.name || "Date în așteptare"),
      node("small", (c.chain || "Chain necunoscut").toUpperCase(), "chain-label"),
    );
    identity.append(candidateAvatar(c.contract, m.symbol || c.discovery.name), identityText);
    name.append(
      identity,
      node("small", short(c.contract), "contract-text"),
      node("small", "Descoperit " + date(c.discovered_at), "footnote"),
    );
    const value = node("td");
    value.append(
      node("strong", price(m.price_usd)),
      node("small", "LP " + cash(m.liquidity_usd), "footnote"),
    );
    const decision = node("td");
    decision.append(
      enginePill(d?.verdict || "PENDING", d?.verdict),
      node(
        "small",
        d?.rank_score == null || !c.fresh
          ? "Neclasat"
          : `Prioritate ${d.rank_score}/100`,
        "footnote",
      ),
    );
    decision.querySelector(".pill").title = verdictDescriptions[d?.verdict || "PENDING"] || "Verdict de cercetare";
    if (d?.rank_score != null && c.fresh) {
      const track = node("span", undefined, "rank-track");
      const fill = node("i");
      fill.style.width = `${Math.min(100, Math.max(0, Number(d.rank_score)))}%`;
      track.setAttribute("aria-hidden", "true");
      track.append(fill); decision.append(track);
    }
    const freshness = node("td");
    freshness.append(
      node("span", `${f.reported_transactions_5m ?? "—"} tx / 5m`),
      node(
        "small",
        `${f.buyers_5m_provider_reported ?? "—"} cumpărători raportați`,
        "footnote",
      ),
      node(
        "small",
        (c.fresh ? "Răspuns recent · " : "Date păstrate · ") +
          date(c.latest_at),
        c.fresh ? "good footnote" : "warn footnote",
      ),
    );
    const controls = node("td");
    controls.append(
      button("Cercetează ↗", "secondary research-button", () => openOpportunity(c.id)),
    );
    [name, value, decision, freshness, controls].forEach((cell, i) => {
      cell.dataset.label = ["Candidat", "Preț / lichiditate", "Verdict / prioritate", "Activitate / date", "Dosar de cercetare"][i];
    });
    if (c.id === opportunityView.selection) row.classList.add("selected-candidate");
    row.append(name, value, decision, freshness, controls);
    root.append(row);
  }
  $("engine-empty").hidden = items.length > 0;
  $("engine-more").hidden =
    !opportunityView.cursor || $("engine-sort").value !== "recent";
}
function engineJson(parent, label, value) {
  jsonDetails(parent, label, value);
}
function dossierOutcomes(parent, items, routed = false) {
  const labels = {
    pending: "În așteptarea observațiilor", evaluated: "Evaluat în simulare", exit_unavailable: "Ieșire indisponibilă",
    entry_unavailable: "Intrare indisponibilă", entry_rejected: "Intrare respinsă", missing_forward_entry: "Observație de intrare lipsă",
    missing_forward_exit: "Observație de ieșire lipsă", missing: "Observații lipsă",
  };
  if (items.length > 15) parent.append(node("p", `Ultimele 15 din ${items.length} rezultate. Istoricul complet este disponibil în dovezile de mai jos.`, "footnote"));
  for (const o of items.slice(-15)) {
    const item = node("article", undefined, "outcome-card");
    const header = node("div", undefined, "outcome-heading");
    header.append(node("strong", `Semnal ${o.signal_id}`), node("span", `${o.horizon_seconds / 60}m`, "pill"), node("span", labels[o.state] || o.state, "outcome-label"));
    item.append(header);
    const metrics = node("div", undefined, "outcome-values");
    metrics.append(node("p", `PnL ${routed ? "virtual " : ""}${cash(o.payload.pnl_usd)}`));
    if (!routed) metrics.append(node("p", `MFE observat ${o.payload.mfe_observed_pct == null ? "—" : percent(o.payload.mfe_observed_pct)}`), node("p", `MAE observat ${o.payload.mae_observed_pct == null ? "—" : percent(o.payload.mae_observed_pct)}`));
    item.append(metrics, node("small", `Stare înregistrată: ${o.state}${o.payload.reason ? " · " + o.payload.reason : ""}`, "footnote"));
    if (!routed && o.payload.priced_observations != null) item.append(node("small", `${o.payload.priced_observations} observații de preț · extrema reale dintre observații sunt necunoscute`, "footnote"));
    if (o.payload.pnl_usd == null) item.append(node("small", "Rezultatul net nu poate fi stabilit din datele disponibile.", "outcome-unknown"));
    parent.append(item);
  }
}
function dossierActivity(parent, features) {
  if (!features) return;
  const section = node("section", undefined, "dossier-section activity-windows");
  section.append(node("h3", "Ce s-a schimbat între observații"), node("p", "Comparații cu istoricul propriu al tokenului. Activitatea raportată și volumul în creștere nu confirmă cerere organică.", "footnote"));
  const windows = node("div", undefined, "activity-window-grid");
  for (const [key, label] of [["5m", "5 minute"], ["15m", "15 minute"], ["1h", "1 oră"]]) {
    const change = features.changes?.[key], card = node("article", undefined, "activity-window");
    card.append(node("h4", label));
    if (!change) card.append(node("p", "Istoric insuficient pentru comparație.", "footnote"));
    else {
      for (const [label, value] of [
        ["Preț", percent(change.price_change_pct)],
        ["Lichiditate", percent(change.liquidity_change_pct)],
        ["Volum 5m / referință", change.volume_5m_ratio == null ? "—" : number(change.volume_5m_ratio) + "×"],
        ["Cumpărători raportați", percent(change.reported_buyers_change_pct)],
      ]) {
        const row = node("div", undefined, "activity-window-value");
        row.append(node("span", label), node("strong", value)); card.append(row);
      }
      card.append(node("p", "Referință: " + date(change.baseline_at), "footnote"));
    }
    windows.append(card);
  }
  section.append(windows);
  const extension = features.excessive_extension === true ? "pragul configurat a fost depășit." : features.excessive_extension === false ? "pragul configurat nu a fost depășit în datele disponibile." : "date indisponibile.";
  section.append(node("p", "Extensie în ultima observație: " + extension + " Momentul lansării tokenului " + (features.token_launch_time_known ? "este raportat de sursă." : "rămâne neconfirmat; vârsta poolului se verifică separat."), features.excessive_extension ? "warn footnote" : "footnote"));
  parent.append(section);
}
function candidateQuery() {
  return new URLSearchParams({
    sort: $("engine-sort").value,
    q: $("engine-search").value.trim(),
    verdict: $("engine-verdict").value,
  });
}
function opportunityError(key, error) {
  if (error) opportunityView.errors[key] = error.message;
  else delete opportunityView.errors[key];
  const root = $("engine-errors");
  root.replaceChildren();
  for (const [name, text] of Object.entries(opportunityView.errors))
    root.append(node("p", `${name}: ${text}. Datele păstrate pot fi vechi.`));
  root.hidden = !Object.keys(opportunityView.errors).length;
  const failedSections = Object.keys(opportunityView.errors);
  $("engine-section-errors").textContent = failedSections.length ? "Secțiuni indisponibile: " + failedSections.join(", ") + ". Deschide detaliile." : "";
  $("engine-section-errors").hidden = !failedSections.length;
  $("engine-status-panel").classList.toggle("has-view-warning", !!failedSections.length);
  if (Object.keys(opportunityView.errors).length)
    state.sectionErrors.opportunities = Object.keys(
      opportunityView.errors,
    ).join(", ");
  else delete state.sectionErrors.opportunities;
  if (key === "Performanță" && error && $("engine-stats").getAttribute("aria-busy") === "true") {
    $("engine-stats").setAttribute("aria-busy", "false");
    $("engine-stats").dataset.state = "unavailable";
    $("engine-stats").replaceChildren(node("p", "Raport indisponibil · indicatorii istorici nu pot fi afișați momentan. Candidații și dosarele pot fi cercetate în continuare.", "footnote"));
  }
  renderHealth();
}
async function loadOpportunityCandidates(mode = "refresh") {
  const params = candidateQuery(),
    key = params.toString();
  if (key !== opportunityView.queryKey) {
    opportunityView.pages = 1;
    opportunityView.queryKey = key;
    opportunityView.cursor = null;
  }
  if (mode === "more" && !opportunityView.cursor) return;
  const serial = ++opportunityView.candidateRequest;
  try {
    if (mode === "more") params.set("before", opportunityView.cursor);
    let data = await api("/api/opportunities?" + params);
    const first = data;
    let items =
      mode === "more" ? [...opportunityView.items, ...data.items] : data.items;
    let pages = mode === "more" ? opportunityView.pages + 1 : 1;
    while (
      mode !== "more" &&
      pages < opportunityView.pages &&
      data.next_cursor
    ) {
      params.set("before", data.next_cursor);
      data = await api("/api/opportunities?" + params);
      items.push(...data.items);
      pages++;
    }
    if (
      serial !== opportunityView.candidateRequest ||
      key !== candidateQuery().toString()
    )
      return;
    opportunityView.items = [...new Map(items.map((c) => [c.id, c])).values()];
    opportunityView.pages = pages;
    opportunityView.cursor = data.next_cursor;
    opportunityView.config = first.config;
    $("engine-list-note").textContent =
      `${opportunityView.items.length} afișați din ${first.matching_total ?? opportunityView.items.length} potriviri` +
      (first.ranking_limited
        ? " · clasament limitat; caută sau folosește Descoperiri recente pentru întregul istoric."
        : ". Căutarea include întregul istoric.");
    $("engine-health").textContent =
      `Motor: ${first.status.state} · ultim ciclu ${date(first.status.at)} · ${first.status.observed ?? 0} observații în ciclu.`;
    if (first.status.errors?.length)
      $("engine-health").textContent +=
        ` Probleme: ${first.status.errors.join(", ")}.`;
    const queue = first.status.queue;
    if (queue?.dispatchable_due != null)
      $("engine-health").textContent +=
        ` Reevaluări periodice eligibile scadente: ${queue.dispatchable_due}; întârziere maximă ${queue.dispatchable_oldest_due_delay_seconds}s. Istoric cu reevaluarea periodică în pauză: ${queue.paused_due}. Total periodic scadent înregistrat: ${queue.due}.`;
    else if (queue?.due)
      $("engine-health").textContent +=
        ` În așteptare: ${queue.due}; întârziere maximă ${queue.oldest_due_delay_seconds}s.`;
    if (queue?.priority_due != null)
      $("engine-health").textContent += ` Prioritare scadente: ${queue.priority_due} (tokenuri recente, prima colectare, lista de urmărire și referințe documentate).`;
    const network = first.status.network_budget, plan = first.status.collection_plan;
    $("engine-network-health").hidden = !network;
    if (network) {
      const timeouts = Object.values(network.calls || {}).reduce((sum, c) => sum + (c.timeouts || 0), 0);
      $("engine-network-health").textContent = `Ultimul ciclu: ${first.status.timing_seconds?.total ?? "—"}s · timp comun disponibil cererilor: ${network.network_budget_seconds}s · așteptări API expirate: ${timeouts}. Colectare pornită pentru ${plan?.started ?? "—"}/${plan?.admitted ?? "—"} candidați; ${plan?.deferred_before_market_read ?? "—"} amânați înaintea citirii prețului.${first.status.routed_dispatch_deferred ? " Cotații virtuale amânate: bugetul de timp nu permite o încercare completă." : ""} Scrierile și finalizarea rezultatelor pot depăși intervalul. O amânare nu este o tranzacție eșuată.`;
    }
    const engineStates = {ok:"Motor activ", running:"Motor în colectare", partial:"Colectare parțială", error:"Eroare de colectare", disabled:"Motor oprit", idle:"Motor în așteptare"};
    $("engine-cycle-state").textContent = `${engineStates[first.status.state] || first.status.state || "Stare necunoscută"} · ultim ciclu ${date(first.status.at)}` + (first.status.errors?.length ? ` · ${first.status.errors.length} probleme` : "") + (queue?.dispatchable_due > 0 ? ` · ${queue.dispatchable_due.toLocaleString("ro-RO")} reevaluări scadente` : "");
    $("engine-status-panel").classList.toggle("has-warning", !!first.status.errors?.length || queue?.dispatchable_due > 0 || ["error", "partial"].includes(first.status.state));
    syncVerdictFilters();
    renderCandidateRows();
    if (!$("engine-config").dataset.loaded) {
      const c = first.config;
      for (const [id, value] of Object.entries({
        enabled: c.enabled,
        ai: c.ai_narratives,
        routed: c.routed_quotes_enabled,
        telegram: c.telegram_enabled,
      }))
        $("engine-" + id).checked = value;
      for (const [id, value] of Object.entries({
        budget: c.observation_budget,
        position: c.position_usd,
        "min-tx": c.min_transactions_5m,
        cooldown: c.cooldown_seconds,
        "route-budget": c.routed_quote_budget,
        "route-slippage": c.routed_slippage_bps,
      }))
        $("engine-" + id).value = value;
      if (c.test_from) {
        const d = new Date(c.test_from);
        $("engine-test-from").value = new Date(
          d.getTime() - d.getTimezoneOffset() * 60000,
        )
          .toISOString()
          .slice(0, 16);
      }
      $("engine-config").dataset.loaded = "1";
    }
    opportunityError("Candidați", null);
  } catch (error) {
    if (serial === opportunityView.candidateRequest)
      opportunityError("Candidați", error);
  }
}
function renderOpportunityStats(report) {
  const t = report.totals,
    root = $("engine-stats");
  root.replaceChildren();
  root.setAttribute("aria-busy", "false");
  delete root.dataset.state;
  root.setAttribute("aria-label", "Indicatori ai cercetării" + (report.generated_at ? " · raport " + date(report.generated_at) : ""));
  const freshness = $("engine-report-freshness"), cache = report.report_cache;
  freshness.hidden = !cache;
  if (cache) {
    freshness.textContent = `Indicatori din snapshot ${date(cache.snapshot_at || report.generated_at)} · calcul finalizat ${date(cache.calculated_at)} · raport păstrat în cache. Actualizare: ${cache.refresh?.state || "necunoscută"}.` + (cache.stale ? " Snapshot vechi; verifică ora datelor înaintea interpretării." : "") + (cache.refresh?.state === "error" ? ` Ultima recalculare a eșuat: ${cache.refresh.error || "eroare"}.` : "");
    freshness.classList.toggle("warn", !!cache.stale || cache.refresh?.state === "error");
  }
  root.append(
    engineStat(
      "CANDIDAȚI",
      number(t.discovered),
      `${number(t.eligible)} eligibili în universul observat`,
    ),
    engineStat(
      "FILTRU DE SECURITATE",
      number(report.current_security_pass),
      "Verificări limitate, fără garanție de siguranță",
    ),
    engineStat(
      "ALERTE",
      number(t.alerts),
      `${number(t.delivered_in_app)} afișate în aplicație`,
    ),
    engineStat("OBSERVAȚII", number(t.observations), "Inclusiv încercările fără date"),
  );
  renderEnginePerformance(report);
}
function renderOpportunityWallets(wallets) {
  const root = $("engine-wallets");
  root.replaceChildren();
  if (!wallets.length)
    root.append(
      node(
        "p",
        "Niciun wallet urmărit. Scorul wallet rămâne necunoscut.",
        "footnote",
      ),
    );
  for (const w of wallets) {
    const box = node("article", undefined, "evidence-item");
    box.append(
      node("strong", w.label || short(w.address)),
      node(
        "p",
        `${w.chain} · ${w.events_total} evenimente · ${w.status.state}`,
        "footnote",
      ),
    );
    engineJson(box, "Activitate raportată", w.activity.slice(0, 5));
    root.append(box);
  }
}
async function renderOpportunities() {
  if (!state.authReady || document.body.classList.contains("locked")) return;
  if (opportunityView.loading) {
    opportunityView.pendingRefresh = true;
    return;
  }
  opportunityView.loading = true;
  const sections = [
    [
      "Alerte",
      "/api/opportunities/alerts",
      async (current) => {
        const merged = new Map(opportunityView.alerts.map((a) => [a.id, a]));
        current.items.forEach((a) => merged.set(a.id, a));
        opportunityView.alerts = [...merged.values()].sort(
          (a, b) => b.id - a.id,
        );
        if (!opportunityView.alertArchiveLoaded)
          opportunityView.alertCursor = current.next_cursor;
        await renderEngineAlerts(opportunityView.alerts);
      },
    ],
    ["Narațiuni", "/api/opportunities/narratives", renderEngineNarratives],
    ["Walleturi", "/api/wallets", renderOpportunityWallets],
    ["Colectare", "/api/opportunities/coverage", renderEngineCoverage],
  ];
  const loadSection = async ([name, path, render]) => {
    try {
      await render(await api(path));
      opportunityError(name, null);
    } catch (error) {
      opportunityError(name, error);
    }
  };
  try {
    await Promise.allSettled([
      loadOpportunityCandidates(),
      loadPilot(),
      ...sections.map(loadSection),
      opportunityView.selection !== null
        ? openOpportunity(opportunityView.selection, false)
        : Promise.resolve(),
    ]);
    // Keep live discovery responsive while full-history reports read the database.
    await loadDailyResearch();
    for (const section of [
      ["Performanță", "/api/opportunities/performance", renderOpportunityStats],
      ["Jupiter", "/api/opportunities/routes", renderEngineRoutes],
    ]) await loadSection(section);
  } finally {
    opportunityView.loading = false;
    if (opportunityView.pendingRefresh) {
      opportunityView.pendingRefresh = false;
      renderOpportunities();
    }
  }
}
const pilotView = { serial: 0, data: null };
async function loadPilot() {
  const serial = ++pilotView.serial;
  try {
    const data = await api("/api/opportunities/pilot");
    if (serial !== pilotView.serial) return;
    renderPilot(data);
    opportunityError("Pilot", null);
  } catch (error) {
    if (serial !== pilotView.serial) return;
    $("engine-pilot-status").textContent = "Bilanțul pilotului nu poate fi actualizat: " + error.message + (pilotView.data ? " Ultimul bilanț rămâne afișat; poate fi vechi." : "");
    opportunityError("Pilot", error);
  }
}
function renderPilot(data) {
  const root = $("engine-pilot"), status = $("engine-pilot-status"), study = data.study;
  $("engine-pilot-start").hidden = !!study;
  if (!study) {
    root.replaceChildren(node("p", "Pilotul înregistrează numai candidații noi, după activare. Fixează perioada și politica; nu poate fi resetat pentru a muta rezultatele. Colectarea continuă cât timp aplicația și calculatorul sunt pornite.", "footnote"));
    status.textContent = "Pilot neînceput · fără rezultate atribuite retrospectiv.";
    $("engine-pilot-export").disabled = true;
    return;
  }
  const period = `${date(study.declared_at)} → ${date(study.ends_at)} · politica ${study.payload.policy_id}`;
  if (data.report_state !== "ready") {
    status.textContent = period + " · primul bilanț se calculează în fundal.";
    return;
  }
  pilotView.data = data;
  $("engine-pilot-export").disabled = false;
  const cache = data.report_cache;
  status.textContent = `${period} · ${Math.min(30, data.elapsed_days).toFixed(1)}/30 zile calendaristice · bilanț ${date(data.generated_at)}.` + (cache ? ` Snapshot în cache, actualizare ${cache.refresh?.state || "necunoscută"}.` : "") + (cache?.stale ? " Date vechi: verifică ora bilanțului." : "") + (cache?.refresh?.state === "error" ? " Ultima recalculare a eșuat." : "");
  if (data.phase === "followup") status.textContent += " Înscrierile s-au încheiat; continuă urmărirea rezultatelor deja promise.";
  const t = data.totals;
  root.replaceChildren();
  const stats = node("div", undefined, "engine-grid");
  stats.append(engineStat("ÎNREGISTRĂRI NOI", t.new_registrations, `${t.eligible} eligibile · ${t.first_evaluations} prime evaluări`), engineStat("ALERTE", t.opportunity_alerts, `${t.alerts_displayed} afișate · ${t.risk_alerts} avertizări de risc`));
  root.append(stats, node("p", `${t.analysis_tokens} tokenuri în comparația politicii inițiale · ${t.initially_selected_tokens} selectate inițial · ${t.control_tokens_excluding_selected} control fără suprapunere.`, "footnote"));
  if (Object.keys(t.analysis_exclusions).length)
    engineJson(root, "Înregistrări în afara comparației · motive", t.analysis_exclusions);
  root.append(node("h3", "Cât de repede ajunge informația"));
  const labels = {registration_to_first_evaluation:"Înregistrare → prima evaluare", discovery_to_alert:"Descoperire în sursă → alertă", alert_to_display:"Alertă → afișare în aplicație", signal_to_pool_paper_entry:"Prima evaluare → observație eligibilă pentru intrarea paper estimată", first_alert_to_pool_paper_entry:"Prima alertă → observație eligibilă pentru intrarea paper estimată"};
  for (const [key, value] of Object.entries(data.latency)) {
    const time = n => n === null ? "—" : `${Number(n).toFixed(1)}s`;
    root.append(node("p", `${labels[key] || key}: mediană ${time(value.p50_seconds)}, p95 ${time(value.p95_seconds)} · ${value.measured}/${value.subjects} măsurate · ${value.missing} lipsă · ${value.invalid_clock} ceas invalid.`, "footnote"));
  }
  if (data.alert_followup) {
    root.append(node("h3", "Ce s-a întâmplat după prima alertă a fiecărui token"));
    root.append(node("p", "Include și alertele emise după prima evaluare. Aceste rezultate sunt descriptive; nu modifică selecția inițială din comparația cu controlul.", "footnote"));
    for (const [model, title] of [["estimated_pool","Pool estimativ"],["jupiter_quotes","Jupiter"]]) {
      for (const [h, value] of Object.entries(data.alert_followup[model])) {
        const s = value.matured;
        root.append(node("p", `${title} · ${Number(h)/60}m: ${s.evaluated}/${s.experiments} evaluate la termen · medie netă evaluată ${cash(s.mean_net_pnl_usd)} · ${s.unresolved_or_unavailable} necunoscute · ${value.not_yet_mature} încă înainte de termen.`, "footnote"));
      }
    }
  }
  for (const [model, title] of [["estimated_pool", "Estimări de pool"], ["jupiter_quotes", "Cotații Jupiter"]]) {
    root.append(node("h3", title));
    const wrapper = node("div", undefined, "table-scroll"), table = node("table"), head = node("thead"), hr = node("tr"), body = node("tbody");
    ["Orizont / grup", "Evaluate / ajunse la termen", "Medie netă evaluată", "Necunoscute"].forEach(s => hr.append(node("th", s)));
    head.append(hr); table.append(head);
    for (const [h, result] of Object.entries(data.models[model])) {
      for (const [group, label] of [["all_first_evaluations", "Toate"], ["selected_at_first_evaluation", "Selectate inițial"], ["control_excluding_selected", "Control distinct"]]) {
        const value = result.comparison[group], tr = node("tr");
        [`${Number(h)/60}m · ${label}`, `${value.evaluated}/${value.experiments}`, cash(value.mean_net_pnl_usd), String(value.unresolved_or_unavailable)].forEach(s => tr.append(node("td", s)));
        body.append(tr);
      }
      const pending = node("tr"), cell = node("td", `${Number(h)/60}m · ${result.not_yet_mature}/${result.planned} nu au ajuns încă la termenul conservator.`); cell.colSpan = 4; pending.append(cell); body.append(pending);
    }
    table.append(body); wrapper.append(table); root.append(wrapper);
  }
  root.append(node("h3", "Punctualitatea colectării"));
  const coverageScroll = node("div", undefined, "table-scroll"), coverageTable = node("table"), coverageHead = node("thead"), coverageHeader = node("tr"), coverageBody = node("tbody");
  ["Grup / observație", "Preț valid în fereastră", "Încercări fără preț valid", "Termene ratate", "În așteptare"].forEach(s => coverageHeader.append(node("th", s)));
  coverageHead.append(coverageHeader); coverageTable.append(coverageHead);
  const phases = {entry:"Intrare",exit:"Ieșire",checkpoint:"Reper de preț",routed_exit:"Reper pentru ieșire Jupiter"};
  for (const [group, title] of [["alerts","Alerte"],["control","Control distinct"]]) {
    for (const [phase, values] of Object.entries(data.collection[group] || {})) {
      const tr = node("tr"), observed = values["price:observed"] || 0;
      [`${title} · ${phases[phase] || phase}`, observed, (values.attempted || 0)-observed, values.missed || 0, (values.due || 0)+(values.not_due || 0)].forEach(s => tr.append(node("td", String(s))));
      coverageBody.append(tr);
    }
  }
  coverageTable.append(coverageBody); coverageScroll.append(coverageTable); root.append(coverageScroll);
  engineJson(root, "Detaliile colectării și motivele datelor nevalide", data.collection);
  root.append(node("p", "Zilele calendaristice nu dovedesc colectare continuă. Comparația include numai orizonturi ajunse la termen; lipsurile rămân necunoscute. Latențele fără intrare includ și intrările refuzate. Mediile folosesc doar rezultate evaluate. Prețurile și cotațiile paper nu confirmă execuția. Rezultatele sunt descriptive, fără dovadă de profitabilitate sau drawdown de portofoliu.", "footnote"));
}
async function renderEngineAlerts(items) {
  const root = $("engine-alerts");
  const receipts = [];
  root.replaceChildren();
  if (!items.length) {
    root.append(
      node(
        "p",
        "Niciun candidat nu a îndeplinit încă regulile pentru o alertă. Filtrele rămân active.",
        "footnote",
      ),
    );
    return;
  }
  for (const a of items.slice(0, opportunityView.alertsShown)) {
    const p = a.payload,
      box = node("article", undefined, "engine-alert evidence-item");
    box.dataset.alertId = a.id;
    box.append(
      enginePill(p.verdict, p.verdict),
      node("strong", `${p.symbol} · ${price(p.price_usd)}`),
      node("p", p.contract, "contract-text"),
      node(
        "p",
        `LP ${cash(p.liquidity_usd)} · descoperit ${date(p.discovered_at)} · date ${date(p.data_observed_at)}`,
        "footnote",
      ),
    );
    for (const reason of p.positive.slice(0, 2))
      box.append(node("p", researchTranslations[reason] || reason, "good footnote"));
    box.append(
      node(
        "p",
        p.negative.concat(p.unknown).slice(0, 2).map(text => researchTranslations[text] || text).join(" "),
        "warn footnote",
      ),
    );
    box.append(
      node(
        "p",
        `Extensie excesivă: ${p.features.excessive_extension ? "DA" : "pragul nu a fost depășit în datele disponibile"} · cost tur-retur estimat ${p.costs.roundtrip_cost_pct?.toFixed(2) ?? "—"}%`,
        "footnote",
      ),
    );
    box.append(
      button("Deschide semnalul", "secondary", () =>
        openOpportunity(a.candidate_id),
      ),
      link("Piață", p.links.market, "text-button"),
    );
    engineJson(box, "Dovezi și condiții de invalidare", p);
    box.append(
      node(
        "small",
        `Telegram: ${a.telegram_state} · ${a.seen_at ? "Citită" : "Necitită"}`,
        "footnote",
      ),
    );
    if (!a.seen_at) {
      const seen = button("Marchează citită", "text-button", () =>
        action(seen, async () => {
          Object.assign(
            a,
            await api(
              `/api/opportunities/alerts/${a.id}/receipt?seen=true`,
              {},
            ),
          );
          await renderOpportunities();
        }),
      );
      box.append(seen);
    }
    root.append(box);
    // Receipt means the alert is in the visible application, not that Telegram/user read it.
    if (
      !a.delivered_in_app_at &&
      state.page === "opportunities" &&
      !document.hidden
    )
      receipts.push(
        (async () => {
          try {
            Object.assign(
              a,
              await api(`/api/opportunities/alerts/${a.id}/receipt`, {}),
            );
          } catch (error) {
            box.append(
              node(
                "p",
                "Confirmarea afișării a eșuat: " + error.message,
                "warn footnote",
              ),
            );
          }
        })(),
      );
  }
  if (
    items.length > opportunityView.alertsShown ||
    opportunityView.alertCursor
  ) {
    const more = button("Mai multe alerte", "secondary", () =>
      action(more, async () => {
        if (
          items.length <= opportunityView.alertsShown &&
          opportunityView.alertCursor
        ) {
          const older = await api(
            `/api/opportunities/alerts?before=${opportunityView.alertCursor}`,
          );
          const merged = new Map(opportunityView.alerts.map((a) => [a.id, a]));
          older.items.forEach((a) => merged.set(a.id, a));
          opportunityView.alerts = [...merged.values()].sort(
            (a, b) => b.id - a.id,
          );
          opportunityView.alertCursor = older.next_cursor;
          opportunityView.alertArchiveLoaded = true;
        }
        opportunityView.alertsShown += 20;
        await renderEngineAlerts(opportunityView.alerts);
      }),
    );
    root.append(more);
  }
  await Promise.allSettled(receipts);
}
function renderEnginePerformance(report) {
  const root = $("engine-performance");
  root.replaceChildren();
  for (const [h, cohorts] of Object.entries(report.horizons)) {
    const all = cohorts.all_eligible_first_evaluations,
      selected = cohorts.selected_at_first_evaluation;
    const box = node("article", undefined, "evidence-item");
    box.append(
      node("h3", `${Number(h) / 60} minute după intrarea observată`),
      node(
        "p",
        `Toți candidații: ${all.experiments} experimente, ${all.evaluated} evaluate, ${all.unresolved_or_unavailable} incomplete.`,
        "footnote",
      ),
      node(
        "p",
        `Selectați la primul semnal: ${selected.experiments} · evaluate ${selected.evaluated} · PnL ${cash(selected.net_pnl_independent_experiments_usd)}`,
        "footnote",
      ),
      node(
        "p",
        `PnL total al experimentelor evaluate: ${cash(all.net_pnl_independent_experiments_usd)} · profitabile ${all.profitable_after_costs}`,
        "footnote",
      ),
    );
    if (cohorts.prospective_comparison) {
      const p = cohorts.prospective_comparison;
      box.append(
        node(
          "p",
          `Grup fix de comparație: ${p.fixed_control.experiments} experimente noi, ${p.fixed_control.evaluated} evaluate, ${p.fixed_control.unresolved_or_unavailable} incomplete. PnL ${cash(p.fixed_control.net_pnl_independent_experiments_usd)}`,
          "footnote",
        ),
      );
    }
    engineJson(box, "Baseline, cohorte și incertitudine", cohorts);
    root.append(box);
  }
  if (!Object.keys(report.horizons).length)
    root.append(
      node(
        "p",
        "Se așteaptă primele evaluări și orizonturi viitoare. Lipsa rezultatelor nu este profit zero.",
        "footnote",
      ),
    );
  root.append(
    node(
      "p",
      "Precizia și profitabilitatea nu sunt demonstrate. Universul este parțial; rata oportunităților ratate rămâne necunoscută.",
      "warn footnote",
    ),
  );
  engineJson(root, "Raport complet și diagnostice exploratorii", report);
}
function renderEngineCoverage(data) {
  const root = $("engine-coverage");
  root.replaceChildren();
  if (data.report_cache) {
    const cache = data.report_cache, refresh = cache.refresh || {};
    const status = {running:"în curs",ok:"în așteptarea următorului calcul",error:"eroare",not_started:"nepornită"};
    root.append(node("p", `Raport calculat la ${date(cache.calculated_at)} · ${cache.served_from_cache ? "date păstrate în cache" : "primul calcul"}. Actualizare: ${status[refresh.state] || refresh.state || "necunoscută"}${refresh.error ? " · " + refresh.error : ""}. Contoarele descriu ultimul raport calculat.`, "footnote"));
  }
  const scope = data.prospective_groups || data.groups;
  $("engine-coverage-summary").textContent =
    `Calitatea colectării · cotații utilizabile la intrare: ${scope.alerts.entry.usable_price_observations ?? "—"} alerte / ${scope.control.entry.usable_price_observations ?? "—"} control · încercări: ${scope.alerts.entry.attempted} / ${scope.control.entry.attempted} · termene ratate: ${scope.alerts.entry.missed + scope.control.entry.missed}`;
  const members = (data.enrollment || []).filter(
    (r) => r.provenance === "prospective",
  );
  const total = members.reduce((s, r) => s + r.n, 0),
    control = members
      .filter((r) => r.control_member)
      .reduce((s, r) => s + r.n, 0);
  root.append(
    node(
      "p",
      `Urmărire echilibrată din ${date(data.activated_at)}. ${total} candidați noi; ${control} în grupul fix de comparație.`,
      "footnote",
    ),
  );
  const monitoring = data.monitoring;
  if (monitoring)
    root.append(
      node(
        "p",
        `Monitorizare: ${monitoring.dispatchable_due} reevaluări periodice scadente · ${monitoring.paused_due} în pauză · total periodic înregistrat ${monitoring.due}. Observații promise scadente: ${monitoring.promised_due_candidates ?? "—"} candidați, dintre care ${monitoring.promised_due_outside_periodic_queue ?? "—"} în afara programului periodic. Fereastra de fundal: ${monitoring.background_watch_hours} ore de la înregistrare. Dosarele și rezultatele rămân păstrate; observațiile promise, prima colectare, lista de urmărire și pozițiile virtuale deschise sunt protejate. Capacitatea API poate lăsa termene ratate; rezultatele lipsă rămân necunoscute.`,
        "footnote",
      ),
    );
  if (monitoring?.priority_due != null) {
    root.append(node("h3", "Punctualitatea colectării"));
    root.append(node("p", `${monitoring.priority_due} reevaluări prioritare scadente · ${monitoring.priority_stale_attempts ?? "—"} ultime încercări prioritare mai vechi de ${monitoring.freshness_max_age_seconds}s.`, "footnote"));
    const states = node("ul", "", "footnote");
    for (const [key, label] of [
      ["awaiting_first_observation", "Prima colectare"],
      ["active", "Tokenuri descoperite recent"],
      ["manual_watch", "Lista de urmărire și poziții virtuale"],
      ["reactivated", "Referințe documentate recente"],
      ["followup", "Rezultate și observații încă promise"],
      ["background", "Reevaluări de fundal"],
      ["paused", "Istoric în pauză"],
    ]) {
      const s = monitoring.counts_by_state?.[key];
      if (s) states.append(node("li", `${label}: ${s.candidates} candidați · ${s.due} scadente · întârziere maximă ${s.oldest_due_delay_seconds}s · ${s.stale_attempts} încercări vechi${s.invalid_attempt_timestamps ? ` · ${s.invalid_attempt_timestamps} timestampuri invalide` : ""}.`));
    }
    root.append(states, node("p", "Prospețimea de aici măsoară ultima încercare de colectare. Un răspuns eșuat recent nu este o cotație validă; prețul și securitatea au verificări separate. Rezervele împart capacitatea disponibilă, fără garanția respectării tuturor termenelor.", "footnote"));
  }
  for (const [key, label] of [
    ["alerts", "Alerte"],
    ["control", "Grup de comparație"],
  ]) {
    const g = (data.prospective_groups || data.groups)[key];
    root.append(node("h3", label));
    for (const [phase, name] of [
      ["entry", "Intrare"],
      ["exit", "Ieșire"],
      ["checkpoint", "Repere de preț, inclusiv tokenuri respinse"],
      ["routed_exit", "Observații pentru ieșirile rutate"],
    ]) {
      const p = g[phase] || { attempted: 0, missed: 0, pending: 0 };
      root.append(
        node(
          "p",
          `${name}: ${p.usable_price_observations ?? "—"} cotații utilizabile / ${p.attempted} încercări · ${p.attempts_without_usable_price ?? "—"} încercări fără preț utilizabil · ${p.missed} termene ratate · ${p.pending} în așteptare.`,
          "footnote",
        ),
      );
    }
  }
  root.append(node("p", "O cotație utilizabilă confirmă numai un preț raportat pentru pool-ul și intervalul cerut. Securitatea, lichiditatea de ieșire și execuția ordinului se verifică separat.", "footnote"));
  const labels = {
    capacity_or_worker_gap: "Nepreluate la timp (capacitate sau pauză)",
    collection_finished_after_deadline: "Colectare încheiată după termen",
    provider_quote_unavailable: "Preț indisponibil la furnizor",
    security_evidence_unavailable: "Securitate insuficient verificată",
    risk_or_liquidity_gate: "Filtru de risc sau lichiditate",
    quote_before_window: "Cotație preluată prea devreme",
    quote_received: "Cotație primită",
    cost_model_unavailable: "Model de cost incompatibil",
  };
  for (const [reason, n] of Object.entries(
    data.prospective_reasons || data.reasons,
  ))
    root.append(node("p", `${labels[reason] || reason}: ${n}`, "footnote"));
  root.append(
    node(
      "p",
      "Grupul se stabilește înaintea evaluării și poate include tokenuri alertate. Datele vechi rămân separate. Completitudinea observațiilor și rezultatele paper se măsoară separat.",
      "footnote",
    ),
  );
  engineJson(root, "Acoperire și reguli de colectare", data);
}
function renderEngineRoutes(data) {
  const root = $("engine-routes");
  root.replaceChildren();
  $("engine-routes-summary").textContent =
    `Paper cu cotații Jupiter · ${data.status.state} · ${data.entry_states.filled || 0} intrări virtuale cotate`;
  if (data.report_cache) {
    const cache = data.report_cache;
    root.append(node("p", `Raport din snapshotul ${date(cache.snapshot_at)} · calculat ${date(cache.calculated_at)} · ${cache.stale ? "date vechi" : "rezultat memorat"}${cache.refresh?.state === "error" ? " · actualizare eșuată; ultimul rezultat complet este păstrat" : ""}. Colectarea curentă se verifică separat în starea componentelor.`, cache.stale || cache.refresh?.state === "error" ? "warn footnote" : "footnote"));
  }
  root.append(
    node(
      "p",
      "Cotații observate de swap, cu minimum de ieșire la slippage-ul ales. Execuția rămâne simulată. Comisioanele de rețea și conversie sunt presupuneri. Aceste rezultate sunt separate de estimările de pool.",
      "footnote",
    ),
  );
  root.append(
    node(
      "p",
      `Ultima colectare: ${date(data.status.at)}. Istoric fără măsurare Jupiter: ${data.legacy_baselines_not_measured} prime evaluări.`,
      "footnote",
    ),
  );
  if (data.overdue_unprocessed?.entries || data.overdue_unprocessed?.exits)
    root.append(
      node(
        "p",
        `Termene expirate, încă neprocesate: ${data.overdue_unprocessed.entries} intrări / ${data.overdue_unprocessed.exits} ieșiri.`,
        "warn footnote",
      ),
    );
  const states = {
    entry_pending: "Intrări în așteptare",
    collecting: "Cotare în curs",
    filled: "Intrări virtuale cu cotație",
    entry_rejected: "Respinse de filtre",
    entry_unavailable: "Intrări indisponibile",
    disabled_at_signal: "Cotare dezactivată la semnal",
  };
  for (const [state, n] of Object.entries(data.entry_states))
    root.append(node("p", `${states[state] || state}: ${n}`, "footnote"));
  for (const [reason, n] of Object.entries(data.entry_failure_reasons))
    root.append(
      node(
        "p",
        `${reason
          .replace(/^ProviderError:/, "Sursă:")
          .replace(/^Rejected:/, "Filtru:")
          .replace(
            /^original_risk_gate$/,
            "Filtrul inițial de risc sau lichiditate",
          )}: ${n}`,
        "warn footnote",
      ),
    );
  for (const [h, groups] of Object.entries(data.horizons)) {
    const g = groups.all_first_evaluations;
    root.append(
      node(
        "p",
        `${Number(h) / 60}m · ${g.evaluated}/${g.experiments} prime evaluări cu ambele cotații · ${g.unresolved_or_unavailable} incomplete · PnL virtual ${cash(g.net_pnl_independent_experiments_usd)}`,
        "footnote",
      ),
    );
  }
  for (const a of data.recent_attempts.slice(0, 5)) {
    const button = node(
      "button",
      `${a.phase === "entry" ? "Intrare" : "Ieșire"} · ${a.status} · ${a.contract.slice(0, 8)}…`,
      "text-button",
    );
    button.type = "button";
    button.onclick = () => openOpportunity(a.candidate_id);
    root.append(button);
  }
  engineJson(root, "Cotații, costuri, eșecuri și grupuri de comparație", data);
}
function renderEngineNarratives(data) {
  const root = $("engine-narratives");
  root.replaceChildren();
  if (data.story_discovery) {
    const s = data.story_discovery;
    const states = s.states || {};
    root.append(node("p", `Contracte găsite în documente: ${s.tracked_contracts} · pool găsit ${states.resolved_pool || 0} · candidați existenți ${states.existing_candidate || 0} · piață indisponibilă ${states.market_unavailable || 0} · dovezi indisponibile ${states.evidence_unavailable || 0} · expirate ${states.evidence_expired || 0} · în așteptare ${(states.pending || 0) + (states.lookup_in_progress || 0)}. Mențiunile nu confirmă emitentul.`, "footnote"));
  }
  for (const story of (data.stories?.items || []).slice(0, 6)) {
    const box = node("article", undefined, "evidence-item");
    box.append(link(story.title, story.url, "text-button"));
    if (story.memecoin_headline)
      box.append(node("p", "Știre despre memecoinuri · selecție după titlu", "footnote"));
    box.append(node("p", `${story.publisher_reported} · publicat ${date(story.published_at)} · observat ${date(story.first_seen_at)}`, "footnote"));
    const labels = {
      read: "Document citit; afirmațiile nu sunt confirmate automat.",
      unavailable: "Document indisponibil; rămâne doar titlul raportat.",
      invalid: "Dovezi incompatibile; asocierea rămâne necunoscută.",
      pending_permitted_document: "Document în așteptarea citirii.",
      headline_only_unpermitted_document: "Titlu RSS; documentul nu este citit de aplicație.",
    };
    box.append(node("p", labels[story.document_state] || story.document_state, "footnote"));
    if ((story.related_reports || []).length > 1) {
      const copies = node("details");
      copies.append(node("summary", `${story.related_reports.length} relatări cu același titlu · independență neconfirmată`));
      for (const report of story.related_reports)
        copies.append(link(`${report.publisher_reported} · ${date(report.published_at)}`, report.url, "text-button"));
      box.append(copies);
    }
    for (const mention of story.contracts) {
      const label = mention.association === "exact_contract_document_mention"
        ? "Adresă exactă și Solana menționate; emitent neconfirmat"
        : mention.association === "contradictory_context"
          ? "Context negativ/contradictoriu; necesită verificare"
          : mention.association === "resolved_market_pair_reference"
            ? "Token identificat prin link de pool și API de piață; emitent neconfirmat"
          : "Adresă observată; blockchain neclar";
      box.append(node("p", `${label} · ${short(mention.contract)}`, "footnote"));
      const reference = mention.payload?.market_reference;
      if (reference) {
        box.append(link("Pool citat în articol", reference.reference_url, "text-button"));
        box.append(node("p", `Pool raportat creat ${reference.pool_created_at_reported ? date(reference.pool_created_at_reported) : "necunoscut"} · variație anterioară 24h raportată ${reference.price_change_24h_reported_pct ?? "—"}% · observat ${date(reference.observed_at)}`, "footnote"));
        if (reference.warning) box.append(node("p", "Cotație în afara activelor suportate sau context negativ: referința nu inițiază descoperire automată.", "footnote"));
      }
      if (mention.candidate_id != null) {
        const button = node("button", mention.eligible ? "Cercetează tokenul" : "Vezi candidatul exclus", "secondary");
        button.type = "button";
        button.onclick = () => openOpportunity(mention.candidate_id);
        box.append(button);
      }
    }
    if (!story.contracts.length)
      box.append(node("p", "Nicio legătură de contract demonstrată pentru această știre.", "footnote"));
    root.append(box);
  }
  if (!data.items.length)
    root.append(
      node(
        "p",
        data.ai_configured && data.enabled
          ? "Se caută documente primare pentru clasificare AI cu citări."
          : "Clasificarea AI nu este activată sau configurată. Dovezile de contract din dosare sunt păstrate separat.",
        "footnote",
      ),
    );
  for (const item of data.items.slice(0, 5)) {
    const box = node("article", undefined, "evidence-item");
    box.append(node("strong", item.category || item.state));
    box.append(
      node(
        "p",
        item.interpretation?.event_summary?.text_ro ||
          item.error ||
          "Analiză în curs.",
        "footnote",
      ),
    );
    box.append(
      node(
        "p",
        "Interpretare AI; asocierea cu un token cere dovezi independente.",
        "warn footnote",
      ),
    );
    for (const s of item.sources)
      box.append(link("Sursă", s.url, "text-button"));
    engineJson(box, "Citări și clasificare", item);
    root.append(box);
  }
  for (const request of (data.document_requests || [])
    .filter((r) => r.error)
    .slice(0, 3)) {
    root.append(
      node("p", `${request.title}: ${request.error}`, "warn footnote"),
    );
  }
  root.append(
    node(
      "p",
      "Nu sunt măsurate automat comunitățile sau volumul social global. Numele asemănătoare sunt asocieri incerte.",
      "footnote",
    ),
  );
}
async function loadDailyResearch() {
  clearTimeout(opportunityView.dailyRetry);
  const day = opportunityView.dailyDay || new Date().toISOString().slice(0, 10);
  const serial = ++opportunityView.dailyRequest;
  $("engine-daily-export").disabled = true;
  $("engine-daily-day").value = day;
  $("engine-daily-day").max = new Date().toISOString().slice(0, 10);
  try {
    const data = await api("/api/opportunities/daily?day=" + encodeURIComponent(day));
    if (serial !== opportunityView.dailyRequest) return;
    if (data.report_state === "preparing") {
      dailyReportNotice(data, day);
      opportunityError("Bilanț zilnic", data.report_cache?.refresh?.state === "error" ? new Error("Calculul bilanțului a eșuat; se reîncearcă în fundal.") : null);
      opportunityView.dailyRetry = setTimeout(() => {
        if (serial === opportunityView.dailyRequest && state.page === "opportunities") loadDailyResearch();
      }, 3000);
      return;
    }
    if (data.day_utc !== day || !data.totals || !data.models || !Number.isFinite(new Date(data.generated_at).getTime()))
      throw new Error("Bilanț invalid sau pentru altă zi; raportul anterior rămâne păstrat.");
    const sameDay = opportunityView.daily?.day_utc === data.day_utc;
    const sameSnapshot = sameDay && opportunityView.daily.generated_at === data.generated_at;
    if (!sameSnapshot) {
      const opened = sameDay ? new Set([...$("engine-daily").querySelectorAll("details[open]")].map(d => d.querySelector("summary")?.textContent)) : new Set();
      renderDailyResearch(data);
      for (const details of $("engine-daily").querySelectorAll("details"))
        details.open = opened.has(details.querySelector("summary")?.textContent);
    }
    opportunityView.daily = data;
    $("engine-daily-export").disabled = false;
    dailyReportNotice(data, day);
    opportunityError("Bilanț zilnic", data.report_cache?.refresh?.state === "error" ? new Error("Ultimul calcul a eșuat; este afișat bilanțul anterior, datat.") : null);
  } catch (error) {
    if (serial === opportunityView.dailyRequest) opportunityError("Bilanț zilnic", error);
  }
}
function dailyReportNotice(data, requestedDay) {
  const root = $("engine-daily"), cache = data.report_cache;
  root.querySelector(".daily-report-notice")?.remove();
  if (!cache) return;
  const refresh = cache.refresh || {}, pending = data.report_state === "preparing";
  const notice = node("p", undefined, "daily-report-notice footnote");
  const previousDay = opportunityView.daily?.day_utc;
  if (pending) {
    notice.textContent = `Bilanțul pentru ${requestedDay} UTC se pregătește în fundal. ${refresh.state === "busy" ? "Coada este ocupată; se reîncearcă automat." : refresh.state === "error" ? "Calculul a eșuat; reîncercarea este automată." : "Candidații rămân accesibili; actualizarea este automată."} ${previousDay ? `Raportul afișat mai jos este pentru ${previousDay} UTC.` : "Nu există încă un rezultat calculat; lipsa lui nu înseamnă zero."}`;
    if (!previousDay) root.replaceChildren();
  } else {
    notice.textContent = `Snapshot din cache · date la ${date(cache.snapshot_at)} · calcul încheiat ${date(cache.calculated_at)}. ${cache.stale ? "Date păstrate, încă neactualizate." : "Ultima versiune completă."} ${refresh.state === "running" || refresh.queued ? "Actualizare în fundal." : ""}`;
  }
  if (refresh.error) notice.textContent += ` Calcul: ${refresh.error}.`;
  if (refresh.last_error && !refresh.error) notice.textContent += ` Ultima eroare păstrată: ${refresh.last_error} · ${date(refresh.last_error_at)}.`;
  if (cache.persistence_error) notice.textContent += ` Cache-ul pe disc nu este disponibil: ${cache.persistence_error}; copia din memorie rămâne datată.`;
  notice.classList.toggle("warn", pending || cache.stale || Boolean(refresh.error) || Boolean(cache.persistence_error));
  root.prepend(notice);
}
function renderForwardEvaluation(root, forward) {
  if (!forward) return;
  const panel = node("details", undefined, "forward-evaluation");
  panel.append(node("summary", "Validare prospectivă · perioade de test declarate în avans"));
  const entries = Object.entries(forward.protocols || {});
  if (!entries.length) panel.append(node("p", "Nicio declarație prospectivă pentru primele semnale din această zi. Datele istorice își păstrează clasificarea.", "footnote"));
  for (const [id, p] of entries) panel.append(node("p", `P${id} · declarat ${date(p.declared_at)} · test de la ${date(p.test_from)} · ${p.state === "test_not_started" ? "Testul nu a început" : "Colectare pentru test; validarea nu este demonstrată"}`, "footnote"));
  for (const [model, horizons] of Object.entries(forward.models || {})) {
    const wrapper = node("div", undefined, "table-scroll"), table = node("table"), head = node("thead"), row = node("tr"), body = node("tbody");
    ["Model / orizont / politică / perioadă", "Selectate evaluate / total", "Control distinct evaluat / total", "PnL mediu net selectate / control"].forEach(v => row.append(node("th", v)));
    head.append(row); table.append(head);
    let count = 0;
    for (const [h, policies] of Object.entries(horizons)) for (const [id, cohorts] of Object.entries(policies)) for (const [cohort, c] of Object.entries(cohorts)) {
      if (!c.all_first_evaluations.experiments) continue;
      const selected = c.selected_at_first_evaluation, control = c.control_excluding_selected, line = node("tr");
      const period = {development: "Dezvoltare", test: "Test", purged_boundary: "La granița perioadelor", unassigned: "Neatribuit"}[cohort] || cohort;
      [`${model === "jupiter_quotes" ? "Jupiter" : "Pool"} · ${Number(h)/60}m · P${id} · ${period}`, `${selected.evaluated} / ${selected.experiments}`, `${control.evaluated} / ${control.experiments}`, `${cash(selected.mean_net_pnl_usd)} / ${cash(control.mean_net_pnl_usd)}`].forEach(v => line.append(node("td", v)));
      body.append(line); count++;
    }
    if (count) { table.append(body); wrapper.append(table); panel.append(wrapper); }
  }
  panel.append(node("p", "Protocol separat de perioadele istorice. Primul semnal fixează selecția; controlul exclude selecțiile suprapuse. Lipsurile rămân necunoscute, iar mediile folosesc numai rezultate evaluate. O perioadă de test începută nu demonstrează profitabilitatea.", "footnote"));
  root.append(panel);
}
function renderDailyResearch(data) {
  const root = $("engine-daily");
  root.replaceChildren();
  root.append(node("h3", `Descoperiri ${data.day_utc} UTC`));
  root.append(node("p", `Rezultate cunoscute la ${date(data.generated_at)}; cohorta rămâne fixată după ziua descoperirii.`, "footnote"));
  const t = data.totals;
  root.append(node("p", `${t.discovered} candidați · ${t.first_evaluations} prime evaluări · ${t.eligible_without_first_evaluation} eligibili fără evaluare · ${t.excluded} excluși`, "footnote"));
  root.append(node("p", `${t.opportunity_alerts} alerte de oportunitate, inclusiv cele ulterioare · ${t.selected_at_first_evaluation} selecții la prima evaluare · ${t.risk_alerts} avertizări de risc`, "footnote"));
  renderForwardEvaluation(root, data.forward_evaluation);
  for (const [model, title] of [["estimated_pool", "Estimări de pool"], ["jupiter_quotes", "Cotații Jupiter"]]) {
    root.append(node("h3", title));
    const wrapper = node("div", undefined, "table-scroll"), table = node("table");
    const header = node("tr");
    ["Orizont / grup", "Evaluate / total", "PnL virtual net", "Rezultate lipsă"].forEach(v => header.append(node("th", v)));
    const head = node("thead"); head.append(header); table.append(head);
    const body = node("tbody");
    for (const [horizon, groups] of Object.entries(data.models[model])) {
      for (const [key, label] of [["all_first_evaluations", "Toate"], ["selected_at_first_evaluation", "Selectate inițial"], ["prospective_fixed_control", "Control prospectiv"]]) {
        const s = groups[key], row = node("tr");
        [`${Number(horizon) / 60}m · ${label}`, `${s.evaluated} / ${s.experiments}`, cash(s.net_pnl_independent_experiments_usd), String(s.unresolved_or_unavailable)]
          .forEach(v => row.append(node("td", v)));
        body.append(row);
      }
    }
    table.append(body); wrapper.append(table); root.append(wrapper);
    const comparisons = node("details", undefined, "daily-comparisons");
    comparisons.append(node("summary", "Selecție versus control · politici și development/test separate"));
    const comparisonScroll = node("div", undefined, "table-scroll"), comparisonTable = node("table");
    const comparisonHead = node("thead"), comparisonHeader = node("tr"), comparisonBody = node("tbody");
    ["Orizont / politică / cohortă", "Selectate evaluate / planificate", "Control fără suprapunere evaluate / planificate", "PnL mediu net selectate / control", "Lipsă selectate / control"].forEach(v => comparisonHeader.append(node("th", v)));
    comparisonHead.append(comparisonHeader); comparisonTable.append(comparisonHead);
    const partitions = {development: "Dezvoltare", test: "Test", unassigned: "Neatribuit", purged_boundary: "Exclus la graniță"};
    for (const [horizon, groups] of Object.entries(data.models[model])) {
      for (const [policy, cohorts] of Object.entries(groups.comparisons_by_policy_and_cohort || {})) {
        for (const [cohort, comparison] of Object.entries(cohorts)) {
          if (!comparison.all_first_evaluations.experiments) continue;
          const selected = comparison.selected_at_first_evaluation, control = comparison.control_excluding_selected, row = node("tr");
          [`${Number(horizon) / 60}m · P${policy} · ${partitions[cohort] || cohort}`, `${selected.evaluated} / ${selected.experiments}`, `${control.evaluated} / ${control.experiments}`, `${cash(selected.mean_net_pnl_usd)} / ${cash(control.mean_net_pnl_usd)}`, `${selected.unresolved_or_unavailable} / ${control.unresolved_or_unavailable}`].forEach(v => row.append(node("td", v)));
          comparisonBody.append(row);
        }
      }
    }
    comparisonTable.append(comparisonBody); comparisonScroll.append(comparisonTable); comparisons.append(comparisonScroll);
    comparisons.append(node("p", "Medii condiționate de rezultatele evaluate. Acoperirea diferă; lipsurile și selecția împiedică o concluzie cauzală sau de profitabilitate. Politicile declarate după vechea dată de test rămân neatribuite.", "footnote"));
    root.append(comparisons);
    if (!Object.keys(data.models[model]).length) root.append(node("p", "Nu există încă experimente pentru această cohortă.", "footnote"));
  }
  root.append(node("p", "Simulări independente, cu costuri modelate. Lipsurile nu sunt profit sau pierdere zero. Grupurile se pot suprapune și au acoperire diferită; profitabilitatea nu este demonstrată.", "footnote"));
  if (data.price_references) {
    const panel = node("details", undefined, "price-reference-comparisons");
    panel.append(node("summary", "Evoluția prețurilor · separat de profitul paper"));
    panel.append(node("p", "De la cotația cunoscută la primul semnal până la prima încercare din intervalul viitor. Fără costuri; creșterea prețului nu dovedește o intrare sau o ieșire executabilă. Tokenurile respinse și lipsurile rămân în numitor.", "footnote"));
    const scroll = node("div", undefined, "table-scroll"), table = node("table"), head = node("thead"), header = node("tr"), body = node("tbody");
    ["Orizont / politică / cohortă", "Selectate observate / planificate", "Control fără suprapunere observate / planificate", "Variație medie selectate / control", "Creșteri ≥100% selectate / control", "Scăderi ≥80% selectate / control", "Lipsă selectate / control"].forEach(v => header.append(node("th", v)));
    head.append(header); table.append(head);
    const percent = value => value != null && Number.isFinite(Number(value)) ? `${Number(value).toLocaleString("ro-RO", {maximumFractionDigits:2})}%` : "—";
    const cohorts = {development:"Dezvoltare", test:"Test", unassigned:"Neatribuit", purged_boundary:"Exclus la graniță"};
    for (const [horizon, groups] of Object.entries(data.price_references.horizons)) {
      for (const [policy, partitions] of Object.entries(groups.by_policy_and_cohort)) {
        for (const [cohort, comparison] of Object.entries(partitions)) {
          if (!comparison.all_first_evaluations.planned) continue;
          const a = comparison.selected_at_first_evaluation, b = comparison.control_excluding_selected, row = node("tr");
          [`${Number(horizon)/60}m · P${policy} · ${cohorts[cohort] || cohort}`, `${a.observed} / ${a.planned}`, `${b.observed} / ${b.planned}`, `${percent(a.mean_price_return_pct)} / ${percent(b.mean_price_return_pct)}`, `${a.increase_at_least_100pct} / ${b.increase_at_least_100pct}`, `${a.decline_at_least_80pct} / ${b.decline_at_least_80pct}`, `${a.unavailable_or_pending} / ${b.unavailable_or_pending}`].forEach(v => row.append(node("td", v)));
          body.append(row);
        }
      }
    }
    table.append(body); scroll.append(table); panel.append(scroll); root.append(panel);
  }
  engineJson(root, "Stări, politici, separare development/test și limite", data);
}
function engineChart(observations, parent) {
  const priced = observations.filter(o => o.market?.price_usd != null && Number.isFinite(Number(o.market.price_usd)));
  if (priced.length < 2) return;
  const values = priced.map(o => Number(o.market.price_usd)), lo = Math.min(...values), hi = Math.max(...values);
  const start = new Date(priced[0].at).getTime(), end = new Date(priced.at(-1).at).getTime();
  const x = o => 18 + 764 * (new Date(o.at).getTime() - start) / Math.max(1, end - start);
  const y = o => 164 - 140 * (Number(o.market.price_usd) - lo) / Math.max(hi - lo, Math.abs(hi) * 0.000001, 1e-30);
  const panel = node("section", undefined, "observed-chart");
  const heading = node("div", undefined, "chart-heading"), readout = node("div", undefined, "chart-readout");
  heading.append(node("h3", "Preț observat"), node("span", "OBSERVAȚII API · FĂRĂ DATE INTERPOLATE", "eyebrow"));
  panel.append(heading, readout);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 800 190");
  svg.classList.add("engine-chart");
  svg.setAttribute("role", "img");
  svg.setAttribute("tabindex", "0");
  svg.setAttribute("aria-label", "Prețuri observate; spațiile fără date nu sunt interpolate. Săgețile stânga și dreapta parcurg observațiile.");
  function element(tag, attributes) {
    const item = document.createElementNS(svg.namespaceURI, tag);
    for (const [key, value] of Object.entries(attributes)) item.setAttribute(key, value);
    svg.append(item); return item;
  }
  for (const height of [24, 94, 164]) element("line", {x1:18, x2:782, y1:height, y2:height, stroke:"currentColor", opacity:0.12, "stroke-dasharray":"4 6"});
  let path = "", previous = null;
  const segments = [];
  for (const o of observations) {
    if (!priced.includes(o)) { previous = null; continue; }
    const t = new Date(o.at).getTime();
    const connected = previous !== null && t - previous < Math.max(180000, (opportunityView.config?.interval_seconds || 60) * 2500);
    path += (connected ? " L" : " M") + `${x(o).toFixed(2)} ${y(o).toFixed(2)}`;
    previous = t;
    segments.push(o);
  }
  const color = values.at(-1) < values[0] ? "var(--red)" : "var(--green)";
  element("path", {d:path, fill:"none", stroke:color, "stroke-width":2, "vector-effect":"non-scaling-stroke"});
  // Isolated observations remain visible even when long gaps break the line.
  for (const o of segments) element("circle", {cx:x(o), cy:y(o), r:2.5, fill:color});
  const cursor = element("line", {x1:0, x2:0, y1:12, y2:176, stroke:"currentColor", opacity:0.3, "stroke-dasharray":"3 4"});
  const point = element("circle", {r:5, fill:color, stroke:"var(--panel)", "stroke-width":3});
  let selected = priced.length - 1;
  function show(index) {
    selected = Math.max(0, Math.min(priced.length - 1, index));
    const o = priced[selected];
    readout.replaceChildren(node("strong", price(o.market.price_usd)), node("span", date(o.at), "footnote"));
    svg.setAttribute("aria-label", `Preț observat ${price(o.market.price_usd)}, ${date(o.at)}. Săgețile stânga și dreapta parcurg observațiile. Golurile fără date nu sunt interpolate.`);
    cursor.setAttribute("x1", x(o)); cursor.setAttribute("x2", x(o));
    point.setAttribute("cx", x(o)); point.setAttribute("cy", y(o));
  }
  svg.onpointermove = event => {
    const rect = svg.getBoundingClientRect(), target = (event.clientX - rect.left) / rect.width * 800;
    let nearest = 0;
    for (let i = 1; i < priced.length; i++) if (Math.abs(x(priced[i]) - target) < Math.abs(x(priced[nearest]) - target)) nearest = i;
    show(nearest);
  };
  svg.onpointerleave = () => show(priced.length - 1);
  svg.onkeydown = event => {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      show(event.key === "Home" ? 0 : event.key === "End" ? priced.length - 1 : selected + (event.key === "ArrowRight" ? 1 : -1));
    }
  };
  show(selected);
  panel.append(svg);
  const axis = node("div", undefined, "chart-axis");
  axis.append(node("span", date(priced[0].at)), node("span", date(priced.at(-1).at)));
  panel.append(axis, node("p", `Min observat ${price(lo)} · max observat ${price(hi)} · ${priced.length} observații. Extrema dintre observații rămân necunoscute.`, "footnote"));
  parent.append(panel);
}
function opportunityPaperForm(candidate) {
  if (opportunityView.paperDraft?.candidateId === candidate.id)
    return opportunityView.paperDraft.element;
  const latest = candidate.observations.at(-1);
  const box = node("details", undefined, "dossier-section opportunity-paper");
  box.append(node("summary", "Portofoliul meu · ordin virtual"));
  box.append(node("p", "Tu decizi suma și momentul. Acest ordin folosește soldul contului tău virtual și este separat de experimentele automate de 50 USD.", "footnote"));
  opportunityView.paperDraft = {candidateId: candidate.id, element: box};
  if (candidate.chain !== "solana" || !candidate.eligible || !["MONITOR", "INVESTIGATE", "CONSIDER"].includes(latest?.decision?.verdict)) {
    box.append(node("p", "Intrare indisponibilă: este necesar un candidat Solana eligibil, evaluat și fără verdict REJECT. Actualizează dosarul după reevaluare.", "warn"));
    // Rebuild disabled forms when a later observation becomes eligible.
    opportunityView.paperDraft = null;
    return box;
  }
  box.append(node("p", `Dovada aleasă: observația #${latest.id} din ${date(latest.at)}, verdict ${latest.decision.verdict}. Rămâne legată de ordin chiar dacă dosarul se actualizează. Prețul intrării va fi colectat din nou.`, "footnote"));
  const form = node("form", undefined, "paper-box"), account = node("select"), amount = node("input"), thesis = node("textarea");
  account.setAttribute("aria-label", "Cont pentru oportunitate");
  for (const [value, label] of [["news", "News · capital inițial 500 USD"], ["scanner", "Scanner"]]) {
    const option = node("option", label); option.value = value; account.append(option);
  }
  amount.type = "number"; amount.min = state.status?.rules?.min_position || "2";
  amount.step = ".01"; amount.value = "50"; amount.required = true;
  amount.setAttribute("aria-label", "Suma ordinului din oportunitate");
  thesis.maxLength = 1000; thesis.placeholder = "De ce intru și ce invalidează ipoteza?";
  thesis.setAttribute("aria-label", "Ipoteza oportunității");
  for (const [labelText, control] of [["Cont virtual", account], ["Suma ordinului · USD", amount], ["Ipoteza mea", thesis]]) {
    const label = node("label", labelText); label.append(control); form.append(label);
  }
  const limits = node("p", undefined, "footnote"), costs = node("p", undefined, "footnote"), status = node("p", "Salvează decizia pentru a colecta dovezi noi. Nu se plasează automat un ordin.", "footnote");
  status.setAttribute("role", "status");
  const renderLimits = () => {
    const r = state.status?.rules;
    limits.textContent = r ? `Alocare maximă ${Number(r.max_allocation) * 100}% din capital, inclusiv costuri. ${account.value === "scanner" ? `Capital inițial Scanner: ${cash(r.initial_balance)}; 50 USD poate depăși limita.` : "Capitalul și expunerea disponibile sunt reverificate la ordin."}` : "Soldul, alocarea, expunerea și costurile sunt verificate pe server.";
  };
  let saved = null, busy = false, generation = 0, readyTimer = null, expiryTimer = null;
  const invalidate = () => {
    generation++; saved = null; clearTimeout(readyTimer); clearTimeout(expiryTimer);
    costs.textContent = "";
    buy.disabled = true; save.textContent = "Salvează decizia și verifică datele";
  };
  const save = button("Salvează decizia și verifică datele", "secondary", async () => {
    if (busy || !form.reportValidity()) return;
    invalidate(); busy = true; save.disabled = true;
    account.disabled = amount.disabled = thesis.disabled = true;
    status.textContent = "Colectăm prețul și verificările de securitate…";
    try {
      const result = await api(`/api/opportunities/${candidate.id}/paper-signal`, {
        observation_id: latest.id, account: account.value, thesis: thesis.value, amount_usd: amount.value,
      });
      const token = ++generation;
      saved = {id: result.id, address: candidate.contract, account: account.value, amount: amount.value};
      const allowed = result.snapshot?.analysis?.paper_allowed === true;
      const analysis = result.snapshot?.analysis;
      const preview = result.cost_preview;
      costs.textContent = preview?.available ? `Estimare pentru suma ta: debit ${cash(-Number(preview.entry.cash_change))}, impact intrare ${percent(Number(preview.entry.price_impact) * 100)}, ieșire la același preț ${cash(preview.exit_at_unchanged_price.cash_change)}, rezultat tur-retur ${cash(preview.roundtrip_pnl_usd)}, break-even +${percent(preview.break_even_rise_pct)}. Include fee și rețea presupuse; nu garantează execuția și se recalculează la ordin.` : preview?.reason || "";
      status.textContent = `Decizie #${result.id} salvată. Preț nou ${price(result.snapshot?.market?.price_usd)}. ${allowed ? `Așteaptă minimum ${result.min_delay_seconds} secunde; ordinul verifică din nou datele.` : `Intrare blocată: ${[...(analysis?.critical || []), ...(analysis?.unknown || [])].join("; ") || "verificări incomplete"}.`}`;
      if (allowed) {
        readyTimer = setTimeout(() => {
          if (generation === token) buy.disabled = false;
        }, result.min_delay_seconds * 1000);
        expiryTimer = setTimeout(() => {
          if (generation === token) {
            invalidate(); status.textContent = "Decizia a expirat. Salvează din nou pentru dovezi actuale.";
          }
        }, result.valid_for_seconds * 1000);
      }
    } catch (error) {
      status.textContent = error.message; message(error.message);
    } finally {
      busy = false; save.disabled = false;
      account.disabled = amount.disabled = thesis.disabled = false;
    }
  });
  const buy = button("Cumpără virtual", "primary", async () => {
    if (busy || !saved || buy.disabled) return;
    const order = saved;
    invalidate(); busy = true; save.disabled = true;
    account.disabled = amount.disabled = thesis.disabled = true;
    status.textContent = "Verificăm datele noi, costurile și limitele contului…";
    try {
      await api("/api/paper/buy", {address: order.address, signal_id: order.id, account: order.account, amount_usd: order.amount});
      status.textContent = "Ordin virtual înregistrat în portofoliu.";
      message("Ordin virtual înregistrat. Verdictul inițial și costurile sunt păstrate în jurnal.", true);
      if (box.isConnected && state.page === "opportunities" && opportunityView.selection === candidate.id) {
        await selectPaperAccount(order.account);
        navigate("portfolio");
      }
    } catch (error) {
      status.textContent = `${error.message} Salvează o decizie nouă înainte să reîncerci.`; message(error.message);
    } finally {
      busy = false; save.disabled = false;
      account.disabled = amount.disabled = thesis.disabled = false;
    }
  });
  buy.disabled = true;
  for (const control of [account, amount, thesis]) control.addEventListener("input", () => {
    invalidate(); renderLimits(); status.textContent = "Date schimbate. Salvează o decizie nouă.";
  });
  form.onsubmit = event => event.preventDefault();
  form.append(limits, save, buy, status, costs);
  renderLimits(); box.append(form); return box;
}
async function openOpportunity(id, scroll = true) {
  opportunityView.selection = id;
  const serial = ++opportunityView.detailRequest;
  try {
    const c = await api("/api/opportunities/" + id);
    if (
      serial !== opportunityView.detailRequest ||
      opportunityView.selection !== id
    )
      return;
    const root = $("engine-detail");
    const focused = root.contains(document.activeElement) ? document.activeElement : null;
    const expanded =
      root.dataset.candidateId === String(id)
        ? new Set(
            [...root.querySelectorAll("details[open]")].map(
              (d) => d.querySelector("summary")?.textContent,
            ),
          )
        : new Set();
    root.dataset.candidateId = id;
    root.hidden = false;
    root.replaceChildren();
    const latest = c.observations.at(-1),
      d = latest?.decision,
      m = latest?.market;
    const header = node("div", undefined, "dossier-header"), identity = node("div", undefined, "dossier-identity"), title = node("div");
    title.append(node("p", "DOSAR DE CERCETARE / " + (c.chain || "CHAIN NECUNOSCUT").toUpperCase(), "eyebrow"), node("h2", m?.name || c.discovery.name || "Candidat"));
    identity.append(candidateAvatar(c.contract, m?.symbol || c.discovery.name), title);
    const close = button("Închide dosarul ×", "secondary dossier-close", () => {
      opportunityView.selection = null;
      opportunityView.paperDraft = null;
      opportunityView.detailRequest++;
      root.hidden = true;
      renderCandidateRows();
      $("engine-candidates").scrollIntoView({block:"start"});
      $("engine-search").focus({preventScroll:true});
    });
    header.append(identity, close); root.append(header);
    const contract = node("div", undefined, "dossier-contract");
    const copy = button("Copiază adresa", "text-button", async () => {
      try { await navigator.clipboard.writeText(c.contract); message("Adresa contractului a fost copiată.", true); }
      catch { message("Copierea nu este disponibilă în acest browser. Selectează adresa afișată."); }
    });
    contract.append(node("code", c.contract, "contract-text"), copy);
    if (["solana", "base"].includes(c.chain)) contract.append(link("Explorer", (c.chain === "solana" ? "https://solscan.io/token/" : "https://basescan.org/token/") + encodeURIComponent(c.contract), "text-button"), link("Piață", `https://dexscreener.com/${c.chain}/${encodeURIComponent(c.pool)}`, "text-button"));
    root.append(contract, node("p", "Identitate oficială neconfirmată · numele și simbolul pot fi imitate.", "footnote"));
    root.append(
      node(
        "p",
        `Prima descoperire ${date(c.discovered_at)} · înregistrare în motor ${date(c.ingested_at)} · pool ${short(c.pool)}`,
        "footnote",
      ),
    );
    if (latest)
      root.append(
        node(
          "p",
          `Ultima observație ${date(latest.at)} · ${Date.now() - new Date(latest.at).getTime() > 120000 ? "date păstrate, reevaluarea este necesară" : "răspuns API recent; ora tranzacției sursă poate fi necunoscută"}`,
          "footnote",
        ),
      );
    if (c.monitoring) {
      const labels = {
        excluded: "Exclus din monitorizarea automată",
        awaiting_first_observation: "Prima colectare este încă necesară",
        manual_watch: "Urmărit prin lista personală sau o poziție virtuală",
        reactivated: "Urmărire reluată după o referință recentă la contract; asocierea oficială nu este confirmată",
        active: "Monitorizare inițială activă",
        followup: "Observații promise sau rezultate încă nerezolvate",
        metadata_unknown: "Momentul înregistrării este necunoscut; verificarea continuă",
        background: "Monitorizare periodică în fereastra de fundal",
        paused: "Reevaluarea periodică este în pauză; istoricul și rezultatele rămân accesibile",
      };
      root.append(node("p", labels[c.monitoring.state] || c.monitoring.state, "footnote"));
    }
    if (c.history_truncated)
      root.append(
        node(
          "p",
          `Graficul arată ultimele ${c.observations.length} din ${c.observations_total} observații. Semnalele și rezultatele sunt păstrate integral.`,
          "warn footnote",
        ),
      );
    if (d) {
      const verdict = node("div", undefined, "dossier-verdict");
      verdict.append(enginePill(d.verdict, d.verdict), node("span", verdictDescriptions[d.verdict] || "Verdict de cercetare"));
      root.append(verdict);
    }
    const metrics = node("div", undefined, "dossier-metrics");
    for (const [label, value, note] of [
      ["Preț raportat", price(m?.price_usd), m?.source || "Sursă de piață indisponibilă"],
      ["Lichiditate disponibilă", cash(m?.liquidity_usd), "Raportată pentru acest pool"],
      ["Volum / 5 minute", cash(m?.volume_5m), "Volumul nu confirmă cerere organică"],
      ["Variație / 5 minute", percent(m?.change_5m), "Raportată de sursă; fără predicție"],
    ]) metrics.append(engineStat(label, value, note));
    root.append(metrics);
    root.append(opportunityPaperForm(c));
    engineChart(c.observations, root);
    dossierActivity(root, latest?.features);
    if (d) {
      const scoreSection = node("section", undefined, "dossier-section");
      scoreSection.append(node("h3", "Profilul de cercetare"), node("p", "Scoruri euristice, fără probabilități de câștig. La riscul de securitate, mai mare înseamnă mai riscant; la celelalte dimensiuni, dovezi mai puternice. Necunoscut nu înseamnă sigur.", "footnote"));
      const scores = node("div", undefined, "engine-scores");
      for (const [key, value] of Object.entries(d.scores)) {
        const score = engineStat(
            opportunityLabels[key] || key,
            value == null ? "Necunoscut" : `${value}/100`,
            key === "security_risk" ? "Mai mic = risc mai mic în verificările disponibile" : value == null ? "Lipsesc dovezile necesare" : "Mai mare = scor euristic mai ridicat",
          );
        score.classList.add("research-score");
        if (value == null) score.classList.add("score-unknown");
        const track = node("span", undefined, "score-track"), fill = node("i");
        fill.style.width = `${value == null ? 0 : Math.min(100, Math.max(0, Number(value)))}%`;
        if (key === "security_risk") fill.classList.add("risk-score-fill");
        track.setAttribute("aria-hidden", "true"); track.append(fill); score.append(track);
        scores.append(score);
      }
      scoreSection.append(scores); root.append(scoreSection);
      const reasons = node("div", undefined, "dossier-reasons");
      for (const [name, list, style] of [
        ["Ce susține cercetarea", d.positive, "good"],
        ["Riscuri", d.negative, "warn"],
        ["Necunoscute", d.unknown, "footnote"],
        ["Când se invalidează ipoteza", d.invalidation, "warn"],
      ]) {
        const card = node("section", undefined, "reason-card " + style.replace("footnote", "unknown-reasons"));
        card.append(node("h3", name), node("span", `${list.length} observații`, "reason-count"));
        const ul = node("ul");
        for (const value of list) {
          const item = node("li", researchTranslations[value] || value);
          if (researchTranslations[value]) item.title = value;
          ul.append(item);
        }
        if (!list.length) card.append(node("p", "Nicio observație raportată în această categorie.", "footnote"));
        card.append(ul); reasons.append(card);
      }
      root.append(reasons);
      const costPanel = node("section", undefined, "dossier-section cost-summary");
      costPanel.append(node("h3", "Costuri pentru o poziție virtuală mică"), node("p", "Model estimativ de pool, separat de cotațiile Jupiter. Nu dovedește executarea unui ordin.", "footnote"));
      if (d.costs.economically_feasible_in_model) {
        const costs = node("div", undefined, "dossier-metrics");
        costs.append(engineStat("Ieșire + intrare", percent(d.costs.roundtrip_cost_pct), "Cost tur-retur la același preț"), engineStat("Prag break-even", percent(d.costs.break_even_rise_pct), "Creștere estimată pentru acoperirea costurilor"));
        costPanel.append(costs);
      } else costPanel.append(node("p", "Intrarea și ieșirea estimate nu sunt disponibile în limitele de lichiditate, mărime sau impact ale modelului.", "warn footnote"));
      root.append(costPanel);
      engineJson(root, "Costuri de intrare / ieșire estimate", d.costs);
    }
    if (c.current_narrative) {
      root.append(node("h3", "Legături actuale cu știrile"));
      root.append(node("p", "Dovezi disponibile acum; semnalele originale și scorurile lor rămân păstrate.", "footnote"));
      const evidence = c.current_narrative;
      for (const [key, label] of [["supported", "Mențiune de adresă și chain; emitent neconfirmat"], ["market_references", "Referință de pool rezolvată prin API; emitent neconfirmat"], ["contradictory", "Context negativ sau contradictoriu"], ["uncertain", "Asociere incertă"]]) {
        for (const item of (evidence[key] || []).slice(0, 5)) {
          const box = node("article", undefined, "evidence-item");
          box.append(node("strong", label), link(item.title, item.url, "text-button"));
          box.append(node("p", `Publicat ${date(item.published_at)} · dovezi observate ${date(item.evidence_indexed_at || item.document_observed_at || item.first_seen_at)}`, "footnote"));
          if (item.excerpt) box.append(node("p", item.excerpt, "footnote"));
          root.append(box);
        }
      }
      if (!["supported", "market_references", "contradictory", "uncertain"].some(key => evidence[key]?.length))
        root.append(node("p", "Nu există dovezi suficiente pentru a lega acest token de o știre.", "footnote"));
    }
    const outcomes = node("div");
    outcomes.className = "dossier-section dossier-outcomes";
    outcomes.append(node("h3", "Rezultate păstrate"));
    outcomes.append(node("p", "Experimente virtuale independente. Un rezultat lipsă sau o ieșire indisponibilă rămâne necunoscut, nu zero. MFE/MAE descriu numai observațiile disponibile.", "footnote"));
    dossierOutcomes(outcomes, c.outcomes);
    if (!c.outcomes.length) outcomes.append(node("p", "Nu există încă rezultate pentru acest candidat.", "footnote"));
    engineJson(outcomes, "Istoricul complet al rezultatelor", c.outcomes);
    root.append(outcomes);
    if (c.routed) {
      const routed = node("div", undefined, "dossier-section");
      routed.append(
        node("h3", "Paper Jupiter · separat de estimările de pool"),
      );
      dossierOutcomes(routed, c.routed.outcomes, true);
      engineJson(routed, "Cotații originale și politica de cost", c.routed);
      root.append(routed);
    }
    engineJson(root, "Semnale originale și politici înghețate", c.signals);
    engineJson(root, "Observații, narațiuni și walleturi", c.observations);
    engineJson(root, "Captura inițială", c.discovery);
    for (const details of root.querySelectorAll("details"))
      details.open = expanded.has(
        details.querySelector("summary")?.textContent,
      );
    if (!scroll && focused?.isConnected) focused.focus({preventScroll: true});
    if (scroll) root.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    if (
      serial !== opportunityView.detailRequest ||
      opportunityView.selection !== id
    )
      return;
    const root = $("engine-detail");
    root.hidden = false;
    if (root.dataset.candidateId !== String(id)) root.replaceChildren();
    let warning = root.querySelector(".engine-detail-error");
    if (!warning) {
      warning = node("p", undefined, "engine-detail-error warn");
      root.prepend(warning);
    }
    warning.textContent =
      "Dosarul nu poate fi actualizat: " +
      error.message +
      ". Datele păstrate pot fi vechi.";
  }
}
function setupOpportunityControls() {
  $("engine-pilot-start").onclick = () => action($("engine-pilot-start"), async () => {
    ++pilotView.serial;
    renderPilot(await api("/api/opportunities/pilot/start", {}));
    await loadPilot();
  });
  $("engine-pilot-refresh").onclick = loadPilot;
  $("engine-pilot-export").onclick = () => {
    if (!pilotView.data) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(pilotView.data, null, 2)], {type:"application/json"}));
    const a = document.createElement("a"); a.href = url;
    a.download = `memescope-pilot-${pilotView.data.study.declared_at.slice(0,10)}.json`;
    a.click(); URL.revokeObjectURL(url);
  };
  document.querySelectorAll("[data-verdict]").forEach(b => {
    b.onclick = () => {
      $("engine-verdict").value = b.dataset.verdict;
      syncVerdictFilters();
      loadOpportunityCandidates();
    };
  });
  document.querySelectorAll("[data-research-target]").forEach(b => {
    b.onclick = () => {
      const target = $(b.dataset.researchTarget);
      if (target.tagName === "DETAILS") target.open = true;
      document.querySelectorAll("[data-research-target]").forEach(other => other.classList.toggle("active", b === other));
      target.scrollIntoView({behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block:"start"});
      target.tabIndex = -1;
      target.focus({preventScroll:true});
    };
  });
  let searchTimer;
  $("engine-search").oninput = () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadOpportunityCandidates(), 250);
  };
  $("engine-verdict").onchange = () => { syncVerdictFilters(); loadOpportunityCandidates(); };
  $("engine-sort").onchange = () => loadOpportunityCandidates();
  $("engine-refresh").onclick = renderOpportunities;
  $("engine-daily-day").onchange = () => {
    opportunityView.dailyDay = $("engine-daily-day").value || null;
    loadDailyResearch();
  };
  $("engine-daily-today").onclick = () => {
    opportunityView.dailyDay = null;
    loadDailyResearch();
  };
  $("engine-daily-export").onclick = () => {
    if (!opportunityView.daily) return;
    const data = opportunityView.daily;
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: "application/json"}));
    const a = document.createElement("a");
    a.href = url;
    a.download = `memescope-${data.day_utc}-observat-${data.generated_at.replaceAll(":", "-")}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  $("engine-more").onclick = () =>
    action($("engine-more"), () => loadOpportunityCandidates("more"));
  $("engine-config").onsubmit = async (event) => {
    event.preventDefault();
    if (!opportunityView.config) return;
    try {
      const c = {
        ...opportunityView.config,
        enabled: $("engine-enabled").checked,
        observation_budget: Number($("engine-budget").value),
        position_usd: Number($("engine-position").value),
        min_transactions_5m: Number($("engine-min-tx").value),
        cooldown_seconds: Number($("engine-cooldown").value),
        ai_narratives: $("engine-ai").checked,
        routed_quotes_enabled: $("engine-routed").checked,
        routed_quote_budget: Number($("engine-route-budget").value),
        routed_slippage_bps: Number($("engine-route-slippage").value),
        telegram_enabled: $("engine-telegram").checked,
      };
      const split = $("engine-test-from").value;
      c.test_from = split ? new Date(split).toISOString() : null;
      await api("/api/opportunities/config", c);
      message(
        "Praguri salvate. Semnalele existente păstrează regulile originale.",
        true,
      );
      await renderOpportunities();
    } catch (error) {
      message(error.message);
    }
  };
}
document.addEventListener("DOMContentLoaded", setupOpportunityControls);
