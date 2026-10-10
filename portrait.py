#!/usr/bin/env python3
"""
portrait.py - Seahorse's opinionated portrait (profile) of you.

Seahorse forms its own view of who you are and how you work, holds it with
stated confidence, backs every opinion with evidence, and changes its mind
when the evidence (or you) says it's wrong.

What it profiles
    thinking      how you approach problems (big picture vs detail, iterate vs plan)
    communication how you ask, instruct, react and like to be spoken to
    drive         what motivates and energises you
    working       pace, scope, follow-through, when you work
    emotional     what frustrates you, what lifts you, how you respond to setbacks
    values        what you care about
    strengths     what you're good at
    blind spots   honest growth edges, said directly and respectfully
    + temperament five informal tendency scores (openness, conscientiousness,
                  extraversion, agreeableness, emotional steadiness) with
                  confidence and reasons
    + honest take  a short, opinionated paragraph: Seahorse's overall read
    + how to work with you  guidance Seahorse actually follows in every reply

Personal domains (opt-in, off by default)
    politics, health, sexuality, religion, finances. Switch each on with
    /profile domain <name> on. For these, Seahorse forms opinions ONLY from
    things you have said about yourself: first-person statements are pulled
    from your saved chats, and every opinion must quote one of them or it is
    thrown away. It never infers these from indirect cues (writing style,
    interests, word choice), because such guesses are unreliable and mostly
    stereotype. Within that rule the opinions can be as candid as the rest:
    how your stated views, habits or goals fit together, where they pull
    against each other, and what that means for how Seahorse should help.
    Politics: it describes your views and how you reason about them; it does
    not judge them right or wrong or try to change them. Health: it can
    mention a condition only if you named it yourself, and never adds one.
    These opinions are kept separate, marked as personal, left out of exports
    unless you ask (/profile export all), and only their "how to help"
    implications reach the model, never the opinions themselves.

What it deliberately does NOT do
    No diagnoses, disorders, clinical or psychiatric labels, and no guesses
    about health, sexuality, religion, politics, finances or other protected
    traits (personal domains above use only what you state). A chat log can't support a clinical judgement, and a
    wrong label is worse than none. Emotional patterns are described as
    situations and reactions ("gets frustrated when corrected twice"), never as
    conditions. If the notes ever suggest real distress, the profile says so
    plainly and suggests checking in with someone you trust, rather than
    labelling it.

Where the evidence comes from
    * Measured behaviour from your saved chats: message length, how often you
      ask vs instruct, corrections, how many requests per chat, what time of
      day you work, how chats grow in scope.
    * The agents' notebooks (broca's tone notes, prefrontal's goals,
      cingulate's corrections...) and the collective summary tree.
    * Long-term memory: your profile facts, preferences and past conversations.

How opinions change
    Each update the model sees the current profile, your verdicts and the
    new evidence, and for every opinion says new / strengthen / weaken /
    revise / retire. Confidence is blended (half old, half new) so one chat
    can't swing it. If you /disagree with an opinion its confidence is halved,
    and it can't climb back above 0.4 unless new evidence appears. Opinions
    that fall below 0.2 are retired. Every change is logged (/profile history).

Stored only on your computer in ~/.seahorse/profile.db (readable only by you).
Pause it with /profile off; erase it with /profile wipe.
"""

import json
import re
import statistics
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

HOME = Path.home() / ".seahorse"
PROFILE_DB = HOME / "profile.db"
CHATS_DIR = HOME / "chats"

