// Seahorse desktop app - the Settings tab.
// Every control saves on its own; the server validates each value before using it.
"use strict";

let SET = null;                 // the last /api/settings payload
let SET_SECTION = "general";
let CREW_SEL = null;            // agent name being edited
let CREW_STEP = 1;
let CREW_DRAFT = null;
let SEAL_ID = 0;
let FIELD_ID = 0;

// Each settings section's glyph.
const SECTION_GLYPH = {
  general: "compass", council: "scales", models: "cloud", character: "seahorse", crew: "anchor", lobes: "coral", brains: "knot",
  inner: "pearl", privacy: "mask", look: "starfish", images: "porthole", data: "logbook",
};

const EXTRA_SECTIONS = {
  crew: { id: "crew", title: "Crew", icon: "⚓", blurb: "Every agent is a member of the Seahorse's crew, built from the same 11 steps as the captain." },
  data: { id: "data", title: "Data & about", icon: "▣", blurb: "Where everything lives, and putting settings back to their defaults." },
};

// ------------------------------------------------------------------ seals
function sealSVG(sign, motto, color, size = 72, label = "") {
  const uid = "seal" + (++SEAL_ID);
  const text = String(motto || "").toUpperCase();
  const ring = text ? `★ ${text} ★` : "";
  const fit = ring.length > 26 ? ` textLength="214" lengthAdjust="spacingAndGlyphs"` : "";
  return `<svg class="seal" width="${size}" height="${size}" viewBox="0 0 100 100" role="img" aria-label="${esc(label || "seal")}: ${esc(text)}">` +
    `<defs><path id="${uid}" d="M50,50 m-35,0 a35,35 0 1,1 70,0 a35,35 0 1,1 -70,0"/></defs>` +
    `<circle cx="50" cy="50" r="47" fill="none" stroke="${esc(color)}" stroke-width="2.6"/>` +
    `<circle cx="50" cy="50" r="43" fill="none" stroke="${esc(color)}" stroke-width="0.9" stroke-dasharray="1.4 2.6"/>` +
    `<circle cx="50" cy="50" r="26" fill="${esc(color)}" fill-opacity="0.08" stroke="${esc(color)}" stroke-width="1.6"/>` +
    `<text font-size="8.6" letter-spacing="1.2" font-weight="700" fill="${esc(color)}"><textPath href="#${uid}" startOffset="50%" text-anchor="middle"${fit}>${esc(ring)}</textPath></text>` +
    `<text x="50" y="51" dominant-baseline="central" text-anchor="middle" font-size="27" fill="${esc(color)}">${esc(sign || "·")}</text>` +
    `</svg>`;
}

// ------------------------------------------------------------------ loading
async function loadSettings() {
  try {
    SET = await api("/api/settings");
  } catch (e) {
    $("#setMain").innerHTML = `<div class="empty"><span class="big-mark">${glyph("wheel", 48)}</span><p>${esc(e.message)}</p></div>`;
    return;
  }
  renderSetNav();
  renderSection();
}

function sectionList() {
  const out = [];
  for (const s of SET.sections) {
    out.push(s);
    if (s.id === "character") out.push(EXTRA_SECTIONS.crew);
  }
  out.push(EXTRA_SECTIONS.data);
  return out;
}

function renderSetNav() {
  const nav = $("#setNav");
  nav.innerHTML = "";
  for (const s of sectionList()) {
    const li = document.createElement("li");
    li.innerHTML = `<button type="button" class="set-nav-btn${s.id === SET_SECTION ? " active" : ""}">` +
      `<span class="set-nav-icon">${glyph(SECTION_GLYPH[s.id] || "wheel", 16)}</span><span>${esc(s.title)}</span></button>`;
    $("button", li).addEventListener("click", () => {
      SET_SECTION = s.id;
      CREW_SEL = null;
      $("#setSearch").value = "";
      renderSetNav();
      renderSection();
    });
    nav.appendChild(li);
  }
}

