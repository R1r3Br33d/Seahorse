#!/usr/bin/env python3
"""
council.py - the council: how all ten agents decide who answers, in auto mode.

1. THE VOTE (instant, no model call)
   Every agent sizes up the message and stakes a claim: its trigger words,
   what routing has learned from your own @picks, what its lens noticed, and
   whether this is a follow-up to the agent already working. Then all ten
   vote. Each votes for the agent with the strongest claim as it sees it
   (an agent with a real claim of its own backs itself). The captain
   votes for continuity on short follow-ups. Most votes leads.

2. THE RELAY (progressional continuation)
   When more than one agent has a strong claim ("look into the evidence and
   write it up as an email"), the work is passed hand to hand in the order
   a ship works: research, measures and numbers, planning, building,
   security, teaching, writing, review. Each step builds on the progress
   before it; the last agent delivers the answer. Up to `council_steps`.

3. THE APPROVAL STEP (between handoffs)
   Before work passes on, three agents vote on it in one short call: the
   next agent in the relay (do I have what I need?), the Bosun (cingulate:
   is it right?) and the Judge (is it sound?). With enough approvals the
   relay continues; otherwise the step is revised once with their notes.
   It never stalls: if a step still isn't approved, the concerns travel
   forward with the work so the next agent can deal with them.

Most messages have one clear owner, so the council costs nothing: one
step, no approval call. Stats: ~/.seahorse/council.json (/council).
"""

import json
import re
from pathlib import Path

STATS_FILE = Path.home() / ".seahorse" / "council.json"
CAPTAIN = "hippocampus"

# The order a ship works in: a relay always runs in this order.
PIPELINE = ["doc", "judge", "parietal", "prefrontal", "cerebellum", "fiery-black", "wernicke", "broca", "cingulate",
            CAPTAIN]

# What each agent contributes as one step of a relay.
PART = {
    "doc": "establish the facts: what is known, what is debated, and what's uncertain",
    "judge": "weigh the options, settle units and measurements, and give a reasoned verdict",
    "parietal": "work out the numbers exactly, with the key steps",
    "prefrontal": "turn it into an ordered plan with the first action",
    "cerebellum": "build the technical part: complete, working code or procedure",
    "fiery-black": "check it for security risks and give the fixes (defensive only)",
    "wernicke": "make it understandable: explain the key ideas simply",
    "broca": "write it up as polished text ready to send or publish",
    "cingulate": "review it candidly: the most important problems and how to fix them",
    CAPTAIN: "answer as Seahorse himself, drawing it all together",
}

DEFAULTS = {
    "council": True,            # the council decides who answers in auto mode
    "council_steps": 3,         # most agents in one relay (1 = never relay)
    "council_approval": True,   # approval vote between relay steps
    "council_threshold": 0.66,  # share of approvers needed to continue
    "council_revisions": 1,     # revisions allowed when a step isn't approved
}

# The council table and the voting sequence:
#      ^ .01.02.03.04.05      votes run left to right along the top row,
#     1+ .10.09.08.07.06      then turn and run right to left along the bottom,
# so seat 10 ends beside seat 01, and "1+" hands back to seat 01 for a casting
# vote that is used only to break a tie. /council seat <n> <agent> reseats them.
SEATS = ["hippocampus", "doc", "parietal", "cerebellum", "prefrontal",      # 01-05, top row, left to right
         "wernicke", "broca", "cingulate", "fiery-black", "judge"]          # 06-10, bottom row, right to left

SELF_BIAS = 1.5       # an agent with a real claim backs itself
CLAIM_FLOOR = 0.34    # below this an agent doesn't put itself forward
RELAY_CLAIM = 0.5     # a second agent needs this much claim to join a relay
FOLLOW_UP_CHARS = 80