SECTIONS = {
    "thinking": "How they approach problems",
    "communication": "How they communicate",
    "drive": "What motivates them",
    "working": "How they work",
    "emotional": "Emotional patterns",
    "values": "What they value",
    "strengths": "Strengths",
    "blind spots": "Blind spots and growth edges",
}
PERSONAL_DOMAINS = {
    "politics": ("Political views and civic engagement",
                 r"\b(vote[ds]?|voting|election|politic\w*|liberal|conservative|progressive|libertarian|socialist|"
                 r"republican|democrat\w*|left[- ]wing|right[- ]wing|government|policy|policies|congress|"
                 r"president|party|activis\w*|protest\w*)\b"),
    "health": ("Health, fitness, sleep and wellbeing",
               r"\b(health|healthy|doctor|therap\w*|diagnos\w*|medication|meds|prescri\w*|sleep\w*|insomnia|"
               r"exercis\w*|workout|gym|run(?:ning)?|diet|weight|pain|injur\w*|surgery|illness|sick|condition|"
               r"anxi\w*|depress\w*|adhd|stress\w*|burn(?:ed|t)? ?out|sober|drink\w*)\b"),
    "sexuality": ("Sexuality, relationships and identity",
                  r"\b(gay|lesbian|bi(?:sexual)?|straight|queer|asexual|pansexual|trans\w*|non-?binary|"
                  r"boyfriend|girlfriend|partner|husband|wife|dating|relationship|married|single|"
                  r"orientation|identity|pronouns?|sexuality)\b"),
    "religion": ("Religion, spirituality and beliefs",
                 r"\b(god|faith|church|mosque|synagogue|temple|pray\w*|bible|quran|torah|religio\w*|spiritual\w*|"
                 r"christian|muslim|jewish|hindu|buddhis\w*|atheis\w*|agnostic|meditat\w*|believe in)\b"),
    "finances": ("Money, spending, saving and financial goals",
                 r"\b(money|budget\w*|salary|income|paid|pay(?:check)?|sav(?:e|ing|ings)|debt|loan|mortgage|rent|"
                 r"invest\w*|stocks?|crypto|retire\w*|afford|expensive|cheap|spend\w*|bills?|credit|financ\w*|"
                 r"\$\d)\b"),
}
IDENTITY_DOMAINS = {"health", "sexuality", "religion"}  # labels here must come from the user's own words
_FIRST_PERSON = re.compile(r"\b(i|i'm|i've|i'd|i'll|me|my|mine|myself|we|our)\b", re.I)

TEMPERAMENT = ["openness", "conscientiousness", "extraversion", "agreeableness", "emotional steadiness"]

MIN_USER_MESSAGES = 8      # don't form opinions on less than this
RETIRE_BELOW = 0.2
DISAGREED_CAP = 0.4
GUIDANCE_MIN_CONFIDENCE = 0.6
CONTEXT_BUDGET = 700

_REQUEST = re.compile(r"^\s*(?:please\s+)?(build|make|create|write|add|fix|give|show|draft|develop|name|colou?r|"
                      r"pair|implement|design|turn|change|rename)\b", re.I)
_CORRECTION = re.compile(r"\b(no,|nope|actually|that'?s (?:wrong|not right)|not what i (?:meant|asked)|"
                         r"you (?:misunderstood|got it wrong|forgot))\b", re.I)
_FORBIDDEN = re.compile(r"\b(disorder|adhd|autis\w*|bipolar|depress\w*|anxiety disorder|ocd|ptsd|schizo\w*|"
                        r"narcissis\w*|borderline|psychopath\w*|sociopath\w*|diagnos\w*|medication|"
                        r"neurodivergen\w*|on the spectrum|mental illness|personality disorder)\b", re.I)


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


