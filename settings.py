#!/usr/bin/env python3
"""
settings.py - every Seahorse setting in one place, for the app's Settings tab.

SECTIONS describes each setting once: where it lives, what kind of control it
is and what values it accepts. describe() reads the current values for the
app; apply() validates changes, applies them to the running session and saves
them. Nothing here trusts the browser: every value is checked against its
field before it touches anything.

Most settings live in ~/.seahorse/config.json (the same file /config edits).
A few live where they always have: the character in personality.json, the
inner voice and Bureau of Magic in agency.db, the profile switch in
profile.db. The Claude API key is never saved: it is held for this run only.
"""

import os
import re
from pathlib import Path

import crew
import lobes
import ui

HOME = Path.home() / ".seahorse"

# Each field: key, label, help, kind, and its limits. kind is one of
# toggle, select, segmented, number, slider, text, secret.
SECTIONS = [
    {"id": "general", "title": "General", "icon": "∫",
     "blurb": "Who you are to Seahorse, and how each chat starts.",
     "fields": [
         {"key": "name", "label": "Your name", "kind": "text", "max": 60,
          "help": "Used in his greeting. Leave empty to stay anonymous."},
         {"key": "agent_mode", "label": "Who answers", "kind": "select", "options": "agents",
          "help": "Auto picks the best agent for each message; or keep one agent at the helm."},
         {"key": "backend_mode", "label": "Models", "kind": "segmented",
          "options": [["auto", "Claude first"], ["claude", "Claude only"], ["local", "Local only"]],
          "help": "Auto uses Claude when it's reachable and your local model when it isn't."},
         {"key": "incognito", "label": "Incognito chat", "kind": "toggle", "where": "session",
          "help": "This chat won't be remembered, learned from or added to his profile of you."},
     ]},
    {"id": "models", "title": "Models & limits", "icon": "⚙",
     "blurb": "Which models he runs on and how far each reply may go. Environment variables, if set, still win.",
     "fields": [
         {"key": "api_key", "label": "Claude API key", "kind": "secret", "where": "session",
          "help": "Held in memory for this run only and never written to disk. For every run, set "
                  "ANTHROPIC_API_KEY before starting Seahorse."},
         {"key": "claude_model", "label": "Claude model", "kind": "text", "max": 80, "where": "model",
          "help": "The Claude API model ID, e.g. claude-sonnet-5-5."},
         {"key": "local_model", "label": "Local model", "kind": "select", "options": "installed", "where": "model",
          "help": "The Ollama model used offline. 'seahorse' is your own built model."},
         {"key": "base_model", "label": "Base model for 'seahorse'", "kind": "text", "max": 80, "where": "persona",
          "help": "What the seahorse Modelfile builds on (FROM). Rebuild the model after changing it."},
         {"key": "max_tokens", "label": "Longest Claude reply (tokens)", "kind": "number", "min": 1024, "max": 128000,
          "step": 1024, "where": "model", "help": "Per reply. Replies cut off by the limit continue automatically."},
         {"key": "max_continuations", "label": "Automatic continuations", "kind": "number", "min": 0, "max": 20,
          "help": "How many times a cut-off reply carries on by itself."},
         {"key": "num_ctx", "label": "Local context window (tokens)", "kind": "number", "min": 0, "max": 131072,
          "step": 1024, "where": "model", "help": "0 sizes it automatically from the model and your free memory."},
         {"key": "keep_alive", "label": "Keep the local model loaded", "kind": "select", "where": "model",
          "options": [["5m", "5 minutes"], ["30m", "30 minutes"], ["2h", "2 hours"], ["24h", "a day"],
                      ["-1", "always"]],
          "help": "Longer means faster replies after a pause, but holds memory."},
     ]},
    {"id": "character", "title": "Character & crew", "icon": "♆",
     "blurb": "The Seahorse and his crew. Edit each crew member's 11 steps in the Crew section.",
     "fields": [
         {"key": "character_enabled", "label": "Play the character", "kind": "toggle", "where": "persona",
          "help": "Off, he speaks plainly as himself, with no accent or story."},
         {"key": "character_strength", "label": "Accent strength", "kind": "segmented", "where": "persona",
          "options": [["light", "Light"], ["medium", "Medium"], ["strong", "Strong"]],
          "help": "How strongly the voice comes through. Code and drafts are always standard English."},
         {"key": "crew", "label": "Crew voices", "kind": "toggle",
          "help": "Each agent answers as their own crew member. Off, every agent speaks as the captain."},
         {"key": "seals", "label": "Notary seals", "kind": "toggle",
          "help": "Stamp each reply with the crew member's seal, like a signature."},
     ]},
    {"id": "lobes", "title": "Lobes & Judge", "icon": "⚖",
     "blurb": "Doc (left) and Fiery Black (right) vote on how Seahorse answers; the Judge breaks close splits.",
     "fields": [
         {"key": "lobes", "label": "Lobe vote", "kind": "toggle",
          "help": "Off makes Seahorse's own replies faster, without the lobes' advice."},
         {"key": "lobe_balance", "label": "Balance", "kind": "segmented",
          "options": [["left", "Left · Doc"], ["even", "Even"], ["right", "Right · Fiery Black"]],
          "help": "A leaning lobe's vote counts 1.25 and the other 0.8."},
         {"key": "judge", "label": "Judge breaks ties", "kind": "toggle",
          "help": "Off, a close split goes to the higher score without an extra call."},
         {"key": "lobe_min_words", "label": "Vote on messages of at least (words)", "kind": "number", "min": 1, "max": 500},
         {"key": "lobe_margin", "label": "Split margin", "kind": "slider", "min": 0, "max": 1, "step": 0.05,
          "help": "How far ahead an approach must be to win without the Judge. Higher calls the Judge more often."},
         {"key": "lobe_timeout", "label": "Time limit (seconds)", "kind": "number", "min": 3, "max": 600,
          "help": "A lobe slower than this abstains, and the other's ballot stands."},
         {"key": "lobe_parallel", "label": "Vote at the same time", "kind": "toggle",
          "help": "Both lobes at once. If Ollama runs one request at a time, set OLLAMA_NUM_PARALLEL=2 to benefit."},
         {"key": "lobe_cache", "label": "Reuse identical votes", "kind": "toggle",
          "help": "Asking the same thing again reuses the last vote instantly."},
     ]},
    {"id": "brains", "title": "Sub-agent brains", "icon": "≋",
     "blurb": "Inner councils that work on a message before Doc or Fiery Black answer it directly.",
     "fields": "sub_brains"},
    {"id": "inner", "title": "Inner voice & magic", "icon": "☉",
     "blurb": "His conscience re-reads replies; the Bureau of Magic slips in the odd surprise.",
     "fields": [
         {"key": "conscience", "label": "Conscience", "kind": "toggle", "where": "agency",
          "help": "After a reply, his inner voice may add an 'on second thought' if something was off."},
         {"key": "magic", "label": "Bureau of Magic", "kind": "segmented", "where": "agency",
          "options": [["often", "Often"], ["sometimes", "Sometimes"], ["rarely", "Rarely"], ["off", "Off"]],
          "help": "Stories, riddles, ideas and small gifts. Never when you seem stressed or busy."},
     ]},
    {"id": "privacy", "title": "Memory & privacy", "icon": "▤",
     "blurb": "What he keeps, and his portrait of you.",
     "fields": [
         {"key": "profile_enabled", "label": "Profile of you", "kind": "toggle", "where": "profile",
          "help": "His opinionated, non-clinical portrait of you, built from your chats. Off pauses it."},
         {"key": "show_perception", "label": "Show what agents noticed", "kind": "toggle",
          "help": "The small chips under your message."},
     ]},
    {"id": "look", "title": "Look", "icon": "◐",
     "blurb": "Colours for the app and terminal; the rest shapes the terminal version.",
     "fields": [
         {"key": "theme", "label": "Theme", "kind": "select", "options": "themes"},
         {"key": "logo", "label": "Logo (terminal)", "kind": "select",
          "options": [["full", "Full"], ["compact", "Compact"], ["minimal", "Minimal"], ["trident", "Trident"],
                      ["none", "None"]]},
         {"key": "spinner", "label": "Spinner (terminal)", "kind": "segmented",
          "options": [["trident", "Trident"], ["wave", "Wave"]]},
         {"key": "boxed_replies", "label": "Boxed replies (terminal)", "kind": "toggle"},
         {"key": "status_panel", "label": "Status panel at start (terminal)", "kind": "toggle"},
         {"key": "greeting", "label": "Greeting at start", "kind": "toggle"},
     ]},
    {"id": "images", "title": "Images", "icon": "◎",
     "blurb": "Where your local image engines are listening.",
     "fields": [
         {"key": "a1111_url", "label": "Stable Diffusion WebUI", "kind": "text", "max": 200, "url": True,
          "help": "AUTOMATIC1111 or Forge, started with --api."},
         {"key": "comfy_url", "label": "ComfyUI", "kind": "text", "max": 200, "url": True},
     ]},
]

