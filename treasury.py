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

import change

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
    _key, (season, _m, rider, horse, charge) = quarter_of()
    who = _riders().get(season)
    return f"Season: it is {season}, the quarter of {rider} ({horse}){', ridden by ' + who['name'] if who else ''} - {charge}."


def quarters_text(chats_dir=None, n=4):
    """/quarters - the books of the last four seasons, each under its horseman."""
    data = _load()
    books = {k: dict(v) for k, v in data.get("quarters", {}).items()}
    dated = ([(e.get("date", ""), "sunk" if e.get("action") == "enact" else "raised") for e in _stone()]
             + [(f.get("date", ""), "ashore") for f in data["failed"]]
             + [(o["when"], "oil") for o in drill(chats_dir)]
             + [(p.stem[5:15], "chats") for p in _chats(chats_dir)])
    for when, what in dated:
        key = quarter_of(when)[0]
        if key:
            b = books.setdefault(key, {})
            b[what] = b.get(what, 0) + 1
    now, (season, _m, rider, horse, charge) = quarter_of()
    riders = {q: f"{m['name']} at {m['horseman'].get('station', '?')}" for q, m in _riders().items()}
    lines = ["  ♞ The quarters - four seasons, four horsemen, the four high-ranking members of Bamba's council.",
             f"    Now: {season}, ridden by {rider} on {horse}" + (f" - {riders[season]}" if season in riders else "") + ":",
             f"    {charge}.", ""]
    year, cur = int(now.split()[0]), [s[0] for s in SEASONS].index(season)
    for i in range(n):
        s = SEASONS[(cur - i) % 4]
        key = f"{year + (cur - i) // 4} {s[0]}"          # stepping back past Winter goes to the year before
        b = books.get(key, {})
        stats = " · ".join(f"{label} {b.get(k, 0)}" for k, label in (
            ("work", "work"), ("paid", "paid ¢"), ("votes", "votes"), ("sunk", "galleons sunk"), ("raised", "wrecks raised"),
            ("ashore", "bottles ashore"), ("oil", "oil"), ("chats", "chats")))
        lines.append(f"  {'▸' if i == 0 else ' '} {key:<12} {s[2]:<9} {riders.get(s[0], ''):<26} {stats}")
    return "\n".join(lines)


# ---- payroll: the change is the agents' internal payment system ---------------------------------------------------
# Every agent keeps a purse in change. The Kraken, as Treasurer, pays:
#   a delivered reply   what it turned out to be worth ($0.00 to a whole value), settled when you answer it
#                       (or when the chat ends) - by how much you had to change it (change.py)
#   a relay step        a nickel in wages, at once
#   a ballot            a penny, at once (council votes and law votes alike)
# What a reply earns is also counted against the goal it served, and in the quarter's books.

def pay(agent, cents, why, data=None):
    """Pay `agent` `cents` hundredths. Pass the loaded ledger to batch with other changes (the caller saves)."""
    own = data is None
    data = data if data is not None else _load()
    purse = data.setdefault("purses", {}).setdefault(agent, {"cents": 0, "by": {}})
    purse["cents"] += cents
    purse["by"][why] = purse["by"].get(why, 0) + cents
    data["payments"] = (data.get("payments", []) + [{"agent": agent, "cents": cents, "why": why,
                                                       "when": datetime.now().isoformat(timespec="seconds")}])[-60:]
    _tick(data, "paid", cents)
    if own:
        _save(data)


def transact(op, agents, amount=0, factor=1.0):
    """The Treasurer's four moves on purses, worked through change.cipher in MDAS order.
    op: 'grow' / 'ration' (multiply each purse by factor), 'split' (divide amount among agents and pay it out),
        'credit' (add amount to each), 'deduct' (subtract amount from each, never below zero).
    Returns (lines, steps)."""
    data = _load()
    purses = data.setdefault("purses", {})
    lines, steps = [], []
    if op == "split":
        shares, steps = change.cipher(amount, divide=len(agents))
        for a, c in zip(agents, shares):
            pay(a, c, "split", data)
            lines.append(f"{a} +{change.dollars(c)}")
    else:
        for a in agents:
            have = purses.get(a, {}).get("cents", 0)
            if op in ("grow", "ration"):
                (new,), steps = change.cipher(have, multiply=factor)
            elif op == "credit":
                (new,), steps = change.cipher(have, add=amount)
            else:
                (new,), steps = change.cipher(have, subtract=amount)
            if new != have:
                pay(a, new - have, f"{op} x{factor:g}" if op in ("grow", "ration") else op, data)
            lines.append(f"{a} {change.dollars(have)} -> {change.dollars(new)}")
    _save(data)
    return lines, steps


