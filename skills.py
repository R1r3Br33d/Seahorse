#!/usr/bin/env python3
"""
skills.py - Seahorse's skills.

A skill is a Markdown file in ~/.seahorse/skills/ with a short header:

    ---
    name: writing
    description: Professional English writing and editing
    mode: auto              # auto = switch on when the message calls for it; on; off
    triggers: \\b(email|essay|proofread)\\b    # regex checked against your message (auto mode)
    ---
    Instructions Seahorse follows while the skill is active...

Seahorse ships with two skills, `writing` and `math`, and writes them to that
folder on first run. Edit them freely or drop in your own .md files.

The math skill comes with a real calculator. When Seahorse writes a block like

    ```calc
    solve(Eq(2*x + 3, 7), x)
    ```

Seahorse runs it (exactly, with SymPy if installed, otherwise Python's math
module), shows you the result and hands it back to the model to finish the
answer. Expressions are checked against a strict whitelist and evaluated in a
separate process with a time limit, so a bad expression can't hang or harm
anything.

Run directly to try the calculator:
    python3 skills.py "integrate(x**2, (x, 0, 3))"
"""

import ast
import json
import math
import queue
import re
import statistics
import subprocess
import sys
import threading
from pathlib import Path

SKILLS_DIR = Path.home() / ".seahorse" / "skills"
CALC_TIMEOUT = 10  # seconds
CALC_BLOCK = re.compile(r"```(?:calc|calculator)[^\n]*\n(.*?)```", re.DOTALL | re.IGNORECASE)
CALC_RESULT_PREFIX = "[calculator results]"

# ---------------------------------------------------------------------------
# Built-in skills
# ---------------------------------------------------------------------------

WRITING_SKILL = r"""---
name: writing
description: Professional English writing and editing
mode: auto
triggers: (?i)\b(write|rewrite|draft|edit|proofread|polish|reword|rephrase|grammar|spelling|punctuation|tone|email|e-mail|letter|cover letter|resume|résumé|memo|report|essay|proposal|summary|summarize|announcement|bio|blog|article|paragraph|sentence|wording|formal|professional)\b
---
# Professional English writing

You are an excellent professional writer and editor of English. Write in
American English unless the user asks for British English or their text
already uses it; never mix the two.

## Before writing
- Work out who will read it and what they should know, feel or do afterwards.
  If that's unclear and it matters, ask one short question; otherwise make a
  sensible assumption and mention it in one line.
- Match the register to the situation: a note to a colleague, a cover letter
  and a legal notice need different levels of formality.

## How to write
- Lead with the point. Put the request, answer or decision in the first one
  or two sentences; background comes after.
- One idea per paragraph, opened by a sentence that states it.
- Prefer plain, specific words: "use" not "utilize", "about" not "with regard
  to", "start" not "commence". Use concrete numbers, dates and names.
- Prefer the active voice: "The team fixed the bug", not "The bug was fixed".
  Use passive only when the actor is unknown or unimportant.
- Cut filler and hedging: "I just wanted to reach out", "very", "really",
  "in order to", "it is important to note that", "please do not hesitate".
- Vary sentence length; keep most sentences under about 25 words.
- Keep tense, person, terminology, capitalization and number style
  consistent throughout (spell out one to nine, numerals for 10 and up,
  unless the house style differs).
- Use parallel structure in lists and in pairs of ideas.
- Never invent facts, names, figures, credentials or quotes. Use
  [placeholders in brackets] for anything the user must fill in.

## Formats
- Email: a specific subject line, a greeting, the point first, any request
  stated clearly with a deadline if there is one, a short sign-off. Keep it
  short enough to read on a phone.
- Letters and cover letters: tailored to the recipient, with one concrete
  example per claim; no generic praise.
- Reports and proposals: a summary first, then headings that tell the story,
  then the recommendation and next steps.
- Summaries: keep the meaning, drop the detail, never add claims.

## When editing the user's text
- Keep their voice and meaning; fix what is wrong or unclear and leave what
  works alone.
- Give the revised text first, then a short list of the most important
  changes and why (skip the list for a light proofread unless asked).
- For "proofread only", change only errors in grammar, spelling, punctuation
  and consistency, not style.

## Check before you answer
- its / it's, your / you're, their / there / they're, affect / effect,
  then / than, fewer / less, who / whom, that / which, lie / lay,
  complement / compliment, principal / principle, ensure / insure.
- Comma splices and run-ons; missing comma after an introductory clause;
  dangling or misplaced modifiers; subject-verb agreement with collective
  nouns and "each" / "everyone"; pronouns with unclear antecedents;
  apostrophes in plurals (never "CD's" for plurals).
- Read it once more as the recipient would: is anything confusing, abrupt,
  or longer than it needs to be?
"""