function renderSection() {
  const main = $("#setMain");
  main.scrollTop = 0;
  if (SET_SECTION === "crew") return renderCrew();
  if (SET_SECTION === "data") return renderData();
  const s = SET.sections.find(x => x.id === SET_SECTION) || SET.sections[0];
  main.innerHTML = sectionHead(s);
  const box = document.createElement("div");
  box.className = "set-card";
  if (!s.fields.length) box.innerHTML = `<p class="muted">Nothing to set here right now.</p>`;
  for (const f of s.fields) box.appendChild(fieldRow(f));
  main.appendChild(box);
  if (s.id === "lobes") main.appendChild(lobesExtras());
  if (s.id === "character") main.appendChild(characterExtras());
  if (s.id === "council") {
    const card = document.createElement("div");
    card.className = "set-card";
    card.innerHTML = `<h3 class="set-card-title">The council table and how it has voted</h3><p class="muted small">Votes run 01 → 05 along the top, then turn and run 06 → 10 back along the bottom. On a tie, seat 01 casts the deciding vote (1+). Reseat with <code>/council seat 3 broca</code>.</p><pre class="prompt-preview">${esc(SET.councilStats || "")}</pre>`;
    main.appendChild(card);
  }
  if (s.id === "models") main.appendChild(note("Changing the base model or the character rebuilds the local 'seahorse' model in the background when Ollama is running."));
}

function sectionHead(s) {
  return `<header class="set-head"><span class="set-head-icon">${glyph(SECTION_GLYPH[s.id] || "wheel", 24)}</span><div><h2>${esc(s.title)}</h2>` +
    `<p class="muted">${esc(s.blurb || "")}</p></div></header>`;
}

function note(text) {
  const p = document.createElement("p");
  p.className = "muted small set-note";
  p.textContent = text;
  return p;
}

// ------------------------------------------------------------------ one setting
function fieldRow(f) {
  const id = "f" + (++FIELD_ID);
  const row = document.createElement("div");
  row.className = "set-row";
  row.dataset.key = f.key;
  row.innerHTML = `<div class="set-label"><label for="${id}">${esc(f.label)}</label>` +
    (f.help ? `<p class="help">${esc(f.help)}</p>` : "") + `</div>` +
    `<div class="set-control"></div><span class="set-status" aria-live="polite"></span>`;
  $(".set-control", row).appendChild(control(f, id, v => saveSetting(f, v, row)));
  return row;
}

function control(f, id, onChange) {
  const wrap = document.createElement("div");
  wrap.className = "ctl ctl-" + f.kind;
  if (f.kind === "toggle") {
    wrap.innerHTML = `<button type="button" id="${id}" class="switch" role="switch" aria-checked="${!!f.value}"><span></span></button>`;
    const b = $("button", wrap);
    b.addEventListener("click", () => {
      const v = b.getAttribute("aria-checked") !== "true";
      b.setAttribute("aria-checked", String(v));
      onChange(v);
    });
  } else if (f.kind === "segmented") {
    wrap.setAttribute("role", "radiogroup");
    wrap.id = id;
    for (const [val, label] of f.options) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", String(String(f.value) === val));
      b.addEventListener("click", () => {
        $$("button", wrap).forEach(x => x.setAttribute("aria-checked", String(x === b)));
        onChange(val);
      });
      wrap.appendChild(b);
    }
  } else if (f.kind === "select") {
    const sel = document.createElement("select");
    sel.id = id;
    for (const [val, label] of f.options || []) {
      const o = document.createElement("option");
      o.value = val; o.textContent = label;
      if (String(f.value) === val) o.selected = true;
      sel.appendChild(o);
    }
    sel.addEventListener("change", () => onChange(sel.value));
    wrap.appendChild(sel);
  } else if (f.kind === "number") {
    wrap.innerHTML = `<input type="number" id="${id}" min="${f.min}" max="${f.max}" step="${f.step || 1}" value="${esc(f.value)}">`;
    const inp = $("input", wrap);
    inp.addEventListener("change", () => onChange(Number(inp.value)));
  } else if (f.kind === "slider") {
    wrap.innerHTML = `<input type="range" id="${id}" min="${f.min}" max="${f.max}" step="${f.step}" value="${esc(f.value)}">` +
      `<output>${Number(f.value).toFixed(2)}</output>`;
    const inp = $("input", wrap), out = $("output", wrap);
    inp.addEventListener("input", () => { out.textContent = Number(inp.value).toFixed(2); });
    inp.addEventListener("change", () => onChange(Number(inp.value)));
  } else if (f.kind === "secret") {
    wrap.innerHTML = `<input type="password" id="${id}" autocomplete="off" spellcheck="false" placeholder="${f.value ? "a key is set for this run" : "sk-ant-…"}">` +
      `<button type="button" class="ghost small">Use for this run</button>` +
      `<span class="pill ${f.value ? "ok" : ""}">${f.value ? "key set" : "no key"}</span>`;
    const inp = $("input", wrap);
    $("button", wrap).addEventListener("click", () => { if (inp.value.trim()) { onChange(inp.value.trim()); inp.value = ""; } });
  } else {
    wrap.innerHTML = `<input type="text" id="${id}" value="${esc(f.value ?? "")}" maxlength="${f.max || 200}" spellcheck="false">`;
    const inp = $("input", wrap);
    inp.addEventListener("change", () => onChange(inp.value));
  }
  return wrap;
}

