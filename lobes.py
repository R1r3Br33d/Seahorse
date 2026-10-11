#!/usr/bin/env python3
"""
lobes.py - the lobe vote: how Doc (left) and Fiery Black (right) advise the core.

When Seahorse himself answers a substantial message, both lobes read it AT
THE SAME TIME and each casts a short, structured ballot:

    {"vote": "explain", "confidence": 0.8,
     "points": ["...", "..."],     # up to 3 things the answer must get right
     "warning": "...",             # a risk or factual caution, or ""
     "view": "..."}                # their party's view, only on a political question

The ballots are tallied:
  - Weights: each vote counts weight x confidence. Balance 'left' or 'right'
    gives that lobe 1.25 and the other 0.8 ('even' is 1 and 1).
  - unanimous: both lobes chose the same approach. Done - no Judge needed.
  - majority:  they differ, but one side wins by at least the margin. Done.
  - split:     too close to call. The Judge breaks the tie with one short
    ruling between the two approaches (or the higher score wins if the Judge
    is off).
  - veto:      either lobe calling the question contested ('balance') wins
    outright, so Seahorse never takes a political side by a vote.
  - A losing 'caution' vote with confidence 0.6 or more still becomes a
    must-mention, so a real risk is never outvoted into silence.
  - A lobe that times out or returns something unreadable abstains; the
    other lobe's ballot stands.

Why it's fast: two calls in parallel instead of three in a row, small slim
prompts (no memory or persona), a hard cap on ballot length, JSON mode on
Ollama, a time limit, the Judge only on a close split, and a small cache so
asking the same thing again costs nothing. Stats live in ~/.seahorse/lobes.json
(/lobes stats).
"""

import hashlib
import json
import re
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path

STATS_FILE = Path.home() / ".seahorse" / "lobes.json"

APPROACHES = {
    "direct": "answer straight away, plainly and concisely",
    "explain": "explain step by step, with clear structure and an example",
    "caution": "lead with the risk, safety or security concern, then help",
    "clarify": "ask one short clarifying question before answering in full",
    "balance": "a contested question: set out the strongest case on each side fairly, no verdict",
    "support": "the person needs care or encouragement first, then practical help",
}

LOBES = {
    "left": {"agent": "doc", "label": "left lobe, blue, west",
             "lens": "analysis, language, facts, logic and sequence: what is precisely being asked, the facts and "
                     "definitions that matter, how a good answer should be structured, and any factual caution "
                     "(myths, uncertainty, things beyond your knowledge cutoff)"},
    "right": {"agent": "fiery-black", "label": "right lobe, red, east",
              "lens": "intuition, the big picture, tone and vigilance: what the user may really need or feel beneath "
                      "the words, the wider context, and anything risky or off (security, safety, wellbeing, a bad "
                      "idea)"},
}

BALANCE = {
    "even": {"left": 1.0, "right": 1.0, "say": "Weigh both lobes equally."},
    "left": {"left": 1.25, "right": 0.8, "say": "Lean on the left lobe's precision, with the right lobe as a check."},
    "right": {"left": 0.8, "right": 1.25, "say": "Lean on the right lobe's instinct, with the left lobe as a check."},
}

DEFAULTS = {
    "lobe_min_words": 10,     # shorter messages skip the vote
    "lobe_timeout": 45,       # seconds before a slow lobe abstains
    "lobe_margin": 0.25,      # how far ahead an approach must be to win without the Judge
    "lobe_max_tokens": 220,   # ballot length cap
    "lobe_parallel": True,    # both lobes at once
    "lobe_cache": True,       # reuse the result for an identical conversation
}
CAUTION_FLOOR = 0.6
CACHE_SIZE = 32


