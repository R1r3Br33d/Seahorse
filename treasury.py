#!/usr/bin/env python3
"""
treasury.py - the ship's treasury, paid in pirate coin and the treasures of the sea.

    SHILLINGS    Each of the ten agents is a shilling, numbered by council seat:
                 s01 is seat 01 (the captain) ... s10 is seat 10 (the Kraken).
                 Every ballot an agent casts and every piece of work it carries
                 is counted in shillings.
    WORK         Moves through the agents one by one, shilling to shilling, in a
                 relay.
    A BOTTLE     A message in a bottle: a single amendment, one proposed change,
                 thrown to the shillings with /law [board:] <text>. All ten vote
                 aye or nay in seat order; a bottle that fails washes ashore on Atlantizz,
                 the land.
    GALLEONS     Ten shillings voting aye make a galleon. The Treasurer sinks it
                 into the reef, where it becomes a SHIPWRECK: a law.
    REEF         The REEF COURTESY STANDARD OPERATION (RCSO) - the constitution:
                 every shipwreck on the reef. Every agent follows it.
    BLACK PEARLS The RCSO is filed by government cabinet board: ten
                 boards, each chaired by an agent, ten shipwrecks per board. A board
                 with all ten shipwrecks is a black pearl, the rarest thing in the
                 sea. A full board takes no more until one is repealed.
    MARLIN       The PEOPLE: you - your goals, direction and future. Every
                 shilling and galleon serves it (/budget).
    TRIDENT      POSEIDON'S TRIDENT: his most powerful asset, his bread and
                 butter. The working class - the processing power
                 (CPU, memory, GPU, the models) and how the work is distributed
                 among them; the Atlantean control of currents, undertow and the
                 flow of information (/trident):
                   currents   how the work is distributed across the workers
                   undertow   what is held back, pulled down by the Mariana
                              Trench (/trench): calls a worker couldn't take,
                              secrets never stored, bottles washed ashore on Atlantizz.
                              Each thing pulled under sinks a tenth of the
                              way (1,093 m); ten reach Challenger Deep.
                   locker     Davy Jones' Locker, the core that churns the
                              currents: the pulse (calls answered) and the
                              hourglass of the two hemispheres (/locker)
                   pockets    treasure pockets, the oil reserves - the blood of
                              the gods. Oil is the ideas scrapped in past chats;
                              asked for ideas, the crew burns the matching oil as
                              fuel (/pockets)
                   flow       how much data, from which source, reaches each reply
    BUDGET       How the marlin is shared across your goals, in parts out of 100
                 (/budget). Every shilling of work the crew carries is counted
                 against the goal it served.
    TREASURER    the Kraken (the Judge) keeps the ledger, counts every vote,
                 sinks the galleons and keeps the budget.

The RCSO never outranks Seahorse's core values or the core character
rules: honesty, your wellbeing, safety. A bottle that conflicts with them is
voted down, and the prompt says plainly that they win. Ledger:
~/.seahorse/treasury.json.
"""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

LEDGER = Path.home() / ".seahorse" / "treasury.json"
TREASURER = "judge"
GALLEON = 10         # shillings voting aye in a galleon (sunk, it becomes a shipwreck: a law)
SHARES = 100       # the marlin, shared across your goals in parts out of 100
DEFAULTS = {"law_threshold": 10}   # ayes needed to set a galleon (10 = every shilling)


def _load():
    try:
        data = json.loads(LEDGER.read_text())
    except (OSError, json.JSONDecodeError):
        data = {}
    data.setdefault("shillings", data.pop("fish", data.pop("pennies", {})))   # older ledgers counted fish, pennies
    data.setdefault("laws", [])
    data.setdefault("failed", [])
    data.setdefault("next_id", 1)
    data.setdefault("goals", [])        # the marlin: [{"text", "cents" (share of 100), "spent", "added"}]
    data.setdefault("general", 0)       # shillings of work that served no listed goal
    data.setdefault("dropped", [])      # goals you dropped: oil for the pockets
    return data


# ---- quarters: the four seasons, the four horsemen ---------------------------------------------------------------
# A quarter is a season of three months, and each has its rider, one of the four horsemen of the apocalypse:
#   Winter (Dec-Feb)  Death, the pale horse     - the year's ledger closes; what was not carried is let go
#   Spring (Mar-May)  Conquest, the white horse - new goals, new ground
#   Summer (Jun-Aug)  War, the red horse        - the council votes hardest, the bottles fly
#   Fall   (Sep-Nov)  Famine, the black horse   - harvest and scarcity: weigh the work, count the scales
# The treasury keeps its books by quarter: work carried, votes cast, galleons sunk, bottles ashore, oil scrapped.

SEASONS = [  # (season, months, horseman, horse, charge)
    ("Winter", (12, 1, 2), "Death", "the pale horse", "the year's ledger closes; what was not carried is let go"),
    ("Spring", (3, 4, 5), "Conquest", "the white horse", "new goals, new ground"),
    ("Summer", (6, 7, 8), "War", "the red horse", "the council votes hardest and the bottles fly"),
    ("Fall", (9, 10, 11), "Famine", "the black horse", "harvest and scarcity: weigh the work, count the scales"),
]