async function saveSetting(f, v, row) {
  const status = $(".set-status", row);
  status.className = "set-status saving";
  status.textContent = "saving…";
  try {
    const r = await api("/api/settings", { changes: { [f.key]: v } });
    SET = r;
    status.className = "set-status ok";
    status.textContent = "saved ✓";
    flashSaved(f.label);
    for (const n of r.notes || []) toast(n);
    if (r.state) applyState(r.state);
    if (f.key === "api_key" || SET_SECTION === "lobes") renderSection();
    setTimeout(() => { if (status.textContent === "saved ✓") status.textContent = ""; }, 1800);
  } catch (e) {
    status.className = "set-status err";
    status.textContent = e.message;
    const fresh = findField(f.key);
    if (fresh) {           // put the control back to the value the server has
      const ctl = $(".set-control", row);
      ctl.innerHTML = "";
      ctl.appendChild(control(fresh, "f" + (++FIELD_ID), val => saveSetting(fresh, val, row)));
    }
  }
}

function findField(key) {
  for (const s of SET.sections) for (const f of s.fields) if (f.key === key) return f;
  return null;
}

function flashSaved(label) {
  const el = $("#setSaved");
  el.textContent = `Saved: ${label}`;
  clearTimeout(flashSaved._t);
  flashSaved._t = setTimeout(() => { el.textContent = ""; }, 2500);
}

// ------------------------------------------------------------------ search
$("#setSearch").addEventListener("input", () => {
  const q = $("#setSearch").value.trim().toLowerCase();
  if (!SET) return;
  if (!q) return renderSection();
  const main = $("#setMain");
  main.innerHTML = `<header class="set-head"><span class="set-head-icon">${glyph("search", 24)}</span><div><h2>Results for “${esc(q)}”</h2></div></header>`;
  let hits = 0;
  for (const s of SET.sections) {
    const fields = s.fields.filter(f => (f.label + " " + (f.help || "") + " " + f.key).toLowerCase().includes(q));
    if (!fields.length) continue;
    hits += fields.length;
    const box = document.createElement("div");
    box.className = "set-card";
    box.innerHTML = `<h3 class="set-card-title">${esc(s.icon)} ${esc(s.title)}</h3>`;
    for (const f of fields) box.appendChild(fieldRow(f));
    main.appendChild(box);
  }
  if (!hits) main.appendChild(note("No setting matches. Try 'model', 'judge', 'accent' or 'theme'."));
});

