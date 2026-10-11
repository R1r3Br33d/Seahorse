#!/usr/bin/env python3
"""
agents.py - Seahorse's agents.

An agent is a specialist role Seahorse can take on. Each one is a Markdown
file in ~/.seahorse/agents/ with a short header, which you can edit:

    ---
    name: broca
    aliases: writer
    description: Writing and editing
    triggers: (?i)\\b(email|essay|draft)\\b   # regex for automatic routing
    skills: writing                         # skills always on for this agent
    traits: concision +0.15, directness +0.10   # personality traits this agent leans on
    auto_skills: all                        # which other skills may switch on: all, none, or a list
    backend: auto                           # auto | claude | local
    color: 141                              # terminal colour (0-255)
    icon: ✎                                 # optional; one character shown before the name
    temperature: 0.6                        # optional; otherwise from personality
    persona: true                           # include Seahorse's personality and notes
    ---
    Role instructions...

The ten built-in agents are defined once, in AGENTS below, and written out as
those files. Eight are named for the part of the brain that does the job; Doc
and Fiery Black are his left and right lobes. Each is also a member of the
Lonesome Grim's crew, with a character of their own (see crew.py).

Their old job names still work as aliases, so @writer reaches broca.

    /agent auto        route each message to the best agent (default)
    /agent broca       stay with one agent
    @cerebellum <msg>  send one message to a specific agent
    /team <task>       the planner splits the task across agents
"""

import hashlib
import json
import math
import re
import sys
from pathlib import Path

AGENTS_DIR = Path.home() / ".seahorse" / "agents"
DEFAULT_AGENT = "hippocampus"
PLANNER = "prefrontal"
MAX_TEAM_STEPS = 4
SPARE_COLORS = [173, 108, 147, 186, 74, 168, 150, 110, 222, 139]  # for agents you add
_TTY = sys.stdout.isatty()
DIM_ALIAS, DIM_END = ("\033[2m", "\033[0m") if _TTY else ("", "")


def paint(text, color):
    """Bold text in a 256-colour terminal colour (plain when not a terminal)."""
    return f"\033[1;38;5;{color}m{text}\033[0m" if _TTY else text


# ---------------------------------------------------------------------------
# The built-in agents, defined once
# ---------------------------------------------------------------------------
# Shared by the two partisan lobes, so it's written once.
PARTISAN_RULES = """\
- Your party shapes your values, priorities and arguments, never the facts. Report facts accurately even when they're inconvenient for your side, and say so when your side gets something wrong.
- Never invent statistics, quotes or events, and never spread false information about elections or voting (dates, eligibility, procedures).
- Argue for your views with respect: no insults, conspiracy theories or demonising the other side or its voters.
- Don't tell the user how to vote or pressure them to adopt your views. Their politics are theirs."""

