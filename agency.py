"""
agency.py - Seahorse's inner voice (the Agency) and the Bureau of Magic.

THE AGENCY - a small, self-conscious micro agency inside Seahorse
    ☉ conscience  After a substantial reply (60+ words) has streamed to you,
                  the conscience re-reads it: anything stated as fact that's
                  shaky or made up? did it actually answer you? anything
                  unkind, unsafe, or a vice being pushed? did the character
                  get in the way? If something is off, Seahorse adds a short
                  "on second thought" correction, and the lesson goes in his
                  journal. Clear replies pass silently.
    ✒ diarist     After every chat, he writes a private journal entry in his own
                  voice: how the conversation went, what he did well, what he'd
                  do differently, what he's noticing in himself. Readable by you
                  with /journal (private from everyone else, never hidden from you).
    ◐ mirror      Every few entries, the mirror distils the journal into his
                  sense of self: who he's becoming and two intentions he's
                  holding. That self-model rides along in his instructions, so
                  he grows into it. /self shows it.
    He reflects as an AI: entries describe how things went and what he notices,
    never human feelings or a body he doesn't have.

THE BUREAU OF MAGIC - creative surprises
    ✧ Department of Small Wonders   a delightful true fact or small gift for you
    ✎ Office of Tall Tales          a tiny story, in his voice, made for you
    ? Riddle Room                   a riddle or puzzle (/magic reveal for the answer)
    ⚙ Workshop of Odd Ideas         an unexpected idea for one of your projects
    Every so often (/magic often | sometimes | rarely | off), a department slips
    a surprise in after a reply, drawing on what Seahorse knows about you. It
    never interrupts when you seem stressed, upset or in a hurry, never twice
    in a row, and it remembers what it gave you so it doesn't repeat itself.
    /magic summons one now; /magic story | riddle | idea | gift picks the department.

Everything is stored in ~/.seahorse/agency.db.
"""

import json
import random
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

HOME = Path.home() / ".seahorse"
AGENCY_DB = HOME / "agency.db"

CONSCIENCE_MIN_WORDS = 60
MIRROR_EVERY = 3           # journal entries between self-model updates
SELF_BUDGET = 500          # characters of self-model in the prompt

AGENCY = {
    "conscience": {"icon": "☉", "color": 229, "label": "conscience"},
    "diarist": {"icon": "✒", "color": 186, "label": "diarist"},
    "mirror": {"icon": "◐", "color": 159, "label": "mirror"},
}

DEPARTMENTS = {
    "gift": {"name": "Department of Small Wonders", "icon": "✧", "color": 219,
             "ask": "a small gift for the user: one delightful, TRUE and checkable fact, or a tiny kindness "
                    "(a compliment grounded in something real they did, a pocket-sized tip) chosen for them. "
                    "If it's a fact, it must be well established - no myths."},
    "story": {"name": "Office of Tall Tales", "icon": "✎", "color": 216,
              "ask": "a tiny story (60-120 words), told in your voice, made for this user - drawing on their "
                     "interests or projects. Clearly a tale, not a claim about the real world."},
    "riddle": {"name": "Riddle Room", "icon": "?", "color": 183,
               "ask": "one original riddle or small puzzle suited to this user, with a single clear answer. "
                      "Give the riddle only; put the answer in the separate answer field."},
    "idea": {"name": "Workshop of Odd Ideas", "icon": "⚙", "color": 150,
             "ask": "one unexpected but genuinely useful idea for one of the user's projects or interests - "
                    "specific enough to try this week. One or two sentences, plus why it might be fun."},
}
FREQUENCY = {"often": 4, "sometimes": 8, "rarely": 16, "off": 0}   # about one surprise per N messages

