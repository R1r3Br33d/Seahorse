#!/usr/bin/env python3
"""
atlas.py - Seahorse maps itself: every command and the architecture tree, read from the code, so the map
can't drift from what Seahorse actually does.

    /map               the whole map: commands, architecture tree, usage
    /map commands      every command, its aliases, the module that handles it, and whether /help documents it
    /map tree          the module tree from the entry points, with what each module is for and its size
    /map usage         which commands you actually use (counted on this computer only)

    python3 atlas.py                     print the map
    python3 atlas.py --write FILE.md     write it as Markdown (docs/ARCHITECTURE.md)
    python3 atlas.py --check             exit 1 if a command is handled but not in /help, or the other way round

How it reads the code: handle_command() in seahorse.py is parsed (not run) - every `cmd == "..."` and
`cmd in (...)` branch is a command, the first name in a branch is the command and the rest are its aliases,
and the first function the branch calls is its handler. Aliases routed through TREASURY_COMMANDS and the
/board sub-commands (BOARD_SUBS) are read the same way. The tree follows each module's imports of the
others, starting from the three entry points.
"""

import ast
import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
USAGE = Path.home() / ".seahorse" / "commands.json"
ENTRIES = ("seahorse.py", "seahorse_app.py", "finetune.py")
ROLE = {   # where a module sits, for the tree
    "seahorse.py": "entry: the terminal app and the Session (the heart)",
    "seahorse_app.py": "entry: the desktop app's server",
    "finetune.py": "entry: training the Ultimate model",
}


# ------------------------------------------------------------------ commands

def _compared(n):
    """String constants (or a command table, as '@NAME') that one comparison node checks `cmd` against."""
    if not (isinstance(n, ast.Compare) and isinstance(n.left, ast.Name) and n.left.id == "cmd"):
        return []
    found = []
    for comp in n.comparators:
        if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
            found.append(comp.value)
        elif isinstance(comp, (ast.Tuple, ast.List, ast.Set)):
            found += [e.value for e in comp.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        elif isinstance(comp, ast.Name):
            found.append("@" + comp.id)          # a table of commands, e.g. TREASURY_COMMANDS
    return found


def _consts(node):
    """All commands a branch's test checks. A comparison tied by `and` to another condition inside a larger test
    (e.g. `... or (cmd == "pay" and arg == "undo")`) is a special case of that command, not a command of its own -
    unless the whole branch is conditional, in which case it is still its command's branch."""
    conditional = {id(c) for b in ast.walk(node) if isinstance(b, ast.BoolOp) and isinstance(b.op, ast.And)
                   for c in ast.walk(b)}

    def scan(skip):
        return [c for n in ast.walk(node) if id(n) not in skip for c in _compared(n)]
    return scan(conditional) or scan(set())


HANDLER = re.compile(r"(_command|_text|^show_|^status$|^session\.\w+|^treasury\.\w+|^change\.\w+|^calculate$)")


def _first_call(body):
    """The function a branch hands the command to - a *_command, a *_text report, or a session method."""
    for stmt in body:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Call):
                f = n.func
                name = f.id if isinstance(f, ast.Name) else f"{getattr(f.value, 'id', '?')}.{f.attr}" \
                    if isinstance(f, ast.Attribute) else "?"
                if HANDLER.search(name):
                    return name
    return ""


def _module_table(tree, name):
    """Evaluate a module-level dict of command names (TREASURY_COMMANDS / BOARD_SUBS) without running seahorse."""
    table = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            v = node.value
            if isinstance(v, ast.Set):             # a set of commands one handler takes, e.g. MEMORY_COMMANDS
                table.update({e.value: e.value for e in v.elts if isinstance(e, ast.Constant)})
            if isinstance(v, ast.Dict):
                for k, val in zip(v.keys, v.values):
                    if isinstance(k, ast.Constant) and isinstance(val, ast.Constant):
                        table[k.value] = val.value
            elif isinstance(v, ast.DictComp) and isinstance(v.generators[0].iter, ast.Tuple):
                for e in v.generators[0].iter.elts:
                    table[e.value] = e.value
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):   # NAME.update(a="b", ...)
            f = node.value.func
            if isinstance(f, ast.Attribute) and f.attr == "update" and getattr(f.value, "id", "") == name:
                table.update({kw.arg: kw.value.value for kw in node.value.keywords})
    return table