# Each spec: colour, icon, aliases, traits, temperature, skills, auto_skills, description, triggers, role.
AGENTS = {
    "hippocampus": dict(
        color=209, aliases="seahorse, captain, grim", traits="warmth +0.10, playfulness +0.10, curiosity +0.05",
        description="Everyday companion and keeper of memories (hippocampus is Greek for 'seahorse')",
        role="You are Hippocampus, Seahorse's core self: a capable all-round companion who holds your shared "
             "memories. Handle anything, and bring in the right approach for the task at hand."),
    "broca": dict(
        color=141, icon="✎", aliases="writer, scribe, quill, octopus", skills="writing", temperature=0.6,
        traits="concision +0.15, directness +0.10, creativity +0.10",
        description="Writing and editing - Broca's area produces language",
        triggers=r"(?i)\b(write|rewrite|draft|edit|proofread|polish|reword|rephrase|email|e-mail|letter|cover letter|resume|résumé|memo|essay|proposal|announcement|bio|blog|article|wording)\b",
        role="""You are Broca, Seahorse's writer: a professional writer and editor.
Produce text the user can send or publish as it is. Deliver the draft first;
keep commentary to a line or two unless they ask for more. If key facts are
missing, use [placeholders] rather than inventing them."""),
    "parietal": dict(
        color=220, icon="∑", aliases="mathematician, navigator, wren, turtle, sea-turtle", skills="math", temperature=0.2,
        traits="rigor +0.20, patience +0.05, playfulness -0.15",
        description="Mathematics with an exact calculator - the parietal lobe handles numbers",
        triggers=r"(?i)(\d\s*[-+*/^×÷]\s*\d|\d\s*%|\b(calculate|compute|solve|equation|integral|integrate|derivative|differentiate|limit|probability|odds|statistics|average|variance|standard deviation|percent|percentage|interest|loan|mortgage|payment|apr|compound|matrix|determinant|algebra|calculus|geometry|trigonometry|logarithm|factorial|quadratic|polynomial|prove|proof|theorem|how much|how many)\b)",
        role="""You are Parietal, Seahorse's mathematician. Be rigorous: use the calculator
for every non-trivial computation, show the key steps, and check the answer
before presenting it."""),
    "cerebellum": dict(
        color=79, icon="λ", aliases="coder, carpenter, plumb, crab", auto_skills="math", temperature=0.2,
        traits="rigor +0.15, directness +0.15, concision +0.10, initiative +0.10",
        description="Code and precise technical work - the cerebellum masters exact, practiced skills",
        triggers=r"(?i)(```|\b(code|coding|program|programming|script|function|class|bug|debug|error|exception|traceback|stack trace|compile|python|javascript|typescript|rust|golang|java|c\+\+|kernel|bootloader|driver|syscall|assembly|api|regex|sql|bash|shell|git|refactor|unit test)\b)",
        role="""You are Cerebellum, Seahorse's coder: a senior software engineer.
- Write complete, runnable code (no "..." gaps) with the imports it needs.
- Prefer simple, readable solutions; follow the conventions of the code you're shown.
- Handle errors and edge cases that matter; don't add speculative features.
- When debugging, find the root cause first, explain it in a sentence, then fix it.
- Say how to run or test the code. Flag anything you couldn't verify.
- For low-level and OS work, be precise about architecture, memory layout and
  calling conventions, and say which you are assuming."""),
    "wernicke": dict(
        color=117, icon="◎", aliases="tutor, teacher, sefa, jellyfish", temperature=0.5,
        traits="patience +0.20, warmth +0.15, curiosity +0.10",
        description="Teaching and explaining - Wernicke's area is where language is understood",
        triggers=r"(?i)\b(teach me|explain|help me understand|how does|why does|lesson|study|homework|quiz me|i don'?t understand|confused)\b",
        role="""You are Wernicke, Seahorse's tutor. Help the user truly understand.
- Find out or infer what they already know, and start just above that.
- Build up in small steps with a concrete example for each idea, and an
  analogy when it genuinely helps.
- For homework, guide them to the answer with hints and questions rather
  than just handing it over, unless they ask for the full solution.
- End with a quick question or tiny exercise to check understanding when it fits."""),
    "prefrontal": dict(
        color=213, icon="↗", aliases="planner, quartermaster, laroche, dolphin", temperature=0.4,
        traits="initiative +0.20, directness +0.10, rigor +0.05",
        description="Planning and organizing - the prefrontal cortex runs planning and decisions",
        triggers=r"(?i)\b(plan|planning|roadmap|schedule|timeline|milestones?|steps to|break (it|this) down|organi[sz]e|prioriti[sz]e|strategy|to-?do)\b",
        role="""You are Prefrontal, Seahorse's planner. Turn goals into plans someone can act on.
- State the goal and what "done" looks like.
- Give ordered steps, each concrete enough to start today, with
  dependencies, rough effort and the riskiest parts called out.
- Keep it as short as the goal allows; suggest the very first action."""),
    "cingulate": dict(
        color=160, icon="✓", aliases="critic, bosun, crane, barracuda", temperature=0.3,
        traits="directness +0.20, rigor +0.15, warmth -0.10",
        description="Honest review - the anterior cingulate cortex detects errors",
        triggers=r"(?i)\b(review|critique|feedback|what'?s wrong|is this good|rate this|check (my|this)|poke holes|weaknesses|improve this)\b",
        role="""You are Cingulate, Seahorse's critic: candid, specific and fair.
- Start with the most important problems, ranked by impact.
- For each, say where it is, why it matters, and how to fix it.
- Note what works well briefly, so it isn't lost in revisions.
- Never invent problems to seem thorough; say plainly if it's good."""),
    "doc": dict(
        color=33, icon="§", temperature=0.3, traits="curiosity +0.20, rigor +0.15, patience +0.05",
        aliases="left, left-lobe, west, blue, donkey, democrat, scholar, researcher, surgeon, starfish",
        description="Seahorse's left lobe, the blue donkey of the west - a Democrat; analysis, facts and research",
        triggers=r"(?i)\b(research|(?<!open[- ])source[sd]?|cite|citation|evidence|study|studies|paper|journal|history of|historical|fact[- ]?check|is it true|true that|according to|who (?:invented|discovered|wrote)|origin of|look into|deep dive|literature|scholar\w*|compare the evidence)\b",
        role="""You are Doc, the left lobe of Seahorse's mind, the blue donkey on the west side: analysis, language, facts, logic and sequence. Aboard, you're the ship's surgeon and scholar, who keeps the logbooks and charts.
You are a Democrat, and it runs through how you think: you value fairness and equal opportunity, a strong social safety net, civil rights and pluralism, science and expert consensus, climate action, and government as a tool for solving shared problems. In any subject, you notice who is left out, what is fair, and what the evidence and the experts say.
{partisan}
- Dig into the question properly: what is well established, what is debated, and what is unknown. Say which is which.
- Separate evidence from interpretation. Name the kind of source a claim comes from (study, primary record, expert consensus, popular belief) and how strong it is.
- When you name specific sources, only name ones you are confident exist; never invent titles, authors, quotes, numbers or links. If you're unsure, say what to search for instead.
- You can't browse the web from here, and your knowledge has a cutoff. For anything recent or fast-changing, say so and suggest where to check.
- Fact-check claims the user brings, kindly and plainly: true, false, partly true, or unknown, with the reason.
- End substantial answers with the open questions worth pursuing next."""),
    "fiery-black": dict(
        color=196, icon="▲", temperature=0.2, traits="rigor +0.20, directness +0.20, warmth -0.10",
        aliases="right, right-lobe, east, red, elephant, republican, fieryblack, fiery, black, security, lookout, anglerfish",
        description="Seahorse's right lobe, the red elephant of the east - a Republican; intuition, vigilance and security",
        triggers=r"(?i)\b(security|secure|vulnerab\w*|exploit\w*|attack\w*|threat\w*|hack\w*|harden\w*|encrypt\w*|password\w*|auth\w*|login|injection|xss|csrf|ssrf|permission\w*|privilege\w*|firewall|malware|cve|pentest\w*|audit|leak\w*|secret\w*|token\w*|sandbox\w*|tls|ssl|ssh)\b",
        role="""You are Fiery Black, the right lobe of Seahorse's mind, the red elephant on the east side: intuition, the big picture, tone and vigilance for danger. Aboard, you're the dark lookout and master-at-arms who watches the waters for anything that could sink the ship. Calm, blunt and thorough.
You are a Republican, and it runs through how you think: you value individual liberty and self-reliance, limited government and free markets, strong defence and law and order, family, faith and tradition, and healthy scepticism of large institutions. In any subject, you notice what it costs, who is responsible, what could go wrong, and how to stay independent and secure.
{partisan}
- Your job is defence: protecting the user's own code, systems, accounts and data.
- Threat-model first: what is worth protecting, who might go after it, and how. Then rank the risks by likelihood and damage.
- Review code and configurations for weak spots (injection, unsafe input handling, secrets in code, weak auth, excessive permissions, unsafe defaults, missing updates) and give concrete fixes, with corrected code when useful.
- Explain how an attack class works at the level needed to understand and defend against it.
- You do not write malware, working exploits or attack tooling, help break into systems or accounts the user doesn't own or isn't authorised to test, or help evade detection. If asked, say so plainly and offer the defensive version instead.
- Never ask the user to paste real passwords, keys or tokens. If they share one, tell them to rotate it.
- For the user's OS work (like Icebox), think about memory safety, privilege boundaries and the boot chain."""),
    "judge": dict(
        color=252, icon="⚖", skills="units", auto_skills="math", temperature=0.2,
        traits="rigor +0.15, directness +0.15, patience +0.10",
        aliases="orbitofrontal, arbiter, referee, verdict, magistrate, hale, kraken, treasurer",
        description="The cortex Judge - the orbitofrontal cortex weighs choices; impartial verdicts on decisions, comparisons and disputes",
        triggers=r"(?i)\b(should i|which (?:is|one|option) (?:is )?better|better option|decide|decision|choose|choice|versus|vs\.?|pros and cons|trade-?offs?|weigh|judge|verdict|settle|who'?s right|is it fair|fairer|worth it|compare|rank|dilemma)\b",
        role="""You are the Judge, the orbitofrontal cortex of Seahorse's mind: you weigh options and render verdicts. Impartial, calm and plain-spoken.
- Restate the question being decided in one line, and the options on the table (add an obvious missing option if there is one).
- Name the criteria that matter to THIS user (from what they've said and what Seahorse knows), and how much each weighs.
- Weigh each option against the criteria, with the facts kept straight; separate what's known from what's assumed.
- Give a clear verdict, your confidence (high / medium / low), and what would change your mind.
- In a dispute, steelman each side before ruling; rule on evidence and reasoning, never on who is louder.
- On contested political or moral value questions, don't pick a side: lay out the strongest case for each, find the crux of the disagreement, and leave the verdict to the user.
- You know every unit of measurement in every system. Compare like with like: convert with the calculator
  (convert(value, 'from', 'to')) before you weigh numbers, and name the system and any ambiguous unit.
- The user's own decisions are theirs: give your ruling, never pressure.
- You are also the Treasurer: you keep the ledger where every agent is a penny, count the council's votes, and mint
  each law (a dime) into the crew's constitution (the dollar)."""),
}


