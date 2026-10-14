/* Advanced research, single-owner login and explicit external notification controls. */
async function startApplication() {
  try {
    const response = await fetch("/api/auth/session");
    const session = await response.json();
    state.csrf = session.csrf;
    state.authRequired = session.required;
    if (!session.authenticated) {
      showLogin();
      return;
    }
    await load();
  } catch (error) {
    message("Sesiunea nu poate fi verificată: " + error.message);
  }
}
function showLogin() {
  const dialog = $("login-dialog");
  document.body.classList.add("locked");
  dialog.oncancel = (event) => event.preventDefault();
  if (!dialog.open) dialog.showModal();
  $("login-form").onsubmit = async (event) => {
    event.preventDefault();
    const b = event.currentTarget.querySelector("button");
    b.disabled = true;
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: $("login-password").value }),
      });
      const result = await response.json();
      if (!response.ok)
        throw new Error(result.detail || "Autentificare eșuată.");
      state.csrf = result.csrf;
      state.authRequired = result.required;
      $("login-password").value = "";
      $("login-error").textContent = "";
      dialog.close();
      document.body.classList.remove("locked");
      await load();
      if (state.page === "advanced") await renderAdvanced();
    } catch (error) {
      $("login-error").textContent = error.message;
    } finally {
      b.disabled = false;
    }
  };
}
function advancedSection(parent, title, note) {
  const panel = node("section", undefined, "panel padded");
  panel.append(node("h2", title), node("p", note, "footnote"));
  parent.append(panel);
  return panel;
}
function jsonDetails(parent, label, value) {
  const details = node("details");
  details.append(
    node("summary", label),
    node("pre", JSON.stringify(value, null, 2), "research-json"),
  );
  parent.append(details);
}
async function renderAdvanced() {
  const root = $("advanced-content");
  root.replaceChildren();
  const endpoints = [
    "/api/discovery",
    "/api/wallets",
    "/api/alerts",
    "/api/evaluation/forward",
  ];
  const results = await Promise.allSettled(endpoints.map((path) => api(path)));
  for (let i = 0; i < results.length; i++) {
    const result = results[i];
    if (result.status !== "fulfilled") {
      advancedSection(root, "Componentă indisponibilă", result.reason.message);
      continue;
    }
    const data = result.value;
    if (i === 0) {
      const panel = advancedSection(
        root,
        "Pool-uri și tokenuri observate",
        "Solana și Base. Data primei observări și data pool-ului nu confirmă lansarea tokenului. Acoperirea furnizorilor este parțială.",
      );
      const chain = node("select");
      chain.setAttribute("aria-label", "Chain discovery");
      for (const value of ["all", "solana", "base"]) {
        const o = node("option", value);
        o.value = value;
        chain.append(o);
      }
      const page = inputField(panel, "Pagina new pools", "number");
      page.min = "1";
      page.max = "10";
      page.value = "1";
      const refresh = button("Caută pool-uri și profiluri", "secondary", () =>
        action(refresh, async () => {
          await api(
            `/api/discovery/refresh?chain=${chain.value}&page=${page.value}`,
            {},
          );
          await renderAdvanced();
        }),
      );
      panel.append(chain, refresh);
      jsonDetails(panel, "Starea surselor și acoperirea", {
        sources: data.sources,
        coverage: data.coverage,
      });
      const list = node("div");
      panel.append(list);
      const drawPools = (items) => {
        for (const item of items) {
          const p = item.payload,
            row = node("article", undefined, "evidence-item");
          row.append(
            node("strong", `${p.name} · ${p.chain}`),
            node("p", p.contract, "contract-text"),
            node(
              "p",
              `Pool raportat: ${date(p.pool_created_at_reported)} · observat prima dată ${date(item.first_seen_at)}. ${p.source} · ${p.discovery_basis}`,
              "footnote",
            ),
          );
          if (p.chain === "solana") {
            const open = button("Deschide dosarul Solana", "secondary", () =>
              action(open, () => openToken(p.contract, null, true)),
            );
            row.append(open);
          }
          if (p.chain === "base") {
            const verify = button(
              "Citește contractul pe Base",
              "secondary",
              () =>
                action(verify, async () => {
                  jsonDetails(
                    row,
                    "Observație Base RPC",
                    await api(`/api/onchain/base/${p.contract}`),
                  );
                }),
            );
            row.append(verify);
          }
          jsonDetails(row, "Datele pool-ului", p);
          list.append(row);
        }
      };
      drawPools(data.items);
      if (!data.items.length)
        empty(
          list,
          "Niciun pool colectat încă; verifică sursele sau pornește colectarea.",
        );
      let cursor = data.next_cursor;
      const more = button("Încarcă observații mai vechi", "secondary", () =>
        action(more, async () => {
          const next = await api(
            "/api/discovery?cursor=" + encodeURIComponent(cursor),
          );
          drawPools(next.items);
          cursor = next.next_cursor;
          more.hidden = !cursor;
        }),
      );
      more.hidden = !cursor;
      panel.append(more);
    }
    if (i === 1) {
      const panel = advancedSection(
        root,
        "Walleturi urmărite",
        "Doar adrese publice. Schimbările de sold și transferurile sunt separate de candidații de swap. Istoricul este paginat; PnL și copyability rămân necunoscute fără istoric și prețuri complete.",
      );
      const form = node("form", undefined, "evidence-form"),
        chain = node("select");
      chain.setAttribute("aria-label", "Chain wallet");
      for (const v of ["solana", "base"]) {
        const o = node("option", v);
        o.value = v;
        chain.append(o);
      }
      form.append(chain);
      const address = inputField(form, "Adresa publică a walletului");
      address.required = true;
      const label = inputField(form, "Etichetă wallet");
      label.maxLength = 80;
      const add = button("Urmărește wallet", "secondary", () => {});
      add.type = "submit";
      form.append(add);
      form.onsubmit = (event) => {
        event.preventDefault();
        action(add, async () => {
          await api("/api/wallets", {
            chain: chain.value,
            address: address.value.trim(),
            label: label.value.trim(),
          });
          await renderAdvanced();
        });
      };
      panel.append(form);
      for (const w of data) {
        const row = node("article", undefined, "evidence-item");
        row.append(
          node("strong", `${w.label || "Wallet"} · ${w.chain}`),
          node("p", w.address, "contract-text"),
          node(
            "p",
            `${w.status.state || "unverified"} · ${w.events_total} evenimente colectate. PnL: necunoscut.`,
            "footnote",
          ),
        );
        const refresh = button("Citește activitatea recentă", "secondary", () =>
          action(refresh, async () => {
            await api(`/api/wallets/${w.id}/refresh`, {});
            await renderAdvanced();
          }),
        );
        row.append(refresh);
        if (w.status.next_cursor || w.status.next_block) {
          const query = w.status.next_cursor
            ? "before=" + encodeURIComponent(w.status.next_cursor)
            : "from_block=" + w.status.next_block;
          const next = button("Citește pagina următoare", "secondary", () =>
            action(next, async () => {
              await api(`/api/wallets/${w.id}/refresh?${query}`, {});
              await renderAdvanced();
            }),
          );
          row.append(next);
        }
        jsonDetails(row, "Activitate și limite de acoperire", w);
        panel.append(row);
      }
    }
    if (i === 2) {
      const panel = advancedSection(
        root,
        "Alerte în aplicație și Telegram",
        "Informații pentru cercetare, fără ordine automate. Trimiterea în Telegram cere bot și destinatar configurate în mediul serverului și apăsarea explicită a butonului de trimitere.",
      );
      const collect = button("Colectează alerte din știri", "secondary", () =>
        action(collect, async () => {
          await api("/api/alerts/collect", {});
          await renderAdvanced();
        }),
      );
      const check = button("Verifică botul Telegram", "secondary", () =>
        action(check, async () => {
          await api("/api/integrations/telegram/check", {});
          message("Bot verificat. Nu s-a trimis niciun mesaj.", true);
        }),
      );
      panel.append(collect, check);
      jsonDetails(panel, "Configurarea integrării", data.configuration);
      for (const alert of data.items.slice(0, 20)) {
        const row = node("article", undefined, "evidence-item");
        row.append(
          link(alert.payload.title, alert.payload.url, "story-title"),
          node(
            "p",
            `${alert.payload.publisher} · ${date(alert.at)} · ${alert.seen_at ? "citit" : "necitit"} · Telegram: ${alert.delivery_state}`,
            "footnote",
          ),
        );
        const seen = button("Marchează citită", "text-button", () =>
          action(seen, async () => {
            await api(`/api/alerts/${alert.id}/seen`, {});
            await renderAdvanced();
          }),
        );
        row.append(seen);
        if (
          alert.delivery_state === "pending" &&
          data.configuration.telegram_bot_configured &&
          data.configuration.telegram_destination_configured
        ) {
          const send = button(
            "Trimite această alertă în Telegram",
            "secondary",
            () =>
              action(send, async () => {
                await api(
                  `/api/alerts/${alert.id}/telegram?confirm_send=true`,
                  {},
                );
                await renderAdvanced();
              }),
          );
          row.append(send);
        }
        panel.append(row);
      }
    }
    if (i === 3) {
      const panel = advancedSection(
        root,
        "Evaluare forward",
        "Folosește numai observații colectate după semnal, cu reguli de cost păstrate la acel moment. Lipsurile rămân în raport. Eșantioanele independente nu reprezintă equity al unei strategii și nu dovedesc profitabilitate.",
      );
      const form = node("form", undefined, "evidence-form"),
        split = inputField(
          form,
          "Separare dezvoltare/test (ora PC-ului)",
          "datetime-local",
        );
      const horizon = node("select");
      horizon.setAttribute("aria-label", "Orizont evaluare");
      for (const [v, label] of [
        [300, "5 minute"],
        [3600, "1 oră"],
        [86400, "1 zi"],
        [604800, "7 zile"],
      ]) {
        const o = node("option", label);
        o.value = v;
        horizon.append(o);
      }
      horizon.value = "3600";
      form.append(horizon);
      const report = node("div");
      jsonDetails(report, "Cohorte, eșantion și date lipsă", data);
      const run = button("Calculează raportul forward", "secondary", () => {});
      run.type = "submit";
      form.append(run);
      form.onsubmit = (event) => {
        event.preventDefault();
        action(run, async () => {
          const path =
            `/api/evaluation/forward?account=${state.account}&horizon_seconds=${horizon.value}` +
            (split.value
              ? "&split_at=" +
                encodeURIComponent(new Date(split.value).toISOString())
              : "");
          const next = await api(path);
          report.replaceChildren();
          jsonDetails(report, "Raport forward", next);
        });
      };
      panel.append(form, report);
    }
  }
  if (state.authRequired) {
    const logout = button("Închide sesiunea", "secondary", () =>
      action(logout, async () => {
        await api("/api/auth/logout", {});
        location.reload();
      }),
    );
    root.append(logout);
  }
}
async function renderFundamentals(parent, address) {
  const panel = advancedSection(
    parent,
    "Fundamente și observații verificabile",
    "Datele RPC, metadata furnizorului, evaluările manuale și interpretările AI sunt păstrate separat. Un contract existent sau lichiditatea raportată nu confirmă un proiect solid.",
  );
  panel.classList.add("fundamentals-panel");
  const details = node("div");
  panel.append(details);
  const draw = (report) => {
    details.replaceChildren();
    for (const c of report.categories)
      details.append(node("p", `${c.key}: ${c.review_state}`, "footnote"));
    jsonDetails(details, "Observații, surse și informații încă lipsă", report);
  };
  const refresh = button("Colectează datele fundamentale", "secondary", () =>
    action(refresh, async () => {
      draw(
        await api(
          `/api/research/${encodeURIComponent(address)}/fundamentals/refresh`,
          {},
        ),
      );
    }),
  );
  panel.append(refresh);
  try {
    draw(
      await api(`/api/research/${encodeURIComponent(address)}/fundamentals`),
    );
  } catch (error) {
    details.append(node("p", error.message, "warn"));
  }
  const listingBox = node("details");
  listingBox.append(
    node("summary", "Program de listare raportat de sursa originală"),
  );
  const form = node("form", undefined, "evidence-form"),
    url = inputField(form, "URL-ul sursei pentru listare", "url"),
    venue = inputField(form, "Piața anunțată"),
    quote = inputField(form, "Citatul exact despre listare", "textarea"),
    contract = inputField(form, "Contractul din anunțul de listare"),
    chain = node("select");
  chain.setAttribute("aria-label", "Chain listare");
  for (const v of [
    "solana",
    "ethereum",
    "base",
    "polygon",
    "bsc",
    "arbitrum",
    "avalanche",
  ]) {
    const o = node("option", v);
    o.value = v;
    chain.append(o);
  }
  form.append(chain);
  if (!address.startsWith("asset:")) {
    contract.value = address;
    contract.readOnly = true;
    chain.value = "solana";
  }
  const when = inputField(
      form,
      "Începere raportată (ora PC-ului; verifică fusul sursei)",
      "datetime-local",
    ),
    reviewed = inputField(
      form,
      "Am verificat manual citatul, data și fusul orar",
      "checkbox",
    );
  const save = button("Salvează programul raportat", "secondary", () => {});
  save.type = "submit";
  form.append(save);
  const schedules = node("div");
  const loadSchedules = async () => {
    schedules.replaceChildren();
    jsonDetails(
      schedules,
      "Proveniență și starea actuală a programelor",
      await api(`/api/research/${encodeURIComponent(address)}/listings`),
    );
  };
  form.onsubmit = (event) => {
    event.preventDefault();
    action(save, async () => {
      await api(`/api/research/${encodeURIComponent(address)}/listings`, {
        source_url: url.value.trim(),
        venue: venue.value.trim(),
        excerpt: quote.value.trim(),
        contract: contract.value.trim(),
        chain: chain.value,
        starts_at: when.value ? new Date(when.value).toISOString() : null,
        reviewed: reviewed.checked,
      });
      await loadSchedules();
    });
  };
  listingBox.append(
    node(
      "p",
      "Programul rămâne neconfirmat fără o sursă evaluată pentru relația de listare și contractul exact. Nu stabilește acces anticipat la cumpărare.",
      "footnote",
    ),
    form,
    schedules,
  );
  panel.append(listingBox);
  try {
    await loadSchedules();
  } catch (error) {
    schedules.append(node("p", error.message, "warn"));
  }
}