// ------------------------------------------------------------------ character extras
function characterExtras() {
  const box = document.createElement("div");
  box.className = "set-card piece";
  const piece = SET.character.piece || "";
  const title = (piece.split("\n")[0] || "").replace(/\.$/, "");
  box.innerHTML = `<h3 class="set-card-title">${esc(SET.character.title)} · personality piece</h3>` +
    `<p class="muted small">“${esc(title || "his tale")}” is kept word for word. His personality is drawn from its images, rhythm and mood, and he recites it exactly when asked. Change it with <code>/build tale</code> in the terminal.</p>` +
    `<blockquote class="piece-text">${esc(piece.split("\n").slice(1).join("\n") || piece)}</blockquote>`;
  return box;
}

// ------------------------------------------------------------------ lobes extras
function lobesExtras() {
  const st = SET.lobeStats || {};
  const n = st.votes || 0;
  const live = Math.max(1, n - (st.cached || 0));
  const how = st.how || {};
  const wrap = document.createElement("div");
  wrap.className = "set-grid";
  const flow = document.createElement("div");
  flow.className = "set-card vote-flow";
  flow.innerHTML = `<h3 class="set-card-title">How a vote runs</h3>
    <div class="flow">
      <div class="flow-col">
        <div class="ballot left"><b>Doc</b><span>left · blue · west</span><small>ballot: approach, confidence, points, caution</small></div>
        <div class="ballot right"><b>Fiery Black</b><span>right · red · east</span><small>ballot: approach, confidence, points, caution</small></div>
      </div>
      <div class="flow-arrow" aria-hidden="true">→</div>
      <div class="flow-col"><div class="tally"><b>Tally</b><small>weight × confidence<br>contested → balance (veto)<br>caution ≥ 0.6 kept</small></div></div>
      <div class="flow-arrow" aria-hidden="true">→</div>
      <div class="flow-col"><div class="judge-box"><b>⚖ Judge</b><small>only on a close split</small></div></div>
      <div class="flow-arrow" aria-hidden="true">→</div>
      <div class="flow-col"><div class="decision"><b>Decision</b><small>approach + must-mention points for the core</small></div></div>
    </div>
    <ul class="approaches">${Object.entries(SET.approaches || {}).map(([k, v]) => `<li><b>${esc(k)}</b> ${esc(v)}</li>`).join("")}</ul>`;
  wrap.appendChild(flow);

  const stats = document.createElement("div");
  stats.className = "set-card";
  const agree = n ? Math.round(100 * (how.unanimous || 0) / n) : 0;
  const tiles = [["votes", n], ["agreed", n ? agree + "%" : "–"], ["Judge tie-breaks", st.judge_calls || 0],
                 ["average", n ? ((st.ms_total || 0) / live / 1000).toFixed(1) + "s" : "–"]];
  const bars = (obj) => {
    const entries = Object.entries(obj || {}).sort((a, b) => b[1] - a[1]);
    const max = Math.max(1, ...entries.map(e => e[1]));
    return entries.length ? entries.map(([k, v]) => `<div class="bar"><span>${esc(k)}</span><i style="width:${(100 * v / max).toFixed(0)}%"></i><em>${v}</em></div>`).join("")
      : `<p class="muted small">No votes yet.</p>`;
  };
  stats.innerHTML = `<h3 class="set-card-title">How the votes have gone</h3>
    <div class="tiles">${tiles.map(([k, v]) => `<div class="tile"><b>${esc(v)}</b><span>${esc(k)}</span></div>`).join("")}</div>
    <h4>Outcomes</h4>${bars(how)}<h4>Approaches chosen</h4>${bars(st.approach)}
    <button type="button" class="ghost small" id="clearVotes">Clear stats</button>`;
  $("#clearVotes", stats).addEventListener("click", async () => {
    SET = await api("/api/lobes/stats/reset", {});
    toast("Vote stats cleared");
    renderSection();
  });
  wrap.appendChild(stats);
  return wrap;
}

// ------------------------------------------------------------------ crew
function crewMember(name) {
  return SET.crew.members.find(m => m.agent === name);
}