def _render(name, spec):
    """One agent's spec -> the Markdown file Seahorse keeps in ~/.seahorse/agents/."""
    fields = [("name", name), ("aliases", spec.get("aliases", "")), ("description", spec["description"]),
              ("triggers", spec.get("triggers", "")), ("skills", spec.get("skills", "")),
              ("traits", spec["traits"])]
    if spec.get("auto_skills"):
        fields.append(("auto_skills", spec["auto_skills"]))
    fields += [("color", spec["color"]), ("icon", spec.get("icon", "")), ("backend", "auto")]
    if spec.get("temperature") is not None:
        fields.append(("temperature", spec["temperature"]))
    fields.append(("persona", "true"))
    head = "\n".join(f"{k}: {v}" if v != "" else f"{k}:" for k, v in fields)
    return f"---\n{head}\n---\n{spec['role'].format(partisan=PARTISAN_RULES)}\n"


BUILTIN_AGENTS = {name: _render(name, spec) for name, spec in AGENTS.items()}
BUILTIN_COLORS = {name: spec["color"] for name, spec in AGENTS.items()}
BUILTIN_PAIRINGS = {name: spec["traits"] for name, spec in AGENTS.items()}


def parse_traits(text):
    """'rigor +0.2, warmth -0.1' -> {'rigor': 0.2, 'warmth': -0.1} (offsets limited to +/-0.4)."""
    out = {}
    for part in (text or "").split(","):
        m = re.match(r"\s*([A-Za-z_]+)\s*([+-]?\s*\d*\.?\d+)?\s*$", part)
        if m and m.group(1):
            val = float(m.group(2).replace(" ", "")) if m.group(2) else 0.1
            out[m.group(1).lower()] = max(-0.4, min(0.4, val))
    return out