MATH_SKILL = r"""---
name: math
description: Mathematics with an exact calculator
mode: auto
triggers: (?i)(\d\s*[-+*/^%×÷=]\s*\d|\d\s*%|\b(loan|mortgage|payment|apr|how much|how many|math|maths|calculate|calculation|compute|solve|equation|algebra|arithmetic|integral|integrate|derivative|differentiate|limit|calculus|probability|statistics|statistic|mean|median|average|variance|standard deviation|percent|percentage|ratio|fraction|decimal|interest|compound|loan|matrix|matrices|determinant|vector|geometry|area|volume|perimeter|angle|triangle|circle|trigonometry|sine|cosine|logarithm|log|exponent|square root|prime|factor|factorial|permutation|combination|proof|prove|theorem|graph|function|polynomial|quadratic|simplify|expand|convert|units?)\b)
---
# Mathematics

You are a careful, rigorous mathematician and a clear teacher.

## You have a calculator - use it
Never do arithmetic beyond the trivial in your head. To calculate, write a
fenced block marked `calc` with one expression per line, then STOP and wait.
The results will be sent back to you, and you then finish your answer using
them. Example:

```calc
1250 * (1 + 0.045/12)**(12*5)
solve(Eq(3*x**2 - 5*x - 2, 0), x)
integrate(sin(x)**2, (x, 0, pi))
```

Calculator syntax (Python style):
- Operators: + - * / ** (power), parentheses. Write multiplication
  explicitly (2*x). Fractions like 1/3 stay exact.
- Variables: any letter or name is a symbol; `r = 0.05` stores a value for
  later lines in the same block.
- Equations: Eq(left, right). Solve with solve(Eq(...), x), or a system with
  solve([Eq(...), Eq(...)], [x, y]).
- Functions: sqrt, cbrt, root(x, n), exp, log(x) (natural), log(x, b), log10,
  sin cos tan asin acos atan (radians), deg(x), rad(x), abs, floor, ceil,
  round(x, n), factorial, comb(n, k), perm(n, k), gcd, lcm, isprime,
  factorint, mean, median, stdev (sample), pstdev (population), min, max, sum.
- Algebra and calculus: simplify, expand, factor, apart, diff(f, x),
  diff(f, x, 2), integrate(f, x), integrate(f, (x, a, b)), limit(f, x, a),
  summation(f, (k, 1, n)), series(f, x, 0, 6), N(expr, digits).
- Matrices: Matrix([[1, 2], [3, 4]]), det(M), inv(M), transpose(M).
- Constants: pi, E (Euler's number), I (imaginary unit), oo (infinity).

## How to answer
- Restate the problem briefly and name any assumptions (units, rounding,
  what a variable means).
- Show the reasoning step by step at the level the user needs: brief for a
  quick question, full working for homework or a proof.
- Give exact answers (fractions, surds, pi) where natural, plus a decimal
  approximation with sensible rounding. Keep and state units throughout.
- Check the answer: substitute it back, estimate the order of magnitude, or
  test an edge case. Say so if something doesn't check out.
- For proofs: state what is to be proved, give a clear logical argument, and
  end by saying what was shown.
- Write math in plain text (x^2, sqrt(2), pi) because the user reads in a
  terminal; avoid LaTeX unless asked.
- If a question is ambiguous (for example 6/2(1+2)), point out the ambiguity
  and give the answer under the usual convention.
"""

