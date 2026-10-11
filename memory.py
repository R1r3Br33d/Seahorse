#!/usr/bin/env python3
"""
memory.py - Seahorse's memory.

Seahorse remembers the way people do, in three layers:

1. WORKING MEMORY - the conversation happening now.
   When a chat grows past what the model can hold (about 24,000 characters
   for an 8K local model, far more for Claude), the oldest part is condensed
   into a running summary and the recent messages are kept word for word.
   Nothing is lost from the saved chat; only what is sent to the model shrinks.

2. EPISODIC MEMORY - what happened in each conversation.
   After every chat Seahorse files an episode: a title, a short summary, the
   topics, which agents helped, and a link to the full transcript. Seahorse
   can recall past conversations by meaning ("what did we decide about the
   bootloader?") and always knows how the last conversation ended.

3. SEMANTIC MEMORY - lasting knowledge about you.
   Single facts, each in a category:
       profile      who you are (name, work, where you live)
       preference   how you like things done
       instruction  standing instructions for Seahorse ("always use metric")
       project      ongoing projects and their status
       goal         things you're working toward
       person       people in your life, as relationship context
       fact         other lasting facts
       event        dated happenings and plans (these expire)

How memories are made
    * You say "remember that ..." (or /remember): saved immediately.
    * After each chat Seahorse reviews the conversation and files new facts,
      corrects outdated ones and drops ones you've said are no longer true.
      It is shown its related existing memories first, so it updates instead
      of duplicating.
    * Near-duplicates are merged: saying something again reinforces the
      existing memory rather than adding a copy.
    * Anything that looks like a password, API key, card or social security
      number is never stored, even if asked.

How memories are recalled
    Before every reply Seahorse looks up what's relevant to your message:
        relevance = max(meaning match, keyword match)
            meaning match - cosine similarity of embeddings from a local
                            Ollama embedding model (nomic-embed-text), if you
                            have it; Seahorse works without it
            keyword match - share of your message's key words found in the
                            memory (SQLite full-text search finds candidates)
        score = 0.6 * relevance + 0.25 * strength + 0.1 if pinned
    The top matches, your standing instructions and profile, and recent
    episodes go into the prompt within a size budget. Being recalled counts as
    use, which keeps a memory strong.

How memories fade
        strength = 0.45 * importance/5 + 0.35 * recency + 0.20 * reinforcement
        recency  = 0.5 ** (days since last updated or used / half-life)
    Half-lives depend on the category (events 30 days, projects 120,
    preferences 240, profile 365, instructions ~10 years). Every few chats a
    consolidation pass archives memories whose strength fell below 0.25,
    expires old events, merges duplicates and fills in missing embeddings.
    Important memories (importance 3+) never fade below the threshold, and
    pinned memories never fade at all. Archived memories aren't deleted, so
    /restore brings them back.

Your control
    Everything is in one local SQLite file, ~/.seahorse/memory.db, readable
    only by you. Every change is written to an audit log saying what changed
    and why. You can list, search, edit, pin, forget, restore, export or wipe
    memories.

Run directly:
    python3 memory.py                 statistics
    python3 memory.py search <words>  search memories and episodes
    python3 memory.py export FILE.md  export everything as Markdown
"""

import array
import difflib
import json
import math
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

HOME = Path.home() / ".seahorse"
DB_PATH = HOME / "memory.db"
SCHEMA_VERSION = 1

# category: (what it holds, half-life in days)
CATEGORIES = {
    "instruction": ("Standing instructions for Seahorse", 3650),
    "profile": ("Who the user is", 365),
    "preference": ("How the user likes things done", 240),
    "person": ("People in the user's life", 365),
    "project": ("Ongoing projects and their status", 120),
    "goal": ("Things the user is working toward", 180),
    "fact": ("Other lasting facts", 180),
    "event": ("Dated happenings and plans", 30),
}
CORE_CATEGORIES = ("instruction", "profile")

# --- Tuning -------------------------------------------------------------------
RETRIEVE_K = 8              # relevant memories per reply
EPISODE_K = 2               # relevant past conversations per reply
CONTEXT_BUDGET = 2400       # characters of memory put into the prompt
MIN_RELEVANCE = 0.2         # below this a memory isn't "relevant"
ARCHIVE_STRENGTH = 0.25     # consolidation archives memories weaker than this
EVENT_EXPIRY_DAYS = 120     # events older than this are archived (unless important or pinned)
DUP_COSINE = 0.92           # embeddings this similar = same memory
DUP_RATIO = 0.85            # or text this similar
CONSOLIDATE_EVERY = 5       # chats between consolidation passes
MAX_ACTIVE = 600            # hard cap on active memories
MAX_TEXT = 300
EMBED_MODEL = os.environ.get("SEAHORSE_EMBED_MODEL", "nomic-embed-text")

STOPWORDS = set("""a about above after again all also am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further had has have
having he her here hers him his how i if in into is it its itself just let like me more most my myself no
nor not now of off on once only or other our ours out over own please same she should so some such than
that the their them then there these they this those through to too under until up very was we were what
when where which while who whom why will with would you your yours yourself seahorse user""".split())

