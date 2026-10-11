"""
ui.py - Seahorse's cosmetic package.

    Themes      ocean (default), reef, abyss, kelp, daylight (for light
                terminal backgrounds) and mono (no colour)
    Logos       full    - seahorse drawing beside the SEAHORSE block title
                compact - small seahorse with a spaced title
                minimal - one line
                trident - the trident mark beside the title
    Icons       one per agent:  ∫ hippocampus  ✎ broca  ∑ parietal  λ cerebellum
                                ◎ wernicke  ↗ prefrontal  ✓ cingulate
                (agents can set their own with `icon:`; plain-text fallbacks
                are used when the terminal has no Unicode)
    Spinner     a pulsing trident with rising bubbles, or a rolling wave
    Replies     drawn in rounded boxes, or with a simple header line

The default starting state lives in ~/.seahorse/config.json and is created
on first run (see DEFAULTS). Change it with /config, /theme and /logo inside
Seahorse, or edit the file.

Colours switch off automatically when output isn't a terminal or the
NO_COLOR environment variable is set.
"""

import json
import os
import re
import shutil
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

try:  # line editing and history for the prompt (macOS / Linux)
    import readline  # noqa: F401
    _READLINE = True
except ImportError:
    _READLINE = False

CONFIG_FILE = Path.home() / ".seahorse" / "config.json"

# ---------------------------------------------------------------------------
# Default starting state
# ---------------------------------------------------------------------------

DEFAULTS = {
    "name": "",                # what Seahorse calls you in its greeting (optional)
    "theme": "ocean",          # ocean | reef | abyss | kelp | daylight | mono
    "logo": "full",            # full | compact | minimal | trident | none
    "status_panel": True,      # show the status box at start
    "greeting": True,          # time-of-day greeting at start
    "spinner": "trident",      # trident | wave
    "boxed_replies": True,     # draw replies in rounded boxes
    "show_perception": True,   # show what each agent noticed in your message
    "agent_mode": "auto",      # auto routing, or an agent name to start with
    "backend_mode": "auto",    # auto | claude | local
    "sub_brains": {},          # per agent: false turns a sub-agent brain off (/brain)
    "lobes": True,             # Doc (left) and Fiery Black (right) read for Seahorse (/lobes)
    "lobe_balance": "even",    # even | left | right
    "judge": True,             # the Judge rules between the lobes (/judge)
    "crew": True,              # each agent answers as their crew member (/crew)
    "seals": True,             # stamp each reply with the crew member's notary seal
    "lobe_min_words": 10,      # the lobes vote on messages at least this long
    "lobe_timeout": 45,        # seconds before a slow lobe abstains
    "lobe_margin": 0.25,       # how close a vote counts as a split for the Judge
    "lobe_parallel": True,     # both lobes vote at once
    "council": True,           # all ten agents vote on who answers in auto mode
    "council_steps": 3,        # most agents in one relay
    "council_approval": True,  # approval vote between relay steps
    "council_threshold": 0.66, # share of approvers needed to continue
    "council_revisions": 1,    # times a step can be sent back
    "law_threshold": 10,       # ayes needed to mint a law (10 pennies = a dime)
}

THEMES = {
    "ocean": {"desc": "teal and aqua on deep blue, coral accents (default)",
              "foam": 195, "aqua": 51, "teal": 37, "sea": 31, "deep": 25, "coral": 209, "sand": 180,
              "kelp": 71, "gradient": [51, 45, 39, 33, 25], "art": 209},
    "reef": {"desc": "warm corals and sand",
             "foam": 224, "aqua": 217, "teal": 174, "sea": 167, "deep": 131, "coral": 209, "sand": 223,
             "kelp": 114, "gradient": [223, 217, 211, 209, 203], "art": 217},
    "abyss": {"desc": "deep-sea indigo and violet glow",
              "foam": 153, "aqua": 111, "teal": 67, "sea": 61, "deep": 17, "coral": 141, "sand": 146,
              "kelp": 72, "gradient": [159, 123, 111, 105, 99], "art": 141},
    "kelp": {"desc": "kelp-forest greens and gold",
             "foam": 194, "aqua": 121, "teal": 72, "sea": 65, "deep": 22, "coral": 179, "sand": 187,
             "kelp": 114, "gradient": [157, 121, 85, 72, 65], "art": 179},
    "daylight": {"desc": "darker tones for light terminal backgrounds",
                 "foam": 24, "aqua": 30, "teal": 30, "sea": 24, "deep": 18, "coral": 166, "sand": 94,
                 "kelp": 28, "gradient": [30, 31, 25, 24, 18], "art": 166},
    "mono": {"desc": "no colour at all"},
}