# ---------------------------------------------------------------------------
# Claims and ballots (pure functions - easy to test)
# ---------------------------------------------------------------------------
def claims(agents, text, router_pick=None, perceived=None, previous=None, follow_up=False):
    """How strongly each agent claims this message, 0 to ~1.5. Returns {name: (claim, reasons)}."""
    out = {}
    for name, agent in agents.items():
        hits = agent.score(text)
        noticed = len((perceived or {}).get(name, []))
        c, why = 0.0, []
        if hits:
            c += min(hits, 3) / 3
            why.append(f"{hits} trigger{'s' if hits > 1 else ''}")
        if router_pick and router_pick[0] == name:
            c += 0.6 * router_pick[1]
            why.append(f"learned from your picks ({router_pick[1]:.0%})")
        if noticed and name != CAPTAIN:
            c += 0.25 * min(noticed, 4) / 4
            why.append(f"noticed {noticed}")
        if follow_up and previous == name:
            c += 0.35
            why.append("already on it")
        if name == CAPTAIN:
            c = max(c, 0.25)   # the generalist always has some claim
            why = why or ["generalist"]
        out[name] = (round(c, 3), why)
    return out


def seating(agents, seats=None):
    """The voting order: seats 01-10 as set (missing agents skipped), then any agents of your own."""
    order = [a for a in (seats or SEATS) if a in agents]
    return order + sorted(a for a in agents if a not in order)


def ballots(claim_map, follow_up=False, previous=None, order=None):
    """Votes cast one at a time in seat order: {voter: candidate} (insertion order = the sequence).

    An agent with a real claim of its own backs itself; the rest back the strongest claim, and when
    claims are level they back whoever is leading the votes cast so far. Order matters.
    """
    votes, running = {}, {}
    for voter in (order or list(claim_map)):
        if voter not in claim_map:
            continue
        if voter == CAPTAIN and follow_up and previous in claim_map:
            pick = previous                   # the captain keeps whoever is already working
        else:
            seen = {}
            for cand, (c, _why) in claim_map.items():
                seen[cand] = c * SELF_BIAS if cand == voter and c >= CLAIM_FLOOR else c
            best = max(seen.values())
            top = [cand for cand, c in seen.items() if abs(c - best) < 1e-9]
            if best < CLAIM_FLOOR or (CAPTAIN in top and len(top) == 1):
                pick = CAPTAIN
            else:   # level claims: follow the running leader, else the earliest seat
                seq = order or list(claim_map)
                pick = max(top, key=lambda c: (running.get(c, 0), -seq.index(c) if c in seq else -99))
        votes[voter] = pick
        running[pick] = running.get(pick, 0) + 1
    return votes


def tally(votes, claim_map=None, order=None):
    """(ranked [(candidate, votes)], casting) - on a tie for first, seat 01 casts the deciding vote (1+)."""
    counts = {}
    for cand in votes.values():
        counts[cand] = counts.get(cand, 0) + 1
    seq = order or list(votes)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], seq.index(kv[0]) if kv[0] in seq else 99))
    casting = None
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        tied = [c for c, n in ranked if n == ranked[0][1]]
        cm = claim_map or {}
        casting = max(tied, key=lambda c: (cm.get(c, (0,))[0], -(seq.index(c) if c in seq else 99)))
        ranked = [(casting, counts[casting])] + [kv for kv in ranked if kv[0] != casting]
    return ranked, casting


def relay(lead, claim_map, max_steps):
    """The relay: the lead plus any other agent with a strong claim, in pipeline order."""
    if max_steps <= 1:
        return [lead]
    members = {lead} | {n for n, (c, _w) in claim_map.items() if c >= RELAY_CLAIM and n != CAPTAIN}
    if len(members) == 1:
        return [lead]
    order = sorted(members, key=lambda n: PIPELINE.index(n) if n in PIPELINE else len(PIPELINE))
    if len(order) > max_steps:   # keep the lead and the strongest others
        others = sorted((n for n in order if n != lead), key=lambda n: -claim_map[n][0])[: max_steps - 1]
        order = [n for n in order if n == lead or n in others]
    return order