class Ballot:
    __slots__ = ("side", "agent", "vote", "confidence", "points", "warning", "view", "ms")

    def __init__(self, side, agent, data, ms=0):
        self.side, self.agent, self.ms = side, agent, ms
        vote = str(data.get("vote", "")).strip().lower()
        self.vote = vote if vote in APPROACHES else _closest(vote)
        try:
            self.confidence = max(0.05, min(1.0, float(data.get("confidence", 0.5))))
        except (TypeError, ValueError):
            self.confidence = 0.5
        pts = data.get("points") or []
        if isinstance(pts, str):
            pts = [pts]
        self.points = [_clip(p, 160) for p in pts if str(p).strip()][:3]
        self.warning = _clip(data.get("warning") or "", 200)
        self.view = _clip(data.get("view") or "", 240)

    def line(self):
        return f"{self.vote} {self.confidence:.2f}"


def _clip(text, n):
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _closest(word):
    """Map a near-miss ('explanation', 'be cautious') onto a ballot option, or None."""
    for key in APPROACHES:
        if key[:4] in word:
            return key
    return None


def parse_ballot(text):
    """The JSON object in a lobe's reply, or None."""
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class Result:
    def __init__(self, approach, how, scores, ballots, ruling=""):
        self.approach, self.how, self.scores, self.ballots, self.ruling = approach, how, scores, ballots, ruling
        self.ms = 0
        self.cached = False

    @property
    def decided(self):
        return self.approach is not None


def tally(ballots, balance="even", margin=DEFAULTS["lobe_margin"]):
    """Count the ballots. Returns a Result whose `how` is unanimous, majority, split, veto, single or none."""
    weights = BALANCE.get(balance, BALANCE["even"])
    valid = [b for b in ballots if b is not None and b.vote]
    scores = {}
    for b in valid:
        scores[b.vote] = scores.get(b.vote, 0.0) + weights[b.side] * b.confidence
    if not valid:
        return Result(None, "none", scores, valid)
    if any(b.vote == "balance" for b in valid):
        return Result("balance", "unanimous" if len(scores) == 1 and len(valid) > 1 else "veto", scores, valid)
    if len(valid) == 1:
        return Result(valid[0].vote, "single", scores, valid)
    if len(scores) == 1:
        return Result(valid[0].vote, "unanimous", scores, valid)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    (top, s1), (_, s2) = ranked[0], ranked[1]
    return Result(top, "majority" if s1 - s2 >= margin else "split", scores, valid)


def must_mention(result):
    """Points, cautions and views the answer has to carry, whatever won."""
    points, cautions, views = [], [], []
    for b in result.ballots:
        for p in b.points:
            if p.lower() not in (x.lower() for x in points):
                points.append(p)
        if b.warning:
            cautions.append(b.warning)
        if b.vote == "caution" and result.approach != "caution" and b.confidence >= CAUTION_FLOOR and not b.warning:
            cautions.append(f"{b.agent} sees a real risk here - name it briefly")
        if b.view:
            views.append((b, b.view))
    return points[:5], cautions[:3], views


def notes_for_core(result, balance="even"):
    """The block added to the core's system prompt."""
    if not result.decided:
        return ""
    points, cautions, views = must_mention(result)
    votes = "; ".join(f"{b.side} {b.line()}" for b in result.ballots)
    lines = ["", "Your two lobes have voted on how to answer the latest message.",
             f"Decision: {result.approach.upper()} - {APPROACHES[result.approach]} ({result.how}; {votes}).",
             BALANCE.get(balance, BALANCE["even"])["say"]]
    if result.ruling:
        lines.append(f"The Judge broke the tie: {result.ruling}")
    if points:
        lines += ["Points the answer must get right:"] + [f"- {p}" for p in points]
    if cautions:
        lines += ["Cautions to carry:"] + [f"- {c}" for c in cautions]
    if views or result.approach == "balance":
        lines += [f"- {b.agent} ({'Democrat' if b.side == 'left' else 'Republican'}): {v}" for b, v in views]
        lines.append("Doc is a Democrat and Fiery Black a Republican: on a political question, set out both views "
                     "fairly with the strongest case for each, keep your own answer balanced unless the user asks for "
                     "one side, keep the facts straight, and never tell the user how to vote.")
    lines.append("Don't mention the lobes or the vote unless asked.")
    return "\n".join(lines)


