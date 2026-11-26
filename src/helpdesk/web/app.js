// Helpdesk Agent demo page. Vanilla JS, no build step, no network beyond this server.
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const els = {
    messages: $("#messages"), form: $("#composer"), msg: $("#msg"), send: $("#send"), status: $("#status"),
    trace: $("#trace"), tickets: $("#tickets"), actions: $("#actions"), model: $("#model-name"), gh: $("#gh-link"),
  };
  const chips = Array.from(document.querySelectorAll(".chip"));
  const switches = Array.from(document.querySelectorAll("#switches input[data-service]"));
  let running = false;
  const flow = window.HelpdeskFlow || null;   // the "Live flow" diagram (flow.js); the page works without it

  // ---------------------------------------------------------------- tabs: Live flow | Steps
  const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
  function selectTab(tab, focus) {
    tabs.forEach((t) => {
      const on = t === tab;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
    });
    $("#flow-ctrls").hidden = tab.id !== "tab-flow";
    if (focus) tab.focus();
    if (tab.id === "tab-flow" && flow) flow.redraw();
  }
  tabs.forEach((t, i) => {
    t.addEventListener("click", () => selectTab(t));
    t.addEventListener("keydown", (e) => {
      const k = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
      if (k) { e.preventDefault(); selectTab(tabs[(i + k + tabs.length) % tabs.length], true); }
    });
  });
  if (flow) {
    flow.init({
      root: $("#flow-card"), stage: $("#flow-stage"), caption: $("#flow-caption"), log: $("#flow-log"),
      dock: $("#flow-dock"), dockSources: [$("#composer"), $("#status")],
      replay: $("#flow-replay"), speeds: Array.from(document.querySelectorAll("[data-speed]")), full: $("#flow-full"),
    });
  }

  // ---------------------------------------------------------------- session id (one per browser)
  function newId() {
    const bytes = new Uint8Array(16);
    (window.crypto || {}).getRandomValues ? crypto.getRandomValues(bytes) : bytes.forEach((_, i) => (bytes[i] = Math.random() * 256));
    return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  }
  let session = null;
  try { session = localStorage.getItem("helpdesk-demo-session"); } catch (e) { /* private mode */ }
  if (!session || !/^[A-Za-z0-9_-]{8,64}$/.test(session)) {
    session = newId();
    try { localStorage.setItem("helpdesk-demo-session", session); } catch (e) { /* keep it in memory */ }
  }
  const headers = (extra) => Object.assign({ "X-Demo-Session": session }, extra || {});

  // ---------------------------------------------------------------- helpers
  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") n.className = v; else if (k === "text") n.textContent = v; else n.setAttribute(k, v);
    }
    for (const k of kids) if (k !== null && k !== undefined) n.append(k);
    return n;
  }
  const ms = (x) => (x >= 1000 ? (x / 1000).toFixed(1) + " s" : Math.round(x) + " ms");
  function compactArgs(args) {
    if (!args || typeof args !== "object") return "";
    return Object.entries(args).map(([k, v]) => {
      let s = typeof v === "string" ? JSON.stringify(v.length > 60 ? v.slice(0, 57) + "…" : v) : JSON.stringify(v);
      return k + "=" + s;
    }).join("  ");
  }
  function setStatus(text, isError) {
    els.status.textContent = text || "";
    els.status.classList.toggle("error", !!isError);
  }
  function setRunning(on) {
    running = on;
    els.send.disabled = on;
    els.msg.disabled = on;
    chips.forEach((c) => (c.disabled = on));
    els.send.textContent = on ? "Working…" : "Send";
  }
  function scrollChat() { els.messages.scrollTop = els.messages.scrollHeight; }

  // ---------------------------------------------------------------- meta
  const gh = document.body.dataset.github;
  if (gh) els.gh.href = gh;
  fetch("v1/meta").then((r) => r.json()).then((m) => {
    els.model.textContent = m.model || "not configured";
    if (flow) flow.setMeta(m);
    const known = new Set(m.services || []);
    if (!m.demo) switches.forEach((s) => { s.disabled = true; s.closest(".switch").title = "Only in demo mode"; });
    switches.forEach((s) => { if (!known.has(s.dataset.service)) s.closest(".switch").hidden = true; });
  }).catch(() => { els.model.textContent = "unavailable"; });

  // ---------------------------------------------------------------- outage switches
  switches.forEach((s) => s.addEventListener("change", () => {
    const sw = s.closest(".switch");
    sw.classList.toggle("down", !s.checked);
    sw.querySelector(".sw-state").textContent = s.checked ? "up" : "down";
    if (flow) flow.setServices({ [s.dataset.service]: s.checked ? "up" : "down" });
  }));
  const downList = () => switches.filter((s) => !s.checked && !s.disabled).map((s) => s.dataset.service);

  // ---------------------------------------------------------------- chat messages
  function addUser(text) {
    els.messages.append(el("li", { class: "msg user", dir: "auto" }, el("div", { class: "bubble", text })));
    scrollChat();
  }
  function addThinking() {
    const li = el("li", { class: "msg agent thinking" }, el("div", { class: "bubble", text: "Working on it…" }));
    els.messages.append(li);
    scrollChat();
    return li;
  }
  function addReply(reply, placeholder) {
    const badges = el("div", { class: "badges" },
      el("span", { class: "badge", text: reply.language === "ar" ? "Arabic" : "English" }),
      reply.needs_human ? el("span", { class: "badge human", text: "needs a person" }) : null,
      reply.ticket_id ? el("span", { class: "badge ticket", text: "ticket #" + reply.ticket_id }) : null);
    const li = el("li", { class: "msg agent", dir: reply.language === "ar" ? "rtl" : "auto", lang: reply.language },
      el("div", { class: "bubble", dir: "auto", text: reply.answer }), badges);
    placeholder ? placeholder.replaceWith(li) : els.messages.append(li);
    scrollChat();
  }
  function addError(text, placeholder) {
    const li = el("li", { class: "msg agent" }, el("div", { class: "bubble", text }),
      el("div", { class: "badges" }, el("span", { class: "badge err", text: "not answered" })));
    placeholder ? placeholder.replaceWith(li) : els.messages.append(li);
    scrollChat();
  }

  // ---------------------------------------------------------------- trace
  function clearTrace() { els.trace.replaceChildren(); }
  function traceTurn(ev) {
    els.trace.append(el("li", { class: "step turn" }, el("span", { class: "n", text: "" }),
      el("span", { class: "tool", text: "model turn " + ev.turn })));
  }
  function traceTool(ev) {
    const risky = ev.tool === "restart_service";
    let note = null;
    if (!ev.ok) {
      let detail = ev.result_preview || "error";
      try {
        const j = JSON.parse(detail);
        if (j.details && Array.isArray(j.details)) detail = j.error + ": " + j.details.map((d) => d.field + " " + d.error).join("; ");
        else if (j.error) detail = j.error;
      } catch (e) { /* validation text, keep as is */ }
      note = el("div", { class: "note bad", text: "Rejected by the code: " + detail });
    } else if (risky) {
      note = el("div", { class: "note", text: "Queued for a human. Nothing was restarted." });
    } else if (ev.tool === "check_service") {
      try {
        const j = JSON.parse(ev.result_preview);
        note = el("div", { class: "note", text: j.service + " is " + j.status + " (" + j.detail + ")" });
      } catch (e) { /* preview cut off */ }
    } else if (ev.tool === "create_ticket") {
      try { note = el("div", { class: "note", text: "Opened ticket #" + JSON.parse(ev.result_preview).ticket_id }); } catch (e) { /* */ }
    }
    const meta = el("span", { class: "meta" },
      el("span", { class: ev.ok ? "ok" : "bad", text: ev.ok ? "ok" : "error" }),
      ev.tool === "final_answer" ? null : document.createTextNode(" · " + ms(ev.latency_ms || 0)),
      risky && ev.ok ? document.createTextNode(" · queued for a human") : null);
    const args = ev.tool === "final_answer" ? null : el("div", { class: "args", dir: "auto", text: compactArgs(ev.args) });
    els.trace.append(el("li", { class: "step" + (risky ? " risk" : "") + (ev.ok ? "" : " error") },
      el("span", { class: "n", text: String(ev.step) }), el("span", { class: "tool", text: ev.tool }), meta, args, note));
  }
  let finalRow = null;
  function traceFinal(ev) {
    const checks = el("ul", { class: "checks" });
    (ev.violations || []).forEach((v) => checks.append(el("li", { class: "viol", text: "caught: " + v })));
    (ev.repairs || []).forEach((v) => checks.append(el("li", { class: "rep", text: "repaired: " + v })));
    if (!checks.children.length) checks.append(el("li", { text: "code checks: no problems found" }));
    finalRow = el("li", { class: "step final" }, el("span", { class: "n", text: "✓" }),
      el("span", { class: "tool", text: "stop: " + ev.stop_reason }), el("span", { class: "meta", text: "" }), checks);
    els.trace.append(finalRow);
  }
  function traceDone(ev) {
    if (!finalRow) return;
    finalRow.querySelector(".meta").textContent =
      ev.input_tokens + " in / " + ev.output_tokens + " out · " + ms(ev.latency_ms);
  }

  // ---------------------------------------------------------------- lists
  async function getJSON(url) {
    const r = await fetch(url, { headers: headers() });
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }
  async function refreshLists() {
    try {
      const [tickets, actions] = await Promise.all([getJSON("v1/tickets"), getJSON("v1/actions?status=all")]);
      els.tickets.replaceChildren(...(tickets.length ? tickets.map((t) => el("li", { class: "row" },
        el("div", { class: "main" }, el("div", { class: "title" }, el("span", { class: "num", text: "#" + t.id }), el("bdi", { dir: "auto", text: t.title })),
          el("div", { class: "sub", text: t.category + " · " + t.status })),
        el("span", { class: "pill " + t.priority, text: t.priority }))) : [el("li", { class: "empty", text: "No tickets yet in this visit." })]));
      if (flow) flow.setCounts({ tickets: tickets.length, last: tickets[0] || null,
        pending: actions.filter((a) => a.status === "pending").length });
      const rows = actions.slice().reverse().map(actionRow);
      els.actions.replaceChildren(...(rows.length ? rows : [el("li", { class: "empty", text: "Nothing waiting." })]));
    } catch (e) { /* lists are a nice-to-have; chat errors are shown elsewhere */ }
  }
  function actionRow(a) {
    const what = a.tool === "restart_service" ? "Restart " + (a.args.name || "?") : a.tool;
    const main = el("div", { class: "main" }, el("div", { class: "title" }, el("span", { class: "num", text: "#" + a.id }), el("span", { text: what })),
      el("div", { class: "sub", dir: "auto", text: a.args.reason || "" }));
    const li = el("li", { class: "row " + a.status }, main);
    if (a.status === "pending") {
      const approve = el("button", { type: "button", class: "btn approve", text: "Approve" });
      const reject = el("button", { type: "button", class: "btn reject", text: "Reject" });
      approve.setAttribute("aria-label", "Approve: " + what);
      reject.setAttribute("aria-label", "Reject: " + what);
      approve.onclick = () => decide(a.id, "approve", li);
      reject.onclick = () => decide(a.id, "reject", li);
      li.append(el("div", { class: "acts" }, approve, reject));
    } else {
      li.append(el("span", { class: "pill " + a.status, text: a.status }));
    }
    return li;
  }
  async function decide(id, decision, li) {
    li.querySelectorAll("button").forEach((b) => (b.disabled = true));
    try {
      const r = await fetch("v1/actions/" + id + "/" + decision, { method: "POST", headers: headers() });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
      const a = await r.json();
      li.replaceWith(actionRow(a));
      refreshLists();
      setStatus(decision === "approve" ? "Approved. In a real company the on-call person now does the restart." : "Rejected.");
    } catch (e) {
      li.querySelectorAll("button").forEach((b) => (b.disabled = false));
      setStatus("Could not record that: " + e.message, true);
    }
  }

  // ---------------------------------------------------------------- send
  function friendly(status, detail) {
    if (status === 429) return detail || "Too many messages. Please wait a little.";
    if (status === 503) return "The model is not configured on this server yet, so the agent cannot answer.";
    if (status === 422) return typeof detail === "string" ? detail : "That message was not accepted (too long or empty).";
    return detail ? String(detail) : "Something went wrong (" + status + ").";
  }

  async function send(text) {
    text = (text || "").trim();
    if (!text || running) return;
    setRunning(true);
    setStatus("");
    addUser(text);
    els.msg.value = "";
    const placeholder = addThinking();
    clearTrace();
    finalRow = null;
    if (flow) flow.begin(text);
    let reply = null, failed = false;
    try {
      const r = await fetch("v1/chat/stream", {
        method: "POST", headers: headers({ "Content-Type": "application/json", Accept: "text/event-stream" }),
        body: JSON.stringify({ message: text, down: downList() }),
      });
      if (!r.ok || !r.body) {
        const j = await r.json().catch(() => ({}));
        const err = Object.assign(new Error(friendly(r.status, j.detail)), { shown: true });
        if (flow) flow.fail(err.message);
        throw err;
      }
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let cut;
        while ((cut = buf.indexOf("\n\n")) >= 0) {
          const chunk = buf.slice(0, cut);
          buf = buf.slice(cut + 2);
          const data = chunk.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trim()).join("\n");
          if (!data) continue;
          const ev = JSON.parse(data);
          if (flow) flow.push(ev);
          if (ev.type === "model_turn") traceTurn(ev);
          else if (ev.type === "tool") traceTool(ev);
          else if (ev.type === "final") { reply = ev.reply; traceFinal(ev); addReply(ev.reply, placeholder); }
          else if (ev.type === "done") traceDone(ev);
          else if (ev.type === "error") { failed = true; addError(ev.detail, placeholder); setStatus(ev.detail, true); }
        }
      }
      if (!reply && !failed) {
        addError("The answer stopped part way. Please try again.", placeholder);
        if (flow) flow.fail("The answer stopped part way.");
      }
    } catch (e) {
      const msg = e.shown ? e.message : "Could not reach the server. Check your connection and try again.";
      if (flow && !e.shown) flow.fail(msg);
      addError(msg, placeholder);
      setStatus(msg, true);
      if (!els.trace.children.length) els.trace.append(el("li", { class: "trace-empty", text: "No steps: the request was not run." }));
    } finally {
      setRunning(false);
      els.msg.focus();
      refreshLists();
    }
  }

  els.form.addEventListener("submit", (e) => { e.preventDefault(); send(els.msg.value); });
  els.msg.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(els.msg.value); }
  });
  chips.forEach((c) => c.addEventListener("click", () => { els.msg.value = c.textContent.trim(); send(c.textContent); }));
  refreshLists();
})();