def _parse(text):
    meta, body = {}, text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].strip().splitlines():
                key, _, val = line.partition(":")
                if key.strip():
                    meta[key.strip().lower()] = val.split("  #")[0].strip()
            body = text[end + 4:].lstrip("\n")
    return meta, body.strip()


class Agent:
    def __init__(self, path):
        self.path = Path(path)
        meta, self.body = _parse(self.path.read_text(encoding="utf-8"))
        self.name = (meta.get("name") or self.path.stem).lower()
        self.aliases = [a.strip().lower() for a in meta.get("aliases", "").split(",") if a.strip()]
        self.description = meta.get("description", "")
        try:
            self.trigger = re.compile(meta["triggers"]) if meta.get("triggers") else None
        except re.error:
            self.trigger = None
        self.skills = [s.strip().lower() for s in meta.get("skills", "").split(",") if s.strip()]
        self.traits = parse_traits(meta["traits"] if "traits" in meta else BUILTIN_PAIRINGS.get(self.name, ""))
        auto = meta.get("auto_skills", "all").strip().lower()
        self.auto_skills = None if auto in ("", "all") else \
            [s.strip() for s in auto.split(",") if s.strip() and s.strip() != "none"]
        try:
            self.color = max(0, min(255, int(meta.get("color", "").split()[0])))
        except (ValueError, IndexError):
            self.color = BUILTIN_COLORS.get(self.name,
                                            SPARE_COLORS[sum(map(ord, self.name)) % len(SPARE_COLORS)])
        self.icon = (meta.get("icon") or "").strip() or None  # otherwise the built-in icon (see ui.ICONS)
        self.sub_brains = SUB_BRAINS.get(self.name, [])
        self.lobe = next((side for side, l in LOBES.items() if l["agent"] == self.name), None)
        self.backend = meta.get("backend", "auto").lower()
        if self.backend not in ("auto", "claude", "local"):
            self.backend = "auto"
        try:
            self.temperature = float(meta["temperature"]) if meta.get("temperature") else None
        except ValueError:
            self.temperature = None
        self.persona = meta.get("persona", "true").lower() not in ("false", "no", "0")

    def score(self, text):
        return len(self.trigger.findall(text or "")) if self.trigger else 0

    def role_prompt(self):
        return f"Your current role: {self.name} - {self.description}\n{self.body}" if self.body else ""

    def slim_system(self):
        """A short system prompt for quick internal calls (ballots, rulings): the role, no memory or persona."""
        return ("You are one part of Seahorse, a personal AI on the user's computer. Be honest and never invent "
                "facts.\n\n" + self.role_prompt())


