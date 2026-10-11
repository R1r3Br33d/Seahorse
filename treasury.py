#!/usr/bin/env python3
"""
treasury.py - the ship's treasury: pennies, dimes and the dollar.

    PENNIES   Each of the ten agents is a penny, numbered by council seat:
              ¢01 is seat 01 (the captain) ... ¢10 is seat 10 (the Judge).
              Every ballot an agent casts and every piece of work it carries
              is counted in pennies.
    WORK      Moves through the agents one by one, penny to penny, in a relay.
    DIMES     Ten pennies make a dime, and a dime is a LAW. You propose a rule
              (/law <text>); all ten pennies vote aye or nay in seat order; when
              the ayes reach a full dime (all ten, by default) the Treasurer
              mints it.
    A BILL    A single amendment: one proposed change, put to the pennies with
              /law <text>. A bill that passes is minted as a dime and becomes law.
    CONSTITUTION  The amendments that became law, up to ten. Every agent follows
              them. A full constitution takes no more until one is repealed
              (/law repeal <n>).
    DOLLAR    POSEIDON'S TRIDENT: the oceanic army, the Atlantean control of
              currents, undertow and the flow of information (data). It is the
              people - you, your goals, direction and future - and every coin
              serves it. Its three prongs:
                currents   where the crew's effort flows: your goals and the budget
                undertow   what is pulled under and kept out of circulation:
                           secrets never stored, laws voted down, chats excluded
                flow       the flow of information: how much data, from which
                           source, reaches each reply (/trident)
    BUDGET    How the dollar's 100 cents are split across your goals (/budget).
              Every penny of work the crew carries is counted against the goal
              it served, so the Treasurer can show what was spent where.
    TREASURER The Judge keeps the ledger, counts every vote, mints the dimes and
              keeps the budget.

The constitution never outranks Seahorse's core values or the core character
rules: honesty, your wellbeing, safety. A law that conflicts with them is
voted down, and the prompt says plainly that they win. Ledger:
~/.seahorse/treasury.json.
"""

import json
import re
from datetime import datetime
from pathlib import Path

LEDGER = Path.home() / ".seahorse" / "treasury.json"
TREASURER = "judge"
DIME = 10          # pennies in a dime
AMENDMENTS = 10    # amendments the constitution holds (a bill is a single amendment)
CENTS = 100        # the dollar: the people - your goals, direction and future
DEFAULTS = {"law_threshold": 10}   # ayes needed to mint a law (10 = a full dime)


def _load():
    try:
        data = json.loads(LEDGER.read_text())
    except (OSError, json.JSONDecodeError):
        data = {}
    data.setdefault("pennies", {})
    data.setdefault("laws", [])
    data.setdefault("failed", [])
    data.setdefault("next_id", 1)
    data.setdefault("goals", [])        # the dollar: [{"text", "cents", "spent", "added"}]
    data.setdefault("general", 0)       # pennies of work that served no listed goal
    return data


def _save(data):
    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LEDGER.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    except OSError:
        pass


def penny(agent, order):
    """An agent's penny label from its council seat: '¢07'."""
    return f"¢{order.index(agent) + 1:02d}" if agent in order else "¢--"


# ---------------------------------------------------------------------------
# The ledger: pennies cast and carried
# ---------------------------------------------------------------------------
def record_votes(voters):
    data = _load()
    for a in voters:
        p = data["pennies"].setdefault(a, {"votes": 0, "work": 0})
        p["votes"] += 1
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
    """A penny of work carried by `agent`, spent on the goal it served (or general upkeep)."""
    data = _load()
    p = data["pennies"].setdefault(agent, {"votes": 0, "work": 0})
    p["work"] += 1
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
# The dollar (the people) and the budget
# ---------------------------------------------------------------------------
def goals():
    return _load()["goals"]


def _rebalance(gs):
    """Keep the budget at exactly 100 cents: goals without a fixed share split what's left evenly."""
    fixed = [g for g in gs if g.get("fixed")]
    free = [g for g in gs if not g.get("fixed")]
    left = max(0, CENTS - sum(g["cents"] for g in fixed))
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
    if cents < 0 or cents + others > CENTS:
        return f"that's more than the dollar: {CENTS - others}¢ is free"
    data["goals"][n - 1].update(cents=cents, fixed=True)
    _rebalance(data["goals"])
    _save(data)
    return None