def hold(agent, asked, chat, goal_text=""):
    """A reply was delivered: hold its pay until you answer it (or the chat ends)."""
    data = _load()
    data["pending"] = {"agent": agent, "asked": asked[:2000], "chat": chat, "goal": goal_text[:300]}
    _save(data)


def settle(next_user="", chat=None):
    """Pay the held reply what it was worth. A reply from another chat (or chat=None with nothing said) stood.
    Returns (agent, cents, ledger) or None if nothing was held."""
    data = _load()
    held = data.pop("pending", None)
    if not held:
        return None
    ended = not next_user or (chat is not None and held.get("chat") != chat)
    cents, ledger = change.worth("", "" if ended else next_user, held.get("asked", ""), ended=ended, scrap=SCRAP)
    pay(held["agent"], cents, "replies delivered", data)
    i = goal_for(held.get("goal", ""), data["goals"])
    if i is not None:
        data["goals"][i]["paid"] = data["goals"][i].get("paid", 0) + cents
    _save(data)
    return held["agent"], cents, ledger


def payroll_text(order=None):
    """/pay - every agent's purse in change, and the last payments."""
    data = _load()
    purses = data.get("purses", {})
    order = order or list(purses)
    total = sum(p["cents"] for p in purses.values())
    lines = [f"  ¢ The payroll - the change is the agents' pay; the Kraken, as Treasurer, pays it out.",
             "    /pay credit|deduct <agent|all> <amount> · split <amount> <agents|all> · grow|ration <factor> <agent|all>",
             f"    a delivered reply earns what it was worth ({change.dollars(0)} to {change.dollars(100)}) · "
             f"a relay step {change.dollars(change.WAGES['relay step'])} · a ballot {change.dollars(change.WAGES['ballot'])}",
             f"    paid out in all: {change.coins(total) if total else '$0.00 - nothing yet'}", ""]
    for a in sorted(order, key=lambda a: -purses.get(a, {}).get("cents", 0)):
        p = purses.get(a)
        if not p:
            continue
        split = " · ".join(f"{why} {change.dollars(c)}" for why, c in sorted(p["by"].items(), key=lambda kv: -kv[1]))
        lines.append(f"    {shilling(a, order) if a in order else '   '} {a:<12} {'$' + format(p['cents'] / 100, ',.2f'):>9}"
                     f"  {split}")
    if not purses:
        lines.append("    no one has been paid yet - answer a reply and its agent is paid what it was worth")
    if data.get("pending"):
        lines += ["", f"    held: {data['pending']['agent']}'s last reply - paid when you answer it"]
    recent = data.get("payments", [])[-6:]
    if recent:
        lines += ["", "    last payments:"] + [f"      {p['when'][11:16]}  {p['agent']:<12} {change.dollars(p['cents']):>6}  {p['why']}"
                                               for p in reversed(recent)]
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
def record_votes(voters, why="council ballot"):
    data = _load()
    for a in voters:
        p = data["shillings"].setdefault(a, {"votes": 0, "work": 0})
        p["votes"] += 1
        pay(a, change.WAGES["ballot"], why, data)
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


def record_work(agent, text="", wage=False):
    """A shilling of work carried by `agent`, spent on the goal it served (or general upkeep).
    wage=True pays a relay step's wage (a nickel) at once; a delivered reply is paid when it is settled."""
    data = _load()
    if wage:
        pay(agent, change.WAGES["relay step"], "relay step carried", data)
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
                     f" · spent {spent} shillings ({share} of the work)"
                     f"{' · paid ' + change.dollars(g['paid']) if g.get('paid') else ''}{' · ' + who if who else ''}")
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
_WELLS = {}   # chat path -> (mtime, size, barrels): each chat is drilled once, until it changes


def _chats(chats_dir=None):
    d = Path(chats_dir) if chats_dir else Path.home() / ".seahorse" / "chats"
    return sorted(d.glob("chat-*.json")) if d.is_dir() else []