class Decision:
    def __init__(self, lead, votes, ranked, claim_map, steps, order=None, casting=None):
        self.lead, self.votes, self.ranked, self.claims, self.steps = lead, votes, ranked, claim_map, steps
        self.order, self.casting = order or list(votes), casting

    def table(self):
        """The council table as voted: top row 01-05, bottom row 10-06 (as the seats sit)."""
        seat = {a: i + 1 for i, a in enumerate(self.order)}
        cell = lambda a: f"{seat[a]:02d} {a}›{self.votes.get(a, '-')}"
        top = [cell(a) for a in self.order[:5]]
        bottom = [cell(a) for a in reversed(self.order[5:10])]
        rows = ["^  " + " · ".join(top), "1+ " + " · ".join(bottom)]
        extra = self.order[10:]
        if extra:
            rows.append("   then " + " · ".join(cell(a) for a in extra))
        return rows

    def lines(self):
        top = self.ranked[0]
        out = [f"lead: {self.lead} · {top[1]} of {len(self.votes)} votes"
               + (f" · tie broken by seat 01's casting vote (1+)" if self.casting else "")]
        out.append("votes: " + " · ".join(f"{n} {c}" for n, c in self.ranked))
        out += self.table()
        why = [f"{n}: {', '.join(self.claims[n][1])}" for n in self.steps if self.claims[n][1]]
        if why:
            out.append("why: " + " | ".join(why))
        if len(self.steps) > 1:
            out.append("relay: " + " → ".join(self.steps))
        return out


def decide(agents, text, router_pick=None, perceived=None, previous=None, has_history=False, max_steps=3,
           seats=None):
    follow_up = bool(has_history and previous and len(text) < FOLLOW_UP_CHARS)
    cm = claims(agents, text, router_pick, perceived, previous, follow_up)
    order = seating(agents, seats)
    votes = ballots(cm, follow_up, previous, order)
    ranked, casting = tally(votes, cm, order)
    lead = ranked[0][0]
    steps = relay(lead, cm, max_steps) if not follow_up else [lead]
    return Decision(lead, votes, ranked, cm, steps, order, casting)


def seat_chart(seats=None):
    """The seating chart for display."""
    s = list(seats or SEATS)
    top = " ".join(f"{i + 1:02d} {a}" for i, a in enumerate(s[:5]))
    bottom = " ".join(f"{10 - i:02d} {a}" for i, a in enumerate(reversed(s[5:10]))) if len(s) > 5 else ""
    return [f"  ^  {top}", f"  1+ {bottom}", "  votes run 01→05 along the top, then 06→10 back along the bottom; on a tie, "
            "seat 01 casts the deciding vote (1+)"]


def reseat(seats, n, agent):
    """Put `agent` in seat n (1-10); whoever sat there takes the agent's old seat."""
    s = list(seats or SEATS)
    if agent in s:
        i = s.index(agent)
        s[i], s[n - 1] = s[n - 1], agent
    else:
        s[n - 1] = agent
    return s


# ---------------------------------------------------------------------------
# The approval step
# ---------------------------------------------------------------------------
def approvers(step_agent, next_agent, seats=None):
    """Who approves a handoff: the next agent, the Bosun and the Judge (the captain stands in for an author).
    They vote in seat order."""
    out = [next_agent]
    for a in ("cingulate", "judge"):
        out.append(CAPTAIN if a == step_agent else a)
    seq = list(seats or SEATS)
    unique = list(dict.fromkeys(out))
    return sorted(unique, key=lambda a: seq.index(a) if a in seq else len(seq))


def approval_prompt(user_text, step_agent, part, work, next_agent, voters):
    who = ", ".join(voters)
    return (f"The user asked:\n{user_text[:3000]}\n\n"
            f"Step by {step_agent} (their part: {part}):\n{work[:6000]}\n\n"
            f"Next, {next_agent} continues from this work. Vote as each of these agents of Seahorse's mind: {who}.\n"
            f"- {next_agent}: does this give you what you need to continue?\n"
            "- cingulate (the Bosun): is it correct and complete for its part?\n"
            "- judge: is the reasoning sound and are any numbers and units right?\n"
            "(hippocampus, if listed, judges it as the captain.)\n"
            'Reply with ONLY JSON: {"votes": [{"agent": "<name>", "vote": "approve" or "revise", '
            '"note": "<one short sentence; for revise, exactly what to fix>"}]}')


def parse_approval(text, voters):
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    try:
        data = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        data = {}
    got = {}
    for v in data.get("votes", []) if isinstance(data, dict) else []:
        if isinstance(v, dict) and v.get("agent") in voters and v["agent"] not in got:
            vote = "revise" if str(v.get("vote", "")).lower().startswith("rev") else "approve"
            got[v["agent"]] = (vote, re.sub(r"\s+", " ", str(v.get("note", ""))).strip()[:200])
    return got   # voters that didn't vote abstain