ICONS = {  # unicode, ascii
    "hippocampus": ("∫", "S"), "broca": ("✎", "W"), "parietal": ("∑", "#"), "cerebellum": ("λ", "L"),
    "wernicke": ("◎", "O"), "prefrontal": ("↗", ">"), "cingulate": ("✓", "!"),
    "doc": ("§", "D"), "fiery-black": ("▲", "^"), "judge": ("⚖", "J"),
}
APP_ICONS = {  # the app window can show emoji: the party animals
    "doc": "🫏", "fiery-black": "🐘", "judge": "⚖️",
}

TERMINAL_COLOR = (sys.stdout.isatty() and "NO_COLOR" not in os.environ) or bool(os.environ.get("FORCE_COLOR"))
UNICODE = (sys.stdout.encoding or "").lower().replace("-", "").startswith("utf")
if os.name == "nt" and TERMINAL_COLOR:
    os.system("")  # turn on ANSI colour handling in the Windows console

COLOR = TERMINAL_COLOR
THEME = "ocean"
SPINNER_STYLE = "trident"
BOXED = True


def c256(n):
    return f"\033[38;5;{n}m" if COLOR and n is not None else ""


RESET = "\033[0m" if TERMINAL_COLOR else ""
BOLD = "\033[1m" if TERMINAL_COLOR else ""
DIM = "\033[2m" if TERMINAL_COLOR else ""
ITALIC = "\033[3m" if TERMINAL_COLOR else ""