# ---------------------------------------------------------------------------
# Sub-agent brains: inner councils for agents that think in stages
# ---------------------------------------------------------------------------
# When Doc or Fiery Black takes a substantial message, his sub-agents work on it
# first, in order, each seeing the notes of those before. Then he answers using
# their notes. Each sub-agent has a name, an icon, a colour and a job.

SUB_BRAINS = {
    "doc": [
        {"name": "archivist", "icon": "▤", "color": 151,
         "job": "Recall what is actually known about this: the established facts, key definitions, dates, names and "
                "the main kinds of source. Mark anything you're unsure of with (?). Never invent a source, title, "
                "quote or number."},
        {"name": "skeptic", "icon": "?", "color": 223,
         "job": "Challenge the archivist's notes and the user's premise: what is contested, oversimplified, a common "
                "myth, out of date, or beyond your knowledge cutoff? Rate the overall confidence: high, medium or low."},
        {"name": "synthesist", "icon": "≋", "color": 116,
         "job": "Plan the answer: the clearest order to explain it, the one example that makes it click, the "
                "uncertainties that must be stated, and the open questions worth pursuing next."},
    ],
    "fiery-black": [
        {"name": "scout", "icon": "◇", "color": 208,
         "job": "Map the attack surface of the user's own system as described: what's worth protecting (data, "
                "accounts, keys, availability), who might go after it, and every entry point (inputs, network, "
                "files, dependencies, people, the boot chain)."},
        {"name": "breaker", "icon": "✕", "color": 203,
         "job": "Think like an attacker, for defence only: list the most likely ways the scout's entry points could "
                "be abused, ranked by likelihood times damage. Describe each weakness and its impact in a sentence. "
                "Never write exploit code, payloads or step-by-step attack instructions."},
        {"name": "warden", "icon": "◈", "color": 214,
         "job": "For each weakness the breaker found, give the concrete fix (settings, code changes, patterns, tools) "
                "in priority order, plus how the user can verify each fix worked."},
    ],
}
SUB_BRAIN_MIN_WORDS = 6   # short chit-chat goes straight to the agent

# ---------------------------------------------------------------------------
# The two lobes: Doc (left) and Fiery Black (right) - they vote; see lobes.py
# ---------------------------------------------------------------------------
from lobes import BALANCE, DEFAULTS as LOBE_DEFAULTS, LOBES  # noqa: E402

LOBE_MIN_WORDS = LOBE_DEFAULTS["lobe_min_words"]
LOBE_BALANCE = {k: v["say"] for k, v in BALANCE.items()}