DEFAULTS = {**ui.DEFAULTS, **lobes.DEFAULTS, "max_continuations": 8, "claude_model": "", "local_model": "",
            "max_tokens": 0, "num_ctx": 0, "keep_alive": "", "a1111_url": "http://127.0.0.1:7860",
            "comfy_url": "http://127.0.0.1:8188"}


class SettingError(ValueError):
    pass


def _fields():
    for section in SECTIONS:
        if isinstance(section["fields"], list):
            for f in section["fields"]:
                yield f


FIELD = {f["key"]: f for f in _fields()}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def _options(session, f):
    opts = f.get("options")
    if opts == "agents":
        return [["auto", "Auto (best agent)"]] + [[n, n] for n in session.agents.agents]
    if opts == "installed":
        names = session.local.installed_models()
        if session.local.model not in names:
            names = [session.local.model] + names
        return [[n, n] for n in names]
    if opts == "themes":
        return [[k, f"{k} - {v.get('desc', '')}"] for k, v in ui.THEMES.items()]
    return opts


def value(session, key):
    cfg = session.config
    if key == "incognito":
        return session.incognito
    if key == "api_key":
        return bool(session.claude.api_key)
    if key == "claude_model":
        return session.claude.model
    if key == "local_model":
        return session.local.model
    if key == "base_model":
        return session.persona.state.get("base_model", "")
    if key == "max_tokens":
        return session.claude.max_tokens
    if key == "num_ctx":
        return int(session.local.fixed_ctx or 0)
    if key == "keep_alive":
        return session.local.keep_alive
    if key == "character_enabled":
        return bool(session.persona.character.get("enabled"))
    if key == "character_strength":
        return session.persona.character.get("strength", "medium")
    if key == "conscience":
        return bool(session.agency.conscience_on()) if session.agency else False
    if key == "magic":
        return session.agency.frequency() if session.agency else "off"
    if key == "profile_enabled":
        return bool(session.profile.enabled) if session.profile else False
    if key == "backend_mode":
        return session.mode
    if key == "agent_mode":
        return session.agent_mode
    v = cfg.get(key)
    return DEFAULTS.get(key) if v is None else v