def summary_lines(result):
    """Short lines for the display."""
    out = []
    for b in result.ballots:
        extra = f" · {b.warning}" if b.warning else ""
        out.append(f"{b.side:<5} {b.agent}: {b.vote} ({b.confidence:.2f}){extra}")
    tail = f"→ {result.approach} · {result.how}"
    if result.ruling:
        tail += f" · Judge: {result.ruling}"
    tail += " · cached" if result.cached else f" · {result.ms / 1000:.1f}s"
    out.append(tail)
    return out


# ---------------------------------------------------------------------------
# Running the vote
# ---------------------------------------------------------------------------
class LobeVote:
    """Runs one vote for a session. `call(agent, system, prompt, max_tokens)` must be thread-safe."""

    def __init__(self, call, config):
        self.call = call
        self.config = config
        self.cache = OrderedDict()

    def setting(self, key):
        val = self.config.get(key)
        return DEFAULTS[key] if val is None else val

    def ballot_prompt(self, side, recent):
        lobe = LOBES[side]
        options = "\n".join(f"- {k}: {v}" for k, v in APPROACHES.items())
        return (f"Conversation (latest message last):\n{recent}\n\n"
                f"You are the {lobe['label']} of Seahorse's mind. Your lens: {lobe['lens']}.\n"
                f"Cast your ballot on how Seahorse should answer the latest message. Options:\n{options}\n\n"
                "Reply with ONLY this JSON, nothing else:\n"
                '{"vote": "<one option>", "confidence": <0.0 to 1.0>, '
                '"points": ["<up to 3 things the answer must get right, 15 words each at most>"], '
                '"warning": "<a risk or factual caution, or empty>", '
                '"view": "<only if the question is political: your party\'s view in one sentence, else empty>"}\n'
                "Never invent sources or statistics. Defensive only: no exploit details.")

    def judge_prompt(self, recent, result):
        a, b = sorted(result.scores, key=lambda k: -result.scores[k])[:2]
        reasons = "\n".join(f"- {x.side} lobe ({x.agent}) voted {x.vote} ({x.confidence:.2f}): "
                            f"{'; '.join(x.points) or 'no points'}{' | warning: ' + x.warning if x.warning else ''}"
                            for x in result.ballots)
        return (f"Conversation (latest message last):\n{recent}\n\nThe two lobes split on how to answer:\n{reasons}\n\n"
                f"Rule between '{a}' ({APPROACHES[a]}) and '{b}' ({APPROACHES[b]}), on what the user most needs. "
                'Reply with ONLY this JSON: {"vote": "' + a + '" or "' + b + '", "reason": "<one short sentence>"}')

    def run(self, agents, messages, user_texts, judge_on=True, show=None, spinner=None):
        """Returns a Result, or None when the vote is skipped."""
        texts = user_texts
        if not texts or len(texts[-1].split()) < int(self.setting("lobe_min_words")):
            return None
        recent = "\n\n".join(f"{m['role'].upper()}: {m['content'][:1500]}" for m in messages[-4:])
        balance = self.config.get("lobe_balance", "even")
        key = hashlib.sha1(f"{balance}|{judge_on}|{recent}".encode()).hexdigest()
        if self.setting("lobe_cache") and key in self.cache:
            result = self.cache[key]
            self.cache.move_to_end(key)
            result.cached = True
            record(result)
            return result

        started = time.monotonic()
        limit = float(self.setting("lobe_timeout"))
        max_tokens = int(self.setting("lobe_max_tokens"))
        jobs = {}

        def cast(side):
            agent = agents.get(LOBES[side]["agent"])
            t0 = time.monotonic()
            raw = self.call(agent, agent.slim_system(), self.ballot_prompt(side, recent), max_tokens)
            data = parse_ballot(raw)
            return Ballot(side, agent.name, data, int((time.monotonic() - t0) * 1000)) if data else None

        sides = [s for s in LOBES if agents.get(LOBES[s]["agent"])]
        ballots = []
        cm = spinner("the lobes are voting") if spinner else _null()
        with cm:
            if self.setting("lobe_parallel"):
                # Not a with-block: that would wait for a slow lobe past the time limit.
                pool = ThreadPoolExecutor(max_workers=len(sides) or 1)
                for side in sides:
                    jobs[pool.submit(cast, side)] = side
                done, _ = wait(jobs, timeout=limit)
                for fut in jobs:
                    if fut in done and not fut.exception():
                        ballots.append(fut.result())
                pool.shutdown(wait=False, cancel_futures=True)
            else:
                for side in sides:
                    if time.monotonic() - started > limit:
                        break
                    try:
                        ballots.append(cast(side))
                    except Exception:  # noqa: BLE001 - a failed lobe abstains
                        ballots.append(None)
        ballots = sorted([b for b in ballots if b], key=lambda b: b.side)
        result = tally(ballots, balance, float(self.setting("lobe_margin")))

        judge = agents.get("judge")
        if result.how == "split" and judge_on and judge:
            a, b = sorted(result.scores, key=lambda k: -result.scores[k])[:2]
            with (spinner("the Judge is breaking the tie") if spinner else _null()):
                raw = self.call(judge, judge.slim_system(), self.judge_prompt(recent, result), 120)
            ruling = parse_ballot(raw) or {}
            pick = str(ruling.get("vote", "")).strip().lower()
            if pick in (a, b):
                result.approach = pick
                result.ruling = _clip(ruling.get("reason") or f"chose {pick}", 160)
            result.how = "split, Judge ruled" if result.ruling else "split, higher score"
        result.ms = int((time.monotonic() - started) * 1000)
        if result.decided and self.setting("lobe_cache"):
            self.cache[key] = result
            while len(self.cache) > CACHE_SIZE:
                self.cache.popitem(last=False)
        record(result)
        if show and result.ballots:
            show(result)
        return result