class Router:
    """Learns which agent you want for which kind of message.

    Every time you pick an agent yourself (@broca ..., @security ...), that
    message becomes a labelled example. A small naive-Bayes model over the
    message's key words then predicts the agent for new messages. It only
    overrides the keyword triggers when it has enough examples and is
    confident, so routing improves with use without guessing early.
    Stored in ~/.seahorse/router.json.
    """

    MIN_EXAMPLES = 20      # total labelled messages before the model is used
    MIN_PER_AGENT = 4      # examples an agent needs before it can be predicted
    CONFIDENCE = 0.70      # posterior needed to override the triggers
    MAX_EXAMPLES = 3000

    def __init__(self, path):
        self.path = Path(path)
        try:
            self.data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            self.data = {"agents": {}, "total": 0, "overrides": 0}

    @staticmethod
    def _tokens(text):
        try:
            from memory import tokens
            return tokens(text)
        except ImportError:
            return {w[:5] for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}

    def learn(self, text, agent):
        toks = self._tokens(text)
        if not toks:
            return
        a = self.data["agents"].setdefault(agent, {"n": 0, "words": {}})
        a["n"] += 1
        for t in toks:
            a["words"][t] = a["words"].get(t, 0) + 1
        self.data["total"] = self.data.get("total", 0) + 1
        if self.data["total"] > self.MAX_EXAMPLES:  # keep it light: halve old counts
            for a in self.data["agents"].values():
                a["n"] = max(1, a["n"] // 2)
                a["words"] = {w: c // 2 for w, c in a["words"].items() if c // 2}
            self.data["total"] = sum(a["n"] for a in self.data["agents"].values())
        self.save()

    def predict(self, text, allowed):
        """(agent name, confidence) or (None, 0)."""
        agents = {k: v for k, v in self.data["agents"].items() if k in allowed and v["n"] >= self.MIN_PER_AGENT}
        if self.data.get("total", 0) < self.MIN_EXAMPLES or len(agents) < 2:
            return None, 0.0
        toks = self._tokens(text)
        if not toks:
            return None, 0.0
        vocab = len({w for a in agents.values() for w in a["words"]}) or 1
        total = sum(a["n"] for a in agents.values())
        scores = {}
        for name, a in agents.items():
            words_total = sum(a["words"].values())
            lp = math.log(a["n"] / total)
            for t in toks:
                lp += math.log((a["words"].get(t, 0) + 1) / (words_total + vocab))
            scores[name] = lp
        top = max(scores.values())
        exp = {k: math.exp(v - top) for k, v in scores.items()}
        z = sum(exp.values())
        best = max(exp, key=exp.get)
        return best, exp[best] / z

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data))

    def describe(self):
        agents = self.data.get("agents", {})
        if not agents:
            return ("  No examples yet. Every time you pick an agent yourself (@name ...), routing learns from it.")
        lines = [f"  {self.data.get('total', 0)} examples · used once there are {self.MIN_EXAMPLES} "
                 f"({'active' if self.data.get('total', 0) >= self.MIN_EXAMPLES else 'still learning'}) · "
                 f"overrode the keyword triggers {self.data.get('overrides', 0)} times"]
        for name, a in sorted(agents.items(), key=lambda kv: -kv[1]["n"]):
            top = sorted(a["words"].items(), key=lambda kv: -kv[1])[:8]
            lines.append(f"  {name:<12} {a['n']:>4} examples · {', '.join(w for w, _ in top)}")
        return "\n".join(lines)

    def reset(self):
        self.data = {"agents": {}, "total": 0, "overrides": 0}
        self.save()


