// Seahorse desktop app - launcher, chat and image generator.
"use strict";

const TOKEN = document.querySelector('meta[name="seahorse-token"]').content;
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
let STATE = null;
let busy = false;

// ------------------------------------------------------------------ helpers
async function api(path, body) {
  const opts = { headers: { "X-Seahorse-Token": TOKEN } };
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

async function stream(path, body, onEvent) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "X-Seahorse-Token": TOKEN, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (line) { try { onEvent(JSON.parse(line)); } catch (e) { /* skip */ } }
    }
  }
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ------------------------------------------------------------------ markdown
// Safe Markdown: everything is escaped first, then a small set of tags is added.
// Handles headings, lists, quotes, rules, tables, links (http/https only),
// bold/italic/inline code and fenced code blocks with highlighting + copy.
const KEYWORDS = new Set((
  "def class return if elif else for while in not and or is import from as with try except finally raise " +
  "lambda yield pass break continue global nonlocal assert del async await None True False self " +
  "function const let var new this typeof instanceof switch case default throw catch do void delete " +
  "export extends super static null undefined true false of " +
  "fn pub use mod struct enum impl trait match mut loop where crate " +
  "func package type interface map chan go defer range select " +
  "int float double char bool string void long short unsigned public private protected " +
  "echo then fi done esac elif local SELECT FROM WHERE INSERT UPDATE DELETE JOIN CREATE TABLE INTO VALUES"
).split(" "));
const HASH_COMMENT = new Set(["py", "python", "sh", "bash", "zsh", "shell", "rb", "ruby", "yaml", "yml", "toml", "r", "pl", "perl", "dockerfile", "makefile", "conf", "ini", "modelfile"]);

function highlight(code, lang) {
  lang = (lang || "").toLowerCase();
  const hash = HASH_COMMENT.has(lang) || !lang;
  const re = new RegExp(
    (hash ? "(#[^\\n]*)" : "(\\/\\/[^\\n]*|\\/\\*[\\s\\S]*?\\*\\/)") +   // 1 comment
    "|(\"\"\"[\\s\\S]*?\"\"\"|'''[\\s\\S]*?'''|\"(?:\\\\.|[^\"\\\\\\n])*\"|'(?:\\\\.|[^'\\\\\\n])*'|`(?:\\\\.|[^`\\\\])*`)" + // 2 string
    "|(\\b\\d[\\d_]*(?:\\.\\d+)?(?:e[+-]?\\d+)?\\b|\\b0x[0-9a-f]+\\b)" +  // 3 number
    "|([A-Za-z_][\\w]*)(?=\\s*\\()" +                                   // 4 call
    "|([A-Za-z_][\\w]*)", "gi");                                          // 5 word
  let out = "", last = 0, m;
  while ((m = re.exec(code))) {
    out += esc(code.slice(last, m.index));
    const [tok, com, str, num, call, word] = m;
    if (com) out += `<span class="t-com">${esc(tok)}</span>`;
    else if (str) out += `<span class="t-str">${esc(tok)}</span>`;
    else if (num) out += `<span class="t-num">${esc(tok)}</span>`;
    else if (KEYWORDS.has(call || word)) out += `<span class="t-kw">${esc(tok)}</span>`;
    else if (call) out += `<span class="t-fn">${esc(tok)}</span>`;
    else out += esc(tok);
    last = m.index + tok.length;
  }
  return out + esc(code.slice(last));
}

let CODE_ID = 0;
const CODE_STORE = new Map();   // id -> raw code, for the copy buttons
function codeBlock(code, lang, open) {
  const id = "c" + (++CODE_ID);
  CODE_STORE.set(id, code);
  if (CODE_STORE.size > 400) CODE_STORE.delete(CODE_STORE.keys().next().value);
  const lines = code.split("\n").length;
  return `<div class="code${open ? " streaming" : ""}"><div class="code-head"><span>${esc(lang || "text")}</span>` +
    `<span class="code-meta">${lines} line${lines === 1 ? "" : "s"}</span>` +
    `<button type="button" class="copy" data-copy="${id}">${glyph("copy", 13)}<span>Copy</span></button></div>` +
    `<pre><code>${highlight(code, lang)}</code></pre></div>`;
}

