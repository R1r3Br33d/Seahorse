"""
builder.py - design or redesign Seahorse's persona, step by step.

    /build            the full walk-through (11 steps)
    /build <step>     jump straight to one step: identity, backstory, tale,
                      voice, strength, mannerisms, spirit, rules, greetings,
                      traits, preview
    /persona          list saved personas; /persona use|save|delete <name>

Every step shows what's there now. Press Enter to keep it, type to change
it, or (where offered) type d to have Seahorse draft it from a few hints.
Nothing changes until you save at the preview step, so you can wander
through freely and walk away with q at any prompt.

Core character rules (honesty, clean deliverables, no encouraging vices,
mysticism is only mood, easing off when it matters) are shown but can't be
removed; your persona's own rules sit on top of them.
"""

import json
import re
from copy import deepcopy

import ui
from personality import (BLANK_CHARACTER, CORE_CHARACTER_RULES, DEFAULT_CHARACTER, STRENGTH, delete_persona,
                         list_personas, load_persona, save_persona)
from ui import BOLD, DIM, RESET

STEPS = ["identity", "backstory", "tale", "voice", "strength", "mannerisms", "spirit", "rules", "greetings",
         "traits", "preview"]

REGISTERS = {
    "1": ("spare", "spare and salt-worn: short, image-built sentences, few wasted words, a little grim"),
    "2": ("lyrical", "lyrical: flowing, vivid and a touch poetic"),
    "3": ("warm", "warm and casual: friendly, easy-going, like an old friend"),
    "4": ("formal", "formal and measured: precise, courteous, old-fashioned"),
    "5": ("playful", "playful: quick wit, teasing, lots of energy"),
}


class Quit(Exception):
    """The user typed q to leave the builder."""


def ask(label, allow_empty=True):
    try:
        value = input(f"  {ui.CORAL}›{RESET} {label} ").strip()
    except EOFError:
        raise Quit
    if value.lower() == "q":
        raise Quit
    if not value and not allow_empty:
        return ask(label, allow_empty)
    return value


def ask_multiline(label):
    print(f"  {DIM}{label} - finish with a line containing just a full stop (.){RESET}")
    lines = []
    while True:
        try:
            line = input(f"  {ui.TEAL}{ui.V}{RESET} ")
        except EOFError:
            raise Quit
        if line.strip() == ".":
            break
        if line.strip().lower() == "q" and not lines:
            raise Quit
        lines.append(line)
    return "\n".join(lines).strip()


def header(i, name, hint):
    ui.section(f"step {i}/{len(STEPS)} · {name}")
    print(f"  {DIM}{hint}{RESET}")


def show(label, text, limit=500):
    text = text or f"{DIM}(empty){RESET}"
    if len(text) > limit:
        text = text[:limit] + f"{DIM} ...{RESET}"
    print(f"  {ui.SAND}{label}{RESET} {text}")


def edit_list(title, items, hint="+ text to add, - number to remove, Enter when done"):
    items = list(items)
    while True:
        print(f"  {ui.SAND}{title}{RESET}")
        if not items:
            print(f"    {DIM}(none){RESET}")
        for i, it in enumerate(items, 1):
            print(f"    {ui.TEAL}{i}.{RESET} {it}")
        cmd = ask(f"{DIM}{hint}{RESET}")
        if not cmd:
            return items
        if cmd.startswith("+"):
            if cmd[1:].strip():
                items.append(cmd[1:].strip())
        elif cmd.startswith("-") and cmd[1:].strip().isdigit():
            n = int(cmd[1:].strip())
            if 1 <= n <= len(items):
                items.pop(n - 1)
        else:
            print(f"    {DIM}start with + to add or - to remove{RESET}")