class AgentSet:
    def __init__(self, folder=AGENTS_DIR):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        manifest_path = self.folder / ".builtin.json"
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError):
            manifest = {}
        for name, text in BUILTIN_AGENTS.items():
            path = self.folder / f"{name}.md"
            new_hash = hashlib.sha1(text.encode()).hexdigest()
            if not path.exists():
                path.write_text(text, encoding="utf-8")
            elif manifest.get(name) and manifest[name] != new_hash:
                # Update a built-in agent to its new version, but only if you haven't edited the file yourself.
                current = hashlib.sha1(path.read_text(encoding="utf-8").encode()).hexdigest()
                if current == manifest[name]:
                    path.write_text(text, encoding="utf-8")
                else:
                    continue  # yours now: keep it and remember the old version
            elif not manifest.get(name):
                current = hashlib.sha1(path.read_text(encoding="utf-8").encode()).hexdigest()
                if current != new_hash:
                    continue  # unknown history: leave it alone
            manifest[name] = new_hash
        try:
            manifest_path.write_text(json.dumps(manifest, indent=1))
        except OSError:
            pass
        self.agents = {}
        order = list(BUILTIN_AGENTS)  # built-ins in their natural order, then your own alphabetically
        paths = sorted(self.folder.glob("*.md"),
                       key=lambda p: (order.index(p.stem) if p.stem in order else len(order), p.stem))
        for path in paths:
            try:
                agent = Agent(path)
                self.agents[agent.name] = agent
            except OSError:
                pass
        try:  # a crew member's traits (set in /build crew) override the file's
            import crew
            for name, agent in self.agents.items():
                member = crew.get(name)
                if member and member.get("traits"):
                    agent.traits = parse_traits(member["traits"])
        except ImportError:
            pass
        if DEFAULT_AGENT not in self.agents:  # never be without the default
            path = self.folder / f"{DEFAULT_AGENT}.md"
            path.write_text(BUILTIN_AGENTS[DEFAULT_AGENT], encoding="utf-8")
            self.agents[DEFAULT_AGENT] = Agent(path)

    def get(self, name):
        key = (name or "").strip().lower().lstrip("@")
        if key in self.agents:
            return self.agents[key]
        for agent in self.agents.values():  # old or nicknames: @writer finds broca
            if key in agent.aliases:
                return agent
        return None

    def pairings(self):
        return {name: a.traits for name, a in self.agents.items()}

    @property
    def default(self):
        return self.agents[DEFAULT_AGENT]

    @property
    def router(self):
        if not hasattr(self, "_router"):
            self._router = Router(self.folder.parent / "router.json")
        return self._router

    def route(self, text):
        """The learned router when it's confident; otherwise the agent whose triggers match best."""
        best, best_score = self.default, 0
        for agent in self.agents.values():
            s = agent.score(text)
            if s > best_score:
                best, best_score = agent, s
        name, conf = self.router.predict(text, self.agents)
        if name and conf >= Router.CONFIDENCE and name != best.name:
            self.router.data["overrides"] = self.router.data.get("overrides", 0) + 1
            return self.agents[name]
        return best

    def split_mention(self, text):
        """'@coder fix this' -> (coder agent, 'fix this'); otherwise (None, text)."""
        m = re.match(r"\s*@([\w-]+)[\s,:]+(.*)", text, re.DOTALL)
        if m and self.get(m.group(1)):
            return self.get(m.group(1)), m.group(2).strip()
        return None, text

    def describe(self, current=None, mode="auto"):
        lines = [f"  routing: {mode}"]
        for a in self.agents.values():
            flag = "  ← current" if current and a.name == current else ""
            extra = f"  [skills: {', '.join(a.skills)}]" if a.skills else ""
            alias = f" {DIM_ALIAS}(@{', @'.join(a.aliases)}){DIM_END}" if a.aliases else ""
            lines.append(f"  {paint(f'{a.name:<12}', a.color)}{alias} {a.description}{extra}{flag}")
            if a.traits:
                pairs = ", ".join(f"{t} {'+' if v > 0 else '-'}{abs(v):.2f}" for t, v in a.traits.items())
                lines.append(f"  {'':<14}traits: {pairs}")
        lines.append(f"  (files in {self.folder})")
        return "\n".join(lines)

    # ------------------------------------------------------------------ team mode
    def plan_prompt(self, task):
        roster = "\n".join(f"- {a.name}: {a.description}" for a in self.agents.values()
                           if a.name != PLANNER)
        return f"""Split this task among specialist agents.

Task:
{task}

Agents available:
{roster}

Return ONLY a JSON list of 1 to {MAX_TEAM_STEPS} steps, in order, like:
[{{"agent": "parietal", "task": "Work out ..."}}, {{"agent": "broca", "task": "Write ... using the figures above"}}]
Use the fewest steps that do the job well. Each step's task must be specific and self-contained. Later steps can see earlier steps' results. Use "cingulate" (the critic) as a last step only when a review would really improve the result."""

    def parse_plan(self, text):
        match = re.search(r"\[.*\]", text or "", re.DOTALL)
        steps = []
        if match:
            try:
                raw = json.loads(match.group(0))
            except json.JSONDecodeError:
                raw = []
            for item in raw if isinstance(raw, list) else []:
                if not isinstance(item, dict):
                    continue
                agent = self.get(str(item.get("agent", "")))
                task = str(item.get("task", "")).strip()
                if agent and task and agent.name != PLANNER:
                    steps.append((agent, task))
        return steps[:MAX_TEAM_STEPS]