def _drill_chat(path):
    st = path.stat()
    hit = _WELLS.get(path)
    if hit and hit[:2] == (st.st_mtime, st.st_size):
        return hit[2]
    try:
        msgs = json.loads(path.read_text()).get("messages", [])
    except (OSError, json.JSONDecodeError):
        msgs = []
    users = [m["content"] for m in msgs if m.get("role") == "user" and isinstance(m.get("content"), str)]
    barrels = [{"idea": " ".join(prev.split())[:220], "why": f"taken back: \"{m.group(0)}\"", "where": path.stem,
                "when": path.stem[5:15]}
               for prev, cur in zip(users, users[1:])
               if (m := SCRAP.search(cur)) and prev.strip() and not prev.startswith("/")]
    _WELLS[path] = (st.st_mtime, st.st_size, barrels)
    return barrels


def drill(chats_dir=None):
    """Every scrapped idea Seahorse can find: [{"idea", "why", "where", "when"}], oldest first."""
    oil = [b for p in _chats(chats_dir) for b in _drill_chat(p)]
    data = _load()
    oil += [{"idea": f["text"], "why": f"bottle washed ashore on Atlantizz ({f.get('ayes', 0)} aye)",
             "where": "the treasury", "when": str(f.get("date", ""))[:10]} for f in data["failed"]]
    oil += [{"idea": g["text"], "why": "goal dropped from the budget", "where": "the marlin", "when": g["when"][:10]}
            for g in data["dropped"]]
    entries, (ok, broken) = _stone(), verify()
    entries = entries if ok else entries[:broken]
    enacted = {e["art"]: e.get("text", "") for e in entries if e.get("action") == "enact"}
    oil += [{"idea": e.get("text") or enacted.get(e["art"], ""), "why": f"Wreck {e['art']} repealed",
             "where": "the reef", "when": str(e.get("date", ""))[:10]} for e in entries if e.get("action") == "repeal"]
    return oil


def refine(query, chats_dir=None, k=3):
    """The oil that best matches the query - the fuel for a request for ideas."""
    q = _words(query)
    scored = [(len(q & _words(o["idea"])), o) for o in drill(chats_dir)] if q else []
    return [o for n, o in sorted(scored, key=lambda t: -t[0]) if n][:k]


def oil_prompt(query, chats_dir=None):
    """Fuel for the prompt: only when the user asks for ideas, and only oil that matches."""
    fuel = refine(query, chats_dir) if query and WANTS_IDEAS.search(query) else []
    return ("Oil from the treasure pockets - ideas the user scrapped in earlier chats. They set these aside for a "
            "reason, so raise one only if it genuinely helps now, and say it was an earlier idea:\n"
            + "\n".join(f"- {o['idea']} ({o['why']}, {o['when']})" for o in fuel)) if fuel else ""


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def pocket_lines(chats_dir=None, detail=False):
    oil = drill(chats_dir)
    pockets = {}
    for o in oil:
        pockets.setdefault(o["where"], []).append(o)
    lines = ["  Treasure pockets - the oil reserves, the blood of the gods: ideas scrapped in past chats.",
             f"    {_plural(len(oil), 'barrel')} of oil in {_plural(len(pockets), 'pocket')}"
             + ("" if oil else " - the reserves are dry; nothing has been scrapped yet")]
    for where, barrels in (sorted(pockets.items(), reverse=True)[:12] if detail else []):
        lines += [f"\n    pocket: {where}"] + [f"      • {o['idea'][:110]}{'…' * (len(o['idea']) > 110)}\n        {o['why']}"
                                               for o in barrels[-5:]]
    return lines


def pockets_text(chats_dir=None, query=""):
    """/pockets - every pocket and its oil; /pockets <words> drills for the oil that matches."""
    if query:
        fuel = [f"    • {o['idea']}\n      {o['why']} · {o['where']} · {o['when']}" for o in refine(query, chats_dir, 10)]
        return "\n".join([f"  ⛁ Drilling the pockets for \"{query}\":"] + (fuel or ["    no oil matches - try other words"]))
    return "\n".join(["  ⛁ Oil is every idea scrapped in a past chat; Seahorse refines it into fuel when you ask for ideas.",
                      ""] + pocket_lines(chats_dir, detail=True) + ["", "  /pockets <words> drills for oil on a topic."])


# ---- the sea under the ship: headroom, the compass, Davy Jones' Locker, the Mariana Trench ----------------------
# Compass: the NEWS - north the bow, east starboard, south the stern, west port, each watched by its horseman.
#   A lightning strike is a magnetic pulse on the instruments: a worker that couldn't take a call. Seahorse
#   then sails by dead reckoning on the next worker.
# Locker: the void at the centre of the earth. Mussels fed on electric-eel blood, wide as satellite dishes,
#   shift between the hemispheres like sand in an hourglass; their pulse churns every current. In Seahorse the
#   pulse is the calls answered and the hourglass is the two lobes, tipping toward the one that carries votes.
# Trench: the Mariana Trench drives the undertow, pulling down whatever is held back. Each thing sinks a tenth
#   of the way; ten reach Challenger Deep. Nothing it takes comes back up into a reply.