def dollar_prompt():
    """The people, for every agent's prompt: what the user is working toward."""
    gs = goals()
    if not gs:
        return ""
    lines = ["Poseidon's Trident (the dollar) - the person you serve: their goals, direction and future, with the "
             "share of the crew's effort they've budgeted to each. These are the currents the crew moves on. Keep "
             "them in mind; where it genuinely helps, connect your answer to them. Never push the goals on the "
             "person or bring them up when they don't fit."]
    lines += [f"- {g['text']} ({g['cents']}¢)" for g in gs]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dimes: laws
# ---------------------------------------------------------------------------
def law_prompt(text, order, laws):
    current = "\n".join(f"{i}. {l['text']}" for i, l in enumerate(laws, 1)) or "(none yet)"
    seats = ", ".join(f"{penny(a, order)} {a}" for a in order)
    return (f"A law has been proposed for the crew's constitution:\n\"{text[:600]}\"\n\n"
            f"Laws already in the constitution:\n{current}\n\n"
            f"Vote as each of the ten agents of Seahorse's mind, in seat order: {seats}.\n"
            "Each votes aye or nay from its own role, with one short reason. Vote nay if the law would conflict "
            "with Seahorse's core values (honesty, the user's real wellbeing, safety, never inventing facts), with "
            "the core character rules, with an existing law, or if it is too vague to follow. Otherwise judge it on "
            "whether it would make the crew better at serving the user.\n"
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
    return {a: got[a] for a in order if a in got}   # in seat order; missing pennies abstain


def count(votes, threshold):
    """The Treasurer's count: (ayes, nays, minted?)."""
    ayes = sum(1 for v, _ in votes.values() if v == "aye")
    nays = sum(1 for v, _ in votes.values() if v == "nay")
    return ayes, nays, ayes >= threshold


def propose(text, votes, threshold):
    """Record the outcome. Returns (status, law) - status: minted, failed, full or empty."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return "empty", None
    data = _load()
    ayes, nays, ok = count(votes, threshold)
    entry = {"id": data["next_id"], "text": text[:400], "ayes": ayes, "nays": nays,
             "date": datetime.now().strftime("%Y-%m-%d"),
             "votes": {a: v for a, (v, _r) in votes.items()}}
    if ok and len(data["laws"]) >= AMENDMENTS:
        return "full", entry
    data["next_id"] += 1
    if ok:
        data["laws"].append(entry)
    else:
        data["failed"] = (data["failed"] + [entry])[-20:]
    record = data
    _save(record)
    return ("minted" if ok else "failed"), entry


def laws():
    return _load()["laws"]


def repeal(n):
    data = _load()
    if 1 <= n <= len(data["laws"]):
        gone = data["laws"].pop(n - 1)
        _save(data)
        return gone
    return None


def constitution_prompt():
    """The constitution for every agent's system prompt (empty when there are no laws)."""
    ls = laws()
    if not ls:
        return ""
    lines = [f"The crew's constitution: amendments the full council passed into law, {len(ls)} of {AMENDMENTS}. Follow "
             "them in every reply. They never outrank your core values or the core character rules; if one ever "
             "seems to conflict with those, the core values win."]
    lines += [f"{i}. {l['text']}" for i, l in enumerate(ls, 1)]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------
def vote_lines(text, votes, threshold, status, order):
    ayes, nays, _ = count(votes, threshold)
    out = [f"bill (a single amendment): \"{text}\""]
    out += [f"{penny(a, order)} {a}: {v}{' - ' + r if r else ''}" for a, (v, r) in votes.items()]
    missing = [a for a in order if a not in votes]
    if missing:
        out.append("abstained: " + ", ".join(f"{penny(a, order)} {a}" for a in missing))
    verdict = {"minted": f"a full dime: the Treasurer mints it as amendment {len(laws())} of the constitution",
               "failed": f"short of the {threshold} pennies needed: the bill fails, no dime is minted",
               "full": "a dime, but the constitution is full: repeal an amendment first (/law repeal <n>)",
               "empty": "nothing to vote on"}[status]
    out.append(f"Treasurer's count: {ayes} aye · {nays} nay → {verdict}")
    return out


def describe(order, threshold=DIME):
    data = _load()
    ls = data["laws"]
    lines = [f"  Treasurer: {TREASURER} · a bill needs {threshold} of {DIME} pennies to become law · the constitution "
             f"holds {len(ls)}/{AMENDMENTS} amendments",
             "", "  Pennies (by seat):"]
    for a in order:
        p = data["pennies"].get(a, {"votes": 0, "work": 0})
        tag = "  Treasurer" if a == TREASURER else ""
        lines.append(f"    {penny(a, order)} {a:<12} {p['votes']:>4} votes cast · {p['work']:>3} pieces of work carried{tag}")
    lines += ["", "  The constitution (amendments in force):"]
    lines += [f"    {i}. {l['text']}  ({l['ayes']} aye, {l['date']})" for i, l in enumerate(ls, 1)] or ["    (no laws yet - propose one with /law <text>)"]
    if data["failed"]:
        last = data["failed"][-1]
        lines += ["", f"  Last failed proposal: \"{last['text']}\" ({last['ayes']} aye, {last['nays']} nay)"]
    lines += ["", budget_text()]
    return "\n".join(lines)


def budget_text():
    """What's in the budget: the dollar's 100 cents across your goals, and the pennies spent on each."""
    data = _load()
    gs = data["goals"]
    total = sum(g.get("spent", 0) for g in gs) + data["general"]
    lines = ["  Currents - Poseidon's Trident (the dollar: your goals, direction, future) and the budget:"]
    if not gs:
        lines.append("    nothing budgeted yet - add a goal with /budget add <goal>; the dollar's 100¢ split across them")
    for i, g in enumerate(gs, 1):
        spent = g.get("spent", 0)
        share = f"{spent / total:.0%}" if total else "0%"
        who = ", ".join(f"{a} {n}" for a, n in sorted(g.get("by", {}).items(), key=lambda kv: -kv[1])[:3])
        lines.append(f"    {i}. {g['text']:<40} budget {g['cents']:>3}¢{' (fixed)' if g.get('fixed') else ''}"
                     f" · spent {spent} {'penny' if spent == 1 else 'pennies'} ({share} of the work){' · ' + who if who else ''}")
    lines.append(f"    general upkeep (work for no listed goal): {data['general']} "
                 f"{'penny' if data['general'] == 1 else 'pennies'}")
    return "\n".join(lines)


def trident_text(flow=None, memory=None):
    """Poseidon's Trident: the three prongs - currents, undertow and the flow of information."""
    data = _load()
    lines = ["  Ψ Poseidon's Trident - the oceanic army: the Atlantean control of currents, undertow and the flow of",
             "    information. It is the dollar: the people, and every coin of the treasury serves it.", "",
             budget_text(), "", "  Undertow - what is pulled under and kept out of circulation:"]
    blocked = 0
    if memory is not None:
        try:
            blocked = memory.db.execute("SELECT COUNT(*) FROM memory_log WHERE action='blocked'").fetchone()[0]
        except Exception:  # noqa: BLE001 - the count is a nicety
            blocked = 0
    lines += [f"    secrets (passwords, keys, card numbers) refused by memory: {blocked}",
              f"    bills voted down and kept out of the constitution: {len(data['failed'])}",
              "    chats saved under the old incognito mode: excluded from training and your profile",
              "", "  Flow of information - the data that reached the last reply:"]
    if flow:
        agent, parts = flow
        total = sum(n for _l, n in parts) or 1
        lines.append(f"    to {agent}: {total:,} characters in all")
        for label, n in sorted(parts, key=lambda kv: -kv[1]):
            bar = "█" * max(1, round(24 * n / total))
            lines.append(f"    {label:<28} {n:>7,}  {bar}")
    else:
        lines.append("    nothing yet - send a message, then look again")
    return "\n".join(lines)