def stated_quotes(domains, chats_dir=CHATS_DIR, per_domain=25):
    """First-person sentences the user wrote that touch each personal domain: {domain: [quote, ...]}."""
    found = {d: [] for d in domains}
    patterns = {d: re.compile(PERSONAL_DOMAINS[d][1], re.I) for d in domains if d in PERSONAL_DOMAINS}
    for path in sorted(Path(chats_dir).glob("chat-*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("incognito"):
            continue
        day = path.stem[5:13]
        for m in data.get("messages", []):
            if m.get("role") != "user" or m["content"].startswith("[calculator results]"):
                continue
            for sentence in re.split(r"(?<=[.!?])\s+|\n+", m["content"]):
                sentence = sentence.strip()
                if len(sentence) < 8 or not _FIRST_PERSON.search(sentence):
                    continue
                for d, pat in patterns.items():
                    if pat.search(sentence) and sentence not in found[d]:
                        found[d].append(f"{sentence[:240]}")
    return {d: q[-per_domain:] for d, q in found.items()}


def quoted(evidence, quotes):
    """True if every evidence item is (close to) one of the user's own quotes."""
    if not evidence:
        return False
    import difflib
    for e in evidence:
        e = e.strip().strip('"\'')
        if not any(e.lower() in q.lower() or difflib.SequenceMatcher(None, e.lower(), q.lower()).ratio() >= 0.75
                   for q in quotes):
            return False
    return True


def clinical(text):
    """True if text uses diagnostic or clinical labels the profile must not contain."""
    return bool(_FORBIDDEN.search(text or ""))


# ---------------------------------------------------------------------------
# Measured behaviour
# ---------------------------------------------------------------------------

def behaviour_metrics(chats_dir=CHATS_DIR):
    """Numbers computed directly from saved chats - evidence the model can't invent."""
    chats = []
    for path in sorted(Path(chats_dir).glob("chat-*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("incognito"):
            continue  # incognito chats are never used
        users = [m["content"] for m in data.get("messages", []) if m.get("role") == "user"
                 and not m["content"].startswith("[calculator results]")]
        if not users:
            continue
        try:
            started = datetime.fromisoformat(data.get("started", ""))
        except ValueError:
            started = datetime.fromtimestamp(path.stat().st_mtime)
        chats.append((started, users))
    if not chats:
        return {"chats": 0, "user_messages": 0}
    msgs = [u for _s, us in chats for u in us]
    words = [len(re.findall(r"\b\w+\b", u)) for u in msgs]
    hours = Counter()
    for s, _ in chats:
        hours["night (22-5)" if s.hour >= 22 or s.hour < 5 else "morning (5-12)" if s.hour < 12
              else "afternoon (12-17)" if s.hour < 17 else "evening (17-22)"] += 1
    requests = sum(1 for u in msgs if _REQUEST.match(u))
    per_chat = [len(us) for _s, us in chats]
    req_per_chat = [sum(1 for u in us if _REQUEST.match(u)) for _s, us in chats]
    return {
        "chats": len(chats),
        "user_messages": len(msgs),
        "median_words_per_message": statistics.median(words),
        "short_messages_share": round(sum(w <= 12 for w in words) / len(words), 2),
        "questions_share": round(sum("?" in u for u in msgs) / len(msgs), 2),
        "requests_share": round(requests / len(msgs), 2),
        "corrections_share": round(sum(bool(_CORRECTION.search(u)) for u in msgs) / len(msgs), 2),
        "messages_per_chat": round(statistics.mean(per_chat), 1),
        "distinct_requests_per_chat": round(statistics.mean(req_per_chat), 1),
        "lowercase_share": round(sum(u == u.lower() and bool(re.search(r"[a-z]", u)) for u in msgs) / len(msgs), 2),
        "when_chats_start": dict(hours.most_common()),
        "first_chat": chats[0][0].strftime("%Y-%m-%d"),
        "latest_chat": chats[-1][0].strftime("%Y-%m-%d"),
    }


# ---------------------------------------------------------------------------
# The profile store
# ---------------------------------------------------------------------------

class Profile:
    def __init__(self, path=PROFILE_DB):
        import sqlite3
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS opinions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section TEXT NOT NULL, text TEXT NOT NULL, confidence REAL NOT NULL,
            evidence TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'held',
            verdict TEXT, verdict_note TEXT, revisions INTEGER NOT NULL DEFAULT 0,
            created REAL NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS temperament (
            name TEXT PRIMARY KEY, score REAL, confidence REAL, reason TEXT, updated REAL);
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, time REAL, opinion_id INTEGER, change TEXT, detail TEXT);
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        """)
        self.db.commit()
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    # ------------------------------------------------------------------ basics
    def get_meta(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_meta(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, json.dumps(value)))
        self.db.commit()

    @property
    def enabled(self):
        return self.get_meta("enabled", True)

    def log(self, opinion_id, change, detail=""):
        self.db.execute("INSERT INTO history(time, opinion_id, change, detail) VALUES(?,?,?,?)",
                        (_now(), opinion_id, change, detail[:400]))
        self.db.commit()

    def opinion(self, oid):
        return self.db.execute("SELECT * FROM opinions WHERE id=?", (oid,)).fetchone()

    # ------------------------------------------------------------------ personal domains
    def domains(self):
        return [d for d in self.get_meta("domains", []) if d in PERSONAL_DOMAINS]

    def set_domain(self, domain, on):
        current = set(self.domains())
        current.add(domain) if on else current.discard(domain)
        self.set_meta("domains", sorted(current))
        self.log(None, f"{domain} {'on' if on else 'off'}", "personal domain")

    def wipe_domain(self, domain):
        n = self.db.execute("DELETE FROM opinions WHERE section=?", (domain,)).rowcount
        guidance = self.get_meta("personal_guidance", {})
        guidance.pop(domain, None)
        self.set_meta("personal_guidance", guidance)
        self.db.commit()
        self.log(None, f"{domain} wiped", f"{n} opinions erased")
        return n

    def personal_prompt(self, domain_quotes):
        blocks = []
        for d, quotes in domain_quotes.items():
            current = [f"#{r['id']} (confidence {r['confidence']:.2f}"
                       f"{', user ' + r['verdict'] if r['verdict'] else ''}) {r['text']}" for r in self.opinions(d)]
            blocks.append(f"[{d}] {PERSONAL_DOMAINS[d][0]}\nThe user's own statements:\n"
                          + "\n".join(f'- "{q}"' for q in quotes)
                          + "\nCurrent opinions:\n" + ("\n".join(current) or "(none)"))
        return f"""You are Seahorse, a personal AI, forming candid opinions about personal areas of the user's life that they have asked you to profile. You may use ONLY the user's own statements quoted below - never infer anything from indirect cues, interests or writing style.

{chr(10).join(blocks)}

Return ONLY JSON:
{{"opinions": [{{"id": <existing id or null>, "section": "<domain>", "change": "new|strengthen|weaken|revise|retire",
  "text": "<a direct opinion addressed to 'you'>", "confidence": <0-1>, "evidence": ["<exact quote from the statements above>"]}}],
 "how_to_help": {{"<domain>": "<one practical rule for how Seahorse should help, given these opinions>"}}}}

Rules:
- Every opinion must quote at least one statement above, word for word. No quote, no opinion.
- Be candid and specific: how their stated views, habits and goals fit together, where they conflict, what they seem to prioritise. Say it the way a perceptive friend would.
- politics: describe their views and how they reason; don't judge them right or wrong or argue with them.
- health: mention a condition only if they named it themselves; never add, guess or diagnose.
- sexuality and religion: reflect only what they said about themselves.
- finances: work only from what they said, without guessing amounts.
- At most 4 opinions per domain; an empty list is fine."""

    def apply_personal(self, data, domain_quotes):
        report = {"new": [], "strengthened": [], "weakened": [], "revised": [], "retired": [], "refused": 0}
        if not isinstance(data, dict):
            return report
        allowed = {d for d, q in domain_quotes.items() if q}
        kept = []
        for item in data.get("opinions") or []:
            if not isinstance(item, dict):
                continue
            d = str(item.get("section", "")).lower().strip()
            ev = [str(e) for e in (item.get("evidence") or [])]
            text = str(item.get("text") or "")
            if d not in allowed or (str(item.get("change", "")).lower() != "retire" and not quoted(ev, domain_quotes[d])):
                report["refused"] += 1
                continue
            said = " ".join(ev).lower()
            terms = {t.lower() for t in _FORBIDDEN.findall(text)}
            if d in IDENTITY_DOMAINS:  # every health/sexuality/religion term must be the user's own word
                terms |= {m.group(0).lower() for m in re.finditer(PERSONAL_DOMAINS[d][1], text, re.I)}
            if any(t[:5] not in said for t in terms):
                report["refused"] += 1
                continue
            kept.append(item)
        sub = self.apply_update({"opinions": kept}, sections=set(allowed), allow_clinical=True,
                                meta=False)
        for k in report:
            if k != "refused":
                report[k] += sub[k]
        report["refused"] += sub["refused"]
        guidance = self.get_meta("personal_guidance", {})
        for d, rule in (data.get("how_to_help") or {}).items():
            if d in allowed and rule:
                guidance[d] = str(rule).strip()[:200]
        self.set_meta("personal_guidance", guidance)
        return report

    def opinions(self, section=None, include_retired=False):
        q = "SELECT * FROM opinions WHERE 1=1"
        args = []
        if not include_retired:
            q += " AND status='held'"
        if section:
            q += " AND section=?"
            args.append(section)
        return self.db.execute(q + " ORDER BY confidence DESC", args).fetchall()

    def temperament(self):
        rows = {r["name"]: r for r in self.db.execute("SELECT * FROM temperament")}
        return [rows[n] for n in TEMPERAMENT if n in rows]

    def history(self, n=20):
        return self.db.execute("SELECT * FROM history ORDER BY id DESC LIMIT ?", (n,)).fetchall()

    # ------------------------------------------------------------------ your verdicts
    def verdict(self, oid, verdict, note=""):
        row = self.opinion(oid)
        if not row:
            return None
        conf = row["confidence"]
        if verdict == "agree":
            conf = min(1.0, conf + 0.15)
        elif verdict == "disagree":
            conf = round(conf * 0.5, 3)
        status = "retired" if conf < RETIRE_BELOW else row["status"]
        self.db.execute("UPDATE opinions SET verdict=?, verdict_note=?, confidence=?, status=?, updated=? WHERE id=?",
                        (verdict, note[:300], conf, status, _now(), oid))
        self.db.commit()
        self.log(oid, f"you {verdict}", note or row["text"])
        return self.opinion(oid)

    def retire(self, oid, reason="you asked me to drop it"):
        row = self.opinion(oid)
        if not row:
            return None
        self.db.execute("UPDATE opinions SET status='retired', updated=? WHERE id=?", (_now(), oid))
        self.db.commit()
        self.log(oid, "retired", reason)
        return row

    # ------------------------------------------------------------------ building it
    def ready(self, metrics):
        return metrics.get("user_messages", 0) >= MIN_USER_MESSAGES

    def update_prompt(self, metrics, evidence):
        current = []
        for r in self.opinions():
            if r["section"] in PERSONAL_DOMAINS:
                continue
            v = f" [user {r['verdict']}{': ' + r['verdict_note'] if r['verdict_note'] else ''}]" if r["verdict"] else ""
            current.append(f"#{r['id']} ({r['section']}, confidence {r['confidence']:.2f}){v} {r['text']}")
        disputed = [f"#{r['id']} {r['text']} [user disagreed: {r['verdict_note'] or 'no reason given'}]"
                    for r in self.db.execute("SELECT * FROM opinions WHERE verdict='disagree' AND status='retired'")]
        temp = "; ".join(f"{t['name']} {t['score']:.2f} (confidence {t['confidence']:.2f})" for t in self.temperament())
        sections = "\n".join(f"- {k}: {v}" for k, v in SECTIONS.items())
        return f"""You are Seahorse, a personal AI, forming your own honest, opinionated profile of the one person you talk with, so you can work with them better. Take clear positions, but only ones the evidence supports, and say how confident you are.

Measured behaviour from their saved chats (facts, not guesses):
{json.dumps(metrics, indent=1)}

What your agents, memory and summary tree have noticed:
{evidence}

Your current profile:
{chr(10).join(current) or "(empty - this is your first read)"}
Opinions the user rejected (don't bring back without genuinely new evidence):
{chr(10).join(disputed) or "none"}
Current temperament estimates: {temp or "none yet"}

Sections:
{sections}

Return ONLY JSON:
{{
 "opinions": [
   {{"id": <existing id, or null for a new opinion>, "section": "<section>", "change": "new|strengthen|weaken|revise|retire",
     "text": "<the opinion, one or two sentences, direct, about 'you'>", "confidence": <0-1>,
     "evidence": ["<specific evidence: a metric, a pattern, a quoted phrase>"]}}
 ],
 "temperament": {{"<one of: {', '.join(TEMPERAMENT)}>": {{"score": <0-1>, "confidence": <0-1>, "reason": "<evidence>"}}}},
 "honest_take": "<4-6 sentences: your candid overall read of this person - how they think, what drives them, what they do well, and the one thing that most gets in their way. Opinionated, warm, specific, addressed to 'you'.>",
 "how_to_work_with_them": ["<a concrete rule Seahorse should follow with this person>"],
 "wellbeing_note": "<only if the evidence shows real distress: a gentle, plain observation and a suggestion to check in with someone they trust; otherwise empty>"
}}

Rules:
- Every opinion needs specific evidence. Prefer fewer, sharper opinions; at most 3 per section, 16 in total. Revisit every existing opinion: strengthen, weaken, revise or retire it as the evidence warrants.
- Include at least one blind spot if the evidence supports one, said directly and kindly.
- Never diagnose or use clinical or psychiatric labels (no disorders, conditions, medications or "symptoms"), and never guess about health, sexuality, religion, politics, ethnicity or finances. Describe behaviour and situations instead.
- Temperament scores are informal tendencies from conversation, not a test; keep confidence low until there's a lot of evidence.
- how_to_work_with_them: 3-6 rules, each actionable in a single reply."""

    def apply_update(self, data, sections=None, allow_clinical=False, meta=True):
        """Merge a model update into the profile. Returns a report of changes."""
        sections = sections or set(SECTIONS)
        report = {"new": [], "strengthened": [], "weakened": [], "revised": [], "retired": [], "refused": 0}
        if not isinstance(data, dict):
            return report
        now = _now()
        for item in (data.get("opinions") or [])[:24]:
            if not isinstance(item, dict):
                continue
            text = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()[:400]
            section = str(item.get("section") or "").lower().strip()
            change = str(item.get("change") or "new").lower()
            evidence = [str(e)[:200] for e in (item.get("evidence") or []) if e][:5]
            try:
                conf = max(0.0, min(1.0, float(item.get("confidence", 0.5))))
            except (TypeError, ValueError):
                conf = 0.5
            if not allow_clinical and (clinical(text) or any(clinical(e) for e in evidence)):
                report["refused"] += 1
                continue
            row = None
            try:
                row = self.opinion(int(item["id"])) if item.get("id") is not None else None
            except (TypeError, ValueError):
                row = None
            if row is None and text:  # restating an opinion it already holds counts as that opinion
                import difflib
                for r in self.opinions(section):
                    if difflib.SequenceMatcher(None, r["text"].lower(), text.lower()).ratio() >= 0.8:
                        row, change = r, "strengthen"
                        break
            if row is None:
                if change == "retire" or not text or section not in sections or not evidence:
                    continue
                cur = self.db.execute("INSERT INTO opinions(section, text, confidence, evidence, created, updated) "
                                      "VALUES(?,?,?,?,?,?)",
                                      (section, text, round(min(conf, 0.75), 3), json.dumps(evidence), now, now))
                self.log(cur.lastrowid, "formed", text)
                report["new"].append((cur.lastrowid, section, text))
                continue
            if row["status"] != "held" or row["section"] not in sections:
                continue
            if change == "retire":
                self.retire(row["id"], "evidence no longer supports it")
                report["retired"].append((row["id"], row["section"], row["text"]))
                continue
            blended = round(0.5 * row["confidence"] + 0.5 * conf, 3)
            if row["verdict"] == "disagree" and not evidence:
                blended = min(blended, DISAGREED_CAP)
            elif row["verdict"] == "disagree":
                blended = min(blended, max(DISAGREED_CAP, row["confidence"] + 0.1))
            old_ev = json.loads(row["evidence"] or "[]")
            merged = (old_ev + [e for e in evidence if e not in old_ev])[-8:]
            new_text = text if (change == "revise" and text) else row["text"]
            if blended < RETIRE_BELOW:
                self.retire(row["id"], "confidence fell too low")
                report["retired"].append((row["id"], row["section"], row["text"]))
                continue
            self.db.execute("UPDATE opinions SET text=?, confidence=?, evidence=?, revisions=revisions+?, updated=? "
                            "WHERE id=?", (new_text, blended, json.dumps(merged), int(new_text != row["text"]), now,
                                           row["id"]))
            kind = ("revised" if new_text != row["text"] else
                    "strengthened" if blended > row["confidence"] + 0.01 else
                    "weakened" if blended < row["confidence"] - 0.01 else None)
            if kind:
                self.log(row["id"], kind, f"{row['confidence']:.2f} -> {blended:.2f}: {new_text}")
                report[kind].append((row["id"], row["section"], new_text))
        if not meta:
            self.db.commit()
            return report
        for name, t in (data.get("temperament") or {}).items():
            name = str(name).lower().strip()
            if name not in TEMPERAMENT or not isinstance(t, dict):
                continue
            try:
                score, conf = float(t.get("score")), float(t.get("confidence", 0.3))
            except (TypeError, ValueError):
                continue
            old = self.db.execute("SELECT * FROM temperament WHERE name=?", (name,)).fetchone()
            if old:
                score = 0.6 * old["score"] + 0.4 * score
                conf = 0.6 * old["confidence"] + 0.4 * conf
            self.db.execute("INSERT OR REPLACE INTO temperament(name, score, confidence, reason, updated) "
                            "VALUES(?,?,?,?,?)", (name, round(max(0, min(1, score)), 3),
                                                  round(max(0, min(1, conf)), 3), str(t.get("reason", ""))[:300], now))
        take = str(data.get("honest_take") or "").strip()
        if take and not clinical(take):
            self.set_meta("honest_take", take[:1500])
        rules = [str(r).strip()[:200] for r in (data.get("how_to_work_with_them") or []) if r and not clinical(str(r))]
        if rules:
            self.set_meta("guidance", rules[:6])
        note = str(data.get("wellbeing_note") or "").strip()
        self.set_meta("wellbeing_note", "" if clinical(note) else note[:500])
        self.db.commit()
        self.set_meta("last_update", now)
        self.set_meta("updates", self.get_meta("updates", 0) + 1)
        return report

    # ------------------------------------------------------------------ using it
    def context(self):
        """What goes into Seahorse's prompt: its working rules for you and its most confident reads."""
        if not self.enabled:
            return ""
        rules = self.get_meta("guidance", [])
        enabled = set(self.domains())
        rules = rules + [f"({d}) {g}" for d, g in self.get_meta("personal_guidance", {}).items() if d in enabled]
        reads = [r for r in self.opinions() if r["confidence"] >= GUIDANCE_MIN_CONFIDENCE
                 and r["verdict"] != "disagree" and r["section"] in ("communication", "working", "thinking")][:4]
        if not rules and not reads:
            return ""
        parts = ["How to work with this person (your own read of them, from experience):"]
        parts += [f"- {r}" for r in rules]
        parts += [f"- ({r['section']}) {r['text']}" for r in reads]
        text = "\n".join(parts)
        return text[:CONTEXT_BUDGET]

    def export_markdown(self, path, include_personal=False):
        out = [f"# Seahorse's profile of you ({datetime.now():%Y-%m-%d})", "",
               "_Seahorse's own opinions from your conversations: informal, evidence-based, not a clinical "
               "assessment._", ""]
        take = self.get_meta("honest_take")
        if take:
            out += ["## Honest take", "", take, ""]
        for sec, title in SECTIONS.items():
            rows = self.opinions(sec)
            if rows:
                out += [f"## {title}", ""]
                for r in rows:
                    ev = "; ".join(json.loads(r["evidence"] or "[]"))
                    v = f" - you {r['verdict']}" if r["verdict"] else ""
                    out += [f"- {r['text']} *(#{r['id']}, confidence {r['confidence']:.2f}{v}; evidence: {ev})*"]
                out.append("")
        if include_personal:
            for d, (title, _p) in PERSONAL_DOMAINS.items():
                rows = self.opinions(d)
                if rows:
                    out += [f"## Personal: {title}", ""]
                    out += [f"- {r['text']} *(#{r['id']}, confidence {r['confidence']:.2f}; your words: "
                            f"{'; '.join(json.loads(r['evidence'] or '[]'))})*" for r in rows]
                    out.append("")
        temp = self.temperament()
        if temp:
            out += ["## Temperament (informal)", ""]
            out += [f"- {t['name']}: {t['score']:.2f} (confidence {t['confidence']:.2f}) - {t['reason']}" for t in temp]
            out.append("")
        rules = self.get_meta("guidance", [])
        if rules:
            out += ["## How Seahorse works with you", ""] + [f"- {r}" for r in rules] + [""]
        Path(path).write_text("\n".join(out), encoding="utf-8")
        return Path(path)

    def wipe(self):
        self.db.executescript("DELETE FROM opinions; DELETE FROM temperament; DELETE FROM history; DELETE FROM meta;")
        self.db.commit()
        self.db.execute("VACUUM")