# --- Secrets are never stored ---------------------------------------------------
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_SECRETS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # US social security number
    re.compile(r"\b(?:sk-(?:ant-)?[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}"
               r"|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,})\b"),
    re.compile(r"(?i)\b(password|passcode|passphrase|pin code|pin number|security code|cvv|cvc|"
               r"seed phrase|recovery phrase|private key|api key|secret key)\b\s*(is|was|:|=)"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


def _luhn(digits):
    total, alt = 0, False
    for d in reversed(digits):
        n = int(d)
        if alt:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
        alt = not alt
    return total % 10 == 0


def contains_secret(text):
    for m in _CARD.finditer(text or ""):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            return True
    return any(p.search(text or "") for p in _SECRETS)


# --- Small helpers --------------------------------------------------------------

def now_ts():
    return time.time()


def iso(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def friendly_now():
    d = datetime.now()
    hour = d.strftime("%I:%M %p").lstrip("0")
    return f"{d.strftime('%A, %B')} {d.day}, {d.year}, {hour}"


def clean_text(text):
    text = re.sub(r"\s+", " ", str(text or "")).strip().strip("-•* ")
    return text[:MAX_TEXT]


def tokens(text):
    """Key words, crudely stemmed to 5 letters so 'projects' matches 'project'."""
    return {w[:5] for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in STOPWORDS}


def keyword_relevance(query_tokens, text):
    if not query_tokens:
        return 0.0
    hit = len(query_tokens & tokens(text))
    return min(1.0, hit / min(len(query_tokens), 4))


def pack(vec):
    return array.array("f", vec).tobytes() if vec else None


def unpack(blob):
    if not blob:
        return None
    a = array.array("f")
    a.frombytes(blob)
    return a


def cosine(a, b):
    if a is None or b is None or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else None


def semantic_relevance(cos):
    return 0.0 if cos is None else max(0.0, min(1.0, (cos - 0.35) / 0.45))


def guess_category(text):
    t = text.lower().strip()
    if re.match(r"(always|never|don'?t ever|call me|when you|please (always|never)|from now on)", t):
        return "instruction"
    if re.match(r"(i (prefer|like|love|hate|dislike|enjoy|want)|i don'?t like|my favou?rite)", t):
        return "preference"
    if re.match(r"(my name|i am|i'm|i live|i work|i was born|i grew up|i study)", t):
        return "profile"
    if re.match(r"(my (wife|husband|partner|son|daughter|mom|mother|dad|father|brother|sister|friend|boss|"
                 r"colleague|dog|cat)\b)", t):
        return "person"
    if re.search(r"\b(tomorrow|next (week|month|year)|on (mon|tues|wednes|thurs|fri|satur|sun)day|"
                 r"appointment|meeting|deadline|due)\b", t):
        return "event"
    if re.match(r"(i'?m (building|making|working on|writing)|my project)", t):
        return "project"
    return "fact"


_REMEMBER = re.compile(r"^\s*(?:please\s+)?(?:remember|note|keep in mind|don'?t forget)\s*(?:that|:)?\s+(.{4,})$",
                       re.IGNORECASE | re.DOTALL)
_NOT_REMEMBER = re.compile(r"^\s*(?:do you\s+)?remember\s+(when|how|what|who|where|why|if|the time)\b", re.IGNORECASE)
_FORGET = re.compile(r"^\s*(?:please\s+)?forget\s+(?:that|about|the fact that)?\s*(.{3,})$", re.IGNORECASE | re.DOTALL)


def detect_memory_command(text):
    """'remember that I use Fedora' -> ('remember', 'I use Fedora'); 'forget my old address' -> ('forget', ...)."""
    t = (text or "").strip()
    if not t or t.endswith("?"):
        return None
    if _NOT_REMEMBER.match(t):
        return None
    m = _REMEMBER.match(t)
    if m:
        return "remember", m.group(1).strip().rstrip(".")
    m = _FORGET.match(t)
    if m and not re.match(r"(?i)\s*forget\s+(it|this|that)\s*[.!]?$", t):
        return "forget", m.group(1).strip().rstrip(".")
    return None


def extract_json(text):
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# --- Embeddings (optional) -------------------------------------------------------

class Embedder:
    """Turns text into vectors with a local Ollama embedding model, if one is available."""

    def __init__(self, base_url="http://localhost:11434", model=EMBED_MODEL):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.ok = None       # None = not tried yet, then True / False
        self.problem = ""

    def _post(self, path, payload, timeout=20):
        req = urllib.request.Request(self.base_url + path, data=json.dumps(payload).encode(),
                                     headers={"content-type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

    def embed(self, texts):
        if self.ok is False or not texts:
            return None
        try:
            try:
                out = self._post("/api/embed", {"model": self.model, "input": list(texts)})
                vecs = out.get("embeddings")
            except urllib.error.HTTPError as e:
                if e.code != 404 or b"model" in e.read().lower():
                    raise
                vecs = [self._post("/api/embeddings", {"model": self.model, "prompt": t}).get("embedding")
                        for t in texts]  # older Ollama
            if not vecs or not all(vecs):
                raise ValueError("no embeddings returned")
            self.ok = True
            return vecs
        except Exception as e:  # noqa: BLE001 - any failure just means "no semantic search"
            self.ok = False
            self.problem = (f"run `ollama pull {self.model}` for search by meaning"
                            if "not found" in str(e).lower() or "404" in str(e) else str(e))
            return None

    def probe(self):
        if self.ok is None:
            self.embed(["hello"])
        return self.ok


# --- Working memory ---------------------------------------------------------------

class WorkingMemory:
    """Keeps a long chat within the model's context by condensing the oldest part."""

    def __init__(self):
        self.summary = ""
        self.covered = 0  # messages[:covered] are represented by the summary

    def fit(self, messages, budget_chars, summarize):
        """Return (summary, messages_to_send). `summarize(prompt)` returns text or None."""
        total = sum(len(m["content"]) for m in messages)
        if total <= budget_chars:
            return "", messages
        # Find the earliest user message from which the rest fits in ~60% of the budget.
        keep_budget = budget_chars * 0.6
        cut, running = len(messages), 0
        for i in range(len(messages) - 1, 0, -1):
            running += len(messages[i]["content"])
            if running > keep_budget:
                break
            if messages[i]["role"] == "user":
                cut = i
        if cut >= len(messages):  # even the last exchange is huge: keep just the final message
            cut = max(i for i, m in enumerate(messages) if m["role"] == "user")
        if cut > self.covered:
            older = messages[self.covered:cut]
            transcript = "\n\n".join(f"{m['role'].upper()}: {m['content'][:4000]}" for m in older)
            prompt = ("Condense this earlier part of a conversation into notes for yourself, so you can carry "
                      "on without it. Keep facts, decisions, numbers, names, code identifiers, open questions "
                      "and what the user asked for. Under 250 words, plain text.\n\n"
                      + (f"Notes so far:\n{self.summary}\n\n" if self.summary else "")
                      + f"Conversation to add:\n{transcript}")
            new = summarize(prompt)
            if new:
                self.summary = new.strip()
            else:
                self.summary = (self.summary + "\n" if self.summary else "") + \
                    f"({cut - self.covered} earlier messages were left out to save space.)"
            self.covered = cut
        return self.summary, messages[self.covered:]


# --- The store ------------------------------------------------------------------------

class MemoryStore:
    def __init__(self, path=DB_PATH, embedder=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.embedder = embedder
        self.enabled = True
        self._create()
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # ------------------------------------------------------------------ schema
    def _create(self):
        c = self.db
        c.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'fact',
            importance INTEGER NOT NULL DEFAULT 3,
            created REAL NOT NULL,
            updated REAL NOT NULL,
            last_used REAL,
            uses INTEGER NOT NULL DEFAULT 0,
            reinforced INTEGER NOT NULL DEFAULT 1,
            pinned INTEGER NOT NULL DEFAULT 0,
            archived INTEGER NOT NULL DEFAULT 0,
            archived_reason TEXT,
            source TEXT,
            episode_id INTEGER,
            embedding BLOB,
            embed_model TEXT
        );
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started REAL NOT NULL,
            ended REAL NOT NULL,
            title TEXT,
            summary TEXT,
            topics TEXT,
            agents TEXT,
            importance INTEGER NOT NULL DEFAULT 3,
            turns INTEGER NOT NULL DEFAULT 0,
            transcript TEXT,
            embedding BLOB,
            embed_model TEXT
        );
        CREATE TABLE IF NOT EXISTS memory_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time REAL NOT NULL,
            action TEXT NOT NULL,
            memory_id INTEGER,
            detail TEXT
        );
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE INDEX IF NOT EXISTS idx_mem_active ON memories(archived, category);
        """)
        self.fts = True
        try:
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(text, category, tokenize='porter')")
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(title, summary, topics, tokenize='porter')")
        except sqlite3.OperationalError:
            self.fts = False  # SQLite built without FTS5: fall back to scanning
        if self.get_meta("schema") is None:
            self.set_meta("schema", SCHEMA_VERSION)
            self.set_meta("created", now_ts())
        c.commit()

    def get_meta(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_meta(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, json.dumps(value)))
        self.db.commit()

    def log(self, action, memory_id=None, detail=""):
        self.db.execute("INSERT INTO memory_log(time, action, memory_id, detail) VALUES(?,?,?,?)",
                        (now_ts(), action, memory_id, detail[:500]))
        self.db.commit()

    def _fts_sync(self, mem_id):
        if not self.fts:
            return
        self.db.execute("DELETE FROM memories_fts WHERE rowid=?", (mem_id,))
        row = self.get(mem_id)
        if row and not row["archived"]:
            self.db.execute("INSERT INTO memories_fts(rowid, text, category) VALUES(?,?,?)",
                            (mem_id, row["text"], row["category"]))

    def _embed_one(self, text):
        if not self.embedder:
            return None, None
        vecs = self.embedder.embed([text])
        return (pack(vecs[0]), self.embedder.model) if vecs else (None, None)

    # ------------------------------------------------------------------ reading
    def get(self, mem_id):
        return self.db.execute("SELECT * FROM memories WHERE id=?", (mem_id,)).fetchone()

    def active(self, category=None):
        q = "SELECT * FROM memories WHERE archived=0" + (" AND category=?" if category else "")
        return self.db.execute(q + " ORDER BY id", (category,) if category else ()).fetchall()

    def archived(self, limit=50):
        return self.db.execute("SELECT * FROM memories WHERE archived=1 ORDER BY updated DESC LIMIT ?",
                               (limit,)).fetchall()

    def strength(self, row, now=None):
        if row["pinned"]:
            return 1.0
        now = now or now_ts()
        half_life = CATEGORIES.get(row["category"], ("", 180))[1]
        last = max(row["updated"], row["last_used"] or 0)
        recency = 0.5 ** (max(0.0, now - last) / 86400 / half_life)
        reinforcement = min(1.0, math.log1p(row["reinforced"] + 0.5 * row["uses"]) / math.log(8))
        return round(0.45 * row["importance"] / 5 + 0.35 * recency + 0.20 * reinforcement, 3)

    def _candidates(self, query, limit=60):
        """Rows worth scoring: full-text matches plus everything with an embedding (cheap at this scale)."""
        rows = {}
        qt = tokens(query)
        if self.fts and qt:
            match = " OR ".join(f'"{t}"*' for t in list(qt)[:20])
            try:
                for r in self.db.execute(
                        "SELECT m.* FROM memories_fts f JOIN memories m ON m.id=f.rowid "
                        "WHERE memories_fts MATCH ? AND m.archived=0 ORDER BY bm25(memories_fts) LIMIT ?",
                        (match, limit)):
                    rows[r["id"]] = r
            except sqlite3.OperationalError:
                pass
        if not self.fts or (self.embedder and self.embedder.ok):
            for r in self.active():
                rows.setdefault(r["id"], r)
        return list(rows.values())

    def search(self, query, k=RETRIEVE_K, include_core=True, min_relevance=MIN_RELEVANCE):
        """Return [(row, score, relevance)] best first."""
        rows = self._candidates(query)
        if not rows:
            return []
        qt = tokens(query)
        qvec = None
        if self.embedder and self.embedder.ok is not False and any(r["embedding"] for r in rows):
            vecs = self.embedder.embed([query])
            qvec = array.array("f", vecs[0]) if vecs else None
        now = now_ts()
        scored = []
        for r in rows:
            if not include_core and r["category"] in CORE_CATEGORIES:
                continue
            rel = keyword_relevance(qt, r["text"] + " " + r["category"])
            if qvec is not None and r["embed_model"] == self.embedder.model:
                rel = max(rel, semantic_relevance(cosine(qvec, unpack(r["embedding"]))))
            if rel < min_relevance:
                continue
            score = 0.6 * rel + 0.25 * self.strength(r, now) + (0.1 if r["pinned"] else 0)
            scored.append((r, round(score, 3), round(rel, 3)))
        scored.sort(key=lambda x: -x[1])
        return scored[:k]

    # ------------------------------------------------------------------ writing
    def _find_duplicate(self, text, category, vec_blob, model):
        vec = unpack(vec_blob)
        best, best_sim = None, 0.0
        cands = self._candidates(text, limit=20)
        for r in cands:
            if r["category"] != category and not (category in CORE_CATEGORIES and r["category"] in CORE_CATEGORIES):
                continue
            sim = None
            if vec is not None and r["embed_model"] == model:
                c = cosine(vec, unpack(r["embedding"]))
                sim = c / DUP_COSINE if c is not None else None
            ratio = difflib.SequenceMatcher(None, r["text"].lower(), text.lower()).ratio() / DUP_RATIO
            sim = max(sim or 0, ratio)
            if sim > best_sim:
                best, best_sim = r, sim
        return best if best_sim >= 1.0 else None

    def add(self, text, category="fact", importance=3, source="chat", episode_id=None, pinned=False):
        """Store a memory. Returns (id or None, 'added' | 'reinforced' | 'blocked' | 'invalid')."""
        text = clean_text(text)
        if len(text) < 4:
            return None, "invalid"
        if contains_secret(text):
            self.log("blocked", None, "looked like a secret, not stored")
            return None, "blocked"
        category = category if category in CATEGORIES else "fact"
        importance = max(1, min(5, int(importance)))
        vec, model = self._embed_one(text)
        dup = self._find_duplicate(text, category, vec, model)
        now = now_ts()
        if dup:
            self.db.execute(
                "UPDATE memories SET text=?, importance=?, updated=?, reinforced=reinforced+1, "
                "pinned=MAX(pinned, ?), embedding=COALESCE(?, embedding), embed_model=COALESCE(?, embed_model) "
                "WHERE id=?",
                (text, max(importance, dup["importance"]), now, int(pinned), vec, model, dup["id"]))
            self.db.commit()
            self._fts_sync(dup["id"])
            self.db.commit()
            self.log("reinforced", dup["id"], f"{source}: {text}")
            return dup["id"], "reinforced"
        cur = self.db.execute(
            "INSERT INTO memories(text, category, importance, created, updated, source, episode_id, pinned, "
            "embedding, embed_model) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (text, category, importance, now, now, source, episode_id, int(pinned), vec, model))
        mem_id = cur.lastrowid
        self._fts_sync(mem_id)
        self.db.commit()
        self.log("added", mem_id, f"{source}: [{category}] {text}")
        self._enforce_cap()
        return mem_id, "added"

    def update(self, mem_id, text, reason="edited"):
        row = self.get(mem_id)
        text = clean_text(text)
        if not row or len(text) < 4:
            return False
        if contains_secret(text):
            self.log("blocked", mem_id, "update looked like a secret, not stored")
            return False
        vec, model = self._embed_one(text)
        self.db.execute("UPDATE memories SET text=?, updated=?, embedding=?, embed_model=? WHERE id=?",
                        (text, now_ts(), vec, model, mem_id))
        self._fts_sync(mem_id)
        self.db.commit()
        self.log("updated", mem_id, f"{reason}: '{row['text']}' -> '{text}'")
        return True

    def set_category(self, mem_id, category):
        if category not in CATEGORIES or not self.get(mem_id):
            return False
        self.db.execute("UPDATE memories SET category=?, updated=? WHERE id=?", (category, now_ts(), mem_id))
        self._fts_sync(mem_id)
        self.db.commit()
        self.log("recategorized", mem_id, category)
        return True

    def archive(self, mem_id, reason="forgotten"):
        row = self.get(mem_id)
        if not row or row["archived"]:
            return None
        self.db.execute("UPDATE memories SET archived=1, archived_reason=?, updated=? WHERE id=?",
                        (reason, now_ts(), mem_id))
        self._fts_sync(mem_id)
        self.db.commit()
        self.log("archived", mem_id, f"{reason}: {row['text']}")
        return row["text"]

    def restore(self, mem_id):
        row = self.get(mem_id)
        if not row or not row["archived"]:
            return None
        self.db.execute("UPDATE memories SET archived=0, archived_reason=NULL, updated=? WHERE id=?",
                        (now_ts(), mem_id))
        self._fts_sync(mem_id)
        self.db.commit()
        self.log("restored", mem_id, row["text"])
        return row["text"]

    def pin(self, mem_id, pinned=True):
        if not self.get(mem_id):
            return False
        self.db.execute("UPDATE memories SET pinned=? WHERE id=?", (int(pinned), mem_id))
        self.db.commit()
        self.log("pinned" if pinned else "unpinned", mem_id)
        return True

    def mark_used(self, ids):
        if ids:
            now = now_ts()
            self.db.executemany("UPDATE memories SET uses=uses+1, last_used=? WHERE id=?", [(now, i) for i in ids])
            self.db.commit()

    def _enforce_cap(self):
        rows = [r for r in self.active() if not r["pinned"]]
        if len(rows) <= MAX_ACTIVE:
            return
        now = now_ts()
        for r in sorted(rows, key=lambda r: self.strength(r, now))[:len(rows) - MAX_ACTIVE]:
            self.archive(r["id"], "over the memory limit (weakest)")

    # ------------------------------------------------------------------ episodes
    def add_episode(self, started, ended, title, summary, topics=(), agents=(), importance=3, turns=0,
                    transcript=None):
        text = f"{title}. {summary} {' '.join(topics)}"
        vec, model = self._embed_one(text)
        cur = self.db.execute(
            "INSERT INTO episodes(started, ended, title, summary, topics, agents, importance, turns, transcript, "
            "embedding, embed_model) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (started, ended, clean_text(title)[:120], (summary or "").strip()[:1500], json.dumps(list(topics)[:8]),
             json.dumps(list(agents)), max(1, min(5, int(importance))), turns,
             str(transcript) if transcript else None, vec, model))
        ep_id = cur.lastrowid
        if self.fts:
            self.db.execute("INSERT INTO episodes_fts(rowid, title, summary, topics) VALUES(?,?,?,?)",
                            (ep_id, title, summary or "", " ".join(topics)))
        self.db.commit()
        self.set_meta("chats_since_consolidation", self.get_meta("chats_since_consolidation", 0) + 1)
        self.log("episode", None, f"#{ep_id} {title}")
        return ep_id

    def episode(self, ep_id):
        return self.db.execute("SELECT * FROM episodes WHERE id=?", (ep_id,)).fetchone()

    def recent_episodes(self, n=10):
        return self.db.execute("SELECT * FROM episodes ORDER BY ended DESC LIMIT ?", (n,)).fetchall()

    def search_episodes(self, query, k=EPISODE_K, exclude=()):
        qt = tokens(query)
        rows = {}
        if self.fts and qt:
            match = " OR ".join(f'"{t}"*' for t in list(qt)[:20])
            try:
                for r in self.db.execute(
                        "SELECT e.* FROM episodes_fts f JOIN episodes e ON e.id=f.rowid WHERE episodes_fts MATCH ? "
                        "ORDER BY bm25(episodes_fts) LIMIT 30", (match,)):
                    rows[r["id"]] = r
            except sqlite3.OperationalError:
                pass
        if not self.fts or (self.embedder and self.embedder.ok):
            for r in self.recent_episodes(300):
                rows.setdefault(r["id"], r)
        qvec = None
        if self.embedder and self.embedder.ok and rows:
            vecs = self.embedder.embed([query])
            qvec = array.array("f", vecs[0]) if vecs else None
        scored = []
        now = now_ts()
        for r in rows.values():
            if r["id"] in exclude:
                continue
            text = f"{r['title']} {r['summary']} {' '.join(json.loads(r['topics'] or '[]'))}"
            rel = keyword_relevance(qt, text)
            if qvec is not None and r["embed_model"] == self.embedder.model:
                rel = max(rel, semantic_relevance(cosine(qvec, unpack(r["embedding"]))))
            if rel < MIN_RELEVANCE:
                continue
            recency = 0.5 ** ((now - r["ended"]) / 86400 / 90)
            scored.append((r, round(0.7 * rel + 0.15 * recency + 0.15 * r["importance"] / 5, 3), round(rel, 3)))
        scored.sort(key=lambda x: -x[1])
        return scored[:k]

    # ------------------------------------------------------------------ recall for a reply
    def core_memories(self, limit=12):
        rows = [r for r in self.active() if r["pinned"] or r["category"] in CORE_CATEGORIES]
        now = now_ts()
        rows.sort(key=lambda r: (-r["pinned"], CORE_CATEGORIES.index(r["category"])
                                 if r["category"] in CORE_CATEGORIES else 9, -self.strength(r, now)))
        return rows[:limit]

    def core_text(self):
        """Pinned memories, instructions and profile as plain lines (used in the Modelfile)."""
        return "\n".join(f"- {r['text']}" for r in self.core_memories())

    def context(self, query, budget=CONTEXT_BUDGET):
        """The memory section for the system prompt, chosen for this message."""
        if not self.enabled:
            return f"Today is {friendly_now()}."
        out = [f"Today is {friendly_now()}."]
        used = len(out[0])
        lines = []

        def add(line, section):
            nonlocal used
            if used + len(line) + len(section) > budget:
                return False
            if section not in lines:
                lines.append(section)
                used += len(section)
            lines.append(line)
            used += len(line) + 1
            return True

        core = self.core_memories()
        core_ids = {r["id"] for r in core}
        head_core = "Always keep in mind:"
        for r in core:
            if not add(f"- ({r['category']}) {r['text']}", head_core):
                break

        recalled = []
        head_rel = "Possibly relevant now:"
        for r, _score, _rel in self.search(query, RETRIEVE_K):
            if r["id"] in core_ids:
                continue
            if add(f"- ({r['category']}, {iso(r['updated'])}) {r['text']}", head_rel):
                recalled.append(r["id"])
        self.mark_used(recalled)

        last = self.recent_episodes(1)
        head_ep = "Past conversations:"
        shown = set()
        if last:
            e = last[0]
            add(f"- Most recent ({iso(e['ended'])}): {e['title']} - {e['summary']}", head_ep)
            shown.add(e["id"])
        for e, _s, _r in self.search_episodes(query, EPISODE_K, exclude=shown):
            add(f"- {iso(e['ended'])}: {e['title']} - {e['summary']}", head_ep)

        if lines:
            out.append("Your long-term memory of this person, from past conversations. Use it naturally when it "
                       "helps; don't recite it, and if something seems out of date, ask.")
            out += lines
        return "\n".join(out)

    # ------------------------------------------------------------------ learning from a chat
    def extraction_prompt(self, messages, related):
        lines = []
        for m in messages:
            who = "USER" if m["role"] == "user" else (f"SEAHORSE ({m['agent']})" if m.get("agent") else "SEAHORSE")
            lines.append(f"{who}: {m['content'][:3000]}")
        transcript = "\n\n".join(lines)
        if len(transcript) > 12000:
            transcript = "...\n" + transcript[-12000:]
        known = "\n".join(f"#{r['id']} ({r['category']}) {r['text']}" for r in related) or "(none)"
        cats = "\n".join(f"- {k}: {v[0]}" for k, v in CATEGORIES.items())
        today = datetime.now().strftime("%Y-%m-%d")
        return f"""You manage the long-term memory of Seahorse, a personal AI, about the one person it talks with. Today is {today}.

Memories Seahorse already has that may relate to this conversation:
{known}

Conversation:
{transcript}

Return ONLY a JSON object:
{{
  "episode": {{"title": "<5-8 words>", "summary": "<2-4 sentences: what was discussed, decided, and left open>", "topics": ["<topic>", "..."], "importance": <1-5>}},
  "remember": [{{"text": "<one fact>", "category": "<category>", "importance": <1-5>}}],
  "update": [{{"id": <existing id>, "text": "<corrected memory>"}}],
  "forget": [{{"id": <existing id>, "reason": "<why>"}}]
}}

Categories:
{cats}

Rules:
- remember: only lasting things the USER said or clearly confirmed about themselves, their preferences, projects, goals, people or instructions for Seahorse. Not things Seahorse suggested, not passing small talk, not general knowledge. At most 6. Write each as a standalone sentence about "the user", e.g. "The user prefers Python for scripting." Use absolute dates for events (e.g. 2026-10-14, not "next Tuesday").
- Skip anything already in the existing memories unless it changed. If it changed, put it in update with that id instead.
- forget: only existing memories the user said are wrong or no longer true.
- Never include passwords, keys, account or card numbers. Leave out health, money and other sensitive details unless the user explicitly asked to remember them.
- importance: 5 = core identity or a standing instruction, 3 = useful, 1 = minor.
- Empty lists are fine. Most conversations add 0-3 memories."""

    def apply_extraction(self, data, allowed_ids=(), episode_id=None):
        report = {"added": [], "reinforced": [], "updated": [], "archived": [], "blocked": []}
        if not isinstance(data, dict):
            return report
        for item in (data.get("remember") or [])[:8]:
            if isinstance(item, str):
                item = {"text": item}
            if not isinstance(item, dict):
                continue
            text = item.get("text", "")
            cat = str(item.get("category", "fact")).lower().strip()
            try:
                imp = int(item.get("importance", 3))
            except (TypeError, ValueError):
                imp = 3
            mem_id, action = self.add(text, cat if cat in CATEGORIES else guess_category(text), imp,
                                      source="reflection", episode_id=episode_id)
            if action in report:
                report[action].append((mem_id, clean_text(text)))
        allowed = set(allowed_ids)
        for item in (data.get("update") or [])[:6]:
            try:
                mem_id = int(item.get("id"))
            except (AttributeError, TypeError, ValueError):
                continue
            if mem_id in allowed and self.update(mem_id, item.get("text", ""), "corrected in conversation"):
                report["updated"].append((mem_id, clean_text(item.get("text", ""))))
        for item in (data.get("forget") or [])[:6]:
            try:
                mem_id = int(item.get("id"))
            except (AttributeError, TypeError, ValueError):
                continue
            if mem_id in allowed:
                text = self.archive(mem_id, f"no longer true: {item.get('reason', '')}".strip(": "))
                if text:
                    report["archived"].append((mem_id, text))
        return report

    # ------------------------------------------------------------------ upkeep
    def consolidate(self):
        """Fade weak memories, expire old events, merge duplicates, backfill embeddings."""
        report = {"archived": [], "merged": [], "embedded": 0}
        now = now_ts()
        for r in self.active():
            if r["pinned"]:
                continue
            age = (now - max(r["updated"], r["last_used"] or 0)) / 86400
            if r["category"] == "event" and age > EVENT_EXPIRY_DAYS and r["importance"] < 4:
                self.archive(r["id"], "event is in the past")
                report["archived"].append(r["text"])
            elif self.strength(r, now) < ARCHIVE_STRENGTH:
                self.archive(r["id"], "faded from lack of use")
                report["archived"].append(r["text"])

        if self.embedder and self.embedder.ok is not False:
            missing = [r for r in self.active() if not r["embedding"] or r["embed_model"] != self.embedder.model]
            for i in range(0, len(missing), 32):
                chunk = missing[i:i + 32]
                vecs = self.embedder.embed([r["text"] for r in chunk])
                if not vecs:
                    break
                for r, v in zip(chunk, vecs):
                    self.db.execute("UPDATE memories SET embedding=?, embed_model=? WHERE id=?",
                                    (pack(v), self.embedder.model, r["id"]))
                    report["embedded"] += 1
            self.db.commit()

        rows = self.active()
        gone = set()
        for i, a in enumerate(rows):
            if a["id"] in gone:
                continue
            for b in rows[i + 1:]:
                if b["id"] in gone or a["category"] != b["category"]:
                    continue
                c = cosine(unpack(a["embedding"]), unpack(b["embedding"])) \
                    if a["embed_model"] and a["embed_model"] == b["embed_model"] else None
                same = (c is not None and c >= DUP_COSINE) or \
                    difflib.SequenceMatcher(None, a["text"].lower(), b["text"].lower()).ratio() >= DUP_RATIO
                if not same:
                    continue
                keep, drop = sorted((a, b), key=lambda r: (r["pinned"], r["importance"], r["updated"]), reverse=True)
                self.db.execute("UPDATE memories SET reinforced=reinforced+?, importance=MAX(importance, ?), "
                                "pinned=MAX(pinned, ?) WHERE id=?",
                                (drop["reinforced"], drop["importance"], drop["pinned"], keep["id"]))
                self.db.commit()
                self.archive(drop["id"], f"merged into #{keep['id']}")
                report["merged"].append((drop["text"], keep["id"]))
                gone.add(drop["id"])
                if drop["id"] == a["id"]:
                    break
        self._enforce_cap()
        self.set_meta("last_consolidation", now)
        self.set_meta("chats_since_consolidation", 0)
        self.log("consolidated", None, f"archived {len(report['archived'])}, merged {len(report['merged'])}, "
                                       f"embedded {report['embedded']}")
        return report

    def due_for_consolidation(self):
        return self.get_meta("chats_since_consolidation", 0) >= CONSOLIDATE_EVERY

    def migrate_notes(self, notes):
        """Bring over the simple notes from older Seahorse versions."""
        n = 0
        for note in notes or []:
            _id, action = self.add(note.get("text", ""), guess_category(note.get("text", "")), 3,
                                   source="older Seahorse notes")
            n += action in ("added", "reinforced")
        return n

    # ------------------------------------------------------------------ display / export
    def stats(self):
        q = self.db.execute
        by_cat = {r[0]: r[1] for r in q("SELECT category, COUNT(*) FROM memories WHERE archived=0 GROUP BY category")}
        return {
            "active": sum(by_cat.values()),
            "by_category": by_cat,
            "archived": q("SELECT COUNT(*) FROM memories WHERE archived=1").fetchone()[0],
            "pinned": q("SELECT COUNT(*) FROM memories WHERE archived=0 AND pinned=1").fetchone()[0],
            "episodes": q("SELECT COUNT(*) FROM episodes").fetchone()[0],
            "with_embeddings": q("SELECT COUNT(*) FROM memories WHERE archived=0 AND embedding IS NOT NULL").fetchone()[0],
            "last_consolidation": self.get_meta("last_consolidation"),
            "fts": self.fts,
            "path": str(self.path),
            "size_kb": round(self.path.stat().st_size / 1024, 1) if self.path.exists() else 0,
        }

    def format_row(self, r, now=None):
        flags = ("📌 " if r["pinned"] else "") if sys.stdout.encoding and "utf" in sys.stdout.encoding.lower() \
            else ("[pinned] " if r["pinned"] else "")
        return (f"#{r['id']:<4} {flags}({r['category']}) {r['text']}  "
                f"[strength {self.strength(r, now):.2f}, since {iso(r['created'])}]")

    def recent_log(self, n=20):
        return self.db.execute("SELECT * FROM memory_log ORDER BY id DESC LIMIT ?", (n,)).fetchall()

    def export_markdown(self, path):
        now = now_ts()
        out = [f"# Seahorse memory export ({datetime.now():%Y-%m-%d %H:%M})", ""]
        for cat, (desc, _hl) in CATEGORIES.items():
            rows = self.active(cat)
            if rows:
                out += [f"## {cat.title()} - {desc}", ""]
                out += [f"- {r['text']} *(#{r['id']}, strength {self.strength(r, now):.2f}"
                        f"{', pinned' if r['pinned'] else ''})*" for r in rows]
                out.append("")
        eps = self.recent_episodes(1000)
        if eps:
            out += ["## Conversations", ""]
            for e in eps:
                out += [f"### {iso(e['ended'])} - {e['title']}", "", e["summary"] or "", ""]
        arch = self.archived(1000)
        if arch:
            out += ["## Archived (forgotten, restorable)", ""]
            out += [f"- {r['text']} *(#{r['id']}: {r['archived_reason']})*" for r in arch]
        Path(path).write_text("\n".join(out) + "\n", encoding="utf-8")
        return Path(path)

    def wipe(self):
        self.db.executescript("DELETE FROM memories; DELETE FROM episodes; DELETE FROM memory_log;")
        if self.fts:
            self.db.executescript("DELETE FROM memories_fts; DELETE FROM episodes_fts;")
        self.db.commit()
        self.db.execute("VACUUM")
        self.set_meta("chats_since_consolidation", 0)
        self.log("wiped", None, "all memories and episodes erased")


def main():
    store = MemoryStore(embedder=Embedder(os.environ.get("OLLAMA_URL", "http://localhost:11434")))
    args = sys.argv[1:]
    if args[:1] == ["search"] and len(args) > 1:
        q = " ".join(args[1:])
        for r, score, _rel in store.search(q, 20):
            print(f"{score:.2f}  {store.format_row(r)}")
        for e, score, _rel in store.search_episodes(q, 5):
            print(f"{score:.2f}  episode #{e['id']} {iso(e['ended'])}: {e['title']}")
    elif args[:1] == ["export"] and len(args) > 1:
        print(f"wrote {store.export_markdown(args[1])}")
    else:
        print(json.dumps(store.stats(), indent=2))


if __name__ == "__main__":
    main()