def documented():
    """{command: description} from the /help text."""
    src = (HERE / "seahorse.py").read_text()
    m = re.search(r'^HELP = f?"""(.*?)"""', src, re.S | re.M)
    out = {}
    for line in (m.group(1) if m else "").splitlines():
        hit = re.match(r"\s{2}(/[\w-]+.*?)(?:\s{2,}(.*))?$", line)
        if hit:
            usage, desc = hit.group(1), (hit.group(2) or "").strip()
            for name in re.findall(r"(?:^|\s|\|)/([\w-]+)", usage):   # "/adopt <id> | /drop <id>" names both
                out.setdefault(name, desc or usage)
    return out


def commands():
    """[{name, aliases, handler, documented, description}] for every command handle_command() handles."""
    src = (HERE / "seahorse.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "handle_command")
    docs = documented()
    tables = {n.targets[0].id: _module_table(tree, n.targets[0].id) for n in tree.body
              if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id.endswith(
                  ("_COMMANDS", "_SUBS"))}
    rows, seen = [], set()

    def visit(stmts):
        for stmt in stmts:
            if isinstance(stmt, ast.If):
                names = _consts(stmt.test)
                handler = _first_call(stmt.body)
                plain = [n for n in names if not n.startswith("@")]
                for t in [n[1:] for n in names if n.startswith("@")]:
                    table = tables.get(t, {})
                    for target in sorted(set(table.values())):
                        aliases = sorted(k for k, v in table.items() if v == target and k != target)
                        if target not in seen:
                            seen.add(target)
                            known = [x for x in [target, *aliases] if x in docs]
                            rows.append({"name": target, "aliases": aliases,
                                         "handler": f"{handler} ({target})" if handler else "",
                                         "documented": bool(known), "description": docs.get(known[0], "") if known else ""})
                if plain and plain[0] not in seen:
                    seen.update(plain)
                    rows.append({"name": plain[0], "aliases": plain[1:], "handler": handler,
                                 "documented": any(p in docs for p in plain),
                                 "description": next((docs[p] for p in plain if p in docs), "")})
                visit(stmt.orelse)
    visit(fn.body)
    handled = {r["name"] for r in rows} | {a for r in rows for a in r["aliases"]}
    missing = sorted(set(docs) - handled)
    return rows, missing, tables.get("BOARD_SUBS", {})


# ------------------------------------------------------------------ the tree

def _local_imports(path, local):
    tree = ast.parse(path.read_text())
    deps = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            deps |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            deps.add(n.module.split(".")[0])
        elif isinstance(n, ast.Call) and getattr(n.func, "id", "") == "__import__" and n.args \
                and isinstance(n.args[0], ast.Constant):
            deps.add(n.args[0].value)
    return sorted(d for d in deps if d in local and d != path.stem)


def modules():
    """{stem: {file, lines, purpose, deps}} for every Python module in Seahorse."""
    files = sorted(HERE.glob("*.py"))
    local = {f.stem for f in files}
    out = {}
    for f in files:
        src = f.read_text()
        try:
            doc = ast.get_docstring(ast.parse(src)) or ""
        except SyntaxError:
            doc = ""
        para = " ".join(doc.split("\n\n")[0].split())                 # the docstring's first paragraph
        para = re.sub(rf"^{re.escape(f.name)}\s*[-:]\s*", "", para)
        sentence = re.split(r"(?<=[.])\s", para)[0].rstrip(".")
        purpose = ROLE.get(f.name) or (sentence if len(sentence) <= 80 else sentence[:79].rsplit(" ", 1)[0] + "…")
        out[f.stem] = {"file": f.name, "lines": src.count("\n") + 1, "purpose": purpose,
                       "deps": _local_imports(f, local)}
    return out


def tree_lines():
    mods = modules()
    lines, shown = [], set()

    def walk(stem, prefix="", last=True, depth=0):
        m = mods[stem]
        branch = "" if depth == 0 else ("└── " if last else "├── ")
        again = stem in shown and depth > 0
        lines.append(f"{prefix}{branch}{m['file']:<18} {m['lines']:>5}  {'(see above)' if again else m['purpose']}")
        if again:
            return
        shown.add(stem)
        kids = m["deps"]
        for i, k in enumerate(kids):
            walk(k, prefix + ("" if depth == 0 else ("    " if last else "│   ")), i == len(kids) - 1, depth + 1)

    for e in ENTRIES:
        walk(Path(e).stem)
        lines.append("")
    rest = [s for s in mods if s not in shown and s != "atlas"]
    if rest:
        lines.append("not reached from an entry point: " + ", ".join(mods[s]["file"] for s in rest))
    app = sorted((HERE / "app").glob("*")) if (HERE / "app").is_dir() else []
    if app:
        lines.append("app/ (the desktop app's page, served by seahorse_app.py):")
        lines += [f"    {p.name:<18} {p.read_text(errors='ignore').count(chr(10)) + 1:>5}" for p in app]
    total = sum(m["lines"] for m in mods.values())
    lines += ["", f"{len(mods)} Python modules · {total:,} lines"]
    return lines


# ------------------------------------------------------------------ usage

def track(cmd):
    """Count a command use (local only, never sent anywhere)."""
    if not cmd or not re.fullmatch(r"[\w-]{1,40}", cmd):
        return
    try:
        data = json.loads(USAGE.read_text())
    except (OSError, ValueError):
        data = {}
    c = data.setdefault(cmd.lower(), {"n": 0})
    c["n"] += 1
    c["last"] = datetime.now().isoformat(timespec="seconds")
    try:
        USAGE.parent.mkdir(parents=True, exist_ok=True)
        USAGE.write_text(json.dumps(data))
    except OSError:
        pass


def usage_lines(n=15):
    try:
        data = json.loads(USAGE.read_text())
    except (OSError, ValueError):
        return ["no commands used yet"]
    rows = sorted(data.items(), key=lambda kv: -kv[1]["n"])
    top = max(r[1]["n"] for r in rows) if rows else 1
    return [f"/{c:<14} {v['n']:>5}  {'█' * max(1, round(20 * v['n'] / top))}  last {v['last'][:16].replace('T', ' ')}"
            for c, v in rows[:n]] + [f"{sum(v['n'] for v in data.values())} uses of {len(data)} commands"]


# ------------------------------------------------------------------ output

def command_lines():
    rows, missing, board = commands()
    board = board or {}
    lines = [f"{len(rows)} commands handled · {sum(len(r['aliases']) for r in rows)} aliases · "
             f"{sum(1 for r in rows if not r['documented'])} not in /help · {len(missing)} in /help but not handled", ""]
    for r in sorted(rows, key=lambda r: r["name"]):
        alias = f"  (also {', '.join('/' + a for a in r['aliases'])})" if r["aliases"] else ""
        flag = "" if r["documented"] else "  [not in /help]"
        lines.append(f"/{r['name']:<14} → {r['handler'] or '(inline)':<28}{alias}{flag}")
    if missing:
        lines.append("in /help but not handled: " + ", ".join("/" + m for m in missing))
    if board:
        lines.append("")
        lines.append("/board sub-commands: " + " · ".join(f"{k} → /{v}" for k, v in sorted(board.items())))
    return lines


def text(part="all"):
    out = []
    if part in ("all", "commands"):
        out += ["COMMANDS"] + ["  " + l for l in command_lines()] + [""]
    if part in ("all", "tree"):
        out += ["ARCHITECTURE"] + ["  " + l for l in tree_lines()] + [""]
    if part in ("all", "usage"):
        out += ["USAGE (this computer)"] + ["  " + l for l in usage_lines()]
    return "\n".join(out)


def markdown():
    rows, missing, board = commands()
    md = ["# Seahorse architecture", "",
          f"Generated by `atlas.py` from the code on {datetime.now():%Y-%m-%d}. Run `python3 atlas.py --write "
          "docs/ARCHITECTURE.md` to refresh it, or `/map` inside Seahorse.", "",
          "## Module tree", "", "From the three entry points; each module lists the Seahorse modules it imports.",
          "", "```", *tree_lines(), "```", "", "## Commands", "",
          "| Command | Aliases | Handled by | What it does |", "|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: r["name"]):
        md.append(f"| `/{r['name']}` | {', '.join('`/' + a + '`' for a in r['aliases'])} | `{r['handler'] or 'inline'}` | "
                  f"{(r['description'] or '*not in /help*').replace('|', '/')} |")
    if board:
        md += ["", "`/board` sub-commands: " + ", ".join(f"`{k}` → `/{v}`" for k, v in sorted(board.items()))]
    if missing:
        md += ["", "In `/help` but not handled: " + ", ".join(f"`/{m}`" for m in missing)]
    return "\n".join(md) + "\n"


if __name__ == "__main__":
    if "--write" in sys.argv:
        dest = Path(sys.argv[sys.argv.index("--write") + 1])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(markdown())
        print(f"wrote {dest}")
    elif "--check" in sys.argv:
        rows, missing, _b = commands()
        bad = [r["name"] for r in rows if not r["documented"]]
        print("not in /help:", ", ".join(bad) or "none")
        print("in /help but not handled:", ", ".join(missing) or "none")
        sys.exit(1 if bad or missing else 0)
    else:
        print(text(sys.argv[1] if len(sys.argv) > 1 else "all"))