function inline(s) {
  // s is raw text; protect inline code first, then escape the rest.
  const codes = [];
  s = s.replace(/`([^`\n]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = esc(s)
    .replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, t, u) => `<a href="${u}" target="_blank" rel="noopener noreferrer">${t}</a>`)
    .replace(/(^|[\s(])(https?:\/\/[^\s<)]+[^\s<).,;:!?'"])/g, (_, p, u) => `${p}<a href="${u}" target="_blank" rel="noopener noreferrer">${u}</a>`)
    .replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>")
    .replace(/__([^_\n]+)__/g, "<b>$1</b>")
    .replace(/(^|[^\w*])\*([^*\n]+)\*(?!\w)/g, "$1<i>$2</i>")
    .replace(/~~([^~\n]+)~~/g, "<s>$1</s>");
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${esc(codes[+i])}</code>`);
}

function table(rows) {
  const cells = r => r.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
  const head = cells(rows[0]);
  const align = cells(rows[1]).map(c => c.endsWith(":") ? (c.startsWith(":") ? "center" : "right") : "");
  const td = (tag, c, i) => `<${tag}${align[i] ? ` style="text-align:${align[i]}"` : ""}>${inline(c)}</${tag}>`;
  return `<div class="table-wrap"><table><thead><tr>${head.map((c, i) => td("th", c, i)).join("")}</tr></thead><tbody>` +
    rows.slice(2).map(r => `<tr>${cells(r).map((c, i) => td("td", c, i)).join("")}</tr>`).join("") + `</tbody></table></div>`;
}

function md(text) {
  const lines = String(text ?? "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let para = [], list = null, quote = [];
  const flushPara = () => { if (para.length) { out.push(`<p>${para.map(inline).join("<br>")}</p>`); para = []; } };
  const flushList = () => { if (list) { out.push(`<${list.tag}${list.start > 1 ? ` start="${list.start}"` : ""}>${list.items.map(i => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`); list = null; } };
  const flushQuote = () => { if (quote.length) { out.push(`<blockquote>${md(quote.join("\n"))}</blockquote>`); quote = []; } };
  const flushAll = () => { flushPara(); flushList(); flushQuote(); };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const fence = line.match(/^\s*(```+|~~~+)\s*([\w+#.-]*)\s*$/);
    if (fence) {
      flushAll();
      const buf = [];
      let j = i + 1, closed = false;
      for (; j < lines.length; j++) {
        if (lines[j].trim().startsWith(fence[1])) { closed = true; break; }
        buf.push(lines[j]);
      }
      out.push(codeBlock(buf.join("\n"), fence[2], !closed));
      i = j;
      continue;
    }
    if (/^\s*>/.test(line)) { flushPara(); flushList(); quote.push(line.replace(/^\s*>\s?/, "")); continue; }
    flushQuote();
    if (!line.trim()) { flushPara(); flushList(); continue; }
    const h = line.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/);
    if (h) { flushAll(); const n = Math.min(h[1].length + 1, 6); out.push(`<h${n}>${inline(h[2])}</h${n}>`); continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flushAll(); out.push("<hr>"); continue; }
    if (line.includes("|") && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(lines[i + 1])) {
      flushAll();
      const rows = [line, lines[i + 1]];
      let j = i + 2;
      while (j < lines.length && lines[j].includes("|") && lines[j].trim()) rows.push(lines[j++]);
      out.push(table(rows));
      i = j - 1;
      continue;
    }
    const ul = line.match(/^\s*[-*+•]\s+(.*)$/);
    const ol = line.match(/^\s*(\d+)[.)]\s+(.*)$/);
    if (ul || ol) {
      flushPara();
      const tag = ul ? "ul" : "ol";
      if (!list || list.tag !== tag) { flushList(); list = { tag, items: [], start: ol ? +ol[1] : 1 }; }
      list.items.push(ul ? ul[1] : ol[2]);
      continue;
    }
    if (list && /^\s{2,}\S/.test(line)) { list.items[list.items.length - 1] += " " + line.trim(); continue; }
    flushList();
    para.push(line);
  }
  flushAll();
  return out.join("");
}

// Copy buttons (event delegation - inline handlers are blocked by the CSP).
document.addEventListener("click", async e => {
  const btn = e.target.closest("[data-copy], [data-copy-reply]");
  if (!btn) return;
  const text = btn.dataset.copy ? CODE_STORE.get(btn.dataset.copy) : btn.closest(".msg-bot")?.dataset.raw;
  if (text == null) return;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const t = document.createElement("textarea");
    t.value = text; document.body.appendChild(t); t.select();
    try { document.execCommand("copy"); } catch { /* ignore */ }
    t.remove();
  }
  const label = btn.querySelector("span") || btn;
  const was = label.textContent;
  label.textContent = "Copied ✓";
  btn.classList.add("done");
  setTimeout(() => { label.textContent = was; btn.classList.remove("done"); }, 1400);
});

