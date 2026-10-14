/* Level 3: persistent discovery, immutable evidence and independent paper outcomes. */
const opportunityView = {
  loading: false,
  config: null,
  items: [],
  cursor: null,
  selection: null,
  alerts: [],
  alertCursor: null,
  alertArchiveLoaded: false,
  alertsShown: 20,
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
  const query = $("engine-search").value.toLowerCase(),
    filter = $("engine-verdict").value;
  const items = opportunityView.items.filter((c) => {
    const m = c.latest?.market || {},
      d = c.latest?.decision;
    return (
      (filter === "all" || (d?.verdict || "PENDING") === filter) &&
      [m.name, m.symbol, c.contract].join(" ").toLowerCase().includes(query)
    );
  });
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
async function renderOpportunities() {
  if (opportunityView.loading || document.body.classList.contains("locked"))
    return;
  opportunityView.loading = true;
  try {
    const paths = [
      `/api/opportunities?sort=${$("engine-sort").value}`,
      "/api/opportunities/alerts",
      "/api/opportunities/performance",
      "/api/opportunities/narratives",
      "/api/wallets",
    ];
    const results = await Promise.allSettled(paths.map((p) => api(p)));
    if (results[0].status === "fulfilled") {
      const data = results[0].value;
      opportunityView.items = data.items;
      opportunityView.cursor = data.next_cursor;
      opportunityView.config = data.config;
      $("engine-health").textContent =
        `Motor: ${data.status.state} · ultim ciclu ${date(data.status.at)} · ${data.status.observed ?? 0} observații în ciclu. ${data.coverage}`;
      if (data.status.errors?.length)
        $("engine-health").textContent +=
          ` Probleme: ${data.status.errors.join(", ")}.`;
      if (data.status.queue)
        $("engine-health").textContent +=
          ` În așteptare: ${data.status.queue.due}; întârziere maximă ${data.status.queue.oldest_due_delay_seconds}s.`;
      renderCandidateRows();
      if (!$("engine-config").dataset.loaded) {
        const c = data.config;
        $("engine-enabled").checked = c.enabled;
        $("engine-position").value = c.position_usd;
        $("engine-min-tx").value = c.min_transactions_5m;
        $("engine-cooldown").value = c.cooldown_seconds;
        $("engine-ai").checked = c.ai_narratives;
        $("engine-telegram").checked = c.telegram_enabled;
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
    } else
      $("engine-health").textContent =
        "Motorul nu poate fi citit: " + results[0].reason.message;
    if (results[2].status === "fulfilled") {
      const report = results[2].value,
        t = report.totals,
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
        engineStat(
          "OBSERVAȚII",
          t.observations,
          "Inclusiv încercările fără date",
        ),
      );
      renderEnginePerformance(report);
    }
    if (results[1].status === "fulfilled") {
      const current = results[1].value;
      const merged = new Map(opportunityView.alerts.map((a) => [a.id, a]));
      current.items.forEach((a) => merged.set(a.id, a));
      opportunityView.alerts = [...merged.values()].sort((a, b) => b.id - a.id);
      if (!opportunityView.alertArchiveLoaded)
        opportunityView.alertCursor = current.next_cursor;
      await renderEngineAlerts(opportunityView.alerts);
    }
    if (results[3].status === "fulfilled")
      renderEngineNarratives(results[3].value);
    if (results[4].status === "fulfilled") {
      const root = $("engine-wallets");
      root.replaceChildren();
      const wallets = results[4].value;
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
    const failed = results
      .map((r, i) =>
        r.status === "rejected" ? paths[i] + ": " + r.reason.message : null,
      )
      .filter(Boolean);
    if (failed.length)
      $("engine-health").textContent +=
        " Componente indisponibile: " + failed.join("; ");
    if (opportunityView.selection !== null)
      await openOpportunity(opportunityView.selection, false);
  } catch (error) {
    $("engine-health").textContent = error.message;
  } finally {
    opportunityView.loading = false;
  }
}
async function renderEngineAlerts(items) {
  const root = $("engine-alerts");
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
      Object.assign(a,await api(`/api/opportunities/alerts/${a.id}/receipt`, {}));
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
function renderEngineNarratives(data) {
  const root = $("engine-narratives");
  root.replaceChildren();
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
  try {
    const c = await api("/api/opportunities/" + id),
      root = $("engine-detail");
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
    engineJson(root, "Semnale originale și politici înghețate", c.signals);
    engineJson(root, "Observații, narațiuni și walleturi", c.observations);
    engineJson(root, "Captura inițială", c.discovery);
    if (scroll) root.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    message(error.message);
  }
}
function setupOpportunityControls() {
  $("engine-search").oninput = renderCandidateRows;
  $("engine-verdict").onchange = renderCandidateRows;
  $("engine-sort").onchange = renderOpportunities;
  $("engine-refresh").onclick = renderOpportunities;
  $("engine-more").onclick = async () => {
    try {
      const d = await api(
        `/api/opportunities?before=${opportunityView.cursor}`,
      );
      opportunityView.items.push(...d.items);
      opportunityView.cursor = d.next_cursor;
      renderCandidateRows();
    } catch (e) {
      message(e.message);
    }
  };
  $("engine-config").onsubmit = async (event) => {
    event.preventDefault();
    if (!opportunityView.config) return;
    try {
      const c = {
        ...opportunityView.config,
        enabled: $("engine-enabled").checked,
        position_usd: Number($("engine-position").value),
        min_transactions_5m: Number($("engine-min-tx").value),
        cooldown_seconds: Number($("engine-cooldown").value),
        ai_narratives: $("engine-ai").checked,
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
