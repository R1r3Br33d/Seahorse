#!/usr/bin/env python3
"""
cortex.py - how Seahorse's agents perceive, take notes, and grow together.

Every agent has a PURPOSE (what it is for) and a PROCESSING SKILL (the one
way it reads every message). All seven agents read every message you send,
each through its own lens, and file what they notice into their own
notebook. A notebook is a tree:

    agent  (agent colour)
    ├── category  (its own colour label, e.g. parietal › numbers)
    │   ├── topic
    │   │   └── note  (×count, weight)

    hippocampus  episodic binding      people · time · events · themes
    broca        language production   tone · style · wording · clarity
    parietal     quantity and logic    numbers · measures · comparisons · logic
    cerebellum   procedure and systems systems · tools · procedures · problems
    wernicke     comprehension         intent · concepts · knowledge gaps · questions
    prefrontal   executive control     goals · decisions · priorities · next steps
    cingulate    error detection       corrections · risks · contradictions · unresolved

Notes come from three places
    1. PERCEPTION - instant, as you type. Each lens has pattern detectors
       (numbers and units for parietal, corrections for cingulate, goals
       for prefrontal...). No model call, so it costs nothing.
    2. REFLECTION - after each chat, one model call asks every lens what it
       understood from the whole conversation, deeper than patterns can.
    3. REINFORCEMENT - noticing the same thing again strengthens the note
       instead of duplicating it. Every chat all notes fade a little
       (x0.97), so stale observations sink and recurring ones rise.

The collective summarization tree ("dreaming")
    Every few chats (or /dream) Seahorse summarizes bottom-up:
        notes      -> branch summary   (per agent and category)
        branches   -> agent summary    (what this agent has learned)
        agents     -> collective root  (what Seahorse as a whole understands)
    Only branches whose notes changed are re-summarized. Without a model the
    tree is still built from the strongest notes.

Self-development
    At the root, Seahorse reviews itself and proposes:
        technique  a concrete practice for one agent ("broca: offer a
                   two-line version first"). Up to 3 per agent go on TRIAL
                   at once and are added to that agent's instructions.
                   At each later dream every trial is reviewed against what
                   the agents noticed since (especially cingulate's
                   corrections) and is ADOPTED or DROPPED.
        trait      nudge a personality target by 0.05 (bounded 0.2-0.95),
                   applied automatically and shown to you; /rollback undoes.
        question   something it would like to learn about you; the
                   hippocampus asks when the moment is natural (one at a
                   time, retired after 3 chats).
        skill      an idea for a new skill   - proposed; /adopt drafts it
        agent      an idea for a new agent   - proposed; /adopt drafts it
        direction  a longer-term growth direction, kept at the root.

Everything lives in ~/.seahorse/cortex.db.
"""

import difflib
import json
import re
import time
from pathlib import Path

from memory import contains_secret

HOME = Path.home() / ".seahorse"
CORTEX_DB = HOME / "cortex.db"

NOTE_DECAY = 0.97
NOTE_REINFORCE = 0.3
NOTE_PRUNE = 0.08          # notes weaker than this are removed at a dream (the tree keeps their gist)
MAX_NOTES_PER_MESSAGE = 3  # per agent
DREAM_EVERY = 3            # chats between dreams
MAX_TRIALS_PER_AGENT = 3
QUESTION_LIFETIME = 3      # chats a question stays active
TRAIT_STEP = 0.05
CONTEXT_BUDGET = 900

I = re.IGNORECASE