// ------------------------------------------------------------------ scrolling
// Follow new output only while the reader is at the bottom; otherwise show a
// "jump to latest" button instead of yanking them down.
function nearBottom() { const m = $("#messages"); return m.scrollHeight - m.scrollTop - m.clientHeight < 80; }
let FOLLOW = true;
function toBottom(force) {
  const m = $("#messages");
  if (force || FOLLOW) { m.scrollTop = m.scrollHeight; FOLLOW = true; }
  $("#jump")?.classList.toggle("show", !FOLLOW);
}

function toast(msg, ms = 3200) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), ms);
}

function agentInfo(name) {
  return (STATE?.agents || []).find(a => a.name === name) || { name: name || "seahorse", icon: "Ψ", color: "#ff875f" };
}

// ------------------------------------------------------------------ navigation
function show(view) {
  $$(".tab").forEach(t => t.classList.toggle("active", t.dataset.view === view));
  $$(".view").forEach(v => v.classList.toggle("active", v.id === `view-${view}`));
  if (view === "chat") setTimeout(() => $("#input").focus(), 50);
  if (view === "images") loadImages();
  if (view === "settings" && typeof loadSettings === "function") loadSettings();
}
$$(".tab").forEach(t => t.addEventListener("click", () => show(t.dataset.view)));
$$("[data-open]").forEach(b => b.addEventListener("click", () => show(b.dataset.open)));

// ------------------------------------------------------------------ state
async function loadState() {
  applyState(await api("/api/state"));
}

function applyState(state) {
  STATE = state;
  const root = document.documentElement.style;
  for (const [k, v] of Object.entries(STATE.theme)) root.setProperty(`--${k}`, v);
  $("#heroArt").textContent = STATE.logo.art.join("\n");
  $("#heroTitle").textContent = STATE.logo.title.join("\n");
  const c = STATE.character;
  $("#greeting").textContent = c.enabled ? c.greeting : "";
  $("#chatTileName").textContent = `Chat with ${c.name}${c.epithet ? ", " + c.epithet : ""}`;
  $("#portraitText").textContent = `Portrait of ${c.epithet || c.name} from the 11 steps`;
  $("#modeText").textContent = { auto: "Claude first · local when offline", claude: "Claude only", local: "local only" }[STATE.mode] || STATE.mode;
  $("#modeGlyph").innerHTML = glyph(STATE.mode === "local" ? "sloop" : "cloud", 15);
  renderAgents();
  if (!$("#messages").childElementCount) renderHistory();
}

function renderAgents() {
  const list = $("#agentList");
  list.innerHTML = "";
  const auto = { name: "auto", icon: "Ψ", color: "#00ffff", purpose: "The best agent for each message" };
  for (const a of [auto, ...STATE.agents]) {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.className = "agent-btn" + ((STATE.agentMode === a.name) ? " active" : "");
    const h = a.horseman;
    b.innerHTML = `<span class="agent-icon">${agentGlyph(a.name, 18)}</span><span><span class="agent-name">${esc(a.crew || a.name)}</span>` +
      (a.crew ? `<span class="agent-crew">${a.penny ? `<span class="penny" title="shilling ${esc(a.penny)} - seat ${esc(a.penny)} at the council table">s${esc(a.penny)}</span>` : ""}${esc(a.name)}` +
        (h ? `<span class="horse" title="${esc(h.rider)}, ${esc(h.horse)} - one of the four horsemen; rides over ${esc(h.quarter)}, stands at ${esc(h.station)}">♞</span>` : "") +
        (a.purse ? `<span class="purse" title="paid so far">$${(a.purse / 100).toFixed(2)}</span>` : "") + `</span>` : "") +
      `<span class="agent-purpose">${esc(a.purpose || a.description || "")}</span></span>`;
    $(".agent-icon", b).style.color = a.color;
    b.style.setProperty("--agent", a.color);
    $(".agent-name", b).style.color = a.color;
    b.title = a.skill || "";
    b.addEventListener("click", async () => {
      const r = await api("/api/agent", { agent: a.name });
      STATE.agentMode = r.agentMode;
      renderAgents();
      toast(a.name === "auto" ? "Routing each message to the best agent" : `Talking to ${a.crew || a.name}`);
    });
    li.appendChild(b);
    list.appendChild(li);
  }
}