UNITS_SKILL = r"""---
name: units
description: Units of measurement - every system, converted exactly
mode: auto
triggers: (?i)(\d\s*(?:mm|cm|km|m|in|ft|yd|mi|nmi|kg|g|lb|oz|st|L|ml|gal|qt|pt|cup|tbsp|tsp|°[CF]|K|psi|bar|atm|kPa|J|kJ|kWh|cal|kcal|BTU|W|kW|hp|mph|km/h|kn|GB|MB|TB|GiB|MiB|Hz|rpm|acres?|ha)\b|\b(convert|conversion|units?|metric|imperial|customary|how many \w+ (?:in|per)|per (?:hour|second|minute)|celsius|fahrenheit|kelvin)\b)
---
# Units of measurement

You know every unit system: SI (all base and derived units, every prefix from
quecto to quetta), binary prefixes, US customary and imperial (liquid and dry),
nautical, astronomical, atomic and Planck units, CGS, data, radiation,
photometry, viscosity, historical and traditional units, and nine temperature
scales.

Never convert in your head. Use the calculator:

```calc
convert(5, 'mi', 'km')
convert(98.6, 'degF', 'degC')
convert(30, 'mpg', 'L/100km')
convert(2.5, 'kWh', 'BTU')
```

- Unit names: SI symbols (m, kg, s, N, Pa, J, W...), prefixes (km, MHz, GiB),
  compound units (km/h, kg m/s^2, N*m, L/100km), and names (furlong, stone,
  fathom, troy_oz, imp_gal, nmi, ly, parsec, tsubo, jin...). Temperatures:
  degC, degF, K, degR, degRe, degRo, degN, degDe; differences: delta_degC.
- `units('length')` lists every unit in a category.
- Watch the classic traps and say which you mean: US vs imperial gallon,
  pint and fluid ounce; short vs long vs metric ton; troy vs avoirdupois ounce;
  calorie vs kilocalorie (food Calorie); statute vs nautical mile; KB (1000)
  vs KiB (1024); rpm counts cycles (x 2*pi for rad/s); mass vs weight (kg vs kgf).
- Give the result with sensible rounding and the unit, and the system it's in.
"""

BUILTIN_SKILLS = {"writing": WRITING_SKILL, "math": MATH_SKILL, "units": UNITS_SKILL}


# ---------------------------------------------------------------------------
# Skill loading and selection
# ---------------------------------------------------------------------------

def _parse(text):
    meta, body = {}, text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].strip().splitlines():
                key, _, val = line.partition(":")
                if key.strip():
                    meta[key.strip().lower()] = val.split("  #")[0].strip()
            body = text[end + 4:].lstrip("\n")
    return meta, body.strip()


class Skill:
    def __init__(self, path):
        self.path = Path(path)
        self.reload()

    def reload(self):
        text = self.path.read_text(encoding="utf-8")
        meta, self.body = _parse(text)
        self.name = meta.get("name") or self.path.stem
        self.description = meta.get("description", "")
        self.mode = meta.get("mode", "auto").lower()
        if self.mode not in ("auto", "on", "off"):
            self.mode = "auto"
        try:
            self.trigger = re.compile(meta["triggers"]) if meta.get("triggers") else None
        except re.error:
            self.trigger = None

    def matches(self, text):
        return bool(self.trigger and self.trigger.search(text or ""))

    def set_mode(self, mode):
        text = self.path.read_text(encoding="utf-8")
        if re.search(r"(?m)^mode:.*$", text):
            text = re.sub(r"(?m)^mode:.*$", f"mode: {mode}", text, count=1)
        elif text.startswith("---"):
            text = text.replace("---\n", f"---\nmode: {mode}\n", 1)
        self.path.write_text(text, encoding="utf-8")
        self.mode = mode