class _null:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
def load_stats():
    try:
        return json.loads(STATS_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {"votes": 0, "how": {}, "approach": {}, "judge_calls": 0, "ms_total": 0, "cached": 0, "abstained": 0}


def record(result):
    s = load_stats()
    s["votes"] = s.get("votes", 0) + 1
    how = result.how.split(",")[0]
    s.setdefault("how", {})[how] = s["how"].get(how, 0) + 1
    if result.approach:
        s.setdefault("approach", {})[result.approach] = s["approach"].get(result.approach, 0) + 1
    won = {b.side for b in result.ballots if b.vote == result.approach}
    if len(won) == 1 and not result.cached:   # one hemisphere carried the vote: the hourglass tips its way
        side = won.pop()
        s.setdefault("hemisphere", {})[side] = s["hemisphere"].get(side, 0) + 1
    if result.ruling and not result.cached:
        s["judge_calls"] = s.get("judge_calls", 0) + 1
    if result.cached:
        s["cached"] = s.get("cached", 0) + 1
    else:
        s["ms_total"] = s.get("ms_total", 0) + result.ms
    s["abstained"] = s.get("abstained", 0) + (2 - len(result.ballots) if not result.cached else 0)
    try:
        STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATS_FILE.write_text(json.dumps(s))
    except OSError:
        pass


def describe_stats():
    s = load_stats()
    n = s.get("votes", 0)
    if not n:
        return "  No votes yet. The lobes vote on messages of at least the minimum length when Seahorse himself answers."
    live = max(1, n - s.get("cached", 0))
    how = s.get("how", {})
    agree = how.get("unanimous", 0)
    lines = [f"  {n} votes · lobes agreed {agree / n:.0%} of the time · Judge broke {s.get('judge_calls', 0)} ties · "
             f"average {s.get('ms_total', 0) / live / 1000:.1f}s · {s.get('cached', 0)} from cache · "
             f"{s.get('abstained', 0)} abstentions",
             "  outcomes:   " + ", ".join(f"{k} {v}" for k, v in sorted(how.items(), key=lambda kv: -kv[1])),
             "  approaches: " + ", ".join(f"{k} {v}" for k, v in sorted(s.get("approach", {}).items(),
                                                                         key=lambda kv: -kv[1]))]
    return "\n".join(lines)


def reset_stats():
    try:
        STATS_FILE.unlink()
    except OSError:
        pass
