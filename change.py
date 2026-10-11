"""
change.py - the change: Seahorse's value system, counted in coins.

Every value is worth between $0.00 and a whole value ($1.00), counted out in change:

    whole value  $1.00   a reply you took exactly as it was
    quarter      $0.25
    dime         $0.10
    nickel       $0.05
    penny        $0.01

Values are kept to the hundredth (a penny) and can be shown to the tenth (a dime's
worth) or rounded to the whole when only "kept or not" matters.

WHAT A REPLY IS WORTH - "change" in both senses: the coins it earns are set by how
much you had to change it.

    starts at                       $0.50   two quarters: it answered
    you thanked or praised it      +$0.50   two quarters: praise makes it a whole value
    you built on it next            +$0.10   a dime
    you let it stand (chat ended)   +$0.05   a nickel
    you scrapped the idea           -$0.10   a dime: the idea went to the oil, the reply may be fine
    you corrected it                -$0.25   a quarter
    you had to ask again            -$0.50   the whole answer was redone

The Ultimate model is trained and judged in this change:
    worth $0.75 or more   trained on twice
    worth $0.30 to $0.74  trained on once
    worth under $0.30     left out
and in evaluation the judge prices each reply, so the tuned and untuned models are
compared by what their answers are worth on average.
"""

import difflib
import re

COINS = [("whole value", 100), ("quarter", 25), ("dime", 10), ("nickel", 5), ("penny", 1)]   # in hundredths
SIGN = {"whole value": "$", "quarter": "Q", "dime": "D", "nickel": "N", "penny": "P"}

START, PRAISED, BUILT_ON, LET_STAND, SCRAPPED, CORRECTED, ASKED_AGAIN = 50, 50, 10, 5, -10, -25, -50
TWICE, ONCE = 75, 30   # training: worth this much or more (in hundredths)

PRAISE = re.compile(r"\b(thanks|thank you|thx|perfect|great|awesome|exactly|love it|nailed it|that works|"
                    r"that'?s right|spot on)\b", re.I)
CORRECTION = re.compile(r"^\s*(no[,.!]|nope|wrong|that'?s (?:wrong|not right|incorrect)|not what i (?:meant|asked)|"
                        r"you (?:misunderstood|got it wrong|forgot)|actually,? (?:no|i said))", re.I)


def cents(value):
    """Any value -> whole hundredths, clamped to $0.00..$1.00."""
    return max(0, min(100, round(value * 100) if isinstance(value, float) else int(value)))


def make_change(c):
    """Hundredths -> coins, largest first: 67 -> [('quarter', 2), ('dime', 1), ('nickel', 1), ('penny', 2)]."""
    out = []
    for name, size in COINS:
        n, c = divmod(c, size)
        if n:
            out.append((name, n))
    return out


def dollars(c):
    return f"${c / 100:.2f}"


def tenths(c):
    return f"${round(c / 10) / 10:.1f}"


def coins(c, short=False):
    """'$0.67 - 2 quarters, 1 dime, 1 nickel, 2 pennies' (or 'QQDNPP' with short)."""
    pile = make_change(c)
    if short:
        return "".join(SIGN[name] * n for name, n in pile) or "-"
    plural = {"penny": "pennies", "whole value": "whole values"}
    words = ", ".join(f"{n} {plural.get(name, name + 's') if n > 1 else name}" for name, n in pile)
    return f"{dollars(c)} - {words or 'nothing'}"


def bar(c, width=20):
    k = round(width * c / 100)
    return "█" * k + "░" * (width - k)


def worth(reply, next_user="", asked="", ended=False, scrap=None):
    """What a reply is worth, in hundredths, and the coins it earned or lost: (cents, [(delta, why)]).

    reply      the reply's text
    next_user  what you said next ("" if nothing)
    asked      what you asked to get the reply (to spot being asked again)
    ended      True if the chat ended on this reply
    scrap      a compiled pattern for "scrap that" (treasury.SCRAP), optional
    """
    ledger = [(START, "it answered")]
    if next_user:
        if PRAISE.search(next_user):
            ledger.append((PRAISED, "you thanked or praised it"))
        if CORRECTION.search(next_user):
            ledger.append((CORRECTED, "you corrected it"))
        elif asked and len(next_user) > 12 and \
                difflib.SequenceMatcher(None, asked.lower(), next_user.lower()).ratio() >= 0.8:
            ledger.append((ASKED_AGAIN, "you had to ask again"))
        elif scrap is not None and scrap.search(next_user):
            ledger.append((SCRAPPED, "you scrapped the idea"))
        else:
            ledger.append((BUILT_ON, "you built on it"))
    elif ended:
        ledger.append((LET_STAND, "you let it stand"))
    return cents(sum(d for d, _w in ledger)), ledger


def copies(c):
    """How many times the Ultimate model trains on a reply worth c hundredths."""
    return 2 if c >= TWICE else 1 if c >= ONCE else 0


def judge_prompt(convo, system, reference, first, second):
    return (f"Conversation so far:\n{convo[-3000:]}\n\nThe persona and instructions:\n{system[:2500]}\n\n"
            f"The user's actual preferred style is shown by this past reply:\n{reference[:1500]}\n\n"
            f"Reply 1:\n{first[:2000]}\n\nReply 2:\n{second[:2000]}\n\n"
            "Price each reply in change: what is it worth to this user, from 0.00 (useless) to 1.00 (a whole "
            "value: helpful, accurate, in character, nothing to change)? Use hundredths. "
            "Answer only in the form:\n1: 0.xx\n2: 0.xx")


def parse_prices(text):
    """'1: 0.72\\n2: 0.55' -> (72, 55); None if the judge didn't price both."""
    found = dict(re.findall(r"([12])\s*[:=\-]\s*\$?\s*([01](?:\.\d+)?|\.\d+)", text or ""))
    if "1" in found and "2" in found:
        return cents(float(found["1"])), cents(float(found["2"]))
    return None


def outline(rows):
    """The dataset in change: how many replies at each worth, and each agent's purse (average worth)."""
    bands = [("whole value  $1.00", 100, 101), ("three quarters+", 75, 100), ("half or more", 50, 75),
             ("a quarter+", 25, 50), ("pennies", 0, 25)]
    counts = {label: 0 for label, *_ in bands}
    purses = {}
    for r in rows:
        c, agent = r["worth"], r["agent"]
        for label, lo, hi in bands:
            if lo <= c < hi:
                counts[label] += 1
                break
        purses.setdefault(agent, []).append(c)
    total = len(rows) or 1
    lines = ["  The Ultimate model's dataset, counted in change:", ""]
    lines += [f"    {label:<20} {n:>5}  {bar(100 * n // total, 30)}" for label, n in counts.items()]
    avg = sum(r["worth"] for r in rows) // total if rows else 0
    lines += ["", f"    average reply worth {coins(avg)}",
              f"    trained twice (≥ {dollars(TWICE)}) {sum(1 for r in rows if copies(r['worth']) == 2)} · "
              f"once {sum(1 for r in rows if copies(r['worth']) == 1)} · "
              f"left out (< {dollars(ONCE)}) {sum(1 for r in rows if copies(r['worth']) == 0)}",
              "", "    each agent's purse (average worth of their replies):"]
    for agent, cs in sorted(purses.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
        a = sum(cs) // len(cs)
        lines.append(f"      {agent:<14} {dollars(a)}  {coins(a, short=True):<10} {bar(a)}  {len(cs)} replies")
    return "\n".join(lines)