def xterm_hex(n):
    """xterm 256-colour number -> #rrggbb."""
    n = int(n)
    base = ["000000", "800000", "008000", "808000", "000080", "800080", "008080", "c0c0c0",
            "808080", "ff0000", "00ff00", "ffff00", "0000ff", "ff00ff", "00ffff", "ffffff"]
    if n < 16:
        return "#" + base[n]
    if n < 232:
        n -= 16
        levels = [0, 95, 135, 175, 215, 255]
        r, g, b = levels[n // 36], levels[(n // 6) % 6], levels[n % 6]
        return f"#{r:02x}{g:02x}{b:02x}"
    v = 8 + 10 * (n - 232)
    return f"#{v:02x}{v:02x}{v:02x}"


def paint_color(text, color):
    """Bold text in a 256-colour (plain without colour)."""
    return f"{BOLD}{c256(color)}{text}{RESET}" if COLOR else text

FOAM = AQUA = TEAL = SEA = DEEP = CORAL = SAND = KELP = ART = ""
GRADIENT = [""] * 5


def apply_theme(name):
    """Switch every themed colour. Unknown names fall back to ocean."""
    global THEME, COLOR, FOAM, AQUA, TEAL, SEA, DEEP, CORAL, SAND, KELP, ART, GRADIENT
    THEME = name if name in THEMES else "ocean"
    COLOR = TERMINAL_COLOR and THEME != "mono"
    t = THEMES[THEME] if THEME != "mono" else THEMES["ocean"]
    FOAM, AQUA, TEAL, SEA, DEEP = (c256(t[k]) for k in ("foam", "aqua", "teal", "sea", "deep"))
    CORAL, SAND, KELP, ART = (c256(t[k]) for k in ("coral", "sand", "kelp", "art"))
    GRADIENT = [c256(n) for n in t["gradient"]]
    return THEME


apply_theme("ocean")

TRIDENT = "Ψ" if UNICODE else "W"
H, V = ("─", "│") if UNICODE else ("-", "|")
TL, BL = ("╭", "╰") if UNICODE else ("+", "+")
WAVES = "~≈~∽~≈~∽" if UNICODE else "~-~-~-~-"


def width():
    return max(40, min(shutil.get_terminal_size((80, 24)).columns, 100))


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def load_config():
    """Returns (config, first_run). Creates the file with defaults on first run."""
    first = not CONFIG_FILE.exists()
    cfg = dict(DEFAULTS)
    if not first:
        try:
            cfg.update({k: v for k, v in json.loads(CONFIG_FILE.read_text()).items() if k in DEFAULTS})
        except (OSError, json.JSONDecodeError):
            pass
    else:
        save_config(cfg)
    return cfg, first


def save_config(cfg):
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n")
    except OSError:
        pass


def apply_config(cfg):
    global SPINNER_STYLE, BOXED
    apply_theme(cfg.get("theme", "ocean"))
    SPINNER_STYLE = cfg.get("spinner", "trident")
    BOXED = bool(cfg.get("boxed_replies", True))


def coerce(key, value):
    """Turn a /config text value into the right type, or raise ValueError."""
    default = DEFAULTS[key]
    if isinstance(default, bool):
        if value.lower() in ("on", "true", "yes", "1"):
            return True
        if value.lower() in ("off", "false", "no", "0"):
            return False
        raise ValueError("use on or off")
    choices = {"theme": list(THEMES), "logo": ["full", "compact", "minimal", "trident", "none"],
               "spinner": ["trident", "wave"], "backend_mode": ["auto", "claude", "local"]}
    if key in choices and value not in choices[key]:
        raise ValueError("choose one of: " + ", ".join(choices[key]))
    return value


# ---------------------------------------------------------------------------
# Icons
# ---------------------------------------------------------------------------

def icon_for(name, custom=None):
    if custom:
        return custom if UNICODE or custom.isascii() else custom[:1]
    pair = ICONS.get(name)
    if pair:
        return pair[0] if UNICODE else pair[1]
    return (name[:1] or "?").upper()


def agent_icon(name, color, custom=None):
    return f"{BOLD}{c256(color)}{icon_for(name, custom)}{RESET}"


def agent_name(name, color, custom=None, with_icon=True):
    """An agent's icon and name in its own colour."""
    mark = f"{icon_for(name, custom)} " if with_icon else ""
    return f"{BOLD}{c256(color)}{mark}{name}{RESET}"


# ---------------------------------------------------------------------------
# Logos
# ---------------------------------------------------------------------------

_FONT = {
    "S": [" ████", "█    ", " ███ ", "    █", "████ "],
    "E": ["█████", "█    ", "████ ", "█    ", "█████"],
    "A": [" ███ ", "█   █", "█████", "█   █", "█   █"],
    "H": ["█   █", "█   █", "█████", "█   █", "█   █"],
    "O": [" ███ ", "█   █", "█   █", "█   █", " ███ "],
    "R": ["████ ", "█   █", "████ ", "█  █ ", "█   █"],
}

SEAHORSE_ART = [
    r"      _/\_      ",
    r"     /  o \___  ",
    r"     \    ___/  ",
    r"      )  (      ",
    r"     /    }     ",
    r"    (     }     ",
    r"     \    }     ",
    r"      )  /      ",
    r"     (  (       ",
    r"      \  `-.    ",
    r"       `-._)    ",
]

SEAHORSE_SMALL = [
    r"  _/\_     ",
    r" / o  \__  ",
    r" \  __(    ",
    r"  ) (_.)   ",
]

TRIDENT_ART = [
    r" \    |    / ",
    r"  \   |   /  ",
    r"   \__|__/   ",
    r"      |      ",
    r"      |      ",
    r"      |      ",
    r"     /_\     ",
]


def _title_rows(word="SEAHORSE"):
    rows = []
    for r in range(5):
        row = " ".join(_FONT[ch][r] for ch in word)
        rows.append(row if UNICODE else row.replace("█", "#"))
    return rows


def _wave(w=None):
    w = w or width()
    return f" {SEA}{(WAVES * (w // len(WAVES) + 1))[: w - 2]}{RESET}"


def _side_by_side(art, art_color, right):
    pad = max(0, (len(art) - len(right)) // 2)
    for i, a in enumerate(art):
        r = right[i - pad] if 0 <= i - pad < len(right) else ""
        print(f"  {art_color}{a}{RESET}  {r}")


def logo(style="full", subtitle=""):
    """Print one of Seahorse's logos."""
    if style == "none":
        return
    w = width()
    sub = f"{SAND}{ITALIC}{subtitle}{RESET}" if subtitle else ""
    title = [f"{BOLD}{GRADIENT[i]}{row}{RESET}" for i, row in enumerate(_title_rows())]
    title_w = len(_title_rows()[0])
    print()
    if style == "minimal" or (style in ("full", "trident") and w < title_w + 6):
        print(f"  {BOLD}{CORAL}{TRIDENT}{RESET} {BOLD}{AQUA}seahorse{RESET}  {sub}")
    elif style == "compact":
        spaced = " ".join("SEAHORSE")
        _side_by_side(SEAHORSE_SMALL, ART, [f"{BOLD}{CORAL}{TRIDENT}{RESET}  {BOLD}{AQUA}{spaced}{RESET}", sub])
    else:
        art, color = (TRIDENT_ART, CORAL) if style == "trident" else (SEAHORSE_ART, ART)
        right = title + ([sub] if sub else [])
        if w >= len(art[0]) + title_w + 6:
            _side_by_side(art, color, right)
        else:
            for r in right:
                print(f"  {r}")
    print(_wave(w))


def banner(subtitle="", lines=(), style="full"):
    """The start screen: logo plus an optional status panel."""
    logo(style, subtitle)
    if lines:
        panel(lines)


def _time_of_day():
    h = datetime.now().hour
    return ("night" if h >= 22 or h < 5 else "morning" if h < 12 else "afternoon" if h < 17 else "evening")


def greeting(name="", character=None):
    """The start-up greeting, in the character's own words when it has them."""
    who = f", {name}" if name else ""
    if character and character.get("enabled") and character.get("greetings"):
        opener = character["greetings"][datetime.now().day % len(character["greetings"])]
        phrase = (character.get("time_phrases") or {}).get(_time_of_day(), "")
        line = f"{opener}{who}!"
        if phrase:
            line += f" {phrase[0].upper() + phrase[1:]}."
        if character.get("ready_line"):
            line += f" {character['ready_line']}"
        return line
    part = {"morning": "Good morning", "afternoon": "Good afternoon", "evening": "Good evening",
            "night": "Hello, night owl"}[_time_of_day()]
    tide = ["the tide is in", "calm waters today", "the current's with you", "fair seas"][datetime.now().day % 4]
    return f"{part}{who if part != 'Hello, night owl' else ''} - {tide}."


def farewell(character=None):
    if character and character.get("enabled") and character.get("farewells"):
        return character["farewells"][datetime.now().minute % len(character["farewells"])]
    return "see you on the next tide"


def panel(lines, title="status"):
    """A rounded box of key: value lines."""
    w = min(width() - 2, 78)
    head = f" {TRIDENT} {title} "
    print(f" {TEAL}{TL}{H}{RESET}{BOLD}{AQUA}{head}{RESET}{TEAL}{H * max(0, w - len(head) - 2)}{RESET}")
    kw = max([9] + [len(str(l[0])) for l in lines if isinstance(l, tuple)])
    for line in lines:
        if isinstance(line, tuple):
            key, val = line
            print(f" {TEAL}{V}{RESET}  {SAND}{key:<{kw}}{RESET} {val}")
        else:
            print(f" {TEAL}{V}{RESET}  {line}")
    print(f" {TEAL}{BL}{H * (w - 1)}{RESET}\n")


def theme_swatch(name):
    """One line showing a theme's colours."""
    if name == "mono" or not TERMINAL_COLOR:
        return f"{name:<9} {THEMES[name]['desc']}"
    t = THEMES[name]
    blocks = "".join(f"\033[38;5;{t[k]}m██" for k in ("foam", "aqua", "teal", "sea", "deep", "coral", "sand", "kelp"))
    return f"{name:<9} {blocks}\033[0m {t['desc']}"


# ---------------------------------------------------------------------------
# Prompt and small text helpers
# ---------------------------------------------------------------------------

def _rl(code):
    """Wrap colour codes so readline measures the prompt correctly."""
    return f"\001{code}\002" if (_READLINE and code) else code


def prompt(continuation=False):
    if continuation:
        return f"  {_rl(TEAL)}{'⋮' if UNICODE else ':'}{_rl(RESET)} "
    return f"{_rl(CORAL)}{TRIDENT}{_rl(RESET)} {_rl(BOLD)}{_rl(FOAM)}you{_rl(RESET)} {_rl(TEAL)}›{_rl(RESET)} "


def note(text):
    """A quiet system line."""
    print(f"  {DIM}{SEA}~{RESET} {DIM}{text}{RESET}")


def section(text, color=None):
    tint = c256(color) if color is not None else AQUA
    print(f"\n {TEAL}{H * 2}{RESET} {BOLD}{tint}{text}{RESET} {TEAL}{H * max(0, min(width(), 80) - len(text) - 6)}{RESET}")


def tree_line(last_flags, text):
    """One line of a branch diagram. last_flags[i]: was the ancestor at depth i its parent's last child."""
    if UNICODE:
        mid, end, pipe, gap = "├─ ", "└─ ", "│  ", "   "
    else:
        mid, end, pipe, gap = "|- ", "`- ", "|  ", "   "
    if not last_flags:
        return f"  {text}"
    prefix = "".join(gap if last else pipe for last in last_flags[:-1])
    return f"  {TEAL}{prefix}{end if last_flags[-1] else mid}{RESET}{text}"


# ---------------------------------------------------------------------------
# Loading animation
# ---------------------------------------------------------------------------

class Spinner:
    """A pulsing trident with rising bubbles (or a rolling wave) while Seahorse works.

        with Spinner("thinking"):
            ...work...
    """

    _BUBBLES = (["   ", "  ·", " ·∘", "·∘°", "∘°·", "°· ", "·  "] if UNICODE
                else ["   ", "  .", " .o", ".oO", "oO.", "O. ", ".  "])
    _WAVE = ("≈∽≈~", "∽≈~≈", "≈~≈∽", "~≈∽≈") if UNICODE else ("~-~=", "-~=~", "~=~-", "=~-~")

    def __init__(self, label="thinking"):
        self.label = label
        self._stop = threading.Event()
        self._thread = None
        self.active = COLOR and sys.stdout.isatty()
        self._colors = [DEEP, SEA, TEAL, AQUA, FOAM, AQUA, TEAL, SEA]

    def _frame(self, i):
        color = self._colors[i % len(self._colors)]
        if SPINNER_STYLE == "wave":
            w = self._WAVE[i % len(self._WAVE)]
            return f"  {color}{w * 2}{RESET} {SAND}{ITALIC}{self.label}{RESET}"
        bubbles = self._BUBBLES[i % len(self._BUBBLES)]
        return f"  {BOLD}{color}{TRIDENT}{RESET} {SAND}{ITALIC}{self.label}{RESET} {TEAL}{bubbles}{RESET}"

    def _run(self):
        i = 0
        start = time.time()
        while not self._stop.is_set():
            secs = time.time() - start
            clock = f" {DIM}{secs:.0f}s{RESET}" if secs >= 3 else ""
            sys.stdout.write("\r" + self._frame(i) + clock + "\033[K")
            sys.stdout.flush()
            i += 1
            self._stop.wait(0.12)
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

    def start(self):
        if self.active and self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def stop(self):
        if self._thread is not None:
            self._stop.set()
            self._thread.join()
            self._thread = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


# ---------------------------------------------------------------------------
# Replies
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Markdown, rendered as it streams
# ---------------------------------------------------------------------------

CODE_KEYWORDS = set("""
and as assert async await break case catch class const continue def defer del do elif else enum export extends
false fn for from func function go if impl import in interface is lambda let loop match mod mut new nil none not
null or package pass pub raise return self static struct super switch this throw trait true try type typeof union
unsafe use var void while with yield comptime errdefer usingnamespace True False None echo fi then done esac local
""".split())
_CODE_TOKEN = re.compile(r"(?P<comment>#[^\n]*|//[^\n]*|--\s[^\n]*)|(?P<string>\"(?:\\.|[^\"\\])*\"?|'(?:\\.|[^'\\])*'?|`[^`]*`?)"
                         r"|(?P<number>\b\d[\d_]*(?:\.\d+)?(?:e[+-]?\d+)?\b|\b0x[0-9a-fA-F_]+\b)"
                         r"|(?P<word>[A-Za-z_][A-Za-z0-9_]*)(?P<call>\s*\()?")


def highlight_code(line, lang=""):
    """Colour one line of code: keywords, strings, comments, numbers, function names."""
    if not COLOR:
        return line
    if lang in ("text", "txt", "plain", "output", "console", "log"):
        return line
    out, pos = [], 0
    for m in _CODE_TOKEN.finditer(line):
        out.append(line[pos:m.start()])
        if m.group("comment"):
            if m.group("comment").startswith("#") and lang in ("c", "cpp", "c++", "rust", "zig", "go", "js",
                                                              "javascript", "ts", "typescript", "java", "css"):
                out.append(m.group(0))  # '#' isn't a comment there (#include, #[derive])
            else:
                out.append(f"{DIM}{ITALIC}{m.group('comment')}{RESET}")
        elif m.group("string"):
            out.append(f"{KELP}{m.group('string')}{RESET}")
        elif m.group("number"):
            out.append(f"{SAND}{m.group('number')}{RESET}")
        else:
            word, call = m.group("word"), m.group("call") or ""
            if word in CODE_KEYWORDS:
                out.append(f"{CORAL}{word}{RESET}{call}")
            elif call:
                out.append(f"{AQUA}{word}{RESET}{call}")
            else:
                out.append(word + call)
        pos = m.end()
    out.append(line[pos:])
    return "".join(out)


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def visible_len(text):
    return len(_ANSI.sub("", text))


class MarkdownStream:
    """Turns streamed Markdown into styled terminal text, a piece at a time.

    Prose streams character by character (bold, `code`, wrapping at word
    boundaries); a line's first few characters decide whether it is a heading,
    list item, quote, rule, table row or code fence; code lines are coloured
    as each one completes.
    """

    MARKERS = ("```", "#", "- ", "* ", "+ ", "> ", "|", "---", "***", "___")

    def __init__(self, width=None):
        self.width = (width or globals()["width"]()) - 6
        self.line = ""          # undecided start of the current line
        self.decided = False    # the current line's kind is known
        self.kind = "prose"
        self.in_code = False
        self.code_lang = ""
        self.code_line = ""
        self.bold = self.icode = False
        self.star = False       # a single '*' waiting to see if it's '**'
        self.col = 0
        self.indent = ""

    # -- helpers
    def _style(self):
        return (BOLD if self.bold or self.kind == "heading" else "") + (AQUA if self.kind == "heading" else "") + \
               (SAND if self.icode else "")

    def _emit_char(self, ch):
        if ch == " " and self.col >= self.width:
            self.col = len(self.indent)
            return f"{RESET}\n{self.indent}{self._style()}"
        self.col += 1
        return ch

    def _inline(self, ch):
        out = ""
        if self.star:
            self.star = False
            if ch == "*":
                self.bold = not self.bold
                return RESET + self._style()
            out += self._emit_char("*")
        if ch == "*":
            self.star = True
            return out
        if ch == "`":
            self.icode = not self.icode
            return out + RESET + self._style()
        return out + self._emit_char(ch)

    def _start_line(self):
        """Decide what the buffered start of a line is; returns the prefix to print."""
        raw = self.line
        stripped = raw.lstrip(" ")
        lead = raw[:len(raw) - len(stripped)]
        self.indent = lead + "  "
        if stripped.startswith("#"):
            self.kind = "heading"
            text = stripped.lstrip("#").lstrip(" ")
            return f"{lead}{BOLD}{AQUA}", text
        if stripped[:2] in ("- ", "* ", "+ "):
            self.kind = "prose"
            return f"{lead}{TEAL}•{RESET} ", stripped[2:]
        m = re.match(r"(\d+)([.)]) ", stripped)
        if m:
            self.kind = "prose"
            self.indent = lead + " " * (len(m.group(0)))
            return f"{lead}{TEAL}{m.group(1)}{m.group(2)}{RESET} ", stripped[len(m.group(0)):]
        if stripped.startswith("> "):
            self.kind = "quote"
            self.indent = lead + "▏ "
            return f"{lead}{SEA}▏{RESET} {ITALIC}", stripped[2:]
        self.kind = "prose"
        self.indent = lead
        return "", raw

    def _finish_whole_line(self, raw):
        """Lines handled whole: fences, code, tables, rules."""
        stripped = raw.strip()
        if stripped.startswith("```"):
            if not self.in_code:
                self.in_code = True
                self.code_lang = stripped[3:].strip().lower()
                label = self.code_lang or "code"
                bar = H * max(4, min(self.width, 60) - len(label) - 4)
                return f"{SEA}{'┌' if UNICODE else '+'}{H} {RESET}{DIM}{label}{RESET} {SEA}{bar}{RESET}\n"
            self.in_code = False
            return f"{SEA}{'└' if UNICODE else '+'}{H * min(self.width, 60)}{RESET}\n"
        if self.in_code:
            return f"{SEA}{V}{RESET} {highlight_code(raw, self.code_lang)}\n"
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                return f"{DIM}{H * min(self.width, 60)}{RESET}\n"
            return f" {DIM}{V}{RESET} ".join(cells) + "\n"
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", stripped):
            return f"{DIM}{H * min(self.width, 60)}{RESET}\n"
        return None

    # -- public
    def feed(self, text):
        out = []
        for ch in text:
            if ch == "\n":
                out.append(self._newline())
                continue
            if self.in_code or (not self.decided and self._whole_line_kind(self.line + ch)):
                self.line += ch
                continue
            if not self.decided:
                self.line += ch
                if len(self.line.lstrip(" ")) < 4 and any(m.startswith(self.line.lstrip(" ")) or
                                                          self.line.lstrip(" ").startswith(m) for m in self.MARKERS) \
                        and not re.match(r"\s*\d+[.)] ", self.line):
                    if not re.match(r"\s*\d+$", self.line):
                        continue
                if re.match(r"\s*\d+$", self.line):
                    continue
                prefix, rest = self._start_line()
                self.decided = True
                self.col = visible_len(prefix)
                out.append(prefix + self._style())
                for c in rest:
                    out.append(self._inline(c))
                continue
            out.append(self._inline(ch))
        return "".join(out)

    def _whole_line_kind(self, start):
        s = start.lstrip(" ")
        return self.in_code or s.startswith("```") or s.startswith("|") or \
            (len(s) >= 3 and re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s) is not None) or s in ("-", "--", "*", "**", "_", "__")

    def _newline(self):
        if self.in_code or (not self.decided and self._whole_line_kind(self.line)):
            done = self._finish_whole_line(self.line)
            self.line = ""
            if done is not None:
                return done
        out = ""
        if not self.decided and self.line:
            prefix, rest = self._start_line()
            out += prefix + self._style() + "".join(self._inline(c) for c in rest)
        if self.star:
            out += "*"
            self.star = False
        self.line, self.decided, self.kind = "", False, "prose"
        self.bold = self.icode = False
        self.col = 0
        return out + RESET + "\n"

    def flush(self):
        if self.line or self.decided or self.star:
            out = self._newline().rstrip("\n")
        else:
            out = ""
        if self.in_code:
            self.in_code = False
            out += f"\n{SEA}{'└' if UNICODE else '+'}{H * min(self.width, 60)}{RESET}"
        return out


class ReplyBox:
    """Draws a reply as it streams in, with Markdown rendered:

        ╭─ ✎ broca · Claude (claude-sonnet-5-5)
        │ The reply text, wrapped inside the box, **bold** and `code` styled...
        │ ┌─ python ────────
        │ │ print("hello")
        │ └────────────────
        ╰─ 2.4s
    """

    def __init__(self, agent, backend_label, color=None, icon=None, seal=""):
        self.agent = agent
        self.seal = seal   # the crew member's notary seal, stamped on the closing line
        self.backend = backend_label
        self.color = c256(color) if color is not None else CORAL
        self.icon = icon_for(agent, icon)
        self.started = time.time()
        self.opened = False
        self.boxed = BOXED
        self.gutter = f"{TEAL}{V}{RESET} " if self.boxed else ""
        self.md = MarkdownStream()
        self.chars = 0
        self.at_line_start = True   # the cursor sits on a fresh gutter

    def open(self):
        if not self.opened:
            head = f"{BOLD}{self.color}{self.icon} {self.agent}{RESET} {DIM}· {self.backend}{RESET}"
            print(f"{TEAL}{TL}{H}{RESET} {head}" if self.boxed else head)
            sys.stdout.write(self.gutter)
            self.opened = True

    def _out(self, text):
        if not text:
            return
        self.at_line_start = text.endswith("\n")
        if text.endswith("\n"):  # hold the gutter for the next line so the box closes cleanly
            text = text[:-1].replace("\n", "\n" + self.gutter) + "\n" + self.gutter
        else:
            text = text.replace("\n", "\n" + self.gutter)
        sys.stdout.write(text)
        sys.stdout.flush()

    def write(self, text):
        self.open()
        self.chars += len(text)
        self._out(self.md.feed(text))

    def close(self, note_text=""):
        self.open()
        tail = self.md.flush()
        if tail:
            self._out(tail)
        secs = time.time() - self.started
        words = f" · {self.chars // 5} words" if self.chars > 400 else ""
        extra = f" · {note_text}" if note_text else ""
        stamp = f"  {self.color}{self.seal}{RESET}" if self.seal else ""
        if self.boxed:
            lead = "\r" if self.at_line_start else "\n"
            print(f"{lead}{TEAL}{BL}{H}{RESET} {DIM}{secs:.1f}s{words}{extra}{RESET}{stamp}\n")
        else:
            print(f"\n{DIM}{secs:.1f}s{words}{extra}{RESET}{stamp}\n")