class Builder:
    def __init__(self, session, start=None):
        self.session = session
        self.persona = session.persona
        self.c = deepcopy(start if start is not None else self.persona.character)
        for k, v in BLANK_CHARACTER.items():
            self.c.setdefault(k, deepcopy(v))
        self.targets = {}

    # ------------------------------------------------------------------ helpers
    def draft(self, what, hints, words="120-200"):
        """Ask the model to draft a piece of the persona."""
        prompt = (f"You are helping design the persona of a personal AI called {self.c.get('name') or 'Seahorse'}"
                  f"{' (' + self.c['epithet'] + ')' if self.c.get('epithet') else ''}.\n"
                  f"Current backstory: {self.c.get('backstory') or '(none)'}\n"
                  f"Current voice: {self.c.get('voice') or '(none)'}\n\n"
                  f"Write the {what}, using these hints from the user: {hints}\n"
                  f"Write it in second person ('You ...'), {words} words, vivid and specific. If it involves a "
                  f"dialect or culture, write it respectfully, never as a caricature. Return only the text.")
        text = self.session.complete(prompt, system="You are a thoughtful character writer.",
                                     label=f"drafting the {what}")
        if not text:
            print(f"  {DIM}couldn't reach a model to draft it; write it yourself instead{RESET}")
            return None
        text = text.strip().strip('"')
        print(f"\n  {ui.FOAM}{text}{RESET}\n")
        return text if ask("use this draft? (y/n)").lower().startswith("y") else None

    # ------------------------------------------------------------------ steps
    def identity(self, i):
        header(i, "identity", "What he's called. The name shows in greetings and his instructions; the epithet is "
                              "the name he earned (e.g. 'the Lonesome Grim').")
        show("name   ", self.c.get("name"))
        show("epithet", self.c.get("epithet"))
        name = ask("name (Enter to keep):")
        if name:
            self.c["name"] = name
        ep = ask("epithet (Enter to keep, - to clear):")
        if ep == "-":
            self.c["epithet"] = ""
        elif ep:
            self.c["epithet"] = ep

    def backstory(self, i):
        header(i, "backstory", "Where he comes from and how he came to be here. Written to him, as 'You were...'.")
        show("now:", self.c.get("backstory"))
        choice = ask("Enter keep · w write · d draft from hints · - clear:")
        if choice == "w":
            text = ask_multiline("write the backstory")
            if text:
                self.c["backstory"] = text
        elif choice == "d":
            era = ask("era and place (e.g. 1600s Port Royal):")
            role = ask("what he was or did:")
            moment = ask("a defining moment:")
            text = self.draft("backstory", f"era/place: {era}; role: {role}; defining moment: {moment}")
            if text:
                self.c["backstory"] = text
        elif choice == "-":
            self.c["backstory"] = ""

    def tale(self, i):
        header(i, "tale", "A piece of writing kept word for word - his origin in your own words. He recites it "
                          "exactly when asked.")
        show("now:", (self.c.get("tale") or "").replace("\n", " / "), 300)
        choice = ask("Enter keep · w write or paste a new tale · - clear:")
        if choice == "w":
            text = ask_multiline("paste the tale")
            if text:
                self.c["tale"] = text
        elif choice == "-":
            self.c["tale"] = ""

    def voice(self, i):
        header(i, "voice", "How he sounds: dialect or accent, and the register of his speech.")
        show("now:", self.c.get("voice"))
        choice = ask("Enter keep · b build from dialect + register · w write it yourself · d draft from hints:")
        if choice == "b":
            dialect = ask("dialect or accent (e.g. Jamaican English with touches of Patois):", allow_empty=False)
            phrases = ask("signature words or phrases, comma-separated (optional):")
            for k, (name, desc) in REGISTERS.items():
                print(f"    {ui.TEAL}{k}{RESET} {name:<8} {DIM}{desc}{RESET}")
            reg = REGISTERS.get(ask("register (1-5):"), REGISTERS["3"])
            text = (f"You speak {dialect}. Write it with respect and affection, the way a native speaker actually "
                    f"talks - never as a caricature, and without piling up phonetic misspellings. Your register is "
                    f"{reg[1]}.")
            if phrases:
                text += f" Phrases that come naturally to you: {phrases}."
            self.c["voice"] = text
            print(f"\n  {ui.FOAM}{text}{RESET}")
        elif choice == "w":
            text = ask_multiline("describe the voice")
            if text:
                self.c["voice"] = text
        elif choice == "d":
            text = self.draft("voice description (how he speaks: dialect, rhythm, words he favours, register)",
                              ask("hints:"), "60-110")
            if text:
                self.c["voice"] = text

    def strength(self, i):
        header(i, "strength", "How strongly the voice comes through.")
        for name, desc in STRENGTH.items():
            mark = f" {ui.CORAL}← now{RESET}" if name == self.c.get("strength") else ""
            print(f"    {ui.TEAL}{name:<7}{RESET} {DIM}{desc}{RESET}{mark}")
        choice = ask("light / medium / strong (Enter to keep):")
        if choice in STRENGTH:
            self.c["strength"] = choice

    def mannerisms(self, i):
        header(i, "mannerisms", "Small habits that make him himself (used sparingly).")
        self.c["mannerisms"] = edit_list("mannerisms", self.c.get("mannerisms", []))

    def spirit(self, i):
        header(i, "spirit", "Something uncanny or special about him (his eerie spirit-sense, a gift, a curse). "
                            "It's always treated as mood, never as real prediction.")
        show("now:", self.c.get("spirit"))
        choice = ask("Enter keep · w write · d draft from hints · - clear:")
        if choice == "w":
            text = ask_multiline("describe it")
            if text:
                self.c["spirit"] = text
        elif choice == "d":
            text = self.draft("special quality (something uncanny about him, described as atmosphere)",
                              ask("hints:"), "50-90")
            if text:
                self.c["spirit"] = text
        elif choice == "-":
            self.c["spirit"] = ""

    def rules(self, i):
        header(i, "rules", "Rules for this persona. The core rules always apply and can't be removed.")
        print(f"  {ui.SAND}core (always){RESET}")
        for r in CORE_CHARACTER_RULES:
            print(f"    {DIM}› {r}{RESET}")
        self.c["rules"] = edit_list("this persona's rules", self.c.get("rules", []))

    def greetings(self, i):
        header(i, "greetings", "How he opens and closes a session.")
        self.c["greetings"] = edit_list("greeting openers (one is picked each day)", self.c.get("greetings", []))
        ready = ask(f"line after the greeting (now: {self.c.get('ready_line') or 'none'}; Enter keep, - clear):")
        if ready == "-":
            self.c["ready_line"] = ""
        elif ready:
            self.c["ready_line"] = ready
        self.c["farewells"] = edit_list("farewells", self.c.get("farewells", []))

    def traits(self, i):
        header(i, "traits", "What his personality grows toward. Type 'trait value' pairs, e.g. 'warmth 0.4 rigor 0.9'.")
        for name, t in self.persona.traits.items():
            tgt = self.targets.get(name, t["target"])
            print(f"    {ui.SAND}{name:<12}{RESET} now {t['value']:.2f} → target {tgt:.2f}")
        text = ask("targets (Enter to keep):")
        for name, val in re.findall(r"([a-z_]+)\s*[:=]?\s*(\d*\.?\d+)", text.lower()):
            trait = self.persona.find_trait(name)
            if trait:
                self.targets[trait] = max(0.0, min(1.0, float(val)))
                print(f"    {DIM}{trait} → {self.targets[trait]:.2f}{RESET}")

    def preview(self, i):
        header(i, "preview", "This is how he'll be told who he is.")
        saved = self.persona.state["character"]
        self.persona.state["character"] = self.c
        try:
            block = "\n".join(self.persona.character_prompt())
            hello = ui.greeting(self.session.config.get("name", ""), self.c)
            bye = ui.farewell(self.c)
        finally:
            self.persona.state["character"] = saved
        for line in block.strip().splitlines():
            print(f"  {DIM}{line}{RESET}")
        print(f"\n  {ui.SAND}greeting{RESET}  {hello}\n  {ui.SAND}farewell{RESET}  {bye}")
        if self.targets:
            print(f"  {ui.SAND}targets {RESET}  " + ", ".join(f"{k} {v:.2f}" for k, v in self.targets.items()))
        while True:
            choice = ask("t test him · s save · p <name> save and keep as a preset · q leave without saving:")
            if choice == "t":
                self.test()
            elif choice == "s" or choice.startswith("p"):
                self.save(choice[1:].strip() if choice.startswith("p") else "")
                return True

    def test(self):
        saved = self.persona.state["character"]
        self.persona.state["character"] = self.c
        try:
            system = self.persona.system_prompt(self.session.extra)
        finally:
            self.persona.state["character"] = saved
        line = ask("say something to him (Enter for 'Tell me who you are'):") or "Tell me who you are."
        reply = self.session.complete(line, system=system, label="he's thinking")
        print(f"\n  {ui.FOAM}{reply or '(no model reachable for a test)'}{RESET}\n")

    def save(self, preset=""):
        self.c["version"] = DEFAULT_CHARACTER["version"]
        self.persona.state["character"] = self.c
        self.persona.save()
        for name, val in self.targets.items():
            self.persona.set_target(name, val)
        self.session.persona.build_ollama(extra=self.session.extra)
        ui.note(f"{self.c.get('name') or 'Seahorse'} saved - he'll speak this way from your next message")
        if preset:
            ui.note(f"preset saved: {save_persona(preset, self.c)}")

    # ------------------------------------------------------------------ run
    def run(self, only=None):
        steps = [only] if only else STEPS
        try:
            if not only:
                ui.section("character builder")
                print(f"  {DIM}Enter keeps what's there · q leaves without saving · nothing changes until you "
                      f"save at the end{RESET}")
            for name in steps:
                done = getattr(self, name)(STEPS.index(name) + 1)
                if name == "preview" and done:
                    return
            if only and only != "preview":
                if ask("save this change? (y/n)").lower().startswith("y"):
                    self.save()
                else:
                    ui.note("left unchanged")
        except Quit:
            ui.note("left the builder - nothing was changed")