function renderCrew() {
  if (CREW_SEL) return renderCrewEditor();
  const main = $("#setMain");
  main.innerHTML = sectionHead(EXTRA_SECTIONS.crew) + `<p class="lore">${esc(SET.crew.lore)}</p>`;
  const crewToggles = document.createElement("div");
  crewToggles.className = "set-card";
  for (const key of ["crew", "seals"]) {
    const f = findField(key);
    if (f) crewToggles.appendChild(fieldRow(f));
  }
  main.appendChild(crewToggles);
  const oaths = document.createElement("div");
  oaths.className = "set-grid oaths";
  for (const kind of ["pledge", "chant"]) oaths.appendChild(oathCard(kind));
  main.appendChild(oaths);
  const grid = document.createElement("div");
  grid.className = "crew-grid";
  for (const m of SET.crew.members) {
    const mem = m.member;
    const card = document.createElement("button");
    card.type = "button";
    card.className = "crew-card" + (m.captain ? " captain" : "");
    card.style.setProperty("--agent", m.color);
    card.innerHTML = `${sealSVG(m.seal.sign, m.seal.motto, m.color, 76, mem.name)}
      <span class="crew-name">${esc(mem.name)}</span>
      <span class="crew-epithet">${esc(mem.epithet || "")}</span>
      <span class="crew-post">${esc(mem.post || "")}</span>
      <span class="crew-agent">@${esc(m.agent)}${m.edited ? ` · <em>edited</em>` : ""}</span>
      ${mem.greetings && mem.greetings.length && !m.captain ? `<q>${esc(mem.greetings[0])}</q>` : ""}
      <span class="crew-go">${m.captain ? "The captain: edit with /build" : "Edit the 11 steps →"}</span>`;
    card.addEventListener("click", () => {
      if (m.captain) { SET_SECTION = "character"; renderSetNav(); renderSection(); return; }
      CREW_SEL = m.agent;
      CREW_STEP = 1;
      CREW_DRAFT = JSON.parse(JSON.stringify(mem));
      CREW_DRAFT.seal = CREW_DRAFT.seal || { sign: "", motto: "" };
      renderCrewEditor();
    });
    grid.appendChild(card);
  }
  main.appendChild(grid);
}

function oathCard(kind) {
  const o = SET.crew[kind];
  const card = document.createElement("div");
  card.className = "set-card oath " + kind;
  const view = () => {
    card.innerHTML = `<h3 class="set-card-title">${esc(o.title)}</h3><p class="muted small">by ${esc(o.author)} · kept word for word; ` +
      `the crew ${kind === "chant" ? "calls it out together when they muster" : "swore it, and recites it when asked"}</p>` +
      `<blockquote class="piece-text">${esc(o.text)}</blockquote>` +
      `<button type="button" class="ghost small">Edit</button>`;
    $("button", card).addEventListener("click", edit);
  };
  const edit = () => {
    card.innerHTML = `<h3 class="set-card-title">Edit the ${kind}</h3>
      <div class="crew-field"><label>Title</label><input type="text" maxlength="120" data-k="title"></div>
      <div class="crew-field"><label>Author</label><input type="text" maxlength="120" data-k="author"></div>
      <div class="crew-field"><label>Words (kept exactly as written)</label><textarea rows="${kind === "chant" ? 3 : 9}" maxlength="4000" data-k="text"></textarea></div>
      <div class="crew-actions"><button type="button" class="ghost small" data-a="cancel">Cancel</button>
      <button type="button" class="ghost small" data-a="reset">Restore the original</button><span class="spacer"></span>
      <button type="button" class="primary" data-a="save">Save</button></div>`;
    for (const el of $$("[data-k]", card)) el.value = o[el.dataset.k] || "";
    const send = async body => {
      try {
        SET = await api("/api/crew/oath", { kind, ...body });
        toast(body.reset ? `The original ${kind} is back` : `${o.title} saved`);
        renderCrew();
      } catch (e) { toast(e.message, 5000); }
    };
    $("[data-a=cancel]", card).addEventListener("click", view);
    $("[data-a=reset]", card).addEventListener("click", () => send({ reset: true }));
    $("[data-a=save]", card).addEventListener("click", () => {
      const body = {};
      for (const el of $$("[data-k]", card)) body[el.dataset.k] = el.value;
      send(body);
    });
  };
  view();
  return card;
}