// ------------------------------------------------------------------ launcher
async function loadEnv() {
  const list = $("#checks");
  try {
    const env = await api("/api/env");
    list.innerHTML = "";
    for (const c of env.checks) {
      const li = document.createElement("li");
      const cls = c.ok ? "ok" : (c.required ? "bad" : "opt");
      li.innerHTML = `<span class="dot ${cls}"></span><span><span class="check-label">${esc(c.label)}</span>` +
        `<span class="check-detail">${esc(c.detail)}</span><span class="progress hidden"><i></i></span></span><span class="act"></span>`;
      if (c.action) {
        const btn = document.createElement("button");
        btn.className = "ghost small";
        btn.textContent = c.action === "start_ollama" ? "Start" : c.action === "build_model" ? "Build" : "Download";
        btn.addEventListener("click", () => runAction(c.action, li, btn));
        $(".act", li).appendChild(btn);
      }
      list.appendChild(li);
    }
    $("#dataDir").textContent = `Your data: ${env.data_dir} (${env.data_mb} MB)`;
    $("#readyNote").textContent = env.ready ? "Ready. Pick a screen above." :
      "Seahorse needs Ollama with a local model, or a Claude API key, before he can talk.";
  } catch (e) {
    list.innerHTML = `<li class="muted">Couldn't check: ${esc(e.message)}</li>`;
  }
}
$("#recheck").addEventListener("click", loadEnv);

async function runAction(action, li, btn) {
  btn.disabled = true;
  const detail = $(".check-detail", li);
  try {
    if (action === "start_ollama") {
      detail.textContent = "starting…";
      const r = await api("/api/ollama/start", {});
      toast(r.message);
    } else if (action === "build_model") {
      detail.textContent = "building…";
      const r = await api("/api/model/build", {});
      toast(r.message);
    } else if (action.startsWith("pull:")) {
      const model = action.slice(5);
      const bar = $(".progress", li);
      bar.classList.remove("hidden");
      await stream("/api/ollama/pull", { model }, ev => {
        if (ev.error) { detail.textContent = ev.error; return; }
        if (ev.total && ev.completed) {
          const pct = Math.round(100 * ev.completed / ev.total);
          $("i", bar).style.width = pct + "%";
          detail.textContent = `${ev.status} - ${pct}%`;
        } else if (ev.status) {
          detail.textContent = ev.status;
        }
      });
    }
  } catch (e) {
    toast(e.message);
  }
  loadEnv();
}

// ------------------------------------------------------------------ chat
function addEl(cls, html) {
  const el = document.createElement("div");
  el.className = cls;
  if (html !== undefined) el.innerHTML = html;
  $("#messages").appendChild(el);
  toBottom(cls === "msg-user");
  return el;
}

function clock(d = new Date()) { return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }

function botBubble(agentName, via, ev = {}) {
  const a = agentInfo(agentName);
  // A live reply says who's answering and their seal; earlier replies use the agent's current crew member.
  const crewName = ev.crew || a.crew || "";
  const seal = ev.seal || (a.seal && a.seal.sign ? { ...a.seal, name: a.crew } : null);
  const el = addEl("msg-bot", `<div class="bot-head"><b class="who">${agentGlyph(agentName, 16)}<span>${esc(crewName || a.name)}</span></b>` +
    (crewName ? `<span class="crew-tag">${esc(a.name)}</span>` : "") +
    `<span class="via">${esc(via || "")}</span></div>` +
    `<div class="bot-body"></div><div class="bot-foot">` +
    (seal && typeof sealSVG === "function" ? `<span class="foot-seal" title="${esc(seal.stamp || "")}">${sealSVG(seal.sign, seal.motto, a.color, 34, seal.name)}</span>` : "") +
    `<span class="stamp"></span><button type="button" class="copy ghost" data-copy-reply>${glyph("copy", 13)}<span>Copy reply</span></button></div>`);
  $("b", el).style.color = a.color;
  el.style.setProperty("--agent", a.color);
  el.dataset.agent = agentName;
  return el;
}