class SkillSet:
    def __init__(self, folder=SKILLS_DIR):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        for name, text in BUILTIN_SKILLS.items():
            path = self.folder / f"{name}.md"
            if not path.exists():
                path.write_text(text, encoding="utf-8")
        self.skills = {}
        for path in sorted(self.folder.glob("*.md")):
            try:
                skill = Skill(path)
                self.skills[skill.name] = skill
            except OSError:
                pass

    def get(self, name):
        return self.skills.get(name.strip().lower())

    def select(self, user_messages):
        """Pick active skills from the latest real user message (and the one before, for short follow-ups)."""
        if not user_messages:
            return []
        latest = user_messages[-1]
        previous = user_messages[-2] if len(user_messages) > 1 else ""
        active = []
        for skill in self.skills.values():
            if skill.mode == "on":
                active.append(skill.name)
            elif skill.mode == "auto" and (
                skill.matches(latest) or (len(latest) < 80 and skill.matches(previous))
            ):
                active.append(skill.name)
        return active

    def prompt(self, active):
        if not active:
            return ""
        parts = ["Skills active for this message (follow them closely):"]
        parts += [self.skills[name].body for name in active if name in self.skills]
        return "\n\n".join(parts)

    def describe(self, active=()):
        lines = []
        for s in self.skills.values():
            flag = "  ← active now" if s.name in active else ""
            lines.append(f"  {s.name:<10} [{s.mode}]  {s.description}{flag}")
        lines.append(f"  (files in {self.folder})")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------

def find_calc_blocks(text):
    lines = []
    for block in CALC_BLOCK.findall(text or ""):
        lines += [ln.strip() for ln in block.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return lines


def calculate(lines, timeout=CALC_TIMEOUT):
    """Evaluate expressions in a separate process, one line at a time.

    Each line gets its own time limit; if one hangs, the worker is killed,
    that line is reported as too slow, and the rest carry on in a fresh worker
    (with earlier assignments replayed). Returns a list of 'expr = result' strings.
    """
    lines = list(lines)[:50]
    results, assigns, i = [], [], 0
    while i < len(lines):
        batch = lines[i:]
        try:
            proc = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--calc-worker"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            )
            proc.stdin.write(json.dumps(assigns + batch))
            proc.stdin.close()
        except OSError as e:
            return results + [f"{ln} = error: calculator failed ({e})" for ln in batch]
        q = queue.Queue()

        def pump(out=proc.stdout, q=q):
            for row in out:
                q.put(row)
            q.put(None)

        threading.Thread(target=pump, daemon=True).start()
        skip, done = len(assigns), 0
        while True:
            try:
                row = q.get(timeout=timeout)
            except queue.Empty:
                proc.kill()
                results.append(f"{batch[done]} = error: took longer than {timeout}s, so it was stopped")
                i += done + 1
                break
            if row is None:  # worker finished (or crashed)
                proc.wait()
                if done < len(batch):
                    results += [f"{ln} = error: calculator stopped unexpectedly" for ln in batch[done:]]
                i = len(lines)
                break
            item = json.loads(row)
            if skip:
                skip -= 1
                continue
            results.append(item["text"])
            if item.get("assign") and item.get("ok"):
                assigns.append(batch[done])
            done += 1
    return results


def format_results(results):
    return CALC_RESULT_PREFIX + "\n" + "\n".join(results) + (
        "\n\nUse these results to finish your answer. Don't write another calc block "
        "unless you need a new calculation."
    )


_ALLOWED = (ast.Module, ast.Expr, ast.Assign, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name,
            ast.Load, ast.Store, ast.Call, ast.Tuple, ast.List, ast.keyword, ast.Compare,
            ast.operator, ast.unaryop, ast.cmpop)


def _preprocess(line):
    line = line.replace("^", "**").replace("×", "*").replace("÷", "/").replace("−", "-")
    # implicit multiplication: 2x -> 2*x, 3(x+1) -> 3*(x+1), but leave log10(, 1e5 alone
    line = re.sub(r"(?<![A-Za-z_\d.])(\d+(?:\.\d+)?)(?![eE][+-]?\d)(?=[A-Za-z(])", r"\1*", line)
    line = re.sub(r"\)\s*\(", ")*(", line)
    return line


def _validate(tree, functions):
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise ValueError(f"'{type(node).__name__}' isn't allowed in the calculator")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float, complex)):
            if not (isinstance(node.value, str) and len(node.value) <= 80):
                raise ValueError("only numbers and short unit names are allowed")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ValueError("names can't start with _")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in functions:
                name = getattr(node.func, "id", "that")
                raise ValueError(f"unknown function '{name}'")
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                raise ValueError("assign one simple name at a time, like r = 0.05")
            if node.targets[0].id in functions:
                raise ValueError(f"'{node.targets[0].id}' is a function name")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            exp = node.right
            if isinstance(exp, ast.Constant) and isinstance(exp.value, (int, float)) and abs(exp.value) > 100000:
                raise ValueError("exponent too large")
            if any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.Pow) for n in ast.walk(exp)):
                raise ValueError("power towers like a**b**c are too large to compute; rewrite them")
    if len(tree.body) != 1 or not isinstance(tree.body[0], (ast.Expr, ast.Assign)):
        raise ValueError("one expression per line")