def describe(session):
    """Everything the Settings tab shows, with current values."""
    out = []
    for section in SECTIONS:
        s = {k: section[k] for k in ("id", "title", "icon", "blurb")}
        if section["fields"] == "sub_brains":
            s["fields"] = [{"key": f"sub_brains.{a.name}", "label": f"{a.name}'s brain", "kind": "toggle",
                            "help": " → ".join(f"{b['icon']} {b['name']}" for b in a.sub_brains),
                            "value": session.sub_brains_on(a)}
                           for a in session.agents.agents.values() if a.sub_brains]
        else:
            s["fields"] = []
            for f in section["fields"]:
                if f.get("where") == "agency" and not session.agency:
                    continue
                g = dict(f)
                g["options"] = _options(session, f)
                g["value"] = value(session, f["key"])
                s["fields"].append(g)
        out.append(s)
    return {"sections": out, "lobeStats": lobes.load_stats(), "lobeStatsText": lobes.describe_stats().strip(),
            "approaches": lobes.APPROACHES, "data": data_summary(session),
            "character": {"title": _title(session), "piece": session.persona.character.get("tale", "")}}


def _title(session):
    from personality import character_title
    return character_title(session.persona.character)


def data_summary(session):
    files = []
    if HOME.exists():
        for p in sorted(HOME.iterdir()):
            if p.name.startswith("."):
                continue
            size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else p.stat().st_size
            files.append({"name": p.name + ("/" if p.is_dir() else ""), "bytes": size})
    stats = {}
    try:
        if session.memory:
            st = session.memory.stats()
            stats = {k: v for k, v in st.items() if isinstance(v, (int, float, str))}
    except Exception:  # noqa: BLE001 - stats are a nicety
        pass
    return {"folder": str(HOME), "files": files, "memory": stats}


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
def _check(f, v, session):
    kind = f["kind"]
    if kind == "toggle":
        if not isinstance(v, bool):
            raise SettingError(f"{f['label']}: expected on or off")
        return v
    if kind in ("select", "segmented"):
        allowed = [o[0] for o in (_options(session, f) or [])]
        if f["key"] == "local_model":
            allowed += [session.local.model]
        if str(v) not in allowed:
            raise SettingError(f"{f['label']}: '{v}' isn't one of the choices")
        return str(v)
    if kind in ("number", "slider"):
        try:
            n = float(v)
        except (TypeError, ValueError):
            raise SettingError(f"{f['label']}: expected a number")
        if not f["min"] <= n <= f["max"]:
            raise SettingError(f"{f['label']}: between {f['min']} and {f['max']}")
        return n if kind == "slider" or f.get("step", 1) < 1 else int(n)
    if kind in ("text", "secret"):
        v = str(v or "").strip()
        if len(v) > f.get("max", 300):
            raise SettingError(f"{f['label']}: too long")
        if f.get("url") and v and not re.match(r"^https?://[\w.\-\[\]:]+(/.*)?$", v):
            raise SettingError(f"{f['label']}: must be an http(s) address")
        return v
    raise SettingError("unknown setting")