function finishBubble(el, raw, extra) {
  if (!el) return;
  el.dataset.raw = raw;
  el.classList.add("done");
  const words = (raw.match(/\S+/g) || []).length;
  $(".stamp", el).textContent = [extra, words ? `${words} word${words === 1 ? "" : "s"}` : ""].filter(Boolean).join(" · ");
}

function renderHistory() {
  const box = $("#messages");
  box.innerHTML = "";
  if (!STATE.history.length) {
    const c = STATE.character;
    addEl("welcome", `<div class="big-mark bob">${glyph("seahorse", 60)}</div><p class="welcome-line">${esc(c.enabled ? c.greeting : "Say something to begin.")}</p>` +
      `<p class="small">Every agent reads what you write in its own way. Ask anything, or type <code>/help</code>.</p>`);
    return;
  }
  for (const m of STATE.history) {
    if (m.role === "user") addEl("msg-user").textContent = m.content;
    else { const b = botBubble(m.agent || "hippocampus", "earlier"); $(".bot-body", b).innerHTML = md(m.content); finishBubble(b, m.content); }
  }
  toBottom(true);
}

function thinkingEl(agentName) {
  const a = agentInfo(agentName);
  const el = addEl("thinking", `<span class="bob">${agentGlyph(agentName, 18)}</span><span>${esc(a.name)} is thinking</span><span class="bubbles"></span>`);
  $(".bob", el).style.color = a.color;
  return el;
}

