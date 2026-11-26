// Live flow: an animated diagram of one agent run, driven by the SSE events of POST /v1/chat/stream.
// Vanilla JS + inline SVG, no build step. Events are queued and played one "hop" at a time (a glowing
// particle travelling along an edge, carrying a label), so a burst of events stays easy to follow.
// Nothing is dropped: when the player falls far behind it plays faster.
(function () {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const HOP_MIN = 550, HOP_MAX = 760;   // ms per hop at 1x, scaled by edge length
  const BEAT = 340;                     // ms for a state change without a particle
  const THINK_MIN = 460;                // ms the "thinking" state shows even when the model was instant
  const CATCHUP_LAG = 15000;            // ms behind the real events before playback speeds up
  const REPLAY_GAP_MAX = 2000;          // long waits are compressed to this in a replay
  const TONES = { sky: "#8fd3ff", risk: "#ff5c8a", ok: "#3fb950", err: "#ff7b72" };
  const reducedMQ = window.matchMedia("(prefers-reduced-motion: reduce)");
  const reduced = () => reducedMQ.matches;

  // ---------------------------------------------------------------- what each tool touches
  const TOOL_NODE = { search_runbooks: "t_search", check_service: "t_check", create_ticket: "t_ticket",
    get_ticket: "t_ticket", restart_service: "t_restart", final_answer: "t_final" };
  const RESOURCE = { t_search: "knowledge", t_check: "services", t_ticket: "tickets", t_restart: "approval" };
  const SERVICES = [["mail", "mail"], ["pbx", "phones"], ["intranet", "intranet"]];

  // ---------------------------------------------------------------- icons (24x24 stroke paths)
  const ICONS = {
    chat: "M4 5h16a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H10l-4.5 4v-4H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM7.5 9.5h9M7.5 12.5h6",
    bolt: "M13.5 2.5 5 13.5h6.5l-1 8 8.5-11h-6.5z",
    chip: "M7 7h10v10H7zM10 10h4v4h-4zM9.5 3v4M14.5 3v4M9.5 17v4M14.5 17v4M3 9.5h4M3 14.5h4M17 9.5h4M17 14.5h4",
    search: "M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zM20 20l-4.8-4.8",
    pulse: "M3 12h4l2.5-6 5 12 2.5-6H21",
    ticket: "M4 7h16v3a2 2 0 0 0 0 4v3H4v-3a2 2 0 0 0 0-4zM14.5 7.5v1.5M14.5 11.25v1.5M14.5 15v1.5",
    restart: "M19.5 12a7.5 7.5 0 1 1-2.6-5.7M19.5 4v4.5H15",
    send: "M3.5 11.5 20.5 4l-6.5 16.5-2.5-6.5z M11.5 14 20.5 4",
    book: "M5 4.5A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5zM5 19.5A1.5 1.5 0 0 0 6.5 21H19v-3M9 7h6",
    server: "M4 4h16v6H4zM4 14h16v6H4zM7.5 7h.5M7.5 17h.5M11 7h5M11 17h5",
    db: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
    clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7.5V12l3 2",
    person: "M12 4a3.75 3.75 0 1 0 0 7.5A3.75 3.75 0 0 0 12 4zM4.5 20.5c0-3.9 3.4-6.5 7.5-6.5s7.5 2.6 7.5 6.5",
    play: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM10 8.5v7l5.5-3.5z",
    shield: "M12 3 4.5 6v5.5c0 4.6 3.2 8 7.5 9.5 4.3-1.5 7.5-4.9 7.5-9.5V6zM8.75 12l2.25 2.25 4.25-4.5",
  };

  // ---------------------------------------------------------------- layouts
  // Each node is a card {x, y, w, h}; the loop is a ring {cx, cy, r}. Edges are SVG paths built from anchors.
  const C = (n) => ({ x: n.x + n.w / 2, y: n.y + n.h / 2 });
  const top = (n, dx = 0) => ({ x: n.x + n.w / 2 + dx, y: n.y });
  const bottom = (n, dx = 0) => ({ x: n.x + n.w / 2 + dx, y: n.y + n.h });
  const left = (n, dy = 0) => ({ x: n.x, y: n.y + n.h / 2 + dy });
  const right = (n, dy = 0) => ({ x: n.x + n.w, y: n.y + n.h / 2 + dy });
  const ring = (l, deg) => ({ x: l.cx + l.r * Math.sin(deg * Math.PI / 180), y: l.cy - l.r * Math.cos(deg * Math.PI / 180) });
  const f = (v) => Math.round(v * 10) / 10;
  // a smooth curve whose ends leave/arrive along the given axes ("v" vertical, "h" horizontal)
  function curve(p, q, a = "v", b = a, k = 0.5) {
    const dx = q.x - p.x, dy = q.y - p.y;
    const c1 = a === "v" ? { x: p.x, y: p.y + dy * k } : { x: p.x + dx * k, y: p.y };
    const c2 = b === "v" ? { x: q.x, y: q.y - dy * k } : { x: q.x - dx * k, y: q.y };
    return `M${f(p.x)},${f(p.y)} C${f(c1.x)},${f(c1.y)} ${f(c2.x)},${f(c2.y)} ${f(q.x)},${f(q.y)}`;
  }

  function wideLayout() {
    const n = {
      run: { x: 14, y: 14, w: 200, h: 98 },
      model: { x: 455, y: 14, w: 250, h: 98 },
      human: { x: 840, y: 14, w: 146, h: 98 },
      employee: { x: 14, y: 176, w: 190, h: 152 },
      api: { x: 242, y: 206, w: 142, h: 92 },
      approval: { x: 840, y: 206, w: 146, h: 92 },
      guards: { x: 14, y: 404, w: 150, h: 92 },
      t_final: { x: 204, y: 404, w: 146, h: 92 },
      t_search: { x: 363, y: 404, w: 146, h: 92 },
      t_check: { x: 522, y: 404, w: 146, h: 92 },
      t_ticket: { x: 681, y: 404, w: 146, h: 92 },
      t_restart: { x: 840, y: 404, w: 146, h: 92 },
      knowledge: { x: 330, y: 548, w: 178, h: 80 },
      services: { x: 522, y: 548, w: 178, h: 80 },
      tickets: { x: 713, y: 548, w: 146, h: 80 },
    };
    const loop = { cx: 580, cy: 252, r: 62, status: { x: 664, y: 232, anchor: "start" } };
    const toolEdge = (id, dx = 0) => {
      const t = top(n[id], dx);
      const deg = 180 - Math.max(-62, Math.min(62, (t.x - loop.cx) / 4.2));
      const s = ring(loop, deg);
      return curve(s, t, "v", "v", 0.55);
    };
    const e = {
      "employee>api": curve(right(n.employee, -24), left(n.api, -24 + 22), "h"),
      "api>loop": curve(right(n.api), ring(loop, 270), "h"),
      "loop>model": curve(ring(loop, -16), bottom(n.model, -18), "v"),
      "model>loop": curve(bottom(n.model, 18), ring(loop, 16), "v"),
      "loop>t_final": toolEdge("t_final"), "loop>t_search": toolEdge("t_search"),
      "loop>t_check": toolEdge("t_check"), "loop>t_ticket": toolEdge("t_ticket"),
      "loop>t_restart": toolEdge("t_restart", -30),
      "t_search>knowledge": curve(bottom(n.t_search), top(n.knowledge)),
      "t_check>services": curve(bottom(n.t_check), top(n.services)),
      "t_ticket>tickets": curve(bottom(n.t_ticket), top(n.tickets)),
      "t_restart>approval": curve(top(n.t_restart, 34), bottom(n.approval, 34)),
      "approval>human": curve(top(n.approval), bottom(n.human)),
      "t_final>guards": curve(left(n.t_final), right(n.guards), "h"),
      "guards>employee": curve(top(n.guards), bottom(n.employee, -13)),
    };
    return { name: "wide", vb: [1000, 640], nodes: n, loop, edges: e, legend: { x: 14, y: 566 } };
  }

  function tallLayout() {
    const L = 12, LW = 166, R = 206, RW = 162;
    const n = {
      employee: { x: L, y: 12, w: LW, h: 128 },
      guards: { x: R, y: 12, w: RW, h: 92 },
      api: { x: L, y: 178, w: LW, h: 84 },
      t_final: { x: R, y: 146, w: RW, h: 88 },
      model: { x: R, y: 296, w: RW, h: 100 },
      t_search: { x: L + 16, y: 486, w: LW - 16, h: 84 },
      t_check: { x: L + 16, y: 588, w: LW - 16, h: 84 },
      t_ticket: { x: L + 16, y: 690, w: LW - 16, h: 84 },
      t_restart: { x: L + 16, y: 792, w: LW - 16, h: 84 },
      knowledge: { x: R, y: 486, w: RW, h: 84 },
      services: { x: R, y: 588, w: RW, h: 84 },
      tickets: { x: R, y: 690, w: RW, h: 84 },
      approval: { x: R, y: 792, w: RW, h: 84 },
      human: { x: R, y: 894, w: RW, h: 84 },
    };
    const loop = { cx: 95, cy: 352, r: 54, status: { x: 95, y: 432, anchor: "middle" } };
    const trunk = (id) => {   // tools hang off one bus line on the left margin
      const t = left(n[id]);
      const s = ring(loop, 214);
      return `M${f(s.x)},${f(s.y)} C${f(s.x - 22)},${f(s.y + 30)} 8,${f(s.y + 40)} 8,${f(s.y + 80)} ` +
        `L8,${f(t.y - 16)} Q8,${f(t.y)} ${f(t.x)},${f(t.y)}`;
    };
    const e = {
      "employee>api": curve(bottom(n.employee), top(n.api)),
      "api>loop": curve(bottom(n.api), ring(loop, 0)),
      "loop>model": curve(ring(loop, 76), left(n.model, -14), "h"),
      "model>loop": curve(left(n.model, 14), ring(loop, 104), "h"),
      "loop>t_final": curve(ring(loop, 40), bottom(n.t_final), "h", "v"),
      "loop>t_search": trunk("t_search"), "loop>t_check": trunk("t_check"),
      "loop>t_ticket": trunk("t_ticket"), "loop>t_restart": trunk("t_restart"),
      "t_search>knowledge": curve(right(n.t_search), left(n.knowledge), "h"),
      "t_check>services": curve(right(n.t_check), left(n.services), "h"),
      "t_ticket>tickets": curve(right(n.t_ticket), left(n.tickets), "h"),
      "t_restart>approval": curve(right(n.t_restart), left(n.approval), "h"),
      "approval>human": curve(bottom(n.approval), top(n.human)),
      "t_final>guards": curve(top(n.t_final), bottom(n.guards)),
      "guards>employee": curve(left(n.guards, -10), right(n.employee, -40), "h"),
    };
    return { name: "tall", vb: [380, 990], nodes: n, loop, edges: e, legend: null };
  }

  // ---------------------------------------------------------------- node content (title, icon, idle lines)
  const SPEC = {
    employee: { title: "Employee", icon: "chat", lines: 3 },
    api: { title: "API", tag: "FastAPI", icon: "bolt" },
    model: { title: "Model", icon: "chip" },
    t_search: { title: "search_runbooks", icon: "search", tool: true },
    t_check: { title: "check_service", icon: "pulse", tool: true },
    t_ticket: { title: "create_ticket", icon: "ticket", tool: true },
    t_restart: { title: "restart_service", icon: "restart", tool: true, risk: true },
    t_final: { title: "final_answer", icon: "send", tool: true },
    run: { title: "Run", icon: "play", lines: 3 },
    knowledge: { title: "Knowledge", icon: "book" },
    services: { title: "Services", icon: "server", lights: true },
    tickets: { title: "Tickets", icon: "db" },
    approval: { title: "Approvals", icon: "clock", risk: true, badge: true },
    human: { title: "Human", icon: "person", risk: true },
    guards: { title: "Guards", icon: "shield" },
  };
  function idleLines(meta) {
    return {
      employee: { l1: "waiting for a message", l2: "", l3: "" },
      api: { l1: "/v1/chat/stream", l1c: "sky", l2: "ready" },
      model: { l1: meta.model || "…", l2: "idle", l3: "" },
      t_search: { l1: "IT guides by meaning", l2: "" },
      t_check: { l1: "real network check", l2: "" },
      t_ticket: { l1: "open or read a ticket", l2: "" },
      t_restart: { l1: "only queues a request", l2: "" },
      t_final: { l1: "structured reply", l2: "" },
      knowledge: { l1: "pgvector · " + (meta.guides || 9) + " guides", l2: "" },
      run: { l1: "idle", l2: "", l3: "" },
      guards: { l1: "checks every reply", l2: "ticket ids · claims" },
    };
  }

  // ---------------------------------------------------------------- small DOM helpers
  function s(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs || {}) if (attrs[k] !== undefined && attrs[k] !== null) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  const isArabic = (t) => /[؀-ۿ]/.test(t || "");
  // put `text` in an SVG <text>, cut with "…" so it fits `maxW` user units
  function fitText(el, text, maxW) {
    text = String(text == null ? "" : text).replace(/\s+/g, " ").trim();
    el.textContent = text;
    let w = 0;
    try { w = el.getComputedTextLength(); } catch (e) { /* not rendered */ }
    if (!w) {   // hidden: estimate from the font size
      const fs = parseFloat(el.getAttribute("font-size")) || 12;
      const max = Math.floor(maxW / (fs * 0.6));
      if (text.length > max) el.textContent = text.slice(0, Math.max(1, max - 1)) + "…";
      return;
    }
    if (w <= maxW) return;
    let lo = 0, hi = text.length;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      el.textContent = text.slice(0, mid).trimEnd() + "…";
      if (el.getComputedTextLength() <= maxW) lo = mid; else hi = mid - 1;
    }
    el.textContent = text.slice(0, lo).trimEnd() + "…";
  }
  // split text into up to `n` lines of about `chars` characters (word wrap)
  function wrap(text, chars, n) {
    const words = String(text || "").replace(/\s+/g, " ").trim().split(" ");
    const out = [];
    let line = "";
    for (const w of words) {
      if ((line + " " + w).trim().length > chars && line) { out.push(line); line = w; } else line = (line + " " + w).trim();
      if (out.length === n) break;
    }
    if (out.length < n && line) out.push(line);
    if (out.length === n && words.join(" ").length > out.join(" ").length) out[n - 1] += " …";
    return out;
  }
  const easeOut = (t) => 1 - Math.pow(1 - t, 3);                 // fast out, gentle land
  const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
  const travel = (t) => easeOut(0.14 * t + 0.86 * easeInOut(t));  // leaves briskly, lands softly
  const ms = (x) => (x >= 1000 ? (x / 1000).toFixed(1) + " s" : Math.round(x) + " ms");
  const num = (x) => Number(x || 0).toLocaleString("en-US");
  function argsText(args, max = 40) {
    if (!args || typeof args !== "object") return "";
    return Object.entries(args).map(([k, v]) => {
      let t = typeof v === "string" ? v : JSON.stringify(v);
      if (t.length > max) t = t.slice(0, max - 1) + "…";
      return k + "=" + t;
    }).join(" ");
  }
  function parse(json) { try { return JSON.parse(json); } catch (e) { return null; } }

  // ================================================================ the Flow object
  const F = {
    root: null, stage: null, svg: null, layout: null, el: {}, memo: {}, meta: { tools: 6, max_steps: 6 },
    services: { mail: "up", pbx: "up", intranet: "up" }, counts: { tickets: 0, last: null, pending: 0 },
    shown: { tickets: 0, last: null, pending: 0 },
    pending: [], steps: [], cur: null, run: null, speed: 1, raf: 0,
    ringAngle: 0, ringFrom: 0, ringTo: 0, ringT0: 0, last: null, rec: null, replayTimers: [],
  };

  // ---------------------------------------------------------------- build the SVG for a layout
  function build() {
    const L = F.layout;
    F.stage.replaceChildren();
    const svg = s("svg", { viewBox: `0 0 ${L.vb[0]} ${L.vb[1]}`, class: "flow-svg flow-" + L.name, role: "img",
      "aria-label": "Live flow of the agent", preserveAspectRatio: "xMidYMid meet" });
    F.svg = svg;
    F.stage.appendChild(svg);   // in the page first, so text can be measured while it is built
    F.el = { nodes: {}, edges: {} };
    const defs = s("defs", {}, svg);
    const glow = s("filter", { id: "fl-glow", x: "-50%", y: "-50%", width: "200%", height: "200%" }, defs);
    s("feGaussianBlur", { stdDeviation: "3.2", result: "b" }, glow);
    const m = s("feMerge", {}, glow);
    s("feMergeNode", { in: "b" }, m);
    s("feMergeNode", { in: "SourceGraphic" }, m);
    const bg = s("pattern", { id: "fl-dots", width: "20", height: "20", patternUnits: "userSpaceOnUse" }, defs);
    s("circle", { cx: "1", cy: "1", r: "1", fill: "#2a4a6b", opacity: "0.45" }, bg);
    s("rect", { x: 0, y: 0, width: L.vb[0], height: L.vb[1], fill: "url(#fl-dots)", class: "fl-grid" }, svg);

    const gEdges = s("g", { class: "fl-edges" }, svg);
    for (const id in L.edges) {
      const g = s("g", { class: "fe", "data-edge": id }, gEdges);
      const base = s("path", { d: L.edges[id], class: "fe-base" }, g);
      const flow = s("path", { d: L.edges[id], class: "fe-flow" }, g);
      F.el.edges[id] = { g, base, flow };
    }
    const gNodes = s("g", { class: "fl-nodes" }, svg);
    for (const id in L.nodes) F.el.nodes[id] = buildNode(gNodes, id, L.nodes[id]);
    F.el.loop = buildLoop(gNodes, L.loop);
    if (L.legend) buildLegend(svg, L.legend);
    const gFx = s("g", { class: "fl-fx" }, svg);
    F.el.fx = gFx;
    reapply();
  }

  function buildNode(parent, id, b) {
    const sp = SPEC[id];
    const g = s("g", { class: "fn" + (sp.risk ? " fn-risk" : "") + (sp.tool ? " fn-tool" : ""), "data-node": id }, parent);
    const box = s("rect", { x: b.x, y: b.y, width: b.w, height: b.h, rx: 11, class: "fn-box" }, g);
    let ic, title;
    if (sp.tool) {   // tools: the name is the hero, the icon sits small in the corner
      s("rect", { x: b.x + b.w - 27, y: b.y + 10, width: 18, height: 18, rx: 5, class: "fn-tile" }, g);
      ic = s("path", { d: ICONS[sp.icon], class: "fn-icon", transform: `translate(${b.x + b.w - 24.5},${b.y + 12.5}) scale(0.54)` }, g);
      title = s("text", { x: b.x + 11, y: b.y + 25, class: "fn-title fn-mono", "font-size": 11.5 }, g);
    } else {
      s("rect", { x: b.x + 12, y: b.y + 11, width: 26, height: 26, rx: 7, class: "fn-tile" }, g);
      ic = s("path", { d: ICONS[sp.icon], class: "fn-icon", transform: `translate(${b.x + 15},${b.y + 14}) scale(0.833)` }, g);
      title = s("text", { x: b.x + 46, y: b.y + 29, class: "fn-title", "font-size": 14 }, g);
    }
    const node = { g, box, ic, title, b, lines: [], titleW: sp.tool ? b.w - 42 : b.w - 56 };
    fitText(title, sp.title, node.titleW);
    if (sp.tag) {
      const tw = title.getComputedTextLength ? title.getComputedTextLength() : sp.title.length * 8;
      node.tag = s("text", { x: b.x + 46 + (tw || sp.title.length * 8) + 7, y: b.y + 29, class: "fn-tag", "font-size": 10.5 }, g);
      node.tag.textContent = sp.tag;
    }
    const n = sp.lines || 2;
    const count = n + (id === "model" ? 1 : 0) + (id === "employee" && b.h >= 140 ? 1 : 0);
    const y0 = b.y + (sp.tool ? 50 : b.h >= 90 ? 55 : 54), dy = count >= 3 ? 16.5 : (b.h >= 90 ? 18 : 17);
    for (let i = 0; i < count; i++) {
      node.lines.push(s("text", { x: b.x + 14, y: y0 + i * dy, class: "fn-line", "font-size": 11.5 }, g));
    }
    if (sp.lights) {   // three service lights
      node.lights = {};
      node.lines.forEach((t) => t.remove());
      node.lines = [];
      // lamp + label pairs, spread evenly across the card by their measured widths
      const items = SERVICES.map(([key, label]) => {
        const lg = s("g", { class: "fl-light", "data-svc": key }, g);
        const lamp = s("circle", { cy: b.y + 51, r: 5.5, class: "fl-lamp" }, lg);
        const t = s("text", { y: b.y + 55, class: "fl-lamp-t", "font-size": 11 }, lg);
        t.textContent = label;
        node.lights[key] = lg;
        return { lamp, t, w: 14 + (t.getComputedTextLength() || label.length * 6) };
      });
      let total = items.reduce((a, it) => a + it.w, 0);
      if (total + 8 > b.w - 24) {   // narrow card: smaller labels
        items.forEach((it) => { it.t.setAttribute("font-size", 9.5); it.w = 12 + (it.t.getComputedTextLength() || 30); });
        total = items.reduce((a, it) => a + it.w, 0);
      }
      const gap = Math.max(3, (b.w - 28 - total) / 2);
      let x = b.x + 16;
      items.forEach((it) => {
        it.lamp.setAttribute("cx", f(x + 5));
        it.t.setAttribute("x", f(x + 14));
        x += it.w + gap;
      });
      node.lines.push(s("text", { x: b.x + 14, y: b.y + 72, class: "fn-line", "font-size": 10.5 }, g));
    }
    if (sp.badge) {
      node.badge = s("g", { class: "fl-badge" }, g);
      s("circle", { cx: b.x + b.w - 6, cy: b.y + 6, r: 12 }, node.badge);   // a notification dot on the corner
      node.badgeText = s("text", { x: b.x + b.w - 6, y: b.y + 10.5, "text-anchor": "middle", "font-size": 12 }, node.badge);
    }
    if (id === "employee") {   // reply language chip
      node.chip = s("g", { class: "fl-chip-lang", opacity: 0 }, g);
      node.chipRect = s("rect", { x: b.x + 14, y: b.y + b.h - 30, width: 60, height: 20, rx: 10 }, node.chip);
      node.chipText = s("text", { x: b.x + 24, y: b.y + b.h - 16, "font-size": 11 }, node.chip);
    }
    return node;
  }

  function buildLoop(parent, L) {
    const g = s("g", { class: "fn fn-loop", "data-node": "loop" }, parent);
    s("circle", { cx: L.cx, cy: L.cy, r: L.r + 12, class: "fl-halo" }, g);
    s("circle", { cx: L.cx, cy: L.cy, r: L.r - 9, class: "fl-core" }, g);
    const rot = s("g", { class: "fl-ring" }, g);
    const segs = [];
    const N = F.meta.max_steps || 6, seg = 360 / N, gap = 7;
    for (let i = 0; i < N; i++) {
      const a0 = i * seg + gap / 2, a1 = (i + 1) * seg - gap / 2;
      const p0 = ring(L, a0), p1 = ring(L, a1);
      segs.push(s("path", { d: `M${f(p0.x)},${f(p0.y)} A${L.r},${L.r} 0 0 1 ${f(p1.x)},${f(p1.y)}`, class: "fl-seg" }, rot));
    }
    const mk = ring({ cx: L.cx, cy: L.cy, r: L.r + 9 }, 0);   // fixed marker at 12 o'clock
    s("path", { d: `M${f(mk.x - 5)},${f(mk.y - 5)} L${f(mk.x + 5)},${f(mk.y - 5)} L${f(mk.x)},${f(mk.y + 2)} Z`, class: "fl-mark" }, g);
    const lab = s("text", { x: L.cx, y: L.cy - 17, "text-anchor": "middle", class: "fl-cap", "font-size": 9.5 }, g);
    lab.textContent = "AGENT LOOP";
    const big = s("text", { x: L.cx, y: L.cy + 11, "text-anchor": "middle", class: "fl-big", "font-size": L.r > 58 ? 27 : 24 }, g);
    const sub = s("text", { x: L.cx, y: L.cy + 28, "text-anchor": "middle", class: "fl-cap", "font-size": 9.5 }, g);
    sub.textContent = "STEP";
    const st = L.status;
    const status = s("text", { x: st.x, y: st.y, "text-anchor": st.anchor, class: "fl-status", "font-size": 12.5 }, g);
    const chip = s("g", { class: "fl-done", opacity: 0 }, g);
    const chipRect = s("rect", { x: st.x, y: st.y + 10, height: 40, rx: 9 }, chip);
    const chipText = s("text", { x: st.x + 11, y: st.y + 26, "font-size": 11 }, chip);
    const chipText2 = s("text", { x: st.x + 11, y: st.y + 42, "font-size": 11, class: "fl-done-2" }, chip);
    return { g, rot, segs, big, status, chip, chipRect, chipText, chipText2, L };
  }

  function buildLegend(svg, p) {
    const g = s("g", { class: "fl-legend" }, svg);
    [["sky", "data"], ["risk", "risky: waits for a person"], ["ok", "ok / up"], ["err", "error / down"]].forEach(([k, t], i) => {
      const y = p.y + i * 17;
      s("circle", { cx: p.x + 6, cy: y, r: 4, fill: TONES[k] }, g);
      const tx = s("text", { x: p.x + 17, y: y + 4, "font-size": 11 }, g);
      tx.textContent = t;
    });
  }

  // ---------------------------------------------------------------- node state (stored, so a layout switch keeps it)
  function setNode(id, patch) {
    F.memo[id] = Object.assign(F.memo[id] || {}, patch);
    paintNode(id);
  }
  function paintNode(id) {
    const st = F.memo[id] || {};
    if (id === "loop") return paintLoop();
    const n = F.el.nodes && F.el.nodes[id];
    if (!n) return;
    const pad = n.b.w - 28;
    n.lines.forEach((t, i) => {
      const k = "l" + (i + 1);
      const text = st[k] || "";
      t.setAttribute("class", "fn-line" + (st[k + "c"] ? " c-" + st[k + "c"] : ""));
      if (id === "employee" && isArabic(text)) {   // the employee's own words read right to left
        t.setAttribute("direction", "rtl"); t.setAttribute("x", n.b.x + n.b.w - 14); }
      else { t.removeAttribute("direction"); t.setAttribute("x", n.b.x + 14); }
      fitText(t, text, pad);
    });
    if (st.title && n.title.textContent !== st.title) fitText(n.title, st.title, n.titleW);
    n.g.classList.toggle("tone-err", st.tone === "err");
    n.g.classList.toggle("tone-ok", st.tone === "ok");
    n.g.classList.toggle("tone-risk", st.tone === "risk");
    if (n.lights) for (const k in n.lights) {
      const v = F.services[k] || "up";
      n.lights[k].setAttribute("class", "fl-light is-" + v + ((st.checked || {})[k] ? " is-checked" : ""));
    }
    if (n.badge) {
      const c = F.shown.pending;
      n.badgeText.textContent = String(c);
      n.badge.classList.toggle("is-on", c > 0);
    }
    if (n.chip) {
      n.chip.setAttribute("opacity", st.chip ? 1 : 0);
      if (st.chip) {
        n.chipText.textContent = st.chip;
        const w = (n.chipText.getComputedTextLength() || st.chip.length * 6.5) + 20;
        n.chipRect.setAttribute("width", f(w));
        n.chip.classList.toggle("is-risk", !!st.chipRisk);
      }
    }
  }
  function paintLoop() {
    const lp = F.el.loop, st = F.memo.loop || {};
    if (!lp) return;
    const turn = st.turn || 0, N = F.meta.max_steps || 6;
    lp.big.replaceChildren();
    const a = s("tspan", {}, lp.big); a.textContent = String(turn);
    const b = s("tspan", { class: "fl-big-of", "font-size": 15, dx: 3 }, lp.big); b.textContent = "/ " + N;
    lp.segs.forEach((p, i) => p.setAttribute("class", "fl-seg" + (i < turn ? " is-lit" : "") + (i === turn - 1 && st.busy ? " is-now" : "")));
    lp.status.setAttribute("class", "fl-status" + (st.statusc ? " c-" + st.statusc : ""));
    fitText(lp.status, st.status || "idle", lp.L.status.anchor === "start" ? 168 : 176);
    lp.g.classList.toggle("tone-err", st.tone === "err");
    lp.chip.setAttribute("opacity", st.done ? 1 : 0);
    if (st.done) {
      lp.chipText.textContent = st.done[0];
      lp.chipText2.textContent = st.done[1];
      const w = Math.max(lp.chipText.getComputedTextLength() || st.done[0].length * 6.6,
        lp.chipText2.getComputedTextLength() || st.done[1].length * 6.6) + 22;
      if (lp.L.status.anchor === "middle") {
        lp.chipRect.setAttribute("x", f(lp.L.status.x - w / 2));
        lp.chipText.setAttribute("x", f(lp.L.status.x - w / 2 + 11));
        lp.chipText2.setAttribute("x", f(lp.L.status.x - w / 2 + 11));
      }
      lp.chipRect.setAttribute("width", f(w));
    }
  }
  function reapply() {
    for (const id in F.el.nodes) paintNode(id);
    paintLoop();
    setRingAngle(F.ringTo);
  }
  function setActive(ids, on) {
    ids.forEach((id) => {
      const n = id === "loop" ? F.el.loop : F.el.nodes[id];
      if (n) n.g.classList.toggle("is-active", on);
    });
  }
  function hold(id, on) {
    const n = id === "loop" ? F.el.loop : F.el.nodes[id];
    if (n) n.g.classList.toggle("is-hold", on);
  }
  function ping(id, tone) {   // a ring that leaves the card when a particle lands
    const n = id === "loop" ? null : F.el.nodes[id];
    if (!n || reduced()) return;
    const b = n.b;
    const r = s("rect", { x: b.x, y: b.y, width: b.w, height: b.h, rx: 11, class: "fl-ping", stroke: TONES[tone] }, F.el.fx);
    r.animate([{ transform: "scale(1)", opacity: 0.9 }, { transform: "scale(1.08)", opacity: 0 }],
      { duration: 520, easing: "cubic-bezier(.2,.7,.2,1)" }).onfinish = () => r.remove();
  }
  function setRingAngle(a) {
    F.ringAngle = a;
    const lp = F.el.loop;
    if (lp) lp.rot.setAttribute("transform", `rotate(${f(a)} ${lp.L.cx} ${lp.L.cy})`);
  }
  function turnRing(turn) {
    const N = F.meta.max_steps || 6;
    F.ringFrom = F.ringAngle;
    F.ringTo = -turn * (360 / N);
    F.ringT0 = performance.now();
    if (reduced()) setRingAngle(F.ringTo);
    setNode("loop", { turn, busy: true });
  }

  // ---------------------------------------------------------------- caption, screen-reader log, summary
  function caption(kind, text, tone) {
    if (!F.cap) return;
    F.cap.k.textContent = kind;
    F.cap.t.textContent = text;
    F.cap.root.dataset.tone = tone || "sky";
  }
  function log(text) {
    if (F.logEl) F.logEl.textContent = text;
    F.lastLog = text;
    summary();
  }
  function summary() {
    if (!F.svg) return;
    const down = Object.keys(F.services).filter((k) => F.services[k] === "down");
    const parts = ["Live flow of the agent"];
    if (F.lastLog) parts.push(F.lastLog);
    parts.push(down.length ? "Down: " + down.join(", ") : "All services up");
    if (F.shown.pending) parts.push(F.shown.pending + " action(s) waiting for a person");
    F.svg.setAttribute("aria-label", parts.join(". ") + ".");
  }

  // ---------------------------------------------------------------- steps: what the player shows
  const hop = (from, to, label, tone, at, opts) => Object.assign({ type: "hop", from, to, label, tone, at }, opts || {});
  const beat = (at, onStart, dur) => ({ type: "beat", at, dur: dur || BEAT, onStart });

  function edgeFor(from, to) {
    const E = F.layout.edges;
    if (E[from + ">" + to]) return { id: from + ">" + to, dir: 1 };
    if (E[to + ">" + from]) return { id: to + ">" + from, dir: -1 };
    return null;
  }

  // the model is asked: Loop -> Model, then "thinking" until its answer arrives
  function askSteps(at, resolvedAt) {
    const run = F.run;
    run.asked = true;
    run.askAt = run.lastAt;
    return [
      hop("loop", "model", "messages + " + F.meta.tools + " tools", "sky", at, {
        onStart() { setNode("loop", { status: "asks the model", statusc: "" }); caption("Model", "The loop sends the conversation and the tool menu."); },
      }),
      { type: "think", at, resolvedAt, onStart() {
        hold("model", true); setActive(["model"], true);
        if (resolvedAt == null) caption("Model", "The model is thinking about the next step.");
      } },
    ];
  }

  function expand(item) {
    const ev = item.ev, at = item.at, run = F.run;
    const out = [];
    if (ev.type === "model_turn") {
      if (!run.asked) out.push(...askSteps(at, at));
      out.push(beat(at, () => {
        run.asked = false; run.chosen = false;
        turnRing(ev.turn);
        setNode("model", { l2: "answered: turn " + ev.turn, l2c: "sky" });
      }, 260));
    } else if (ev.type === "tool") out.push(...toolSteps(ev, at));
    else if (ev.type === "final") out.push(...finalSteps(ev, at));
    else if (ev.type === "done") out.push(doneStep(ev, at));
    else if (ev.type === "error") out.push(errorStep(ev.detail || "error", at, "model"));
    else if (ev.type === "http_error") out.push(errorStep(ev.detail, at, "api"));
    run.lastAt = at;
    return out;
  }

  function toolLabel(ev) {
    const a = ev.args || {};
    const v = a.name || a.ticket_id || (a.query ? "“" + String(a.query).slice(0, 18) + (String(a.query).length > 18 ? "…" : "") + "”" : "") || a.priority || "";
    return ev.tool + "(" + v + ")";
  }
  function outcome(ev) {   // {label, tone, node patch, resource patch, log}
    const j = parse(ev.result_preview) || {};
    const lat = ev.latency_ms != null ? " · " + ms(ev.latency_ms) : "";
    if (ev.tool === "search_runbooks") {
      const ids = Array.from(String(ev.result_preview || "").matchAll(/"id":\s*"([^"]+)"/g), (m) => m[1]);
      const k = (ev.args && ev.args.k) || 3;
      return { label: "top " + k + " guides", tone: "ok", line: "ok · " + k + " guides" + lat,
        res: { l2: ids.length ? ids.join(", ") + (ids.length < k ? ", …" : "") : "top " + k + " by meaning", l2c: "sky" },
        say: "found the top " + k + " guides" + (ids.length ? " (" + ids[0] + (ids.length > 1 ? ", …" : "") + ")" : "") };
    }
    if (ev.tool === "check_service") {
      const down = j.status === "down";
      return { label: j.status || "checked", tone: down ? "err" : "ok", line: (j.status || "ok") + lat, lineTone: down ? "err" : "ok",
        svc: j.service, svcState: j.status, say: (j.service || "service") + " is " + (j.status || "checked") };
    }
    if (ev.tool === "create_ticket") {
      return { label: "ticket #" + j.ticket_id, tone: "ok", line: "ok · #" + j.ticket_id + " " + (j.priority || ""),
        ticket: { id: j.ticket_id, priority: j.priority }, say: "opened ticket #" + j.ticket_id };
    }
    if (ev.tool === "get_ticket") {
      return { label: "#" + j.ticket_id + " " + (j.status || ""), tone: "ok", line: "ok · " + (j.status || "found") + lat,
        say: "read ticket #" + j.ticket_id };
    }
    if (ev.tool === "restart_service") {
      return { label: "pending #" + (j.action_id || "?"), tone: "risk", line: "queued, not restarted", lineTone: "risk",
        say: "queued a restart for a person to approve" };
    }
    return { label: "ok", tone: "ok", line: "ok" + lat, say: "ok" };
  }
  function errorText(ev) {
    const j = parse(ev.result_preview);
    if (j && Array.isArray(j.details)) return j.error + ": " + j.details.map((d) => d.field + " " + d.error).join("; ");
    if (j && j.error) return j.error;
    return ev.result_preview || "error";
  }

  function toolSteps(ev, at) {
    const run = F.run, node = TOOL_NODE[ev.tool], risky = ev.tool === "restart_service";
    const tone = risky ? "risk" : "sky", out = [];
    run.asked = false;
    if (!run.chosen) {
      out.push(hop("model", "loop", "chose " + ev.tool, tone, at, {
        onStart() { hold("model", false); setNode("model", { l2: "chose: " + ev.tool, l2c: risky ? "risk" : "sky" });
          caption("Step " + ev.step, "The model chose " + ev.tool + ".", tone); },
      }));
      run.chosen = true;
    }
    if (!node) {
      out.push(beat(at, () => { setNode("loop", { status: "unknown tool " + ev.tool, statusc: "err" });
        caption("Step " + ev.step, "Rejected: unknown tool " + ev.tool, "err"); log("Step " + ev.step + ": unknown tool " + ev.tool); }));
      return out;
    }
    const callStart = () => {
      if (node === "t_ticket") setNode(node, { title: ev.tool });
      setNode(node, { l1: argsText(ev.args, 28) || "(no arguments)", l1c: "", l2: "running…", l2c: "", tone: risky ? "risk" : "" });
      setNode("loop", { status: "calls " + ev.tool, statusc: risky ? "risk" : "" });
    };
    if (ev.tool === "final_answer") {
      run.finalVisited = true;
      const r = ev.args || {};
      out.push(hop("loop", node, "final_answer", "sky", at, { onStart() {
        setNode(node, { l1: "language=" + (r.language || "?") + (r.ticket_id ? " ticket=" + r.ticket_id : ""),
          l2: ev.ok ? "valid shape" : "invalid", l2c: ev.ok ? "ok" : "err", tone: ev.ok ? "" : "err" });
        setNode("loop", { status: "step " + ev.step + ": final answer", statusc: "" });
        caption("Step " + ev.step, "The model writes the final answer.");
      } }));
      if (!ev.ok) out.push(hop(node, "loop", "invalid answer", "err", at, { onStart() {
        log("Step " + ev.step + ": final_answer rejected by the code"); caption("Step " + ev.step, "Rejected by the code: " + errorText(ev), "err");
        run.finalVisited = false; } }));
      return out;
    }
    const verb = { t_search: "vector search", t_check: "probe " + ((ev.args || {}).name || ""),
      t_ticket: ev.tool === "get_ticket" ? "SELECT #" + ((ev.args || {}).ticket_id || "") : "INSERT ticket", t_restart: "queue restart" }[node];
    out.push(hop("loop", node, toolLabel(ev), tone, at, { onStart: callStart }));
    if (!ev.ok) {
      const msg = errorText(ev);
      out.push(hop(node, "loop", "error", "err", at, {
        onStart() { setNode(node, { l2: "error: " + msg, l2c: "err", tone: "err" }); caption("Step " + ev.step, ev.tool + " failed: " + msg, "err"); },
        onEnd() { setNode("loop", { status: "error goes back to the model", statusc: "err" }); log("Step " + ev.step + ": " + toolLabel(ev) + " → error: " + msg); },
      }));
      return out;
    }
    const o = outcome(ev), res = RESOURCE[node];
    out.push(hop(node, res, verb, tone, at, { onEnd() {
      if (o.svc) { F.services[o.svc] = o.svcState === "down" ? "down" : "up";
        setNode("services", { checked: Object.assign({}, (F.memo.services || {}).checked, { [o.svc]: true }), l1: o.svc + ": " + o.svcState, l1c: o.svcState === "down" ? "err" : "ok" }); }
      if (o.res) setNode(res, o.res);
      if (o.ticket) { F.shown.tickets += 1; F.shown.last = o.ticket; paintCounts(); }
      if (risky) { F.shown.pending += 1; paintCounts(); setNode("approval", { l1: "restart " + ((ev.args || {}).name || ""), l1c: "risk", l2: "status: pending" }); }
    } }));
    if (risky) out.push(hop("approval", "human", "approve?", "risk", at, { onEnd() {
      setNode("human", { l1: "asked to approve", l1c: "risk", l2: F.shown.pending + " to review", l2c: "risk", tone: "risk" });
      caption("Step " + ev.step, "Nothing restarts until a person approves.", "risk");
    } }));
    out.push(hop(res, node, o.label, o.tone, at, { onEnd() { setNode(node, { l2: o.line, l2c: o.lineTone || "ok", tone: risky ? "risk" : "ok" }); } }));
    out.push(hop(node, "loop", "result", o.tone === "err" ? "err" : tone, at, {
      onStart() { caption("Step " + ev.step, toolLabel(ev) + " → " + o.say, o.tone === "ok" ? "sky" : o.tone); },
      onEnd() { setNode("loop", { status: "result added to the conversation", statusc: "" }); log("Step " + ev.step + ": " + toolLabel(ev) + " → " + o.label); },
    }));
    return out;
  }

  function finalSteps(ev, at) {
    const run = F.run, r = ev.reply || {}, out = [];
    const viol = ev.violations || [], rep = ev.repairs || [];
    if (!run.finalVisited) out.push(hop("loop", "t_final", ev.stop_reason === "final_answer" ? "final_answer" : "fallback reply", "sky", at, {
      onStart() { setNode("t_final", { l1: "stop: " + ev.stop_reason, l2: "fallback reply", l2c: "risk" }); } }));
    out.push(hop("t_final", "guards", "reply", "sky", at, {
      onStart() { caption("Guards", "Code checks the reply before it is sent."); },
      onEnd() {
        if (viol.length) setNode("guards", { l1: "caught " + viol.length + ": " + viol[0], l1c: "risk", l2: rep.length ? "repaired " + rep.length : "fixed before sending", l2c: "risk", tone: "risk" });
        else if (rep.length) setNode("guards", { l1: "code checks: ok", l1c: "ok", l2: "repaired: " + rep[0], l2c: "sky", tone: "ok" });
        else setNode("guards", { l1: "code checks: ok", l1c: "ok", l2: "ticket ids verified", l2c: "", tone: "ok" });
      },
    }));
    const lang = r.language === "ar" ? "AR" : "EN";
    out.push(hop("guards", "employee", "reply · " + lang, viol.length ? "risk" : "ok", at, { onEnd() {
      const lines = wrap(r.answer, 26, 2);
      setNode("employee", { l3: "↩ " + (lines[0] || ""), l3c: "ok", l4: lines[1] || "", l4c: "ok",
        chip: (lang === "AR" ? "Arabic reply" : "English reply") + (r.ticket_id ? " · #" + r.ticket_id : ""), chipRisk: false });
      caption("Reply", (r.answer || "").slice(0, 140), "ok");
      log("Reply sent in " + (lang === "AR" ? "Arabic" : "English") + (viol.length ? " after " + viol.length + " correction(s)" : ""));
      run.sawFinal = true;
    } }));
    return out;
  }

  function doneStep(ev, at) {
    return beat(at, () => {
      const run = F.run, steps = run.toolCount;
      const t = ["✓ " + steps + " steps · " + ms(ev.latency_ms || 0), num(ev.input_tokens) + " in / " + num(ev.output_tokens) + " out"];
      setNode("loop", { done: t, status: "done", statusc: "ok", busy: false });
      setNode("run", { l1: "done · " + ms(ev.latency_ms || 0) + " on server", l1c: "ok", l3: "run " + String(ev.run_id || "").slice(0, 8), l3c: "" });
      setNode("model", { l3: num(ev.input_tokens) + " in / " + num(ev.output_tokens) + " out tokens", l3c: "" });
      setNode("api", { l2: "200 · closed", l2c: "ok" });
      caption("Done", steps + " tool calls, " + ms(ev.latency_ms || 0) + " on the server.", "ok");
      log("Done: " + steps + " steps, " + ev.input_tokens + " tokens in, " + ev.output_tokens + " out, " + ms(ev.latency_ms || 0));
      endRun();
    }, 500);
  }
  function errorStep(detail, at, where) {
    return beat(at, () => {
      hold("model", false);
      setNode(where, { l2: "failed", l2c: "err", tone: "err" });
      if (where === "api") setNode("loop", { status: "not started", statusc: "err", busy: false });
      else setNode("loop", { status: "stopped: error", statusc: "err", tone: "err", busy: false });
      if (where === "api") setNode("api", { l2: String(detail).slice(0, 60), l2c: "err", tone: "err" });
      setNode("run", { l1: "stopped · error", l1c: "err" });
      caption("Error", detail, "err");
      log("Error: " + detail);
      endRun();
    }, 500);
  }

  // ---------------------------------------------------------------- the player (requestAnimationFrame)
  function ensureLoop() { if (!F.raf) F.raf = requestAnimationFrame(frame); }
  function busy() { return !!(F.cur || F.steps.length || F.pending.length || (F.run && F.run.active)); }

  function shouldAsk() {
    const r = F.run;
    return r && r.active && !r.asked && !r.finalVisited && !r.sawFinal && !r.ended && r.phase !== "final";
  }

  function frame(now) {
    F.raf = 0;
    let guard = 0;
    while (!F.cur && guard++ < 50) {
      if (F.steps.length) startStep(F.steps.shift(), now);
      else if (F.pending.length) {
        const item = F.pending.shift();
        if (item.ev.type === "tool") F.run.toolCount += 1;
        F.steps.push(...expand(item));
      } else if (shouldAsk()) F.steps.push(...askSteps(now, null));
      else break;
    }
    if (F.cur) tickStep(F.cur, now);
    tickRing(now);
    if (F.run && F.run.active && now - (F.runPaint || 0) > 100) {   // the run card's live clock
      F.runPaint = now;
      setNode("run", { l1: "live · " + ((now - F.run.t0) / 1000).toFixed(1) + " s", l1c: "sky",
        l2: F.run.events + " events · " + F.run.toolCount + (F.run.toolCount === 1 ? " tool call" : " tool calls") });
    }
    if (F.cur || F.steps.length || F.pending.length || (F.run && F.run.active) || now - F.ringT0 < 900) ensureLoop();
  }

  function rate(step, now) {   // playback speed for this step: chosen speed x catch-up
    const lag = now - (step.at || now);
    const catchup = lag > CATCHUP_LAG ? Math.min(3, 1 + (lag - CATCHUP_LAG) / 8000) : 1;
    return F.speed * catchup;
  }

  function startStep(step, now) {
    F.cur = step;
    step.t0 = now;
    if (step.type === "hop") {
      const e = edgeFor(step.from, step.to);
      step.edge = e;
      const len = e ? F.el.edges[e.id].base.getTotalLength() : 0;
      step.len = len;
      step.dur = Math.min(HOP_MAX, Math.max(HOP_MIN, 450 + len * 0.8)) / rate(step, now);
      if (reduced()) step.dur *= 0.8;
      setActive([step.from, step.to], true);
      if (e) {
        const E = F.el.edges[e.id];
        E.g.setAttribute("class", "fe is-hot t-" + step.tone);
        if (!reduced()) makeParticle(step, E);
      }
    } else if (step.type === "think") {
      step.dur = THINK_MIN / rate(step, now);
    } else step.dur = (step.dur || BEAT) / rate(step, now);
    if (step.onStart) step.onStart();
  }

  function tickStep(step, now) {
    const t = Math.min(1, (now - step.t0) / step.dur);
    if (step.type === "hop" && step.p) drawParticle(step, t);
    if (step.type === "think") {
      const end = step.resolvedAt != null ? step.resolvedAt : (F.pending[0] && F.pending[0].at);
      const el = ((end != null ? end : now) - F.run.askAt) / 1000;
      const dots = reduced() ? "…" : ["·  ", "·· ", "···"][Math.floor(now / 260) % 3];
      setNode("model", { l2: (end != null ? "answered in " : "thinking " + dots + " ") + Math.max(0, el).toFixed(1) + " s", l2c: end != null ? "sky" : "" });
      if (end == null) setNode("loop", { status: "waiting for the model", statusc: "" });
      const ready = end != null || !F.run.active;
      if (t >= 1 && ready) { hold("model", false); finishStep(step); }
      return;
    }
    if (t >= 1) finishStep(step);
  }

  function finishStep(step) {
    if (step.type === "hop") {
      if (step.p) step.p.g.remove();
      setActive([step.from, step.to], false);
      if (step.edge) F.el.edges[step.edge.id].g.setAttribute("class", "fe is-seen t-" + step.tone);
      ping(step.to, step.tone);
    }
    if (step.onEnd) step.onEnd();
    F.cur = null;
  }

  // a comet: three stacked dash segments (trail) + a bright head + a label chip
  function makeParticle(step, E) {
    const g = s("g", { class: "fp t-" + step.tone }, F.el.fx);
    const d = E.base.getAttribute("d");
    const trails = [[46, 5, 0.22], [26, 3.4, 0.5], [12, 2.4, 0.95]].map(([len, w, o]) =>
      ({ el: s("path", { d, class: "fp-trail", "stroke-width": w, opacity: o }, g), len }));
    const head = s("circle", { r: 4.2, class: "fp-head", filter: "url(#fl-glow)" }, g);
    const chip = s("g", { class: "fp-chip" }, g);
    const rect = s("rect", { height: 20, rx: 10, y: -10 }, chip);
    const text = s("text", { y: 4, "text-anchor": "middle", "font-size": 11 }, chip);
    text.textContent = step.label || "";
    const w = (text.getComputedTextLength() || (step.label || "").length * 6.6) + 18;
    rect.setAttribute("x", f(-w / 2));
    rect.setAttribute("width", f(w));
    step.p = { g, trails, head, chip, w, path: E.base };
  }
  function drawParticle(step, t) {
    const p = step.p, L = step.len, dir = step.edge.dir;
    const k = travel(t);
    const at = dir > 0 ? k * L : (1 - k) * L;
    const pt = p.path.getPointAtLength(at);
    p.head.setAttribute("cx", f(pt.x));
    p.head.setAttribute("cy", f(pt.y));
    const fade = Math.min(1, t * 8, (1 - t) * 5 + 0.15);
    p.trails.forEach((tr) => {
      const len = Math.min(tr.len, k * L);
      tr.el.setAttribute("stroke-dasharray", f(len) + " " + f(L + 200));
      tr.el.setAttribute("stroke-dashoffset", f(dir > 0 ? -(at - len) : -at));
    });
    const vb = F.layout.vb;
    const cx = Math.max(p.w / 2 + 4, Math.min(vb[0] - p.w / 2 - 4, pt.x));
    const cy = Math.max(14, pt.y - 19);
    p.chip.setAttribute("transform", `translate(${f(cx)},${f(cy)})`);
    p.g.setAttribute("opacity", f(fade));
    p.chip.setAttribute("opacity", f(Math.min(1, (1 - t) * 5)));   // the label leaves before the particle lands
  }

  function tickRing(now) {
    if (F.ringAngle === F.ringTo) return;
    const t = Math.min(1, (now - F.ringT0) / (720 / F.speed));
    setRingAngle(F.ringFrom + (F.ringTo - F.ringFrom) * easeOut(t));
  }

  function endRun() {
    if (!F.run) return;
    F.run.active = false;
    F.run.ended = true;
    if (F.svg) F.svg.classList.remove("running");
    F.root.classList.remove("is-running");
    if (F.onIdle) setTimeout(F.onIdle, 0);
    syncCounts();
  }

  // ---------------------------------------------------------------- run lifecycle
  function resetNodes() {
    const idle = idleLines(F.meta);
    const keep = { services: F.memo.services, tickets: F.memo.tickets, approval: F.memo.approval, human: F.memo.human };
    F.memo = {};
    for (const id in idle) F.memo[id] = Object.assign({}, idle[id]);
    F.memo.services = { l1: "", checked: {} };
    F.memo.loop = { turn: 0, status: "idle" };
    Object.assign(F.memo, { tickets: keep.tickets || {}, approval: keep.approval || {}, human: keep.human || {} });
    paintCounts(true);
    F.ringFrom = F.ringTo = 0;
    setRingAngle(0);
    if (F.el.edges) for (const id in F.el.edges) F.el.edges[id].g.setAttribute("class", "fe");
    if (F.el.fx) F.el.fx.replaceChildren();
    reapply();
  }

  function paintCounts(silent) {
    const c = F.shown;
    F.memo.tickets = Object.assign(F.memo.tickets || {}, { l1: c.tickets + (c.tickets === 1 ? " ticket" : " tickets"),
      l2: c.last ? "last #" + c.last.id + " · " + (c.last.priority || "") : "none yet", l2c: c.last ? "sky" : "" });
    if (!c.pending) {
      F.memo.approval = Object.assign(F.memo.approval || {}, { l1: "queue: empty", l1c: "", l2: "risky steps wait" });
      F.memo.human = Object.assign(F.memo.human || {}, { l1: "waits for a person", l1c: "", l2: "nothing to review", tone: "" });
    } else if (silent) {
      F.memo.approval = Object.assign(F.memo.approval || {}, { l1: "queue: " + c.pending + " waiting", l1c: "risk", l2: "approve or reject" });
      F.memo.human = Object.assign(F.memo.human || {}, { l1: "waits for a person", l1c: "", l2: c.pending + " to review", l2c: "risk" });
    }
    ["tickets", "approval", "human"].forEach(paintNode);
    summary();
  }
  function syncCounts() {   // the server's numbers win once a run is over
    if (busy()) return;
    F.shown = Object.assign({}, F.counts);
    paintCounts(true);
  }

  function begin(message, opts) {
    opts = opts || {};
    if (!opts.replay) clearReplay();
    F.pending = []; F.steps = [];
    if (F.cur && F.cur.p) F.cur.p.g.remove();
    F.cur = null;
    F.shown = Object.assign({}, F.counts);
    resetNodes();
    const now = performance.now();
    F.run = { active: true, asked: false, chosen: false, phase: "start", lastAt: now, askAt: now, toolCount: 0, t0: now, events: 0,
      finalVisited: false, sawFinal: false, ended: false };
    if (!opts.replay) F.rec = { message, events: [], t0: now };
    F.svg.classList.add("running");
    F.root.classList.add("is-running");
    const ar = isArabic(message), lines = wrap(message, ar ? 22 : 24, 2);
    const q0 = ar ? "" : "“", q1 = ar ? "" : "”";   // curly quotes only around left-to-right text
    F.steps.push(hop("employee", "api", "message", "sky", now, { onStart() {
      setNode("employee", { l1: q0 + (lines[0] || ""), l2: lines[1] ? lines[1] + q1 : "", l1c: "", l2c: "", l3: "", l4: "", chip: "" });
      if (!lines[1]) setNode("employee", { l1: q0 + (lines[0] || "") + q1 });
      caption("Request", "An employee writes: “" + message.slice(0, 120) + (message.length > 120 ? "…" : "") + "”");
      log("New message: " + message.slice(0, 120));
    } }));
    F.steps.push(hop("api", "loop", "new run", "sky", now, {
      onStart() { setNode("api", { l2: "POST · SSE stream open", l2c: "sky" }); },
      onEnd() { F.run.phase = "tool"; setNode("loop", { status: "run started", busy: true }); },
    }));
    ensureLoop();
    updateControls();
  }

  function push(ev) {
    if (!F.run) return;
    const now = performance.now();
    if (F.rec && !F.replaying) F.rec.events.push({ ev, dt: now - F.rec.t0 });
    if (ev.type === "done" || ev.type === "error") { F.last = F.rec; }
    F.pending.push({ ev, at: now });
    F.run.events += 1;
    ensureLoop();
  }

  function fail(detail) {   // the request was refused before the stream started: no run reaches the loop
    F.steps = F.steps.filter((st) => !(st.from === "api" && st.to === "loop"));
    push({ type: "http_error", detail });
  }

  function clearReplay() {
    F.replayTimers.forEach(clearTimeout);
    F.replayTimers = [];
    F.replaying = false;
  }
  function replay() {
    const rec = F.last;
    if (!rec || busy()) return;
    clearReplay();
    F.replaying = true;
    begin(rec.message, { replay: true });
    let t = 0, prev = 0;
    rec.events.forEach((item, i) => {
      t += Math.min(REPLAY_GAP_MAX, item.dt - prev) / F.speed;
      prev = item.dt;
      F.replayTimers.push(setTimeout(() => {
        push(item.ev);
        if (i === rec.events.length - 1) F.replaying = false;
      }, t));
    });
    updateControls();
  }

  // ---------------------------------------------------------------- page wiring: controls, presentation mode, layout choice
  function updateControls() {
    if (!F.ctrl) return;
    F.ctrl.replay.disabled = !F.last || busy();
    F.ctrl.speeds.forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.speed) === F.speed)));
  }

  function chooseLayout() {
    const w = F.stage.clientWidth || F.root.clientWidth;
    const want = w && w < 600 ? "tall" : "wide";
    if (F.layout && F.layout.name === want) return;
    F.layout = want === "tall" ? tallLayout() : wideLayout();
    if (F.cur && F.cur.p) { F.cur.p.g.remove(); F.cur.p = null; }
    build();
    if (F.run && F.run.active) F.svg.classList.add("running");
  }

  function present(on) {
    const card = F.root;
    if (on === card.classList.contains("presenting")) return;
    card.classList.toggle("presenting", on);
    document.body.classList.toggle("flow-presenting", on);
    F.ctrl.full.querySelector("span").textContent = on ? "Exit full screen" : "Full screen";
    F.ctrl.full.setAttribute("aria-pressed", String(on));
    if (on) {   // dock the composer under the flow, and remember where it was
      F.dockHome = F.dockSrc.map((n) => [n, n.parentNode, n.nextSibling]);
      F.dockSrc.forEach((n) => F.dock.appendChild(n));
      if (document.documentElement.requestFullscreen && !document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(() => { /* a window that fills the viewport is enough */ });
      }
    } else {
      (F.dockHome || []).forEach(([n, parent, next]) => parent.insertBefore(n, next));
      if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(() => {});
    }
    F.layout = null;
    chooseLayout();
  }

  function init(opts) {
    F.root = opts.root;
    F.stage = opts.stage;
    F.cap = { root: opts.caption, k: opts.caption.querySelector(".cap-k"), t: opts.caption.querySelector(".cap-t") };
    F.logEl = opts.log;
    F.dock = opts.dock;
    F.dockSrc = opts.dockSources || [];
    F.onIdle = opts.onIdle;
    F.ctrl = { replay: opts.replay, speeds: opts.speeds, full: opts.full };
    opts.replay.addEventListener("click", replay);
    opts.speeds.forEach((b) => b.addEventListener("click", () => { F.speed = Number(b.dataset.speed) || 1; updateControls(); }));
    opts.full.addEventListener("click", () => present(!F.root.classList.contains("presenting")));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && F.root.classList.contains("presenting")) present(false); });
    document.addEventListener("fullscreenchange", () => { if (!document.fullscreenElement && F.root.classList.contains("presenting")) present(false); });
    chooseLayout();
    resetNodes();
    caption("Ready", "Send a message and watch each step of the agent here.");
    if (window.ResizeObserver) new ResizeObserver(() => chooseLayout()).observe(F.stage);
    else window.addEventListener("resize", chooseLayout);
    setInterval(updateControls, 500);
  }

  // ---------------------------------------------------------------- public API for app.js
  window.HelpdeskFlow = {
    init, begin, push, fail, replay, busy,
    setMeta(m) {
      F.meta = Object.assign(F.meta, { model: m.model, tools: m.tools || F.meta.tools, guides: m.guides, max_steps: m.max_steps || F.meta.max_steps });
      F.layout = null;
      chooseLayout();
      if (!busy()) resetNodes(); else reapply();
    },
    setServices(map) {
      Object.assign(F.services, map);
      if (!busy()) { F.memo.services = { l1: "", checked: {} }; }
      paintNode("services");
      summary();
    },
    setCounts(c) {
      F.counts = { tickets: c.tickets || 0, last: c.last || null, pending: c.pending || 0 };
      syncCounts();
    },
    redraw() { F.layout = null; chooseLayout(); },
  };
})();