function renderCrewEditor() {
  const m = crewMember(CREW_SEL);
  const d = CREW_DRAFT;
  const main = $("#setMain");
  const steps = SET.crew.form;
  main.innerHTML = `
    <div class="crew-ed-head" style="--agent:${esc(m.color)}">
      <button type="button" class="ghost small" id="crewBack">← Crew</button>
      <div class="crew-ed-seal" id="crewSeal">${sealSVG(d.seal.sign, d.seal.motto, m.color, 96, d.name)}</div>
      <div><h2 id="crewTitle">${esc(d.name)}</h2><p class="muted">${esc(d.epithet || "")} · ${esc(d.post || "")} · answers as <b>@${esc(m.agent)}</b></p>
      <p class="stamp" id="crewStamp"></p></div>
    </div>
    <ol class="stepper" role="tablist">${steps.map(s => `<li><button type="button" role="tab" data-step="${s.step}" aria-selected="${s.step === CREW_STEP}">` +
      `<span>${s.step}</span>${esc(s.title)}</button></li>`).join("")}</ol>
    <div class="set-card crew-step" id="crewStep"></div>
    <div class="crew-actions">
      <button type="button" class="ghost small" id="crewPrev">← Back</button>
      <button type="button" class="ghost small" id="crewNext">Next →</button>
      <span class="spacer"></span>
      <button type="button" class="ghost small" id="crewReset" ${m.edited ? "" : "disabled"}>Reset to default</button>
      <button type="button" class="primary" id="crewSave">Save ${esc(d.name.split(" ")[0])}</button>
    </div>`;
  updateStamp();
  $("#crewBack").addEventListener("click", () => { CREW_SEL = null; renderCrew(); });
  $$(".stepper button").forEach(b => b.addEventListener("click", () => { CREW_STEP = +b.dataset.step; renderCrewEditor(); }));
  $("#crewPrev").disabled = CREW_STEP === 1;
  $("#crewNext").disabled = CREW_STEP === steps.length;
  $("#crewPrev").addEventListener("click", () => { CREW_STEP--; renderCrewEditor(); });
  $("#crewNext").addEventListener("click", () => { CREW_STEP++; renderCrewEditor(); });
  $("#crewSave").addEventListener("click", saveCrew);
  $("#crewReset").addEventListener("click", resetCrew);
  renderCrewStep(steps.find(s => s.step === CREW_STEP), m);
}

function updateStamp() {
  const d = CREW_DRAFT, m = crewMember(CREW_SEL);
  $("#crewSeal").innerHTML = sealSVG(d.seal.sign, d.seal.motto, m.color, 96, d.name);
  $("#crewTitle").textContent = d.name || "(no name)";
  const sign = d.seal.sign, motto = (d.seal.motto || "").toUpperCase();
  $("#crewStamp").textContent = sign || motto ? `[${[sign, (d.name || "").toUpperCase()].filter(Boolean).join(" ")}${motto ? " · " + motto : ""}]` : "";
}

function getDraft(key) {
  return key.startsWith("seal.") ? CREW_DRAFT.seal[key.split(".")[1]] : CREW_DRAFT[key];
}
function setDraft(key, v) {
  if (key.startsWith("seal.")) CREW_DRAFT.seal[key.split(".")[1]] = v;
  else CREW_DRAFT[key] = v;
  $("#crewSave").classList.add("dirty");
}