def apply(session, changes, hooks=None):
    """Validate and apply {key: value}. Returns a list of notes. Raises SettingError on the first bad value."""
    hooks = hooks or {}
    cfg = session.config
    checked = {}
    for key, v in changes.items():   # validate everything before changing anything
        if key.startswith("sub_brains."):
            agent = session.agents.get(key.split(".", 1)[1])
            if not agent or not agent.sub_brains or not isinstance(v, bool):
                raise SettingError("unknown sub-agent brain")
            checked[key] = v
        elif key in FIELD:
            checked[key] = _check(FIELD[key], v, session)
        else:
            raise SettingError(f"unknown setting: {key}")

    notes, rebuild = [], False
    for key, v in checked.items():
        where = FIELD.get(key, {}).get("where", "config")
        if key.startswith("sub_brains."):
            cfg.setdefault("sub_brains", {})[key.split(".", 1)[1]] = v
        elif key == "incognito":
            session.incognito = v
        elif key == "api_key":
            if v:
                session.claude.api_key = v
                notes.append("API key held for this run only")
        elif key == "agent_mode":
            cfg["agent_mode"] = v
            session.agent_mode = v
            if v != "auto":
                session.agent = session.agents.get(v)
        elif key == "backend_mode":
            cfg["backend_mode"] = v
            session.mode = v
        elif where == "model":
            if key == "claude_model":
                cfg[key] = v
                session.claude.model = v or os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
            elif key == "local_model":
                cfg[key] = v
                session.local.model = v
            elif key == "max_tokens":
                cfg[key] = v
                session.claude.max_tokens = v
            elif key == "num_ctx":
                cfg[key] = v
                from seahorse import apply_model_settings
                apply_model_settings(cfg, session.claude, session.local)
            elif key == "keep_alive":
                cfg[key] = v
                session.local.keep_alive = v
        elif where == "persona":
            p = session.persona
            if key == "base_model":
                p.state["base_model"] = v
                notes.append("rebuild the seahorse model to use the new base")
            elif key == "character_enabled":
                p.character["enabled"] = v
                rebuild = True
            elif key == "character_strength":
                p.character["strength"] = v
                rebuild = True
            p.save()
        elif where == "agency" and session.agency:
            session.agency.set(key, v)
        elif where == "profile" and session.profile:
            session.profile.set_meta("enabled", v)
        else:
            cfg[key] = v
            if key in hooks:
                hooks[key](v)
    ui.save_config(cfg)
    if any(k in checked for k in ("theme", "logo", "spinner", "boxed_replies")):
        ui.apply_config(cfg)
    if rebuild:
        try:
            session.persona.build_ollama(extra=session.extra)
        except Exception:  # noqa: BLE001 - the model rebuild is best-effort
            pass
    return notes