CHALLENGER_DEEP = 10_935   # metres
COMPASS = [("N", "the bow"), ("E", "starboard"), ("S", "the stern"), ("W", "port")]


def _bar(frac, on="●", off="○", n=10):
    k = max(0, min(n, round(n * frac)))
    return on * k + off * (n - k)


def _riders():
    """{quarter: crew member} for the four horsemen; {} if the crew can't be read."""
    try:
        import crew
        return {q: m for q, (_a, m) in crew.horsemen().items()}
    except Exception:  # noqa: BLE001 - the horsemen are a nicety in reports
        return {}


def _answered(w):
    return max(0, w["calls"] - w.get("unavailable", 0))


def headroom_lines(power=None, flow=None):
    """Free memory, free disk, and the context the last reply left unused."""
    import shutil
    power, rows = power or {}, []
    ram, ram_total, ctx = power.get("ram"), power.get("ram_total"), power.get("num_ctx")
    if ram and ram_total:
        rows.append(("memory", ram, ram_total, f"{ram:.1f} of {ram_total:.1f} GB free"))
    try:
        d = shutil.disk_usage(Path.home())
        rows.append(("disk", d.free, d.total, f"{d.free / 1e9:.0f} of {d.total / 1e9:.0f} GB free"))
    except OSError:
        pass
    if ctx:
        left = max(0, ctx - (sum(n for _l, n in flow[1]) // 4 if flow else 0))   # ~4 characters to a token
        rows.append(("context", left, ctx, f"~{left:,} of {ctx:,} tokens free after the last prompt"))
    lines = [f"    headroom {name:<7} {_bar(free / total)}  {text}" for name, free, total, text in rows]
    low = [name for name, free, total, _t in rows if free < total * 0.1]
    return lines + (["    running low: " + ", ".join(low)] if low else [])


def compass_lines(workers=None):
    at = {m["horseman"].get("station"): m["name"] for m in _riders().values()}
    strikes = sum(w.get("unavailable", 0) for w in workers or [])
    return ["  Compass - the NEWS: " + " · ".join(f"{p} {at.get(st, st)}" for p, st in COMPASS),
            f"    ⚡ struck by lightning {_plural(strikes, 'time')} - the pulse threw the needle; Seahorse sailed on by "
            "dead reckoning (the next worker took the call)" if strikes else
            "    needle steady - no lightning on the instruments this session"]


def locker_lines(workers=None):
    import lobes
    beats = sum(_answered(w) for w in workers or [])
    hemi = lobes.load_stats().get("hemisphere", {})
    left, right = hemi.get("left", 0), hemi.get("right", 0)
    lean = ("the mussels sit level, half in each hemisphere" if left == right else
            f"the mussels are massing in the {'left' if left > right else 'right'} hemisphere")
    return ["  Davy Jones' Locker - the void at the centre of the earth, which churns the currents:",
            "    mussels fed on electric-eel blood, each as wide as a satellite dish, shift between the",
            "    hemispheres like sand in a giant hourglass. Their pulse at the core drives every current.",
            f"    pulse      {beats} beats (calls the workers answered this session)" + (" - still" if not beats else ""),
            f"    hourglass  left ◀ {_bar(left / (left + right) if left + right else 0.5, '█', '░')} ▶ right   "
            f"left lobe carried {left} · right lobe carried {right}",
            f"               {lean}"]


def trench_lines(data=None, memory=None, workers=None):
    data, blocked = data or _load(), 0
    if memory is not None:
        try:
            blocked = memory.db.execute("SELECT COUNT(*) FROM memory_log WHERE action='blocked'").fetchone()[0]
        except Exception:  # noqa: BLE001 - the count is a nicety
            pass
    down, ashore = sum(w.get("unavailable", 0) for w in workers or []), len(data.get("failed", []))
    pulled = down + blocked + ashore
    depth = min(CHALLENGER_DEEP, round(pulled * CHALLENGER_DEEP / 10))
    zone = next(z for d, z in ((CHALLENGER_DEEP, "resting on the floor of Challenger Deep"),
                               (6_000, "in the hadal zone, the trench's own water"), (4_000, "in the abyss"),
                               (1_000, "in the midnight zone"), (1, "in the twilight zone"),
                               (0, "still in the sunlight zone, nothing pulled under")) if depth >= d)
    return ["  Undertow - the Mariana Trench pulls under whatever is held back:",
            f"    calls a worker couldn't take (sent on to the next): {down}",
            f"    secrets (passwords, keys, card numbers) refused by memory: {blocked}",
            f"    bottles voted down and washed ashore on Atlantizz: {ashore}",
            "    chats saved under the old incognito mode: excluded from training and your profile",
            f"    depth  {_bar(pulled / 10, '▼', '·')}  {depth:,} m of {CHALLENGER_DEEP:,} m - {zone}"]


REPORTS = {   # /name -> (heading, lines(memory, workers), footer)
    "trench": ("⌄ The Mariana Trench - the source of the undertow. Nothing it takes comes back up into a reply.",
               lambda memory, workers: trench_lines(None, memory, workers), ""),
    "compass": ("🧭 The compass", lambda memory, workers: compass_lines(workers), ""),
    "locker": ("⧗ Davy Jones' Locker", lambda memory, workers: locker_lines(workers),
               "(The currents it drives are in /trident; the undertow it feeds is in /trench.)"),
}


def report(name, memory=None, workers=None):
    """/trench, /compass, /locker - one part of the sea on its own."""
    head, body, foot = REPORTS[name]
    return "\n".join([f"  {head}", ""] + body(memory, workers) + ([f"", f"  {foot}"] if foot else []))


def trident_text(flow=None, memory=None, power=None, workers=None, order=None):
    """Poseidon's Trident - the working class: the processing power, and how the work is distributed."""
    data = _load()
    power, workers, order = power or {}, workers or [], order or []
    ram, loaded = power.get("ram"), power.get("loaded") or []
    lines = ["  Ψ Poseidon's Trident - his most powerful asset, his bread and butter. The working class: the",
             "    processing power that does the crew's work, and how that work is distributed. Its prongs are",
             "    currents (distribution), undertow (what is held back, pulled down by the Mariana Trench)",
             "    and the flow of information.", "",
             "  Processing power:",
             f"    CPU     {power.get('cpu', '?')}",
             f"    memory  {f'{ram:.1f} GB free' if ram else 'unknown'}",
             f"    GPU     {power.get('gpu', '?')}",
             f"    local   context window {power.get('context', '?')} · "
             f"{'lobes vote in parallel' if power.get('parallel', True) else 'lobes vote one after the other'}",
             "    loaded  " + (", ".join(loaded) if loaded else "no local model loaded right now")]
    lines += headroom_lines(power, flow)
    lines += [""] + locker_lines(workers) + [""] + compass_lines(workers) + [""] + pocket_lines()
    lines += ["", "  Currents - how the work is distributed:"]
    total = sum(_answered(w) for w in workers)
    for w in workers:
        n = _answered(w)
        rate = f" · {w['chars'] / w['seconds']:.0f} chars/s" if w["seconds"] > 0.5 and w["chars"] else ""
        missed = f" · couldn't take {w['unavailable']}" if w.get("unavailable") else ""
        lines.append(f"    {w['name']:<32} {n:>4} calls answered ({n / total if total else 0:.0%}) · "
                     f"{w['chars']:,} chars produced{rate}{missed}")
    if not total:
        lines.append("    no calls yet this session")
    carried = sorted(((a, data["shillings"].get(a, {}).get("work", 0)) for a in order), key=lambda kv: -kv[1])
    busy = [f"{shilling(a, order)} {a} {n}" for a, n in carried if n][:6]
    lines.append("    work carried by the crew: " + (" · ".join(busy) or "none yet"))
    lines += [""] + trench_lines(data, memory, workers)
    lines += ["", "  Flow of information - the data that reached the last reply:"]
    if flow:
        agent, parts = flow
        total_chars = sum(n for _l, n in parts) or 1
        lines.append(f"    to {agent}: {total_chars:,} characters in all")
        lines += [f"    {label:<28} {n:>7,}  {'█' * max(1, round(24 * n / total_chars))}"
                  for label, n in sorted(parts, key=lambda kv: -kv[1])]
    else:
        lines.append("    nothing yet - send a message, then look again")
    return "\n".join(lines + ["", "  (The marlin - the people: your goals and the budget - is /budget.)"])