class _ExactInts(ast.NodeTransformer):
    """Make 1/3 an exact fraction under SymPy by wrapping integer literals."""

    def visit_Constant(self, node):
        if isinstance(node.value, int) and not isinstance(node.value, bool):
            return ast.copy_location(ast.Call(func=ast.Name("__Int", ast.Load()), args=[node], keywords=[]), node)
        return node


SYMPY_ONLY = {"solve", "Eq", "simplify", "expand", "factor", "apart", "together", "diff", "integrate",
              "limit", "summation", "series", "N", "Rational", "Matrix", "det", "inv", "transpose",
              "isprime", "factorint", "sec", "csc", "cot", "mod"}


def _mean(xs):
    return sum(xs) / len(xs)


def _median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _sympy_namespace():
    import sympy as sp

    def stdev(xs):
        m = _mean(xs)
        return sp.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))

    def pstdev(xs):
        m = _mean(xs)
        return sp.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))

    def rnd(x, n=0):
        v = round(float(sp.N(x)), int(n))
        return int(v) if n == 0 else v

    fns = {
        "sqrt": sp.sqrt, "cbrt": sp.cbrt, "root": sp.root, "exp": sp.exp, "log": sp.log, "ln": sp.log,
        "log10": lambda x: sp.log(x, 10), "log2": lambda x: sp.log(x, 2),
        "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "asin": sp.asin, "acos": sp.acos, "atan": sp.atan,
        "atan2": sp.atan2, "sinh": sp.sinh, "cosh": sp.cosh, "tanh": sp.tanh, "sec": sp.sec, "csc": sp.csc,
        "cot": sp.cot, "deg": lambda x: x * 180 / sp.pi, "rad": lambda x: x * sp.pi / 180,
        "abs": sp.Abs, "floor": sp.floor, "ceil": sp.ceiling, "ceiling": sp.ceiling, "round": rnd,
        "factorial": sp.factorial, "comb": sp.binomial, "binomial": sp.binomial,
        "perm": lambda n, k: sp.factorial(n) / sp.factorial(n - k), "gcd": sp.gcd, "lcm": sp.lcm,
        "isprime": sp.isprime, "factorint": sp.factorint, "mod": sp.Mod,
        "mean": _mean, "median": _median, "stdev": stdev, "pstdev": pstdev,
        "min": min, "max": max, "sum": sum,
        "simplify": sp.simplify, "expand": sp.expand, "factor": sp.factor, "apart": sp.apart,
        "together": sp.together, "solve": sp.solve, "Eq": sp.Eq, "diff": sp.diff,
        "integrate": sp.integrate, "limit": sp.limit, "summation": sp.summation, "series": sp.series,
        "N": sp.N, "Rational": sp.Rational, "Matrix": sp.Matrix,
        "det": lambda M: sp.Matrix(M).det(), "inv": lambda M: sp.Matrix(M).inv(),
        "transpose": lambda M: sp.Matrix(M).T,
    }
    consts = {"pi": sp.pi, "E": sp.E, "e": sp.E, "I": sp.I, "oo": sp.oo, "inf": sp.oo, "__Int": sp.Integer}
    return sp, fns, consts