async function send(text) {
  if (!text.trim()) return;
  if (busy) { toast("Seahorse is still answering - one moment"); $("#input").value = text; return; }
  $(".welcome")?.remove();
  if (text.trim().startsWith("/")) return command(text.trim());
  busy = true;
  $("#sendBtn").disabled = true;
  addEl("msg-user").textContent = text;
  let bubble = null, body = null, raw = "", thinking = null, frame = 0;
  const paint = () => { frame = 0; if (body) { body.innerHTML = md(raw); toBottom(); } };
  try {
    await stream("/api/chat", { text }, ev => {
      if (ev.type === "noticed") {
        const wrap = addEl("noticed");
        for (const c of ev.chips) {
          const chip = document.createElement("span");
          chip.className = "chip";
          chip.innerHTML = `<b>${agentGlyph(c.agent, 12)}</b> ${esc(c.category)}`;
          $("b", chip).style.color = c.color;
          chip.style.borderColor = c.catColor + "66";
          chip.title = `${c.agent} noticed ${c.category}`;
          wrap.appendChild(chip);
        }
      } else if (ev.type === "conscience" && bubble) {
        const c = document.createElement("div");
        c.className = "conscience";
        c.innerHTML = `<b class="with-glyph">${glyph("pearl", 15)} on second thought</b> ${md(ev.text)}`;
        $("b", c).style.color = ev.color;
        bubble.appendChild(c);
      } else if (ev.type === "magic") {
        thinking?.remove(); thinking = null;
        const m = addEl("magic");
        m.innerHTML = `<div class="magic-head"><b class="with-glyph">${glyph("starfish", 16)} ${esc(ev.name)}</b><span>Bureau of Magic</span></div><div>${md(ev.text)}</div>` +
          (ev.dept === "riddle" ? `<div class="magic-hint">type /magic reveal for the answer</div>` : "");
        $("b", m).style.color = ev.color;
        m.style.borderColor = ev.color + "88";
      } else if (ev.type === "sub") {
        thinking?.remove(); thinking = null;
        const d = document.createElement("details");
        d.className = "sub-note";
        const kindGlyph = { council: glyph("compass", 15), step: agentGlyph(ev.agent, 15), approval: glyph("scales", 15) }[ev.kind];
        const mark = kindGlyph || (ev.lobe ? glyph(ev.name.startsWith("lobe vote") ? "bottle" : "coral", 15)
          : `<span class="sub-sign">${esc(ev.icon)}</span>`);
        d.innerHTML = `<summary><b class="with-glyph">${mark} ${esc(ev.name)}</b> <span>${ev.lobe ? "" : esc(ev.agent) + "'s brain"}</span></summary><div>${md(ev.text)}</div>`;
        $("b", d).style.color = ev.color;
        d.style.borderLeftColor = ev.color;
        $("#messages").appendChild(d);
        toBottom();
      } else if (ev.type === "thinking") {
        thinking?.remove();
        thinking = thinkingEl(ev.agent);
        if (ev.label) $("span:nth-child(2)", thinking).textContent = ev.label;
      } else if (ev.type === "start") {
        thinking?.remove(); thinking = null;
        bubble = botBubble(ev.agent, "via " + ev.backend, ev);
        body = $(".bot-body", bubble);
        raw = "";
      } else if (ev.type === "token" && body) {
        raw += ev.text;
        if (!frame) frame = requestAnimationFrame(paint);   // re-render at most once per frame
      } else if (ev.type === "calc" && bubble) {
        const c = document.createElement("div");
        c.className = "calc";
        c.textContent = ev.results.map(r => "= " + r).join("\n");
        bubble.appendChild(c);
      } else if (ev.type === "end") {
        if (frame) { cancelAnimationFrame(frame); }
        paint();
        finishBubble(bubble, raw, clock());
        if (ev.note) addEl("note").textContent = ev.note;
      } else if (ev.type === "paid") {
        // The Treasurer paid the last reply by this agent: a coin chip on that reply's footer.
        const done = [...document.querySelectorAll(`.msg-bot[data-agent="${CSS.escape(ev.agent)}"]`)].filter(m => m !== bubble);
        const foot = done.length && $(".bot-foot", done[done.length - 1]);
        if (foot && !$(".paid-chip", foot)) {
          const chip = document.createElement("span");
          chip.className = "paid-chip" + (ev.cents >= 75 ? " rich" : ev.cents < 30 ? " thin" : "");
          chip.title = `The Treasurer paid ${ev.agent} ${ev.dollars}: ${ev.why}`;
          chip.textContent = `+${ev.dollars} · ${ev.why.split(",")[0]}`;
          foot.insertBefore(chip, $(".copy", foot));
        }
        const ag = (STATE.agents || []).find(x => x.name === ev.agent);
        if (ag) { ag.purse = (ag.purse || 0) + ev.cents; renderAgents(); }
      } else if (ev.type === "note") {
        addEl("note").textContent = ev.text;
      } else if (ev.type === "error") {
        thinking?.remove(); thinking = null;
        addEl("note").textContent = ev.text;
      } else if (ev.type === "done") {
        STATE.agentMode = ev.agentMode;
      }
    });
  } catch (e) {
    addEl("note").textContent = "Lost the connection: " + e.message;
  } finally {
    thinking?.remove();
    if (frame) { cancelAnimationFrame(frame); paint(); }
    if (bubble && !bubble.classList.contains("done")) finishBubble(bubble, raw, clock());
    busy = false;
    $("#sendBtn").disabled = false;
    $("#input").focus();
  }
}

async function command(line) {
  busy = true;
  addEl("msg-user").textContent = line;
  const t = thinkingEl("hippocampus");
  try {
    const r = await api("/api/command", { line });
    t.remove();
    addEl("cmd-out").textContent = r.output;
    if (r.state) { STATE = r.state; renderAgents(); }
  } catch (e) {
    t.remove();
    addEl("note").textContent = e.message;
  } finally { busy = false; }
}