# agent: purpose, processing skill, categories {name: (colour, what it holds, [patterns])}
LENSES = {
    "hippocampus": {
        "purpose": "Keep the thread of your life and our conversations: who, when, what happened, what keeps coming up.",
        "skill": "Episodic binding - links people, times and events into a timeline and spots recurring themes.",
        "categories": {
            "people": (209, "people in the user's life and how they relate",
                       [re.compile(r"\b(?i:my)\s+(?i:(wife|husband|partner|son|daughter|kids?|children|mom|mother|dad|"
                                   r"father|brother|sister|friend|boss|manager|colleague|coworker|team|dog|cat|puppy))"
                                   r"\b(?:\s+([A-Z][a-z]+))?")]),
            "time": (180, "dates, schedules and sequences",
                     [re.compile(r"\b(today|tonight|tomorrow|yesterday|next (?:week|month|year)|last (?:week|month|year)|"
                                 r"(?:mon|tues|wednes|thurs|fri|satur|sun)day|\d{4}-\d{2}-\d{2}|"
                                 r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{1,2})\b", I)]),
            "events": (173, "things that happened or will happen",
                       [re.compile(r"\b(happened|finished|started|launched|shipped|broke|moved|met|visited|attended|"
                                   r"celebrat\w+|graduat\w+|released)\b", I)]),
            "themes": (216, "topics that keep coming back", []),
        },
    },
    "broca": {
        "purpose": "Speak well: write and edit in a voice that fits you and the moment.",
        "skill": "Language production - reads tone, style, word choice and clarity to learn how the user communicates.",
        "categories": {
            "tone": (141, "emotional tone of the user's messages",
                     [(re.compile(r"\b(ugh|argh|annoying|frustrat\w*|sick of|wtf|damn)\b", I), "frustration"),
                      (re.compile(r"\b(thanks|thank you|thx|appreciate)\b", I), "gratitude"),
                      (re.compile(r"(!!|\b(awesome|amazing|love it|perfect|excited)\b)", I), "excitement"),
                      (re.compile(r"\b(please|could you|would you)\b", I), "politeness")]),
            "style": (183, "how the user writes", []),
            "wording": (147, "characteristic words and phrasing",
                        [(re.compile(r"\b(basically|literally|kinda|sorta|gonna|wanna|super)\b", I), "casual words")]),
            "clarity": (104, "where messages are vague or hedged",
                        [(re.compile(r"\b(it|this|that) (?:doesn'?t|isn'?t|won'?t) work\b", I), "vague problem report"),
                         (re.compile(r"\b(something like|sort of|i guess|i think maybe)\b", I), "hedged request")]),
        },
    },
    "parietal": {
        "purpose": "Get the numbers right and keep reasoning sound.",
        "skill": "Quantity and logic - extracts numbers, units, comparisons and if-then reasoning from everything.",
        "categories": {
            "numbers": (220, "figures the user mentions",
                        [re.compile(r"(?<![\w.$])(\$?\d{2,}[\d,]*(?:\.\d+)?)(?![\w.])")]),
            "measures": (186, "units, sizes, durations and money",
                         [re.compile(r"\b\d[\d,.]*\s*(%|percent|kb|mb|gb|tb|ms|seconds?|minutes?|hours?|days?|weeks?|"
                                     r"months?|years?|km|miles?|kg|lbs?|ghz|mhz|bytes?|bits?|dollars?|usd|eur)\b", I)]),
            "comparisons": (214, "trade-offs and comparisons",
                            [re.compile(r"\b(more than|less than|faster|slower|bigger|smaller|better|worse|versus|vs\.?|"
                                        r"compared to|cheaper|instead of)\b", I)]),
            "logic": (228, "conditions, causes and assumptions",
                      [re.compile(r"\b(if\b.{2,60}\bthen|because|therefore|unless|implies|assuming)\b", I)]),
        },
    },
    "cerebellum": {
        "purpose": "Do precise technical work: code, systems and procedures that run correctly.",
        "skill": "Procedure and systems - maps the tools, systems, steps and failures in the user's technical world.",
        "categories": {
            "systems": (79, "systems and components being built or used",
                        [re.compile(r"\b(kernel|bootloader|uefi|bios|filesystem|scheduler|driver|compiler|database|"
                                    r"server|api|frontend|backend|network|allocator|shell|operating system)\b", I)]),
            "tools": (115, "languages, tools and platforms",
                      [re.compile(r"\b(python|rust|zig|c\+\+|golang|javascript|typescript|java|bash|git|github|docker|"
                                  r"linux|fedora|ubuntu|arch|macos|windows|qemu|gcc|clang|llvm|cargo|npm|pip|ollama|"
                                  r"vim|neovim|vscode|sqlite|postgres|sympy|claude)\b", I),
                       re.compile(r"\b([\w-]+\.(?:py|rs|zig|c|h|cpp|js|ts|md|json|toml|ya?ml|sh|asm|ld))\b")]),
            "procedures": (72, "how-tos and processes",
                           [re.compile(r"\b(how (?:do|can|to) i|steps? to|install|set ?up|configure|compile|deploy|"
                                       r"migrate|debug)\b", I)]),
            "problems": (167, "errors, bugs and failures",
                         [re.compile(r"\b(error|bug|crash(?:es|ed)?|fails?|failing|broken|traceback|exception|segfault|"
                                     r"panic|doesn'?t (?:work|compile|boot))\b", I)]),
        },
    },
    "wernicke": {
        "purpose": "Understand what you really mean and help you understand in return.",
        "skill": "Comprehension - works out intent, the concepts in play, and gaps in the user's understanding.",
        "categories": {
            "intent": (117, "what the user is trying to do with each message",
                       [(re.compile(r"^\s*(what|how|why|when|where|who|which|can|could|should|is|are|do|does)\b", I),
                         "asks"),
                        (re.compile(r"^\s*(?:please\s+)?(build|make|create|write|add|fix|give|show|draft|explain|help|"
                                    r"name|color|colour|pair)\b", I), "requests")]),
            "concepts": (110, "ideas and names the user works with",
                         [re.compile(r"(?<=[a-z,] )([A-Z][a-zA-Z]{2,})\b")]),
            "knowledge gaps": (153, "things the user is still learning",
                               [re.compile(r"\b(don'?t (?:understand|get|know)|confus\w*|what does .{1,30} mean|new to|"
                                           r"never (?:used|done)|learning)\b", I)]),
            "questions": (75, "open questions", []),
        },
    },
    "prefrontal": {
        "purpose": "Keep you moving toward your goals: plan, decide, prioritise.",
        "skill": "Executive control - tracks goals, decisions, priorities and the next actions they imply.",
        "categories": {
            "goals": (213, "what the user wants to achieve",
                      [re.compile(r"\b(i want to|i'?d like to|i need to|my goal|i'?m trying to|i plan to|i'?m going to|"
                                  r"aim to|hoping to)\b", I)]),
            "decisions": (177, "choices made",
                          [re.compile(r"\b(decided|i'?ll go with|let'?s (?:use|go)|switched to|chose|picked|settled on)\b", I)]),
            "priorities": (205, "urgency and order",
                           [re.compile(r"\b(urgent|asap|priority|deadline|by (?:tomorrow|monday|tuesday|wednesday|thursday|"
                                       r"friday|next week)|top of my list)\b", I)]),
            "next steps": (219, "actions requested or planned",
                           [re.compile(r"^\s*(?:now\s+|next\s+|then\s+)?(build|make|create|add|name|colou?r|give|write|fix|"
                                       r"set up|pair|implement)\b", I)]),
        },
    },
    "cingulate": {
        "purpose": "Catch mistakes, including Seahorse's own, before they cost anything.",
        "skill": "Error detection - watches for corrections, risks, contradictions and things left unresolved.",
        "categories": {
            "corrections": (160, "times the user corrected Seahorse",
                            [(re.compile(r"\b(no,|nope|actually|that'?s (?:wrong|not right|incorrect)|not what i "
                                         r"(?:meant|asked)|you (?:misunderstood|got it wrong|forgot)|i said)\b", I),
                              "user correction")]),
            "risks": (196, "risky actions or data",
                      [re.compile(r"\b(risk|danger\w*|security|vulnerab\w*|delete|rm -rf|production|backup|data loss|"
                                  r"irreversible|overwrite)\b", I)]),
            "contradictions": (167, "things that don't add up",
                               [re.compile(r"\b(but (?:earlier|before|you said)|contradict\w*|inconsistent|doesn'?t match|"
                                           r"changed my mind)\b", I)]),
            "unresolved": (131, "problems still open",
                           [re.compile(r"\b(still (?:broken|not working|doesn'?t|fails|panics|crashes|hangs)|didn'?t work|not sure|unclear|stuck|"
                                       r"no idea)\b", I)]),
        },
    },
    "doc": {
        "purpose": "Know things properly: research, weigh the evidence and keep the facts straight.",
        "skill": "Scholarship - tracks the subjects you're curious about, the claims you make or meet, the sources "
                 "behind them, and the questions still open.",
        "categories": {
            "subjects": (151, "topics the user wants to understand",
                         [re.compile(r"\b(?:history of|origin of|how (?:does|do|did)|why (?:does|do|did|is|are)|"
                                     r"research(?:ing)?|learn(?:ing)? about|read(?:ing)? about|curious about)\s+([\w' -]{3,40})", I)]),
            "claims": (115, "facts asserted that may need checking",
                       [(re.compile(r"\b(is it true|true that|i heard|i read|apparently|they say|everyone knows|"
                                    r"studies show|science says|fact[- ]?check)\b", I), "claim to check")]),
            "sources": (108, "where information comes from",
                        [re.compile(r"\b(wikipedia|paper|study|journal|book|article|documentation|docs|manual|"
                                    r"textbook|encyclopedia|archive|record|source)\b", I)]),
            "open questions": (194, "questions worth researching further",
                               [(re.compile(r"\b(i wonder|nobody knows|no one knows|unsolved|mystery|still debated|"
                                            r"open question)\b", I), "open question")]),
        },
    },
    "judge": {
        "purpose": "Weigh things fairly: help you decide, and settle disputes on evidence.",
        "skill": "Judgment - notices the choices you face, what matters to you in making them, the decisions you "
                 "reach, and the disagreements that need settling.",
        "categories": {
            "dilemmas": (252, "choices the user is weighing",
                         [re.compile(r"\b(should i|which (?:is|one|option)|whether to|or should|torn between|"
                                     r"can'?t decide|thinking about (?:switching|moving|buying|quitting))\b", I)]),
            "criteria": (250, "what matters to the user when choosing",
                         [re.compile(r"\b(cheaper|faster|safer|simpler|easier|more reliable|matters (?:most|to me)|"
                                     r"priority|deal-?breaker|must have|nice to have|worth it)\b", I)]),
            "verdicts": (188, "decisions the user reached",
                         [re.compile(r"\b(i(?:'ll| will) go with|decided|going with|settled on|final answer|"
                                     r"made up my mind)\b", I)]),
            "disputes": (181, "disagreements to settle",
                         [re.compile(r"\b(who'?s right|argument|disagree\w*|debate|my (?:friend|partner|boss|wife|"
                                     r"husband) (?:says|thinks)|they claim|is it fair)\b", I)]),
        },
    },
    "fiery-black": {
        "purpose": "Keep you safe: find the weak spots in your code and systems before anyone else does.",
        "skill": "Threat sense - reads every message for exposed secrets, risky actions, attack surfaces and things "
                 "that need hardening.",
        "categories": {
            "threats": (202, "risks and attack paths mentioned",
                        [re.compile(r"\b(attack\w*|hack\w*|breach\w*|phish\w*|malware|virus|ransomware|exploit\w*|"
                                    r"vulnerab\w*|cve|injection|xss|csrf|ssrf|brute[- ]?force|ddos)\b", I)]),
            "weak spots": (166, "risky practices and exposed surfaces",
                           [re.compile(r"\b(chmod 777|sudo|as root|root access|disable[ds]? (?:the )?(?:firewall|auth|"
                                       r"ssl|tls|verification)|plain ?text|hard[- ]?coded|open port|public (?:bucket|repo)|"
                                       r"no password|default password|skip(?:ping)? (?:auth|validation))\b", I)]),
            "secrets": (196, "credentials that were exposed in chat (never the secret itself)", []),
            "hardening": (172, "defences in place or wanted",
                          [re.compile(r"\b(harden\w*|encrypt\w*|2fa|mfa|two[- ]factor|backup\w*|firewall|sandbox\w*|patch\w*|"
                                      r"update[sd]?|least privilege|permissions?|secure boot|signing|audit\w*|"
                                      r"password manager|vpn|tls|ssh key\w*)\b", I)]),
        },
    },
}

COMMON_CAPS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january",
               "february", "march", "april", "june", "july", "august", "september", "october", "november",
               "december", "the", "this", "that", "and", "but", "can", "please", "thanks", "okay"}

GENERIC_LENS = {"purpose": "", "skill": "General observation of anything relevant to its role.",
                "categories": {"observations": (250, "what this agent noticed", [])}}


def lens(agent):
    return LENSES.get(agent, GENERIC_LENS)


def category_color(agent, category):
    return lens(agent)["categories"].get(category, (250,))[0]


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def _snippet(sentence, limit=110):
    s = re.sub(r"\s+", " ", sentence).strip()
    return f'"{s[:limit]}{"..." if len(s) > limit else ""}"'


def _now():
    return time.time()


def _json(text):
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


class Cortex:
    def __init__(self, path=CORTEX_DB):
        import sqlite3
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT NOT NULL, category TEXT NOT NULL, topic TEXT NOT NULL, text TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 0.5, count INTEGER NOT NULL DEFAULT 1,
            source TEXT, created REAL NOT NULL, updated REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_notes_branch ON notes(agent, category);
        CREATE TABLE IF NOT EXISTS tree (
            level TEXT NOT NULL, agent TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '',
            summary TEXT, signature TEXT, updated REAL,
            PRIMARY KEY (level, agent, category));
        CREATE TABLE IF NOT EXISTS ideas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created REAL NOT NULL, kind TEXT NOT NULL, agent TEXT, title TEXT NOT NULL, detail TEXT,
            status TEXT NOT NULL, payload TEXT, reviews INTEGER NOT NULL DEFAULT 0, chats INTEGER NOT NULL DEFAULT 0,
            updated REAL);
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        """)
        self.db.commit()
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    # ------------------------------------------------------------------ meta
    def get_meta(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_meta(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, json.dumps(value)))
        self.db.commit()

    # ------------------------------------------------------------------ notes
    def add_note(self, agent, category, topic, text, source="perception", weight=0.5):
        topic = re.sub(r"\s+", " ", str(topic or category)).strip().lower()[:60] or category
        text = re.sub(r"\s+", " ", str(text or "")).strip()[:300]
        if contains_secret(text) or contains_secret(topic):  # notebooks never keep credentials
            text = "[redacted - the original looked like a password, key or card number]"
            topic = "redacted" if contains_secret(topic) else topic
        if not text:
            return None
        now = _now()
        rows = self.db.execute("SELECT * FROM notes WHERE agent=? AND category=? AND topic=?",
                               (agent, category, topic)).fetchall()
        for r in rows:
            if difflib.SequenceMatcher(None, r["text"].lower(), text.lower()).ratio() >= 0.8:
                self.db.execute("UPDATE notes SET count=count+1, weight=MIN(1.0, weight+?), updated=?, text=? "
                                "WHERE id=?", (NOTE_REINFORCE, now, text, r["id"]))
                self.db.commit()
                return r["id"]
        cur = self.db.execute("INSERT INTO notes(agent, category, topic, text, weight, source, created, updated) "
                              "VALUES(?,?,?,?,?,?,?,?)", (agent, category, topic, text, weight, source, now, now))
        self.db.commit()
        return cur.lastrowid

    def perceive(self, text, agents=None, previous_agent=None):
        """Every lens reads the message. Stores notes; returns {agent: [(category, topic)]}."""
        found = {}
        names = agents or list(LENSES)
        sentences = _sentences(text)
        for agent in names:
            spec = lens(agent)
            hits = []
            for cat, (_color, _desc, patterns) in spec["categories"].items():
                for pat in patterns:
                    regex, fixed = pat if isinstance(pat, tuple) else (pat, None)
                    for s in sentences:
                        m = regex.search(s)
                        if not m:
                            continue
                        groups = [g for g in m.groups() if g] if m.groups() else []
                        topic = fixed or (groups[-1] if groups else m.group(0))
                        if agent == "wernicke" and cat == "concepts" and topic.lower() in COMMON_CAPS:
                            continue
                        note = _snippet(s)
                        if agent == "cingulate" and cat == "corrections" and previous_agent:
                            note += f" (after {previous_agent}'s reply)"
                        hits.append((cat, topic, note))
                        break
            hits += self._special(agent, text, sentences)
            seen, kept = set(), []
            for cat, topic, note in hits:
                if (cat, topic.lower()) in seen:
                    continue
                seen.add((cat, topic.lower()))
                kept.append((cat, topic, note))
                if len(kept) >= MAX_NOTES_PER_MESSAGE:
                    break
            for cat, topic, note in kept:
                self.add_note(agent, cat, topic, note, "perception", 0.4)
            if kept:
                found[agent] = [(c, t) for c, t, _ in kept]
        return found

    @staticmethod
    def _special(agent, text, sentences):
        """Observations that aren't simple patterns."""
        out = []
        words = re.findall(r"\b\w+\b", text)
        if agent == "broca":
            if 0 < len(words) <= 8:
                out.append(("style", "short messages", "writes short, direct messages"))
            elif len(words) > 120:
                out.append(("style", "long messages", "writes long, detailed messages"))
            if len(text) > 20 and text == text.lower() and re.search(r"[a-z]", text):
                out.append(("style", "lowercase", "writes in all lowercase"))
            if "```" in text or re.search(r"^\s{4}\S", text, re.M):
                out.append(("style", "shares code", "pastes code into messages"))
        if agent == "fiery-black" and contains_secret(text):
            out.append(("secrets", "exposed credential",
                        "the user pasted something that looks like a password, key or card number - "
                        "remind them to rotate it"))
        if agent == "wernicke":
            for s in sentences:
                if s.endswith("?"):
                    out.append(("questions", "open question", _snippet(s)))
                    break
        return out

    def decay(self):
        self.db.execute("UPDATE notes SET weight = weight * ?", (NOTE_DECAY,))
        self.db.commit()

    def notebook(self, agent):
        """{category: {topic: [note rows]}} strongest first."""
        tree = {}
        for r in self.db.execute("SELECT * FROM notes WHERE agent=? ORDER BY weight DESC, count DESC", (agent,)):
            tree.setdefault(r["category"], {}).setdefault(r["topic"], []).append(r)
        order = list(lens(agent)["categories"])
        return dict(sorted(tree.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 99))

    def note_counts(self):
        return {r[0]: r[1] for r in self.db.execute("SELECT agent, COUNT(*) FROM notes GROUP BY agent")}

    # ------------------------------------------------------------------ reflection (after each chat)
    def reflection_prompt(self, messages, agents):
        lines = []
        for m in messages:
            who = "USER" if m["role"] == "user" else (f"SEAHORSE ({m['agent']})" if m.get("agent") else "SEAHORSE")
            lines.append(f"{who}: {m['content'][:2500]}")
        transcript = "\n\n".join(lines)
        if len(transcript) > 10000:
            transcript = "...\n" + transcript[-10000:]
        specs = []
        for a in agents:
            spec = lens(a)
            cats = ", ".join(spec["categories"])
            specs.append(f"- {a}: {spec['skill']} Categories: {cats}.")
        return f"""Seahorse is one mind made of specialist agents. Each reads the same conversation through its own lens and keeps its own notes.

Agents and their lenses:
{chr(10).join(specs)}

Conversation:
{transcript}

For each agent, write up to 3 notes about what ITS lens reveals - about the user, their situation, how they communicate, or how well Seahorse helped. Notes should be specific and useful later, not restatements of the conversation. Skip an agent if its lens found nothing worth noting.

Return ONLY JSON:
{{"<agent>": [{{"category": "<one of that agent's categories>", "topic": "<2-4 words>", "note": "<one sentence>"}}]}}"""

    def apply_reflection(self, data, agents):
        added = {}
        if not isinstance(data, dict):
            return added
        for agent in agents:
            items = data.get(agent) or []
            cats = list(lens(agent)["categories"])
            for item in items[:4] if isinstance(items, list) else []:
                if not isinstance(item, dict) or not item.get("note"):
                    continue
                cat = str(item.get("category", "")).lower().strip()
                cat = cat if cat in cats else difflib.get_close_matches(cat, cats, 1, 0.5)[0] \
                    if difflib.get_close_matches(cat, cats, 1, 0.5) else cats[0]
                self.add_note(agent, cat, item.get("topic") or cat, item["note"], "reflection", 0.7)
                added[agent] = added.get(agent, 0) + 1
        return added

    def end_chat(self):
        """Called after each chat: fade notes, age trial questions, count toward the next dream."""
        self.decay()
        self.db.execute("UPDATE ideas SET chats=chats+1 WHERE status='trial'")
        self.db.execute("UPDATE ideas SET status='done', updated=? WHERE kind='question' AND status='trial' AND chats>=?",
                        (_now(), QUESTION_LIFETIME))
        self.db.commit()
        self.set_meta("chats_since_dream", self.get_meta("chats_since_dream", 0) + 1)

    def due_to_dream(self):
        return self.get_meta("chats_since_dream", 0) >= DREAM_EVERY and self.db.execute(
            "SELECT COUNT(*) FROM notes").fetchone()[0] > 0

    # ------------------------------------------------------------------ the summarization tree
    def node(self, level, agent="", category=""):
        return self.db.execute("SELECT * FROM tree WHERE level=? AND agent=? AND category=?",
                               (level, agent, category)).fetchone()

    def _set_node(self, level, agent, category, summary, signature=""):
        self.db.execute("INSERT OR REPLACE INTO tree(level, agent, category, summary, signature, updated) "
                        "VALUES(?,?,?,?,?,?)", (level, agent, category, (summary or "").strip()[:1200], signature, _now()))
        self.db.commit()

    @staticmethod
    def _signature(rows):
        return str(hash(tuple((r["id"], r["count"]) for r in rows)))

    @staticmethod
    def _extractive(rows, n=3):
        return "; ".join(r["text"].strip('"') for r in rows[:n])

    def dream(self, complete, agents, persona=None, on_step=None):
        """Build the tree bottom-up and generate self-development ideas.

        complete(prompt, label) -> text or None. Returns a report dict.
        """
        report = {"branches": 0, "agents": [], "ideas": [], "reviews": [], "pruned": 0}
        agent_summaries = {}
        for agent in agents:
            book = self.notebook(agent)
            if not book:
                continue
            changed = {}
            for cat, topics in book.items():
                rows = sorted((r for notes in topics.values() for r in notes), key=lambda r: -r["weight"])
                sig = self._signature(rows)
                old = self.node("branch", agent, cat)
                if not old or old["signature"] != sig:
                    changed[cat] = rows[:25]
            old_agent = self.node("agent", agent)
            if not changed and old_agent:
                agent_summaries[agent] = old_agent["summary"]
                continue
            if on_step:
                on_step(agent)
            spec = lens(agent)
            listing = "\n".join(
                f"[{cat}]\n" + "\n".join(f"- ({r['topic']}, x{r['count']}) {r['text']}" for r in rows)
                for cat, rows in changed.items())
            prior = old_agent["summary"] if old_agent else "(none yet)"
            text = complete(f"""You are {agent}, one part of Seahorse's mind. Your purpose: {spec['purpose']}
Your processing skill: {spec['skill']}

Your previous overall understanding: {prior}

Your notes, by branch:
{listing}

Summarize each branch in 1-2 sentences that capture patterns (not a list of notes). Then write your updated overall understanding of the user and how to help them, from your lens, in 2-3 sentences.
Return ONLY JSON: {{"branches": {{"<branch>": "<summary>"}}, "summary": "<overall understanding>"}}""",
                            f"{agent} is dreaming")
            data = _json(text) or {}
            branch_sums = data.get("branches") if isinstance(data.get("branches"), dict) else {}
            for cat, rows in changed.items():
                summary = branch_sums.get(cat) or self._extractive(rows)
                self._set_node("branch", agent, cat, summary, self._signature(
                    sorted((r for n in book[cat].values() for r in n), key=lambda r: -r["weight"])))
                report["branches"] += 1
            agent_sum = data.get("summary") or "; ".join(
                (self.node("branch", agent, c) or {"summary": ""})["summary"] for c in book)[:600]
            self._set_node("agent", agent, "", agent_sum)
            agent_summaries[agent] = agent_sum
            report["agents"].append(agent)

        if not agent_summaries:
            return report

        trials = self.ideas(("trial",))
        trait_text = ""
        if persona is not None:
            trait_text = ", ".join(f"{n} {t['value']:.2f}->{t['target']:.2f}" for n, t in persona.traits.items())
        corrections = self.db.execute(
            "SELECT text FROM notes WHERE agent='cingulate' AND category='corrections' ORDER BY updated DESC LIMIT 6"
        ).fetchall()
        root_prior = (self.node("root") or {"summary": "(none yet)"})["summary"]
        if on_step:
            on_step("collective")
        text = complete(f"""You are Seahorse's whole mind, reviewing what each of your agents has learned, to understand the user better and to improve yourself.

Previous collective understanding: {root_prior}

Each agent's understanding:
{chr(10).join(f"- {a}: {s}" for a, s in agent_summaries.items())}

Personality traits (current -> target): {trait_text or "n/a"}
Recent times the user corrected you: {"; ".join(r[0] for r in corrections) or "none noted"}
Techniques currently on trial:
{chr(10).join(f"[{t['id']}] {t['agent']}: {t['detail']}" for t in trials) or "none"}

Return ONLY JSON:
{{"collective": "<3-5 sentences: who the user is, what they need, how Seahorse best helps them>",
  "directions": ["<a longer-term direction for Seahorse's growth>"],
  "ideas": [
    {{"kind": "technique", "agent": "<agent>", "title": "<short name>", "detail": "<one concrete instruction that agent will follow>"}},
    {{"kind": "trait", "trait": "<trait name>", "change": "+ or -", "title": "<short name>", "detail": "<why>"}},
    {{"kind": "question", "title": "<a question to ask the user to understand them better>", "detail": "<why it matters>"}},
    {{"kind": "skill", "title": "<new skill name>", "detail": "<what it would teach Seahorse>"}},
    {{"kind": "agent", "title": "<new agent, ideally named for a brain region>", "detail": "<its purpose and lens>"}}
  ],
  "reviews": [{{"id": <trial id>, "verdict": "keep or drop", "reason": "<evidence>"}}]}}
Rules: at most 5 ideas, only ones the notes really support; prefer techniques that fix observed problems (especially corrections). Up to 3 directions. Review every technique on trial: keep it if the notes since suggest it helps or there's no evidence against it, drop it if it caused problems.""",
                        "Seahorse is dreaming")
        data = _json(text) or {}
        collective = data.get("collective") or " ".join(f"{a}: {s}" for a, s in agent_summaries.items())[:900]
        self._set_node("root", "", "", collective)
        directions = [str(d) for d in (data.get("directions") or []) if d][:3]
        if directions:
            self._set_node("directions", "", "", json.dumps(directions))
        for rv in (data.get("reviews") or [])[:10]:
            try:
                idea = self.idea(int(rv.get("id")))
            except (TypeError, ValueError, AttributeError):
                continue
            if idea and idea["status"] == "trial" and idea["kind"] == "technique":
                verdict = "adopted" if str(rv.get("verdict", "")).lower().startswith("keep") else "dropped"
                self._set_status(idea["id"], verdict, reviews=idea["reviews"] + 1)
                report["reviews"].append((idea["id"], verdict, idea["agent"], idea["detail"], rv.get("reason", "")))
        for item in (data.get("ideas") or [])[:6]:
            made = self.add_idea(item, agents)
            if made:
                report["ideas"].append(made)
        report["pruned"] = self.db.execute("DELETE FROM notes WHERE weight < ?", (NOTE_PRUNE,)).rowcount
        self.db.commit()
        self.set_meta("chats_since_dream", 0)
        self.set_meta("last_dream", _now())
        self.set_meta("dreams", self.get_meta("dreams", 0) + 1)
        return report

    # ------------------------------------------------------------------ ideas
    def idea(self, idea_id):
        return self.db.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()

    def ideas(self, statuses=None):
        if statuses:
            q = f"SELECT * FROM ideas WHERE status IN ({','.join('?' * len(statuses))}) ORDER BY id"
            return self.db.execute(q, tuple(statuses)).fetchall()
        return self.db.execute("SELECT * FROM ideas ORDER BY id").fetchall()

    def _set_status(self, idea_id, status, reviews=None):
        if reviews is None:
            self.db.execute("UPDATE ideas SET status=?, updated=? WHERE id=?", (status, _now(), idea_id))
        else:
            self.db.execute("UPDATE ideas SET status=?, reviews=?, updated=? WHERE id=?",
                            (status, reviews, _now(), idea_id))
        self.db.commit()

    def add_idea(self, item, agents):
        """Store one idea and decide its starting status. Returns the stored row or None."""
        if not isinstance(item, dict):
            return None
        kind = str(item.get("kind", "")).lower()
        if kind not in ("technique", "trait", "question", "skill", "agent"):
            return None
        title = re.sub(r"\s+", " ", str(item.get("title") or item.get("detail") or "")).strip()[:120]
        detail = re.sub(r"\s+", " ", str(item.get("detail") or "")).strip()[:400]
        agent = str(item.get("agent", "")).lower() or None
        if kind == "technique" and agent not in agents:
            return None
        if not title:
            return None
        for old in self.db.execute("SELECT * FROM ideas WHERE kind=? AND status!='dropped'", (kind,)):
            if difflib.SequenceMatcher(None, (old["title"] + old["detail"]).lower(),
                                       (title + detail).lower()).ratio() > 0.75:
                return None  # already have this idea
        payload = {}
        status = "proposed"
        if kind == "technique":
            active = self.db.execute("SELECT COUNT(*) FROM ideas WHERE kind='technique' AND agent=? AND status IN "
                                     "('trial','adopted')", (agent,)).fetchone()[0]
            status = "trial" if active < MAX_TRIALS_PER_AGENT else "proposed"
        elif kind == "trait":
            payload = {"trait": str(item.get("trait", "")).lower(),
                       "change": "+" if str(item.get("change", "+")).strip().startswith("+") else "-"}
            status = "pending"  # applied by Seahorse (it owns the personality), then marked done
        elif kind == "question":
            active = self.db.execute("SELECT COUNT(*) FROM ideas WHERE kind='question' AND status='trial'").fetchone()[0]
            status = "trial" if active == 0 else "proposed"
        cur = self.db.execute("INSERT INTO ideas(created, kind, agent, title, detail, status, payload, updated) "
                              "VALUES(?,?,?,?,?,?,?,?)",
                              (_now(), kind, agent, title, detail, status, json.dumps(payload), _now()))
        self.db.commit()
        return self.idea(cur.lastrowid)

    def apply_trait_ideas(self, persona):
        """Nudge personality targets for pending trait ideas. Returns [(trait, old, new, reason)]."""
        done = []
        for idea in self.ideas(("pending",)):
            p = json.loads(idea["payload"] or "{}")
            name = persona.find_trait(p.get("trait", "")) if p.get("trait") else None
            if not name:
                self._set_status(idea["id"], "dropped")
                continue
            old = persona.traits[name]["target"]
            new = round(min(0.95, max(0.2, old + (TRAIT_STEP if p.get("change") == "+" else -TRAIT_STEP))), 3)
            if new != old:
                persona.set_target(name, new)
            self._set_status(idea["id"], "done")
            done.append((name, old, new, idea["detail"] or idea["title"]))
        return done

    def adopt(self, idea_id):
        idea = self.idea(idea_id)
        if not idea:
            return None
        status = "trial" if idea["kind"] in ("technique", "question") else "adopted"
        self._set_status(idea_id, status)
        return self.idea(idea_id)

    def drop(self, idea_id):
        idea = self.idea(idea_id)
        if idea:
            self._set_status(idea_id, "dropped")
        return idea

    def draft_prompt(self, idea, examples):
        """Prompt to draft a skill or agent file from an idea."""
        if idea["kind"] == "skill":
            return f"""Write a new skill file for Seahorse, a personal AI. Idea: {idea['title']} - {idea['detail']}

Use exactly this format (Markdown with a header), modelled on this example:
{examples}

Give it a short lowercase name, a description, mode: auto, and a triggers regex of words that signal the skill is needed. The body is clear, practical instructions Seahorse follows while the skill is active (15-40 lines). Return only the file."""
        return f"""Write a new agent file for Seahorse, a personal AI whose agents are named after brain regions. Idea: {idea['title']} - {idea['detail']}

Use exactly this format, modelled on this example:
{examples}

Name it after a fitting brain region (one lowercase word), include description, triggers (regex), skills (blank if none), traits (2-3 of: curiosity, warmth, playfulness, directness, concision, initiative, creativity, rigor, patience, with +/- offsets up to 0.2), color (a 0-255 terminal colour), backend: auto, persona: true. The body starts "You are <Name>, Seahorse's <role>." followed by 4-6 bullet points of how it works. Return only the file."""

    # ------------------------------------------------------------------ using what was learned
    def techniques_for(self, agent):
        return self.db.execute("SELECT * FROM ideas WHERE kind='technique' AND agent=? AND status IN ('trial','adopted') "
                               "ORDER BY status, id", (agent,)).fetchall()

    def active_question(self):
        return self.db.execute("SELECT * FROM ideas WHERE kind='question' AND status='trial' ORDER BY id LIMIT 1").fetchone()

    def context_for(self, agent):
        """This agent's lens, its own understanding, its techniques and the collective view."""
        spec = lens(agent)
        parts = []
        if spec.get("purpose"):
            parts.append(f"Your purpose: {spec['purpose']}\nYour processing skill: {spec['skill']}")
        mine = self.node("agent", agent)
        if mine and mine["summary"]:
            parts.append(f"What you have learned through your lens: {mine['summary']}")
        techs = self.techniques_for(agent)
        if techs:
            parts.append("Techniques you are practising (follow them):\n" +
                         "\n".join(f"- {t['detail'] or t['title']}" for t in techs))
        root = self.node("root")
        if root and root["summary"]:
            parts.append(f"What all of Seahorse has come to understand: {root['summary']}")
        if agent == "hippocampus":
            q = self.active_question()
            if q:
                parts.append(f"Something you'd like to learn about the user; ask only if it fits naturally: {q['title']}")
        text = "\n\n".join(parts)
        return text[:CONTEXT_BUDGET * 2] if agent == "hippocampus" else text[:CONTEXT_BUDGET * 2]

    def directions(self):
        node = self.node("directions")
        try:
            return json.loads(node["summary"]) if node else []
        except (TypeError, json.JSONDecodeError):
            return []

    def stats(self):
        return {
            "notes": self.db.execute("SELECT COUNT(*) FROM notes").fetchone()[0],
            "branches": self.db.execute("SELECT COUNT(*) FROM tree WHERE level='branch'").fetchone()[0],
            "dreams": self.get_meta("dreams", 0),
            "last_dream": self.get_meta("last_dream"),
            "chats_since_dream": self.get_meta("chats_since_dream", 0),
            "trials": len(self.ideas(("trial",))),
            "adopted": len(self.ideas(("adopted",))),
            "proposed": len(self.ideas(("proposed",))),
        }