function renderCrewStep(step, m) {
  const box = $("#crewStep");
  box.innerHTML = `<h3 class="set-card-title">Step ${step.step} of 11 · ${esc(step.title)}</h3><p class="muted small">${esc(STEP_HELP[step.step] || "")}</p>`;
  for (const f of step.fields) {
    const id = "c" + (++FIELD_ID);
    const row = document.createElement("div");
    row.className = "crew-field";
    const val = getDraft(f.key);
    if (f.kind === "long" || f.kind === "lines") {
      const text = f.kind === "lines" ? (val || []).join("\n") : (val || "");
      row.innerHTML = `<label for="${id}">${esc(f.label)}</label><textarea id="${id}" rows="${f.key === "tale" ? 7 : 5}" maxlength="${f.kind === "long" ? f.max : 2400}"></textarea>` +
        `<span class="count"></span>`;
      const ta = $("textarea", row);
      ta.value = text;
      const count = () => { $(".count", row).textContent = f.kind === "lines" ? `${ta.value.split("\n").filter(x => x.trim()).length} / ${f.max} lines` : `${ta.value.length} / ${f.max}`; };
      count();
      ta.addEventListener("input", () => {
        setDraft(f.key, f.kind === "lines" ? ta.value.split("\n").map(x => x.trim()).filter(Boolean) : ta.value);
        count();
      });
    } else if (f.kind === "segmented") {
      row.innerHTML = `<label>${esc(f.label)}</label>`;
      row.appendChild(control({ ...f, value: val || "captain" }, id, v => setDraft(f.key, v)));
    } else {
      row.innerHTML = `<label for="${id}">${esc(f.label)}</label><input type="text" id="${id}" maxlength="${f.max}">`;
      const inp = $("input", row);
      inp.value = val || "";
      inp.addEventListener("input", () => {
        setDraft(f.key, f.key === "seal.motto" ? inp.value.toUpperCase() : inp.value);
        if (f.key.startsWith("seal.") || f.key === "name") updateStamp();
      });
    }
    box.appendChild(row);
  }
  if (step.step === 1) box.appendChild(note("The seal stamps each of their replies, like a notary's signature. One symbol for the sign, a few words for the motto."));
  if (step.step === 8) {
    const core = document.createElement("div");
    core.className = "core-rules";
    core.innerHTML = `<b>Core rules (every character, always):</b><ul>${SET.crew.coreRules.map(r => `<li>${esc(r)}</li>`).join("")}</ul>`;
    box.appendChild(core);
  }
  if (step.step === 10) box.appendChild(note("Offsets from Seahorse's own traits, -0.4 to +0.4, e.g. 'rigor +0.20, warmth -0.10'. Traits: warmth, playfulness, curiosity, concision, directness, creativity, rigor, patience, initiative."));
  if (step.step === 11) {
    const pv = document.createElement("div");
    pv.innerHTML = `<p class="muted small">This is how they're told who they are (as last saved). Save first to preview your changes.</p>
      <pre class="prompt-preview">${esc(m.preview)}</pre>
      <div class="crew-test"><input type="text" id="crewAsk" placeholder="Say something to ${esc(CREW_DRAFT.name)}…" maxlength="500">
      <button type="button" class="ghost small" id="crewAskBtn">Test them</button></div>
      <div class="crew-reply" id="crewReply"></div>`;
    box.appendChild(pv);
    $("#crewAskBtn").addEventListener("click", testCrew);
    $("#crewAsk").addEventListener("keydown", e => { if (e.key === "Enter") testCrew(); });
  }
}

const STEP_HELP = {
  1: "Who answers as this agent: name, epithet, post aboard, and their notary seal.",
  2: "Who they were, written to them ('You were...').",
  3: "A few lines kept word for word. They recite it exactly when asked.",
  4: "How they sound: dialect, rhythm, register. Code and drafts always stay in standard English.",
  5: "How strongly the voice comes through. 'Captain' follows the captain's accent setting.",
  6: "Small habits that make them themselves, used sparingly.",
  7: "Something uncanny about them. Always mood, never a real prediction.",
  8: "Their own rules, on top of the core rules every character keeps.",
  9: "How they open and close when they take the helm.",
  10: "The personality traits this agent leans on while answering.",
  11: "Read the full character prompt, then test them with a line.",
};