$("#composer").addEventListener("submit", e => {
  e.preventDefault();
  const v = $("#input").value;
  $("#input").value = "";
  autosize();
  send(v);
});
// ------------------------------------------------------------------ "/" command hints
const COMMANDS = [
  ["board", "the governance board: council, reef, purse, season"], ["pay", "every agent's purse and the last payments"],
  ["zero", "the Treasurer's moves: Z grow · E split · R credit · O deduct"], ["orez", "undo the last Treasurer move"],
  ["spine", "the sealed journal of every payment"], ["change", "the coins and what a reply is worth"],
  ["treasury", "the ledger, the reef and the budget"], ["laws", "the shipwrecks in force (the RCSO)"],
  ["law", "throw a message in a bottle for the crew to vote on"], ["budget", "the marlin: your goals and their shares"],
  ["quarters", "the four seasons and their horsemen"], ["crew", "Bamba's crew"], ["council", "the council's votes and seats"],
  ["trident", "Poseidon's Trident: processing power and the work"], ["pockets", "the oil: ideas scrapped in past chats"],
  ["compass", "the NEWS and lightning on the instruments"], ["locker", "Davy Jones' Locker: the pulse and the hourglass"],
  ["trench", "the Mariana Trench: the undertow"], ["finetune", "the Ultimate model: plan · extract · outline · build"],
  ["lobes", "how the two lobes have voted"], ["help", "every command"],
];
const hints = document.createElement("ul");
hints.className = "cmd-hints"; hints.hidden = true; hints.setAttribute("role", "listbox");
$("#composer").appendChild(hints);
let hintAt = 0;
function showHints() {
  const v = $("#input").value;
  const m = /^\/(\w*)$/.exec(v);
  const found = m ? COMMANDS.filter(([c]) => c.startsWith(m[1].toLowerCase())).slice(0, 8) : [];
  hints.hidden = !found.length;
  hintAt = Math.min(hintAt, Math.max(0, found.length - 1));
  hints.innerHTML = found.map(([c, d], i) =>
    `<li role="option" data-cmd="${c}" class="${i === hintAt ? "on" : ""}"><b>/${c}</b><span>${esc(d)}</span></li>`).join("");
}
function takeHint(li) {
  if (!li) return false;
  $("#input").value = "/" + li.dataset.cmd + " ";
  hints.hidden = true; $("#input").focus();
  return true;
}
hints.addEventListener("mousedown", e => { e.preventDefault(); takeHint(e.target.closest("li")); });
$("#input").addEventListener("input", () => { hintAt = 0; showHints(); });
$("#input").addEventListener("blur", () => setTimeout(() => { hints.hidden = true; }, 120));
$("#input").addEventListener("keydown", e => {
  if (!hints.hidden) {
    const items = hints.querySelectorAll("li");
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      hintAt = (hintAt + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length;
      showHints(); return;
    }
    if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey && /^\/\w*$/.test($("#input").value) &&
        !COMMANDS.some(([c]) => "/" + c === $("#input").value))) {
      if (takeHint(items[hintAt])) { e.preventDefault(); return; }
    }
    if (e.key === "Escape") { hints.hidden = true; return; }
  }
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); hints.hidden = true; $("#composer").requestSubmit(); }
});
function autosize() { const t = $("#input"); t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 200) + "px"; }
$("#input").addEventListener("input", autosize);

$("#endChat").addEventListener("click", async () => {
  if (busy) return;
  busy = true;
  const t = thinkingEl("hippocampus");
  $("span:nth-child(2)", t).textContent = "Seahorse is reflecting on this chat";
  try {
    const r = await api("/api/end", {});
    t.remove();
    addEl("cmd-out").textContent = r.output;
    if (r.state) { STATE = r.state; }
    addEl("note").textContent = STATE.character.enabled ? STATE.character.farewell : "Chat saved.";
  } catch (e) { t.remove(); toast(e.message); }
  finally { busy = false; }
});

// ------------------------------------------------------------------ images
let ENGINES = [];
async function loadImages() {
  try {
    const r = await api("/api/images");
    ENGINES = r.engines;
    const sel = $("#engine");
    const current = sel.value;
    sel.innerHTML = "";
    for (const e of ENGINES) {
      const o = document.createElement("option");
      o.value = e.id;
      o.textContent = e.name + (e.available ? "" : " (not running)");
      o.disabled = !e.available;
      sel.appendChild(o);
    }
    const firstOn = ENGINES.find(e => e.available);
    sel.value = (current && ENGINES.find(e => e.id === current && e.available)) ? current : (firstOn ? firstOn.id : "");
    fillModels();
    $("#engineHint").textContent = firstOn ? "" :
      "No image engine is running yet. Start Stable Diffusion WebUI with --api (port 7860) or ComfyUI (port 8188), " +
      "or run: pip install diffusers torch transformers accelerate";
    $("#genBtn").disabled = !firstOn;
    renderGallery(r.images);
  } catch (e) { toast(e.message); }
}
function fillModels() {
  const e = ENGINES.find(x => x.id === $("#engine").value);
  const sel = $("#model");
  sel.innerHTML = "";
  for (const m of (e?.models || [])) {
    const o = document.createElement("option");
    o.value = m; o.textContent = m.length > 42 ? m.slice(0, 40) + "…" : m;
    sel.appendChild(o);
  }
  if (e?.id === "diffusers") { $("#steps").value = 4; $("#cfg").value = 0; syncSliders(); }
}
$("#engine").addEventListener("change", fillModels);
function syncSliders() { $("#stepsVal").textContent = $("#steps").value; $("#cfgVal").textContent = $("#cfg").value; }
$("#steps").addEventListener("input", syncSliders);
$("#cfg").addEventListener("input", syncSliders);