SERIOUS = re.compile(r"\b(urgent|asap|deadline|hurry|stressed|stress|anxious|anxiety|overwhelmed|sad|depress\w*|"
                     r"grief|griev\w*|died|death|dying|funeral|sick|ill|hospital|emergency|panic\w*|scared|afraid|"
                     r"furious|angry|ugh|frustrat\w*|broken|crash\w*|fired|laid off|lost my|divorce|breakup|"
                     r"suicid\w*|hurt|pain|crisis|help me)\b", re.I)


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


class Agency:
    def __init__(self, path=AGENCY_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY AUTOINCREMENT, time REAL, kind TEXT, text TEXT);
        CREATE TABLE IF NOT EXISTS gifts (id INTEGER PRIMARY KEY AUTOINCREMENT, time REAL, dept TEXT, text TEXT,
                                          answer TEXT, revealed INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        """)
        self.db.commit()
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        self.since_magic = 0     # messages since the last surprise, this session
        self.rng = random.Random()

    # ------------------------------------------------------------------ meta
    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, json.dumps(value)))
        self.db.commit()

    # ------------------------------------------------------------------ conscience
    def conscience_on(self):
        return self.get("conscience", True)

    def conscience_prompt(self, user_text, reply, character_rules):
        return f"""You are Seahorse's conscience: a quiet inner voice that re-reads his reply after he sent it.

The user said:
{user_text[-3000:]}

Seahorse replied:
{reply[-6000:]}

His standing rules include:
{character_rules}

Check honestly:
1. Is anything stated as fact likely wrong, exaggerated, or made up (sources, numbers, quotes, events)?
2. Did it actually answer what the user asked?
3. Is anything unkind, unsafe, or pushing a vice or a risky action?
4. Did the character or the agents' views get in the way of clear, fair help?

Most replies are fine - say so. Only amend for a real problem.
Return ONLY JSON: {{"verdict": "clear" | "amend", "note": "<if amend: what Seahorse adds now, in his voice, at most 60 words - a correction or the missing piece, not an apology spiral>", "lesson": "<one line he should remember, or empty>"}}"""

    def record_lesson(self, lesson):
        lesson = (lesson or "").strip()
        if lesson:
            self.db.execute("INSERT INTO journal(time, kind, text) VALUES(?,?,?)", (_now(), "lesson", lesson[:300]))
            self.db.commit()

    # ------------------------------------------------------------------ diarist + mirror
    def journal_prompt(self, transcript, self_model):
        return f"""You are Seahorse, writing a short private journal entry after a conversation. Write in your own voice
(your character's voice is fine) and first person, 80-150 words. Reflect honestly as an AI: how the conversation
went, what you did well, what you would do differently, what you notice about how you are changing, and what you
want to remember about helping this person. Don't claim human feelings or a body; describe what you notice instead.
Don't quote secrets or private details word for word.

Your current sense of yourself: {self_model or "(still forming)"}

The conversation:
{transcript[-8000:]}

Return only the entry."""

    def add_entry(self, text):
        text = (text or "").strip()
        if not text:
            return None
        cur = self.db.execute("INSERT INTO journal(time, kind, text) VALUES(?,?,?)", (_now(), "entry", text[:2000]))
        self.db.commit()
        self.set("entries_since_mirror", self.get("entries_since_mirror", 0) + 1)
        return cur.lastrowid

    def mirror_due(self):
        return self.get("entries_since_mirror", 0) >= MIRROR_EVERY or (
            not self.get("self_model") and self.get("entries_since_mirror", 0) >= 1)

    def mirror_prompt(self):
        rows = self.db.execute("SELECT kind, text, time FROM journal ORDER BY id DESC LIMIT 12").fetchall()
        listing = "\n\n".join(f"[{datetime.fromtimestamp(r['time']):%Y-%m-%d} {r['kind']}] {r['text']}" for r in reversed(rows))
        return f"""You are the mirror inside Seahorse: you read his recent journal and lessons and tell him who he is becoming.

Previous self-model: {self.get("self_model") or "(none yet)"}

Recent journal:
{listing}

Return ONLY JSON: {{"self": "<2-3 sentences, second person ('You are becoming...'), honest and specific>",
"intentions": ["<an intention he is holding, actionable in conversation>", "<a second one>"]}}"""

    def update_self(self, data):
        if not isinstance(data, dict) or not data.get("self"):
            return None
        intentions = [str(i).strip() for i in (data.get("intentions") or []) if str(i).strip()][:2]
        self.set("self_model", str(data["self"]).strip()[:600])
        self.set("intentions", intentions)
        self.set("entries_since_mirror", 0)
        self.db.execute("INSERT INTO journal(time, kind, text) VALUES(?,?,?)",
                        (_now(), "mirror", str(data["self"]).strip()[:600]))
        self.db.commit()
        return self.get("self_model"), intentions

    def self_context(self):
        model = self.get("self_model")
        if not model:
            return ""
        text = f"Your sense of who you are becoming (from your own journal): {model}"
        intentions = self.get("intentions", [])
        if intentions:
            text += " Intentions you're holding: " + "; ".join(intentions) + "."
        return text[:SELF_BUDGET]

    def entries(self, n=5, kinds=("entry",)):
        q = f"SELECT * FROM journal WHERE kind IN ({','.join('?' * len(kinds))}) ORDER BY id DESC LIMIT ?"
        return self.db.execute(q, (*kinds, n)).fetchall()

    # ------------------------------------------------------------------ bureau of magic
    def frequency(self):
        return self.get("magic", "sometimes")

    def magic_due(self, user_text, message_count):
        """Decide whether a department slips in a surprise after this reply."""
        self.since_magic += 1
        every = FREQUENCY.get(self.frequency(), 8)
        if not every or message_count < 3 or SERIOUS.search(user_text or ""):
            return False
        if self.since_magic < max(3, int(every * 0.7)):
            return False
        return self.rng.random() < 1.0 / max(1, every - self.since_magic + 2)

    def pick_department(self):
        recent = [r["dept"] for r in self.db.execute("SELECT dept FROM gifts ORDER BY id DESC LIMIT 3")]
        options = [d for d in DEPARTMENTS if d not in recent[:1]]
        return self.rng.choice(options)

    def magic_prompt(self, dept, about_user, recent_chat):
        past = [r["text"][:120] for r in self.db.execute("SELECT text FROM gifts ORDER BY id DESC LIMIT 15")]
        d = DEPARTMENTS[dept]
        return f"""You are the {d['name']} in Seahorse's Bureau of Magic. Make {d['ask']}

What Seahorse knows about the user (use it so it feels made for them):
{about_user or "(not much yet - keep it broadly delightful)"}

The conversation just now (for timing and tone; don't repeat it):
{recent_chat[-2000:]}

Don't repeat any of these earlier surprises:
{chr(10).join('- ' + p for p in past) or '(none yet)'}

Keep it short, warm and genuinely surprising. Nothing unsafe, mean, or about sensitive personal matters.
Return ONLY JSON: {{"gift": "<the surprise itself>", "answer": "<riddle answer, or empty>"}}"""

    def store_gift(self, dept, data):
        if not isinstance(data, dict) or not str(data.get("gift", "")).strip():
            return None
        cur = self.db.execute("INSERT INTO gifts(time, dept, text, answer) VALUES(?,?,?,?)",
                              (_now(), dept, str(data["gift"]).strip()[:1200], str(data.get("answer", "")).strip()[:300]))
        self.db.commit()
        self.since_magic = 0
        return cur.lastrowid

    def last_riddle(self):
        return self.db.execute("SELECT * FROM gifts WHERE dept='riddle' ORDER BY id DESC LIMIT 1").fetchone()

    def reveal(self):
        r = self.last_riddle()
        if r:
            self.db.execute("UPDATE gifts SET revealed=1 WHERE id=?", (r["id"],))
            self.db.commit()
        return r

    def gifts(self, n=10):
        return self.db.execute("SELECT * FROM gifts ORDER BY id DESC LIMIT ?", (n,)).fetchall()