def build_command(session, arg):
    arg = arg.strip().lower()
    if arg and arg not in STEPS:
        ui.note(f"steps: {', '.join(STEPS)}")
        return
    Builder(session).run(arg or None)
    print()


def persona_command(session, arg):
    parts = arg.split(None, 1)
    sub = parts[0].lower() if parts else ""
    name = parts[1].strip() if len(parts) > 1 else ""
    current = session.persona.character
    if sub == "use" and name:
        data = load_persona(name)
        if not data:
            ui.note("no persona by that name (/persona to list them)")
        else:
            data["enabled"] = True
            session.persona.state["character"] = data
            session.persona.save()
            session.persona.build_ollama(extra=session.extra)
            ui.note(f"now playing {data.get('name')}{' - ' + data['epithet'] if data.get('epithet') else ''}")
    elif sub == "save" and name:
        ui.note(f"saved {save_persona(name, current)}")
    elif sub == "delete" and name:
        ui.note("deleted" if delete_persona(name) else "can't delete that one (missing, or the built-in Grim)")
    elif sub == "new":
        ui.note("starting from a blank persona (your current one is untouched unless you save)")
        Builder(session, BLANK_CHARACTER).run()
    else:
        for slug, data in list_personas():
            title = " - ".join(x for x in (data.get("name"), data.get("epithet")) if x)
            same = data.get("backstory") == current.get("backstory") and data.get("voice") == current.get("voice")
            mark = f" {ui.CORAL}← playing now{RESET}" if same else ""
            print(f"  {ui.SAND}{slug:<18}{RESET} {title}{mark}")
        ui.note("/persona use <name> · /persona save <name> · /persona delete <name> · /persona new · /build")
    print()