def approved(votes, voters, threshold):
    """Approved when approvals reach the threshold among those who voted (abstentions don't block)."""
    cast = [v for a, v in votes.items() if a in voters]
    if not cast:
        return True
    yes = sum(1 for vote, _n in cast if vote == "approve")
    return yes / len(cast) >= threshold - 1e-9


def approval_line(step_no, step_agent, votes, ok, revised):
    marks = " · ".join(f"{a} {'✓' if v == 'approve' else '✗'}{': ' + n if v != 'approve' and n else ''}"
                       for a, (v, n) in votes.items()) or "no votes (abstained)"
    state = "approved" if ok else ("carried forward with concerns" if revised else "sent back for revision")
    return f"step {step_no} ({step_agent}) {state} · {marks}"


# ---------------------------------------------------------------------------
# Prompts for the relay
# ---------------------------------------------------------------------------
def step_prompt(user_text, step_no, total, agent, next_agent, progress, concerns="", revise_notes=""):
    parts = [f"The user's message:\n{user_text}", ""]
    if progress:
        parts += ["Progress so far from the crew:", progress, ""]
    if concerns:
        parts += ["Open concerns passed forward (deal with them):", concerns, ""]
    if revise_notes:
        parts += ["Your previous attempt was sent back. Fix exactly this:", revise_notes, ""]
    parts += [f"You are step {step_no} of {total} in a relay among Seahorse's agents. Your part: "
              f"{PART.get(agent, 'your specialty')}. Do only your part, well and concisely; {next_agent} continues "
              "from your work next. Write working notes and results for them, not a reply to the user."]
    return "\n".join(parts)


def final_notes(progress, concerns):
    if not progress:
        return ""
    text = ("\n\nYour crew has already worked on this message in a relay. Build on their progress below: keep "
            "what's right, fix what isn't, and deliver the final answer yourself, in your own voice. Don't mention "
            "the relay unless asked.\n" + progress)
    if concerns:
        text += "\n\nConcerns still open from the approval votes (resolve them):\n" + concerns
    return text


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
def load_stats():
    try:
        return json.loads(STATS_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {"votes": 0, "leads": {}, "relays": 0, "steps": 0, "approvals": 0, "sent_back": 0, "carried": 0,
                "unanimous": 0, "last": None}


def record(decision=None, **counts):
    s = load_stats()
    if decision:
        s["votes"] = s.get("votes", 0) + 1
        s.setdefault("leads", {})[decision.lead] = s["leads"].get(decision.lead, 0) + 1
        if decision.ranked[0][1] == len(decision.votes):
            s["unanimous"] = s.get("unanimous", 0) + 1
        if len(decision.steps) > 1:
            s["relays"] = s.get("relays", 0) + 1
            s["steps"] = s.get("steps", 0) + len(decision.steps)
        s["last"] = decision.lines()
    for k, v in counts.items():
        s[k] = s.get(k, 0) + v
    try:
        STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATS_FILE.write_text(json.dumps(s))
    except OSError:
        pass


def describe_stats():
    s = load_stats()
    n = s.get("votes", 0)
    if not n:
        return "  No council votes yet. In auto mode, every message you send is voted on by all ten agents."
    leads = ", ".join(f"{k} {v}" for k, v in sorted(s.get("leads", {}).items(), key=lambda kv: -kv[1]))
    lines = [f"  {n} votes · {s.get('unanimous', 0)} unanimous · {s.get('relays', 0)} relays "
             f"({s.get('steps', 0)} steps) · handoffs approved {s.get('approvals', 0)}, sent back "
             f"{s.get('sent_back', 0)}, carried with concerns {s.get('carried', 0)}",
             f"  leads: {leads}"]
    if s.get("last"):
        lines.append("  last vote:")
        lines += [f"    {line}" for line in s["last"]]
    return "\n".join(lines)


def reset_stats():
    try:
        STATS_FILE.unlink()
    except OSError:
        pass