def reset(session, hooks=None):
    """Settings back to their defaults (your character, crew, memories and profile are untouched)."""
    keep = {k: session.config[k] for k in ("name",) if k in session.config}
    session.config.clear()
    session.config.update({**ui.DEFAULTS, **keep})
    ui.save_config(session.config)
    ui.apply_config(session.config)
    session.claude.model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
    session.claude.max_tokens = int(os.environ.get("SEAHORSE_MAX_TOKENS", "16000"))
    session.local.keep_alive = os.environ.get("SEAHORSE_KEEP_ALIVE", "30m")
    from seahorse import apply_model_settings
    apply_model_settings(session.config, session.claude, session.local)
    for key, hook in (hooks or {}).items():
        hook(DEFAULTS.get(key))


# ---------------------------------------------------------------------------
# Crew editing (the 11 steps, as a form)
# ---------------------------------------------------------------------------
CREW_FORM = [
    {"step": 1, "title": "Identity", "fields": [
        {"key": "name", "label": "Name", "kind": "text", "max": 60},
        {"key": "epithet", "label": "Epithet", "kind": "text", "max": 60},
        {"key": "post", "label": "Post aboard", "kind": "text", "max": 100},
        {"key": "seal.sign", "label": "Seal sign", "kind": "text", "max": 2},
        {"key": "seal.motto", "label": "Seal motto", "kind": "text", "max": 40}]},
    {"step": 2, "title": "Backstory", "fields": [{"key": "backstory", "label": "Backstory", "kind": "long", "max": 3000}]},
    {"step": 3, "title": "Tale", "fields": [{"key": "tale", "label": "Tale (kept word for word)", "kind": "long", "max": 3000}]},
    {"step": 4, "title": "Voice", "fields": [{"key": "voice", "label": "Voice", "kind": "long", "max": 1500}]},
    {"step": 5, "title": "Strength", "fields": [{"key": "strength", "label": "Strength", "kind": "segmented",
                                                 "options": [[s, s.title()] for s in crew.STRENGTHS]}]},
    {"step": 6, "title": "Mannerisms", "fields": [{"key": "mannerisms", "label": "Mannerisms (one per line)", "kind": "lines", "max": 8}]},
    {"step": 7, "title": "Spirit", "fields": [{"key": "spirit", "label": "Spirit", "kind": "long", "max": 800}]},
    {"step": 8, "title": "Rules", "fields": [{"key": "rules", "label": "Their rules (one per line)", "kind": "lines", "max": 8}]},
    {"step": 9, "title": "Greetings", "fields": [
        {"key": "greetings", "label": "Greetings (one per line)", "kind": "lines", "max": 8},
        {"key": "farewells", "label": "Farewells (one per line)", "kind": "lines", "max": 8}]},
    {"step": 10, "title": "Traits", "fields": [{"key": "traits", "label": "Trait offsets", "kind": "text", "max": 200}]},
    {"step": 11, "title": "Preview", "fields": []},
]