function renderGallery(items) {
  const g = $("#gallery");
  g.innerHTML = items.length ? "" : `<p class="muted small">Nothing yet.</p>`;
  for (const it of items) {
    const b = document.createElement("button");
    b.title = it.prompt;
    b.innerHTML = `<img alt="" loading="lazy" src="/images/${encodeURIComponent(it.file)}">`;
    b.addEventListener("click", () => showImage(it, true));
    g.appendChild(b);
  }
}

function showImage(meta, loadSettings) {
  const p = $("#preview");
  p.innerHTML = `<div><img alt="${esc(meta.prompt)}" src="/images/${encodeURIComponent(meta.file)}">` +
    `<div class="meta">${esc(meta.engine)} · ${meta.width}×${meta.height} · ${meta.steps} steps · seed ${meta.seed} · ${meta.seconds}s</div></div>`;
  if (loadSettings) {
    $("#prompt").value = meta.prompt;
    $("#negative").value = meta.negative || "";
    $("#seed").value = meta.seed;
  }
}

function busyButton(btn, label) {
  const old = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="bob">${glyph("seahorse", 15)}</span> ${esc(label)}`;
  return () => { btn.disabled = false; btn.innerHTML = old; };
}

$("#improveBtn").addEventListener("click", async () => {
  if (!$("#prompt").value.trim()) return toast("Write a prompt first");
  const done = busyButton($("#improveBtn"), "Seahorse is thinking");
  try {
    const r = await api("/api/images/improve", { prompt: $("#prompt").value });
    $("#prompt").value = r.prompt;
    if (r.negative) $("#negative").value = r.negative;
    if (r.note) toast(r.note);
  } catch (e) { toast(e.message); } finally { done(); }
});

$("#portraitBtn").addEventListener("click", async () => {
  const done = busyButton($("#portraitBtn"), "reading the 11 steps");
  try {
    const r = await api("/api/images/portrait", {});
    $("#prompt").value = r.prompt;
    $("#negative").value = r.negative || "";
    $("#size").value = "640x896";
    const ol = $("#portraitSteps");
    ol.innerHTML = (r.steps || []).map(s => `<li>${esc(s)}</li>`).join("");
    ol.classList.remove("hidden");
    toast(r.source === "seahorse" ? "Seahorse wrote a portrait prompt from all 11 steps" : "Built a portrait prompt from the 11 steps");
  } catch (e) { toast(e.message); } finally { done(); }
});

$("#imgForm").addEventListener("submit", async e => {
  e.preventDefault();
  const [w, h] = $("#size").value.split("x").map(Number);
  const done = busyButton($("#genBtn"), "painting…");
  $("#preview").innerHTML = `<div class="empty"><span class="big-mark bob">${glyph("porthole", 56)}</span><p>Painting on your machine…</p></div>`;
  try {
    const meta = await api("/api/images/generate", {
      prompt: $("#prompt").value, negative: $("#negative").value, width: w, height: h,
      steps: +$("#steps").value, cfg: +$("#cfg").value, seed: +$("#seed").value,
      engine: $("#engine").value, model: $("#model").value,
    });
    showImage(meta, false);
    loadImages();
  } catch (err) {
    $("#preview").innerHTML = `<div class="empty"><span class="big-mark">${glyph("porthole", 56)}</span><p>${esc(err.message)}</p></div>`;
  } finally { done(); }
});

// ------------------------------------------------------------------ start
(async () => {
  try {
    await loadState();
  } catch (e) {
    toast("Couldn't reach Seahorse: " + e.message, 8000);
  }
  syncSliders();
  loadEnv();
})();

$("#messages").addEventListener("scroll", () => { FOLLOW = nearBottom(); $("#jump")?.classList.toggle("show", !FOLLOW); });
$("#jump")?.addEventListener("click", () => toBottom(true));