def quarter_of(when=None):
    """The quarter a date falls in: (key like '2026 Fall', season tuple). December belongs to next year's Winter."""
    when = when or datetime.now()
    if isinstance(when, str):
        try:
            when = datetime.fromisoformat(when[:10])
        except ValueError:
            return None, None
    season = next(s for s in SEASONS if when.month in s[1])
    year = when.year + 1 if when.month == 12 else when.year
    return f"{year} {season[0]}", season


def _tick(data, what, n=1):
    q = data.setdefault("quarters", {}).setdefault(quarter_of()[0], {})
    q[what] = q.get(what, 0) + n


def quarter_prompt():
    key, (season, _m, rider, horse, charge) = quarter_of()
    return f"Season: it is {season}, the quarter of {rider} ({horse}) - {charge}."


def quarters_text(chats_dir=None, n=4):
    """/quarters - the books of the last four seasons, each under its horseman."""
    data = _load()
    books = {k: dict(v) for k, v in data.get("quarters", {}).items()}

    def add(when, what):
        key = quarter_of(when)[0]
        if key:
            books.setdefault(key, {})[what] = books[key].get(what, 0) + 1
    entries = _stone()
    for e in entries:
        add(e.get("date", ""), "sunk" if e.get("action") == "enact" else "raised")
    for f in data["failed"]:
        add(f.get("date", ""), "ashore")
    for o in drill(chats_dir):
        add(o["when"], "oil")
    chats = Path(chats_dir) if chats_dir else Path.home() / ".seahorse" / "chats"
    for p in (chats.glob("chat-*.json") if chats.is_dir() else []):
        add(p.stem.replace("chat-", "")[:10], "chats")
    now, (season, _m, rider, horse, charge) = quarter_of()
    lines = [f"  ♞ The quarters - four seasons, four horsemen. Now: {season}, ridden by {rider} on {horse}:",
             f"    {charge}.", ""]
    order = [s[0] for s in SEASONS]
    year, cur = int(now.split()[0]), order.index(season)
    for i in range(n):
        idx = cur - i
        y = year + (idx // 4)           # stepping back past Winter goes to the year before
        s = SEASONS[idx % 4]
        key = f"{y} {s[0]}"
        b = books.get(key, {})
        stats = (f"work {b.get('work', 0)} · votes {b.get('votes', 0)} · galleons sunk {b.get('sunk', 0)} · "
                 f"wrecks raised {b.get('raised', 0)} · bottles ashore {b.get('ashore', 0)} · oil {b.get('oil', 0)} · "
                 f"chats {b.get('chats', 0)}")
        mark = "▸" if i == 0 else " "
        lines.append(f"  {mark} {key:<12} {s[2]:<9} {s[3]:<16} {stats}")
    return "\n".join(lines)


def _save(data):
    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LEDGER.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    except OSError:
        pass


def shilling(agent, order):
    """An agent's shillings label from its council seat: 's07'."""
    return f"s{order.index(agent) + 1:02d}" if agent in order else "s--"


fish = penny = shilling   # older names


# ---------------------------------------------------------------------------
# The ledger: shillings cast and carried
# ---------------------------------------------------------------------------
def record_votes(voters):
    data = _load()
    for a in voters:
        p = data["shillings"].setdefault(a, {"votes": 0, "work": 0})
        p["votes"] += 1
    _tick(data, "votes", len(voters))
    _save(data)


_STOP = set("the and for with that this from your into about have make what when where which their them they "
            "then than will would could should just like more some very".split())


def _words(text):
    return {w for w in re.findall(r"[a-z0-9]{4,}", (text or "").lower()) if w not in _STOP}


def goal_for(text, goals):
    """Which goal a piece of work served: the goal sharing the most key words with it, or None."""
    words = _words(text)
    best, best_n = None, 0
    for i, g in enumerate(goals):
        n = len(words & _words(g["text"]))
        if n > best_n:
            best, best_n = i, n
    return best


def record_work(agent, text=""):
    """A shilling of work carried by `agent`, spent on the goal it served (or general upkeep)."""
    data = _load()
    p = data["shillings"].setdefault(agent, {"votes": 0, "work": 0})
    p["work"] += 1
    _tick(data, "work")
    i = goal_for(text, data["goals"])
    if i is None:
        data["general"] += 1
    else:
        g = data["goals"][i]
        g["spent"] = g.get("spent", 0) + 1
        by = g.setdefault("by", {})
        by[agent] = by.get(agent, 0) + 1
    _save(data)


# ---------------------------------------------------------------------------
# The marlin (the people) and the budget
# ---------------------------------------------------------------------------
def goals():
    return _load()["goals"]


def _rebalance(gs):
    """Keep the budget at exactly 100 shares: goals without a fixed share split what's left evenly."""
    fixed = [g for g in gs if g.get("fixed")]
    free = [g for g in gs if not g.get("fixed")]
    left = max(0, SHARES - sum(g["cents"] for g in fixed))
    for i, g in enumerate(free):
        g["cents"] = left // len(free) + (1 if i < left % len(free) else 0)
    return gs


def add_goal(text):
    data = _load()
    text = re.sub(r"\s+", " ", text or "").strip()[:200]
    if not text or len(data["goals"]) >= 10:
        return None
    data["goals"].append({"text": text, "cents": 0, "spent": 0, "added": datetime.now().strftime("%Y-%m-%d")})
    _rebalance(data["goals"])
    _save(data)
    return data["goals"][-1]


def drop_goal(n):
    data = _load()
    if 1 <= n <= len(data["goals"]):
        gone = data["goals"].pop(n - 1)
        data["dropped"].append({"text": gone["text"], "when": datetime.now().isoformat(timespec="seconds")})
        if data["goals"]:
            _rebalance(data["goals"])
        _save(data)
        return gone
    return None


def set_cents(n, cents):
    """Fix goal n's share; the other unfixed goals share the rest. Returns an error string or None."""
    data = _load()
    if not 1 <= n <= len(data["goals"]):
        return "no goal by that number (/budget)"
    others = sum(g["cents"] for i, g in enumerate(data["goals"]) if g.get("fixed") and i != n - 1)
    if cents < 0 or cents + others > SHARES:
        return f"that's more than the whole marlin: {SHARES - others} of {SHARES} shares are free"
    data["goals"][n - 1].update(cents=cents, fixed=True)
    _rebalance(data["goals"])
    _save(data)
    return None


def marlin_prompt():
    """The people, for every agent's prompt: what the user is working toward."""
    gs = goals()
    if not gs:
        return ""
    lines = ["The marlin - the person you serve: their goals, direction and future, with the "
             "share of the crew's effort they've budgeted to each. Keep "
             "them in mind; where it genuinely helps, connect your answer to them. Never push the goals on the "
             "person or bring them up when they don't fit."]
    lines += [f"- {g['text']} ({g['cents']} of 100 shares)" for g in gs]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The cabinet: ten boards, ten amendments each
# ---------------------------------------------------------------------------
# Each board is chaired by an agent and holds up to ten amendments. Ten boards
# of ten shipwrecks is a hundred; a full board is a black pearl.
BOARDS = {
    "hippocampus": "State",                 # the captain's board: amendments here apply to everything
    "broca": "Communications",
    "parietal": "Navigation & Numbers",
    "cerebellum": "Works & Engineering",
    "wernicke": "Education",
    "prefrontal": "Planning & Provisions",
    "cingulate": "Inspection",
    "doc": "Science & Research",
    "fiery-black": "Defense & Security",
    "judge": "Treasury & Justice",
}
STATE = "hippocampus"
PER_BOARD = 10


def board_of(law):
    return law.get("board") or STATE


# ---------------------------------------------------------------------------
# The Reef Courtesy Standard Operation (the constitution), set in stone: a numbered index for processing
# ---------------------------------------------------------------------------
# Every shipwreck gets a permanent wreck number: its board's number, then its
# place on that board - Wreck 9.01 is the first galleon ever sunk on the Defense &
# Security board. The stone is append-only: an enactment or a repeal is a new
# entry, each sealed with a SHA-256 hash of the one before it, so numbers are
# never reused or rewritten and any tampering with the file shows. Wrecks are
# processed in index order: State (board 1) first, then board by board; where
# two conflict, the lower wreck number prevails. ~/.seahorse/constitution.json
# is the stone; RCSO.md beside it is rewritten from it for reading.
STONE = Path.home() / ".seahorse" / "constitution.json"
STONE_MD = Path.home() / ".seahorse" / "RCSO.md"
BOARD_NO = {chair: i for i, chair in enumerate(BOARDS, 1)}


def _seal(entry, prev):
    body = json.dumps({k: entry[k] for k in ("n", "action", "art", "board", "text", "date", "ayes", "nays")},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256((prev + body).encode("utf-8")).hexdigest()


def _stone():
    try:
        return json.loads(STONE.read_text()).get("entries", [])
    except (OSError, json.JSONDecodeError, AttributeError):
        return []


def verify():
    """(intact, index of the first broken entry or None)."""
    prev = "stone"
    for i, e in enumerate(_stone()):
        if e.get("prev") != prev or _seal(e, prev) != e.get("hash"):
            return False, i
        prev = e["hash"]
    return True, None


def _carve(action, art, board, text, ayes=0, nays=0):
    entries = _stone()
    ok, broken = verify()
    if not ok:
        raise ValueError(f"the reef's seal is broken at entry {broken + 1}: restore constitution.json "
                         "before carving anything new")
    prev = entries[-1]["hash"] if entries else "stone"
    e = {"n": len(entries) + 1, "action": action, "art": art, "board": board, "text": text,
         "date": datetime.now().strftime("%Y-%m-%d %H:%M"), "ayes": ayes, "nays": nays, "prev": prev}
    e["hash"] = _seal(e, prev)
    entries.append(e)
    STONE.parent.mkdir(parents=True, exist_ok=True)
    STONE.write_text(json.dumps({"about": "Seahorse's Reef Courtesy Standard Operation, set in stone. Append-only and hash-chained: "
                                          "do not edit by hand (any change breaks the seal).",
                                 "entries": entries}, indent=1, ensure_ascii=False))
    _write_md()
    return e


def in_force():
    """Shipwrecks in force, in processing order (board number, then wreck number). If the stone was changed by
    hand, only the entries before the break are trusted: a forged or altered wreck never takes effect."""
    live = {}
    entries = _stone()
    ok, broken = verify()
    if not ok:
        entries = entries[:broken]
    for e in entries:
        if e["action"] == "enact":
            live[e["art"]] = e
        elif e["action"] == "repeal":
            live.pop(e["art"], None)
    return sorted(live.values(), key=lambda e: tuple(int(x) for x in e["art"].split(".")))


def _next_art(board):
    used = [e for e in _stone() if e["action"] == "enact" and e["board"] == board]
    return f"{BOARD_NO[board]}.{len(used) + 1:02d}"


def _migrate():
    """Laws kept in the old ledger are carved into the stone once, in the order they passed."""
    data = _load()
    if data.get("laws") and not _stone():
        for l in data["laws"]:
            b = board_of(l)
            _carve("enact", _next_art(b), b, l["text"], l.get("ayes", 0), l.get("nays", 0))
        data["laws"] = []
        _save(data)


def cite(e):
    return f"Wreck {e['art']}"


def _write_md():
    ok, _ = verify()
    lines = ["# The Reef Courtesy Standard Operation (RCSO)", "",
             "The constitution of Seahorse's crew, set in stone. Every shipwreck on the reef is a law, and keeps its "
             "number forever. Processed in index order, State first; where two conflict, the lower wreck number "
             "prevails. No shipwreck outranks Seahorse's core values.", "",
             f"Seal: {'intact' if ok else 'BROKEN - the stone file was changed by hand'}", ""]
    live = {e["art"] for e in in_force()}
    for chair, name in BOARDS.items():
        lines.append(f"## {BOARD_NO[chair]}. {name} board (chaired by {chair})")
        rows = [e for e in _stone() if e["action"] == "enact" and e["board"] == chair]
        lines += [f"- **Wreck {e['art']}** {e['text']} *(sunk {e['date'][:10]}, {e['ayes']} aye)*"
                  + ("" if e["art"] in live else " - **raised (repealed)**") for e in rows] or ["- (no shipwrecks)"]
        lines.append("")
    try:
        STONE_MD.write_text("\n".join(lines))
    except OSError:
        pass


def board_for(text, agents=None):
    """(chair, bottle text): a message in a bottle may name its board ('security: ...', 'Education: ...', '@doc: ...');
    otherwise it goes to the board whose chair's subject it matches best, or to State."""
    m = re.match(r"\s*@?([\w &-]{2,30}?)\s*:\s*(.+)$", text or "", re.S)
    if m:
        key = m.group(1).strip().lower()
        for chair, name in BOARDS.items():
            if key in (chair, name.lower()) or key == name.lower().split()[0] or key == name.lower().split(" & ")[-1]:
                return chair, m.group(2).strip()
        agent = agents.get(key) if agents is not None and hasattr(agents, "get") else None
        if agent is not None and getattr(agent, "name", None) in BOARDS:
            return agent.name, m.group(2).strip()
    best, score = STATE, 0
    for chair in BOARDS:
        agent = agents.get(chair) if agents is not None and hasattr(agents, "get") else None
        n = agent.score(text) if agent is not None else 0
        if n > score:
            best, score = chair, n
    return best, (text or "").strip()


# ---------------------------------------------------------------------------
# Messages in bottles (single amendments), galleons and shipwrecks (laws)
# ---------------------------------------------------------------------------
def law_prompt(text, order, board=STATE):
    current = "\n".join(f"- {l['text']}" for l in laws(board)) or "(none yet)"
    seats = ", ".join(f"{shilling(a, order)} {a}" for a in order)
    return (f"A message in a bottle - a single amendment - has been proposed to the {BOARDS[board]} board of the crew's "
            f"Reef Courtesy Standard Operation (the crew's constitution):\n\"{text[:600]}\"\n\n"
            f"Amendments already in force on this board:\n{current}\n\n"
            f"Vote as each of the ten agents of Seahorse's mind, in seat order: {seats}.\n"
            "Each votes aye or nay from its own role, with one short reason. Vote nay if the amendment would conflict "
            "with Seahorse's core values (honesty, the user's real wellbeing, safety, never inventing facts), with "
            "the core character rules, with an amendment in force, or if it is too vague to follow. Otherwise judge "
            "it on whether it would make the crew better at serving the user.\n"
            'Reply with ONLY JSON: {"votes": [{"agent": "<name>", "vote": "aye" or "nay", "reason": "<short>"}]}')


def parse_votes(raw, order):
    m = re.search(r"\{.*\}", raw or "", re.DOTALL)
    try:
        data = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        data = {}
    got = {}
    for v in data.get("votes", []) if isinstance(data, dict) else []:
        if isinstance(v, dict) and v.get("agent") in order and v["agent"] not in got:
            aye = str(v.get("vote", "")).strip().lower().startswith(("aye", "yes", "y"))
            got[v["agent"]] = ("aye" if aye else "nay", re.sub(r"\s+", " ", str(v.get("reason", ""))).strip()[:160])
    return {a: got[a] for a in order if a in got}   # in seat order; missing shillings abstain


def count(votes, threshold):
    """The Treasurer's count: (ayes, nays, minted?)."""
    ayes = sum(1 for v, _ in votes.values() if v == "aye")
    nays = sum(1 for v, _ in votes.values() if v == "nay")
    return ayes, nays, ayes >= threshold


def propose(text, votes, threshold, board=STATE):
    """Record the outcome. Returns (status, entry) - status: minted, failed, full or empty.
    A bottle that passes is a galleon sunk into the reef: a shipwreck with its permanent wreck number."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return "empty", None
    board = board if board in BOARDS else STATE
    _migrate()
    ayes, nays, ok = count(votes, threshold)
    if ok and len(laws(board)) >= PER_BOARD:
        return "full", {"text": text, "board": board, "ayes": ayes, "nays": nays}
    if ok:
        e = _carve("enact", _next_art(board), board, text[:400], ayes, nays)
        return "minted", e
    data = _load()
    entry = {"id": data["next_id"], "board": board, "text": text[:400], "ayes": ayes, "nays": nays,
             "date": datetime.now().strftime("%Y-%m-%d")}
    data["next_id"] += 1
    data["failed"] = (data["failed"] + [entry])[-20:]
    _save(data)
    return "failed", entry

def laws(board=None):
    """Shipwrecks (laws) in force, optionally one board's, in index order. Each has art, board, text, ayes, date."""
    _migrate()
    return [e for e in in_force() if board is None or e["board"] == board]

def repeal(article):
    """Raise (repeal) a shipwreck by its number ('9.01', 'Wreck 9.01'). The repeal is carved too; the number is
    retired."""
    art = re.sub(r"(?i)^(wreck|art\.?|article|#)\s*", "", str(article).strip())
    for e in in_force():
        if e["art"] == art:
            _carve("repeal", art, e["board"], e["text"])
            return e
    return None

def constitution_prompt(agent_name=None, query="", agents=None):
    """The amendments that apply to this reply: the State board's always, the answering agent's own board, and
    the boards whose subject the message touches. Keeps prompts short even with a full cabinet."""
    ls = laws()
    if not ls:
        return ""
    boards = {STATE}
    if agent_name in BOARDS:
        boards.add(agent_name)
    for chair in BOARDS:
        agent = agents.get(chair) if agents is not None and hasattr(agents, "get") else None
        if agent is not None and query and agent.score(query):
            boards.add(chair)
    if agents is None:
        boards = set(BOARDS)
    picked = [l for l in ls if board_of(l) in boards]
    if not picked:
        return ""
    lines = ["The Reef Courtesy Standard Operation (RCSO), the crew's constitution, set in stone: shipwrecks - laws "
             "the full council passed and sank into the reef - numbered by cabinet "
             "board (only the boards that bear on this message are shown). Process them in index order; where two "
             "conflict, the lower wreck number prevails. Cite a wreck by its number if you need to. They never "
             "outrank your core values or the core character rules; if one ever seems to conflict with those, the "
             "core values win."]
    for chair in BOARDS:
        mine = [l for l in picked if board_of(l) == chair]
        if mine:
            lines.append(f"Board {BOARD_NO[chair]} - {BOARDS[chair]}:")
            lines += [f"Wreck {l['art']} {l['text']}" for l in mine]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------
def vote_lines(text, votes, threshold, status, order, board=STATE):
    ayes, nays, _ = count(votes, threshold)
    out = [f"message in a bottle (a single amendment) to the {BOARDS.get(board, 'State')} board: \"{text}\""]
    out += [f"{shilling(a, order)} {a}: {v}{' - ' + r if r else ''}" for a, (v, r) in votes.items()]
    missing = [a for a in order if a not in votes]
    if missing:
        out.append("abstained: " + ", ".join(f"{shilling(a, order)} {a}" for a in missing))
    n = len(laws(board))
    black = n == PER_BOARD
    art = laws(board)[-1]["art"] if status == "minted" and laws(board) else ""
    verdict = {"minted": f"a galleon - sunk into the reef as Wreck {art}, a law ({n} of {PER_BOARD} on the "
                         f"{BOARDS.get(board, 'State')} board)" + (" - the board is complete: a BLACK PEARL" if black else ""),
               "failed": f"short of the {threshold} shillings needed: the bottle washes ashore on Atlantizz, no galleon sails",
               "full": f"a galleon, but the {BOARDS.get(board, 'State')} board is already a black pearl ({PER_BOARD} "
                       "shipwrecks): raise one first (/law repeal <wreck>)",
               "empty": "nothing to vote on"}[status]
    out.append(f"Treasurer's count: {ayes} aye · {nays} nay → {verdict}")
    return out


def cabinet_text(show_repealed=False):
    """The numbered index of the Reef Courtesy Standard Operation, as set in stone."""
    ls = laws()
    ok, broken = verify()
    blacks = sum(1 for c in BOARDS if len([l for l in ls if board_of(l) == c]) >= PER_BOARD)
    lines = [f"  The Reef Courtesy Standard Operation (RCSO), set in stone - {len(ls)} shipwrecks (laws) in force across {len(BOARDS)} cabinet boards, "
             f"{PER_BOARD} shipwrecks per board; a full board is a black pearl ({blacks} so far)",
             f"  seal: {'intact - ' + str(len(_stone())) + ' entries, each hash-chained to the last' if ok else 'BROKEN at entry ' + str((broken or 0) + 1) + ': the stone file was changed by hand'}",
             "  processing order: board 1 (State) first, then by wreck number; the lower number prevails"]
    live = {e["art"] for e in ls}
    for chair, name in BOARDS.items():
        mine = [l for l in ls if board_of(l) == chair]
        lines.append(f"    Board {BOARD_NO[chair]:>2} · {name} ({chair}) · {len(mine)}/{PER_BOARD} shipwrecks"
                     + (" · a BLACK PEARL" if len(mine) >= PER_BOARD else ""))
        lines += [f"      Wreck {l['art']}  {l['text']}  ({l['ayes']} aye, {l['date'][:10]})" for l in mine]
        if show_repealed:
            gone = [e for e in _stone() if e["action"] == "enact" and e["board"] == chair and e["art"] not in live]
            lines += [f"      Wreck {e['art']}  (raised - repealed) {e['text']}" for e in gone]
    return "\n".join(lines)


def describe(order, threshold=GALLEON):
    data = _load()
    lines = [f"  Treasurer: the Kraken ({TREASURER}) · a bottle needs {threshold} of {GALLEON} shillings to become a galleon",
             "", "  The shillings (by seat):"]
    for a in order:
        p = data["shillings"].get(a, {"votes": 0, "work": 0})
        tag = "  Treasurer" if a == TREASURER else ""
        chair = f"  chairs {BOARDS[a]}" if a in BOARDS else ""
        lines.append(f"    {shilling(a, order)} {a:<12} {p['votes']:>4} votes cast · {p['work']:>3} pieces of work"
                     f"{chair}{tag}")
    lines += ["", cabinet_text()]
    if data["failed"]:
        last = data["failed"][-1]
        lines += ["", f"  Last bottle washed ashore on Atlantizz: \"{last['text']}\" ({last['ayes']} aye, {last['nays']} nay)"]
    lines += ["", budget_text()]
    return "\n".join(lines)


def budget_text():
    """What's in the budget: the marlin's 100 shares across your goals, and the shillings of work spent on each."""
    data = _load()
    gs = data["goals"]
    total = sum(g.get("spent", 0) for g in gs) + data["general"]
    lines = ["  The marlin (the people: your goals, direction, future) and the budget:"]
    if not gs:
        lines.append("    nothing budgeted yet - add a goal with /budget add <goal>; the marlin's 100 shares split across them")
    for i, g in enumerate(gs, 1):
        spent = g.get("spent", 0)
        share = f"{spent / total:.0%}" if total else "0%"
        who = ", ".join(f"{a} {n}" for a, n in sorted(g.get("by", {}).items(), key=lambda kv: -kv[1])[:3])
        lines.append(f"    {i}. {g['text']:<40} budget {g['cents']:>3}/100{' (fixed)' if g.get('fixed') else ''}"
                     f" · spent {spent} shillings ({share} of the work){' · ' + who if who else ''}")
    lines.append(f"    general upkeep (work for no listed goal): {data['general']} "
                 "shillings")
    return "\n".join(lines)


# ---- treasure pockets: the oil reserves -------------------------------------------------------------------------
# Oil is the blood of the gods: the ideas scrapped in past chats. Each past chat that holds some is a treasure
# pocket. The drill finds them four ways: a message you took back ("scrap that", "never mind", "instead"...),
# bottles that washed ashore on Atlantizz, goals dropped from the budget, and shipwrecks repealed from the reef.
# Nothing is thrown away: when you ask for ideas, the matching oil is refined into the prompt as fuel.

SCRAP = re.compile(r"\b(scrap( that| it)?|scratch that|never ?mind|forget (that|it|about it)|nah\b|instead|change that|"
                   r"undo( that)?|don'?t (do|want|need) (that|it)|actually,? no|on second thought|drop (that|it)|"
                   r"remove (that|it)|pause( that)?|stop (that|it)|not that)\b", re.I)
WANTS_IDEAS = re.compile(r"\b(ideas?|brainstorm|suggest|what else|inspir|options?|alternatives?|oil|scrapped)\b", re.I)
_OIL_STOP = set("the a an and or but to of in on for with is are was be it that this i you my me we our your "
            "what how can could would should do does just like so make give".split())


def _oil_words(text):
    return {w for w in re.findall(r"[a-z][a-z'-]{2,}", text.lower()) if w not in _OIL_STOP}


def drill(chats_dir=None):
    """Every scrapped idea Seahorse can find: [{"idea", "why", "where", "when"}], oldest first."""
    oil = []
    chats = Path(chats_dir) if chats_dir else Path.home() / ".seahorse" / "chats"
    for path in sorted(chats.glob("chat-*.json")) if chats.is_dir() else []:
        try:
            msgs = json.loads(path.read_text()).get("messages", [])
        except (OSError, json.JSONDecodeError):
            continue
        users = [m.get("content", "") for m in msgs if m.get("role") == "user" and isinstance(m.get("content"), str)]
        for prev, cur in zip(users, users[1:]):
            m = SCRAP.search(cur)
            if m and prev.strip() and not prev.startswith("/"):
                oil.append({"idea": " ".join(prev.split())[:220], "why": f"taken back: \"{m.group(0)}\"",
                            "where": path.stem, "when": path.stem.replace("chat-", "")[:10]})
    data = _load()
    for f in data["failed"]:
        oil.append({"idea": f["text"], "why": f"bottle washed ashore on Atlantizz ({f.get('ayes', 0)} aye)",
                    "where": "the treasury", "when": str(f.get("date", ""))[:10]})
    for g in data["dropped"]:
        oil.append({"idea": g["text"], "why": "goal dropped from the budget", "where": "the marlin",
                    "when": g["when"][:10]})
    entries = _stone()
    ok, broken = verify()
    enacted = {e["art"]: e for e in (entries if ok else entries[:broken]) if e.get("action") == "enact"}
    for e in (entries if ok else entries[:broken]):
        if e.get("action") == "repeal":
            oil.append({"idea": e.get("text") or enacted.get(e["art"], {}).get("text", ""),
                        "why": f"Wreck {e['art']} repealed", "where": "the reef", "when": str(e.get("date", ""))[:10]})
    return oil


def refine(query, chats_dir=None, k=3):
    """The oil that best matches the query - the fuel for a request for ideas."""
    q = _oil_words(query)
    scored = [(len(q & _oil_words(o["idea"])), o) for o in drill(chats_dir)]
    return [o for n, o in sorted(scored, key=lambda t: -t[0]) if n][:k]


def oil_prompt(query, chats_dir=None):
    """Fuel for the prompt: only when the user asks for ideas, and only oil that matches."""
    if not query or not WANTS_IDEAS.search(query):
        return ""
    fuel = refine(query, chats_dir)
    if not fuel:
        return ""
    return ("Oil from the treasure pockets - ideas the user scrapped in earlier chats. They set these aside for a "
            "reason, so raise one only if it genuinely helps now, and say it was an earlier idea:\n"
            + "\n".join(f"- {o['idea']} ({o['why']}, {o['when']})" for o in fuel))


def pocket_lines(chats_dir=None):
    oil = drill(chats_dir)
    pockets = {}
    for o in oil:
        pockets.setdefault(o["where"], []).append(o)
    lines = ["  Treasure pockets - the oil reserves, the blood of the gods: ideas scrapped in past chats.",
             f"    {len(oil)} barrel{'s' if len(oil) != 1 else ''} of oil in {len(pockets)} pocket{'s' if len(pockets) != 1 else ''}"
             + (" - the reserves are dry; nothing has been scrapped yet" if not oil else "")]
    return lines, pockets


def pockets_text(chats_dir=None, query=""):
    """/pockets - every pocket and its oil; /pockets <words> drills for the oil that matches."""
    if query:
        fuel = refine(query, chats_dir, k=10)
        head = [f"  ⛁ Drilling the pockets for \"{query}\":"]
        return "\n".join(head + ([f"    • {o['idea']}\n      {o['why']} · {o['where']} · {o['when']}" for o in fuel]
                                 or ["    no oil matches - try other words"]))
    lines, pockets = pocket_lines(chats_dir)
    lines = ["  ⛁ Treasure pockets - oil reserves, the blood of the gods. The oil is every idea scrapped in a past",
             "    chat. Seahorse refines it into fuel when you ask for ideas.", ""] + lines
    for where, barrels in sorted(pockets.items(), key=lambda kv: kv[0], reverse=True)[:12]:
        lines.append(f"\n    pocket: {where}")
        lines += [f"      • {o['idea'][:110]}{'…' if len(o['idea']) > 110 else ''}\n        {o['why']}" for o in barrels[-5:]]
    lines += ["", "  /pockets <words> drills for oil on a topic."]
    return "\n".join(lines)


def headroom_lines(power=None, flow=None):
    """Headroom in the processing power: free memory, free disk, the context the last reply left unused."""
    import shutil
    power, dry, lines = power or {}, [], []

    def gauge(free, total):
        n = max(0, min(10, round(10 * free / total))) if total else 0
        return "●" * n + "○" * (10 - n)
    ram, ram_total = power.get("ram"), power.get("ram_total")
    if ram and ram_total:
        lines.append(f"    headroom memory  {gauge(ram, ram_total)}  {ram:.1f} of {ram_total:.1f} GB free")
        if ram < ram_total * 0.1:
            dry.append("memory")
    try:
        d = shutil.disk_usage(Path.home())
        lines.append(f"    headroom disk    {gauge(d.free, d.total)}  {d.free / 1e9:.0f} of {d.total / 1e9:.0f} GB free")
        if d.free < d.total * 0.1:
            dry.append("disk")
    except OSError:
        pass
    ctx = power.get("num_ctx")
    if ctx:
        used = sum(n for _l, n in flow[1]) // 4 if flow else 0   # roughly four characters to a token
        left = max(0, ctx - used)
        lines.append(f"    headroom context {gauge(left, ctx)}  ~{left:,} of {ctx:,} tokens free after the last prompt")
        if left < ctx * 0.1:
            dry.append("context")
    if dry:
        lines.append("    running low: " + ", ".join(dry))
    return lines


CHALLENGER_DEEP = 10_935   # metres - the deepest point of the Mariana Trench


def trench_lines(data=None, memory=None, workers=None):
    """The undertow. The Mariana Trench drives it: whatever is held back is pulled down into
    the trench. Each thing sinks a tenth of the way; ten of them reach Challenger Deep."""
    data, workers = data or _load(), workers or []
    blocked = 0
    if memory is not None:
        try:
            blocked = memory.db.execute("SELECT COUNT(*) FROM memory_log WHERE action='blocked'").fetchone()[0]
        except Exception:  # noqa: BLE001 - the count is a nicety
            blocked = 0
    down = sum(w.get("unavailable", 0) for w in workers)
    ashore = len(data.get("failed", []))
    pulled = down + blocked + ashore
    depth = min(CHALLENGER_DEEP, round(pulled * CHALLENGER_DEEP / 10))
    gauge = "▼" * min(10, pulled) + "·" * (10 - min(10, pulled))
    where = ("still in the sunlight zone, nothing pulled under" if not pulled else
             "resting on the floor of Challenger Deep" if depth >= CHALLENGER_DEEP else
             "in the hadal zone, the trench's own water" if depth >= 6_000 else
             "in the abyss" if depth >= 4_000 else
             "in the midnight zone" if depth >= 1_000 else "in the twilight zone")
    return ["  Undertow - the Mariana Trench pulls under whatever is held back:",
            f"    calls a worker couldn't take (sent on to the next): {down}",
            f"    secrets (passwords, keys, card numbers) refused by memory: {blocked}",
            f"    bottles voted down and washed ashore on Atlantizz: {ashore}",
            "    chats saved under the old incognito mode: excluded from training and your profile",
            f"    depth  {gauge}  {depth:,} m of {CHALLENGER_DEEP:,} m - {where}"]


def trench_text(memory=None, workers=None):
    """/trench - the undertow on its own."""
    return "\n".join(["  ⌄ The Mariana Trench - the source of the undertow. Nothing it takes comes back up",
                      "    into a reply: not a refused secret, not a sunk bottle, not a call that failed.", ""]
                     + trench_lines(None, memory, workers))


def locker_lines(workers=None):
    """Davy Jones' Locker, the void at the centre of the earth. Mussels fed on the blood of electric eels grow
    there as wide as satellite dishes, so many that they shift between hemispheres like the sand in a giant
    hourglass. Their pulse at the core churns the ocean: it drives every current above.
    In Seahorse: the pulse is every call the workers answered; the hourglass is the two lobes (the
    hemispheres) - it tips toward whichever lobe has carried more votes on its own."""
    import lobes
    workers = workers or []
    beats = sum(max(0, w["calls"] - w.get("unavailable", 0)) for w in workers)
    hemi = lobes.load_stats().get("hemisphere", {})
    left, right = hemi.get("left", 0), hemi.get("right", 0)
    total = left + right
    sand = round(10 * left / total) if total else 5
    glass = "◀ " + "█" * sand + "░" * (10 - sand) + " ▶"
    lean = ("the mussels sit level, half in each hemisphere" if left == right else
            f"the mussels are massing in the {'left' if left > right else 'right'} hemisphere")
    return ["  Davy Jones' Locker - the void at the centre of the earth, which churns the currents:",
            "    mussels fed on electric-eel blood, each as wide as a satellite dish, shift between the",
            "    hemispheres like sand in a giant hourglass. Their pulse at the core drives every current.",
            f"    pulse      {beats} beats (calls the workers answered this session)" + (" - still" if not beats else ""),
            f"    hourglass  left {glass} right   left lobe carried {left} · right lobe carried {right}",
            f"               {lean}"]


def locker_text(workers=None):
    """/locker - the core on its own."""
    return "\n".join(["  ⧗ Davy Jones' Locker", ""] + locker_lines(workers)
                     + ["", "  (The currents it drives are in /trident; the undertow it feeds is in /trench.)"])


def trident_text(flow=None, memory=None, power=None, workers=None, order=None):
    """Poseidon's Trident - the working class: the processing power, and how the work is distributed."""
    data = _load()
    power, workers, order = power or {}, workers or [], order or []
    lines = ["  Ψ Poseidon's Trident - his most powerful asset, his bread and butter. The working class: the",
             "    processing power that does the crew's work, and how that work is distributed. Its prongs are",
             "    currents (distribution), undertow (what is held back, pulled down by the Mariana Trench)",
             "    and the flow of information.", "",
             "  Processing power:"]
    ram = power.get("ram")
    lines += [f"    CPU     {power.get('cpu', '?')}",
              f"    memory  {f'{ram:.1f} GB free' if ram else 'unknown'}",
              f"    GPU     {power.get('gpu', '?')}",
              f"    local   context window {power.get('context', '?')} · "
              f"{'lobes vote in parallel' if power.get('parallel', True) else 'lobes vote one after the other'}"]
    loaded = power.get("loaded") or []
    lines.append("    loaded  " + (", ".join(loaded) if loaded else "no local model loaded right now"))
    lines += [""] + locker_lines(workers)
    lines += headroom_lines(power, flow)
    lines += [""] + pocket_lines()[0]
    lines += ["", "  Currents - how the work is distributed:"]
    done = {w["name"]: max(0, w["calls"] - w.get("unavailable", 0)) for w in workers}
    total = sum(done.values())
    for w in workers:
        n = done[w["name"]]
        share = f"{n / total:.0%}" if total else "0%"
        rate = f" · {w['chars'] / w['seconds']:.0f} chars/s" if w["seconds"] > 0.5 and w["chars"] else ""
        missed = f" · couldn't take {w['unavailable']}" if w.get("unavailable") else ""
        lines.append(f"    {w['name']:<32} {n:>4} calls answered ({share}) · {w['chars']:,} chars produced{rate}{missed}")
    if not total:
        lines.append("    no calls yet this session")
    carried = [(a, data["shillings"].get(a, {}).get("work", 0)) for a in order]
    busy = [f"{shilling(a, order)} {a} {n}" for a, n in sorted(carried, key=lambda kv: -kv[1]) if n][:6]
    lines.append("    work carried by the crew: " + (" · ".join(busy) if busy else "none yet"))
    lines += [""] + trench_lines(data, memory, workers)
    lines += ["", "  Flow of information - the data that reached the last reply:"]
    if flow:
        agent, parts = flow
        total_chars = sum(n for _l, n in parts) or 1
        lines.append(f"    to {agent}: {total_chars:,} characters in all")
        for label, n in sorted(parts, key=lambda kv: -kv[1]):
            bar = "█" * max(1, round(24 * n / total_chars))
            lines.append(f"    {label:<28} {n:>7,}  {bar}")
    else:
        lines.append("    nothing yet - send a message, then look again")
    lines += ["", "  (The marlin - the people: your goals and the budget - is /budget.)"]
    return "\n".join(lines)