def crew_state(session):
    from personality import CORE_CHARACTER_RULES, STRENGTH
    members = []
    for name, agent in session.agents.agents.items():
        m = crew.get(name)
        if not m:
            continue
        if not m.get("traits"):
            m["traits"] = ", ".join(f"{t} {v:+.2f}" for t, v in agent.traits.items())
        lines = crew.prompt(m, session.persona.character, CORE_CHARACTER_RULES, STRENGTH)
        sign, motto = crew.seal(m)
        members.append({"agent": name, "color": ui_hex(agent.color), "captain": bool(m.get("captain")),
                        "edited": crew.edited(name), "member": m, "seal": {"sign": sign, "motto": motto},
                        "stamp": crew.stamp(m), "preview": "\n".join(lines or []).strip()})
    return {"lore": crew.LORE, "form": CREW_FORM, "members": members,
            "pledge": crew.oath("pledge"), "chant": crew.oath("chant"),
            "coreRules": __import__("personality").CORE_CHARACTER_RULES}


def ui_hex(n):
    return ui.xterm_hex(n)


def save_crew(session, agent_name, member):
    agent = session.agents.get(agent_name)
    if not agent or agent.name == "hippocampus":
        raise SettingError("pick a crew member (the captain is edited with the character builder)")
    clean = {}
    for step in CREW_FORM:
        for f in step["fields"]:
            key = f["key"]
            v = member.get(key) if "." not in key else (member.get("seal") or {}).get(key.split(".")[1])
            if f["kind"] == "lines":
                items = v if isinstance(v, list) else str(v or "").splitlines()
                items = [str(x).strip()[:300] for x in items if str(x).strip()][: f["max"]]
                clean[key] = items
            elif f["kind"] == "segmented":
                if v not in [o[0] for o in f["options"]]:
                    raise SettingError(f"{f['label']}: pick one of the choices")
                clean[key] = v
            else:
                v = str(v or "").strip()
                if len(v) > f["max"]:
                    raise SettingError(f"{f['label']}: too long (max {f['max']})")
                if key.startswith("seal."):
                    clean.setdefault("seal", {})[key.split(".")[1]] = v.upper() if key == "seal.motto" else v
                else:
                    clean[key] = v
    if not clean.get("name"):
        raise SettingError("every crew member needs a name")
    if clean.get("traits"):
        from agents import parse_traits
        parsed = {k: v for k, v in parse_traits(clean["traits"]).items() if session.persona.find_trait(k)}
        clean["traits"] = ", ".join(f"{k} {v:+.2f}" for k, v in parsed.items())
        agent.traits = parsed or agent.traits
    crew.save(agent.name, clean)
    return clean


def reset_crew(session, agent_name):
    agent = session.agents.get(agent_name)
    if not agent:
        raise SettingError("no such agent")
    crew.reset(agent.name)
    reload_traits(session, agent)


def reload_traits(session, agent):
    """After a crew reset: the agent's traits from its file again, in place."""
    from agents import AgentSet
    fresh = AgentSet(session.agents.folder).get(agent.name)
    if fresh:
        agent.traits = fresh.traits


def save_oath(kind, body):
    if kind not in ("pledge", "chant"):
        raise SettingError("pledge or chant")
    if body.get("reset"):
        crew.reset_oath(kind)
        return
    title, author, text = (str(body.get(k) or "").strip() for k in ("title", "author", "text"))
    if not text:
        raise SettingError("the words can't be empty")
    if len(text) > 4000 or len(title) > 120 or len(author) > 120:
        raise SettingError("too long")
    crew.save_oath(kind, title, author, text)