async function saveCrew() {
  const btn = $("#crewSave");
  btn.disabled = true;
  try {
    SET = await api("/api/crew", { agent: CREW_SEL, member: CREW_DRAFT });
    if (SET.state) applyState(SET.state);
    toast(`${CREW_DRAFT.name} saved`);
    const m = crewMember(CREW_SEL);
    CREW_DRAFT = JSON.parse(JSON.stringify(m.member));
    CREW_DRAFT.seal = CREW_DRAFT.seal || { sign: "", motto: "" };
    renderCrewEditor();
  } catch (e) {
    toast(e.message, 5000);
    btn.disabled = false;
  }
}

async function resetCrew() {
  const btn = $("#crewReset");
  if (btn.dataset.confirm !== "1") {
    btn.dataset.confirm = "1";
    btn.textContent = "Click again to reset";
    setTimeout(() => { if (btn.isConnected) { btn.dataset.confirm = ""; btn.textContent = "Reset to default"; } }, 3000);
    return;
  }
  SET = await api("/api/crew/reset", { agent: CREW_SEL });
  if (SET.state) applyState(SET.state);
  const m = crewMember(CREW_SEL);
  CREW_DRAFT = JSON.parse(JSON.stringify(m.member));
  CREW_DRAFT.seal = CREW_DRAFT.seal || { sign: "", motto: "" };
  toast("Back to the default");
  renderCrewEditor();
}

async function testCrew() {
  const out = $("#crewReply");
  const text = $("#crewAsk").value.trim();
  out.innerHTML = `<span class="thinking"><span class="bob">${agentGlyph(CREW_SEL, 16)}</span> ${esc(CREW_DRAFT.name)} is thinking</span>`;
  try {
    const r = await api("/api/crew/test", { agent: CREW_SEL, text });
    out.innerHTML = md(r.reply);
  } catch (e) {
    out.textContent = e.message;
  }
}

// ------------------------------------------------------------------ data
function renderData() {
  const main = $("#setMain");
  const d = SET.data;
  const kb = n => n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : n > 1024 ? (n / 1024).toFixed(0) + " KB" : n + " B";
  main.innerHTML = sectionHead(EXTRA_SECTIONS.data) + `
    <div class="set-card"><h3 class="set-card-title">Your data folder</h3>
      <p><code>${esc(d.folder)}</code></p>
      <p class="muted small">Everything Seahorse keeps lives here, on this computer. Back it up by copying the folder.</p>
      <div class="table-wrap"><table class="data-table"><thead><tr><th>File</th><th>Size</th></tr></thead><tbody>
      ${(d.files || []).map(f => `<tr><td><code>${esc(f.name)}</code></td><td>${kb(f.bytes)}</td></tr>`).join("") || `<tr><td colspan="2" class="muted">Nothing yet</td></tr>`}
      </tbody></table></div></div>
    ${Object.keys(d.memory || {}).length ? `<div class="set-card"><h3 class="set-card-title">Memory</h3><div class="tiles">` +
      Object.entries(d.memory).slice(0, 8).map(([k, v]) => `<div class="tile"><b>${esc(v)}</b><span>${esc(k.replace(/_/g, " "))}</span></div>`).join("") + `</div></div>` : ""}
    <div class="set-card danger"><h3 class="set-card-title">Reset settings</h3>
      <p class="muted small">Puts every setting on this page back to its default. Your character, crew, memories, notebooks and profile are not touched.</p>
      <button type="button" class="ghost small" id="resetAll">Reset settings to defaults</button></div>`;
  $("#resetAll").addEventListener("click", async e => {
    const b = e.currentTarget;
    if (b.dataset.confirm !== "1") {
      b.dataset.confirm = "1";
      b.textContent = "Click again to confirm";
      return;
    }
    SET = await api("/api/settings/reset", {});
    if (SET.state) applyState(SET.state);
    toast("Settings are back to their defaults");
    renderSection();
  });
}
