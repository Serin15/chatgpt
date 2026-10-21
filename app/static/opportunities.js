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
  for (const c of items) {
    const m = c.latest?.market || {},
      d = c.latest?.decision,
      f = c.latest?.features || {},
      row = node("tr");
    const name = node("td");
    name.append(
      node("strong", m.symbol || c.discovery.name || "Date în așteptare"),
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
      button("Cercetează", "secondary", () => openOpportunity(c.id)),
    );
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
  if (Object.keys(opportunityView.errors).length)
    state.sectionErrors.opportunities = Object.keys(
      opportunityView.errors,
    ).join(", ");
  else delete state.sectionErrors.opportunities;
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
  root.append(
    engineStat(
      "CANDIDAȚI",
      t.discovered,
      `${t.eligible} eligibili în universul observat`,
    ),
    engineStat(
      "FILTRU DE SECURITATE",
      report.current_security_pass,
      "Verificări limitate, fără garanție de siguranță",
    ),
    engineStat(
      "ALERTE",
      t.alerts,
      `${t.delivered_in_app} afișate în aplicație`,
    ),
    engineStat("OBSERVAȚII", t.observations, "Inclusiv încercările fără date"),
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
      box.append(node("p", reason, "good footnote"));
    box.append(
      node(
        "p",
        p.negative.concat(p.unknown).slice(0, 2).join(" "),
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
  const day = opportunityView.dailyDay || new Date().toISOString().slice(0, 10);
  const serial = ++opportunityView.dailyRequest;
  $("engine-daily-export").disabled = true;
  $("engine-daily-day").value = day;
  $("engine-daily-day").max = new Date().toISOString().slice(0, 10);
  try {
    const data = await api("/api/opportunities/daily?day=" + encodeURIComponent(day));
    if (serial !== opportunityView.dailyRequest) return;
    opportunityView.daily = data;
    $("engine-daily-export").disabled = false;
    renderDailyResearch(data);
    opportunityError("Bilanț zilnic", null);
  } catch (error) {
    if (serial === opportunityView.dailyRequest) opportunityError("Bilanț zilnic", error);
  }
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
  const priced = observations.filter((o) => o.market);
  if (priced.length < 2) return;
  const values = priced.map((o) => o.market.price_usd),
    lo = Math.min(...values),
    hi = Math.max(...values),
    start = new Date(priced[0].at).getTime(),
    end = new Date(priced.at(-1).at).getTime();
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 600 130");
  svg.classList.add("engine-chart");
  svg.setAttribute(
    "aria-label",
    "Prețuri observate; spațiile fără date nu sunt interpolate",
  );
  let path = "",
    previous = null;
  for (const o of observations) {
    if (!o.market) {
      previous = null;
      continue;
    }
    const t = new Date(o.at).getTime(),
      x = 10 + (580 * (t - start)) / Math.max(1, end - start),
      y =
        115 -
        (100 * (o.market.price_usd - lo)) / Math.max(hi - lo, hi * 0.000001);
    path +=
      (previous &&
      t - previous <
        Math.max(
          180000,
          (opportunityView.config?.interval_seconds || 60) * 2500,
        )
        ? " L"
        : " M") + `${x.toFixed(2)} ${y.toFixed(2)}`;
    previous = t;
  }
  const line = document.createElementNS(svg.namespaceURI, "path");
  line.setAttribute("d", path);
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", "#9af3c4");
  line.setAttribute("stroke-width", "2");
  svg.append(line);
  parent.append(
    svg,
    node(
      "p",
      `Min observat ${price(lo)} · max observat ${price(hi)} · ${priced.length} observații. Extrema dintre observații rămân necunoscute.`,
      "footnote",
    ),
  );
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
    root.append(
      node("h2", m?.name || c.discovery.name || "Candidat"),
      node("p", c.contract, "contract-text"),
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
      root.append(enginePill(d.verdict, d.verdict));
      const scores = node("div", undefined, "engine-scores");
      for (const [key, value] of Object.entries(d.scores))
        scores.append(
          engineStat(
            opportunityLabels[key] || key,
            value == null ? "Necunoscut" : `${value}/100`,
          ),
        );
      root.append(scores);
      for (const [name, list, style] of [
        ["Pozitive", d.positive, "good"],
        ["Riscuri", d.negative, "warn"],
        ["Necunoscute", d.unknown, "footnote"],
        ["Invalidare", d.invalidation, "warn"],
      ]) {
        root.append(node("h3", name));
        for (const value of list)
          root.append(node("p", value, style + " footnote"));
      }
      engineJson(root, "Costuri de intrare / ieșire estimate", d.costs);
    }
    engineChart(c.observations, root);
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
    outcomes.append(node("h3", "Rezultate păstrate"));
    for (const o of c.outcomes.slice(-15)) {
      outcomes.append(
        node(
          "p",
          `Semnal ${o.signal_id} · ${o.horizon_seconds / 60}m · ${o.state} · PnL ${cash(o.payload.pnl_usd)} · MFE observat ${o.payload.mfe_observed_pct?.toFixed(2) ?? "—"}% · MAE ${o.payload.mae_observed_pct?.toFixed(2) ?? "—"}%`,
          "footnote",
        ),
      );
    }
    root.append(outcomes);
    if (c.routed) {
      const routed = node("div");
      routed.append(
        node("h3", "Paper Jupiter · separat de estimările de pool"),
      );
      for (const o of c.routed.outcomes.slice(-15))
        routed.append(
          node(
            "p",
            `Semnal ${o.signal_id} · ${o.horizon_seconds / 60}m · ${o.state} · PnL virtual ${cash(o.payload.pnl_usd)}${o.payload.reason ? ` · ${o.payload.reason}` : ""}`,
            "footnote",
          ),
        );
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
  let searchTimer;
  $("engine-search").oninput = () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadOpportunityCandidates(), 250);
  };
  $("engine-verdict").onchange = () => loadOpportunityCandidates();
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