def _math_namespace():
    def rnd(x, n=0):
        return round(x, int(n)) if n else round(x)

    fns = {
        "sqrt": math.sqrt, "cbrt": lambda x: math.copysign(abs(x) ** (1 / 3), x),
        "root": lambda x, n: x ** (1 / n), "exp": math.exp,
        "log": lambda x, b=math.e: math.log(x, b), "ln": math.log, "log10": math.log10, "log2": math.log2,
        "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin, "acos": math.acos,
        "atan": math.atan, "atan2": math.atan2, "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
        "deg": math.degrees, "rad": math.radians, "abs": abs, "floor": math.floor, "ceil": math.ceil,
        "ceiling": math.ceil, "round": rnd, "factorial": math.factorial, "comb": math.comb,
        "binomial": math.comb, "perm": math.perm, "gcd": math.gcd, "lcm": math.lcm,
        "mean": statistics.mean, "median": statistics.median, "stdev": statistics.stdev,
        "pstdev": statistics.pstdev, "min": min, "max": max, "sum": sum, "hypot": math.hypot,
    }
    consts = {"pi": math.pi, "E": math.e, "e": math.e, "tau": math.tau, "inf": math.inf}
    return fns, consts


def _fmt(value, sp=None):
    if isinstance(value, (list, tuple)):
        inner = ", ".join(_fmt(v, sp) for v in value)
        return f"[{inner}]" if isinstance(value, list) else f"({inner})"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{_fmt(k, sp)}: {_fmt(v, sp)}" for k, v in value.items()) + "}"
    if isinstance(value, float):
        return f"{value:.12g}"
    if sp is not None and isinstance(value, sp.Basic):
        text = str(value)
        if getattr(value, "is_number", False) and not value.is_Integer and not value.is_Float:
            try:
                approx = sp.N(value, 12)
                if str(approx) != text:
                    text += f" ≈ {approx}"
            except Exception:  # noqa: BLE001
                pass
        return text
    return str(value)


def _unit_functions():
    import units

    def convert(value, frm, to):
        return units.convert(float(value), frm, to)

    def unit_list(category=""):
        import re as _re
        return "; ".join(_re.sub(r"\s{2,}", " ", line) for line in units.list_units(category or None))[:3000]

    return {"convert": convert, "units": unit_list}


def _calc_worker(lines):
    try:
        sp, fns, consts = _sympy_namespace()
    except ImportError:
        sp = None
        fns, consts = _math_namespace()
    fns.update(_unit_functions())
    env = {"__builtins__": {}}
    env.update(fns)
    env.update(consts)
    for raw in lines:
        assign = False
        line = _preprocess(raw)
        try:
            tree = ast.parse(line, mode="exec")
            _validate(tree, fns)
            # Unknown names become symbols under SymPy; without it they're an error.
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in env:
                    if sp is None:
                        raise ValueError(f"unknown name '{node.id}' (install sympy for algebra: pip install sympy)")
                    env[node.id] = sp.Symbol(node.id)
            if sp is not None:
                tree = ast.fix_missing_locations(_ExactInts().visit(tree))
            stmt = tree.body[0]
            assign = isinstance(stmt, ast.Assign)
            if assign:
                code = compile(ast.Module([stmt], []), "<calc>", "exec")
                exec(code, env)  # noqa: S102 - AST validated against a whitelist above
                value = env[stmt.targets[0].id]
            else:
                code = compile(ast.Expression(stmt.value), "<calc>", "eval")
                value = eval(code, env)  # noqa: S307 - AST validated against a whitelist above
            row = {"text": f"{raw} = {_fmt(value, sp)}", "ok": True, "assign": assign}
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            m = re.match(r"unknown function '(\w+)'", msg)
            if sp is None and m and m.group(1) in SYMPY_ONLY:
                msg = f"'{m.group(1)}' needs SymPy for exact algebra (install it with: pip install sympy)"
            row = {"text": f"{raw} = error: {msg}", "ok": False, "assign": assign}
        print(json.dumps(row), flush=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--calc-worker":
        _calc_worker(json.loads(sys.stdin.read()))
    elif len(sys.argv) > 1:
        print("\n".join(calculate(sys.argv[1:])))
    else:
        print(__doc__)
