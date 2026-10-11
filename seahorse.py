#!/usr/bin/env python3
"""
seahorse - a hybrid local chat assistant.

Uses the real Claude (via the Anthropic API) when you're online and have an
API key, and falls back to a local open-weight model served by Ollama when
you're offline or the API is unreachable. Pure Python standard library.

Usage:
    python3 seahorse.py            # auto mode (Claude, then local fallback)
    python3 seahorse.py --local    # always use the local model
    python3 seahorse.py --claude   # always use Claude (no fallback)

Environment variables (all optional except the API key for Claude):
    ANTHROPIC_API_KEY   your Anthropic API key
    CLAUDE_MODEL        default: claude-sonnet-5-5
    LOCAL_MODEL         default: seahorse if built, else SEAHORSE_BASE_MODEL
    SEAHORSE_BASE_MODEL base model for the Seahorse Modelfile (default: llama3.1:8b)
    OLLAMA_URL          default: http://localhost:11434
    SEAHORSE_NUM_CTX    local model context size in tokens (default: 8192)
    SEAHORSE_EMBED_MODEL  Ollama embedding model for memory search (default: nomic-embed-text)

Keep these files together: seahorse.py, personality.py (who Seahorse is and
how it grows), skills.py (writing, math and the calculator), agents.py
(specialist agent types), builder.py (the character builder), memory.py (long-term memory), cortex.py (how the
agents perceive, take notes and develop), portrait.py (Seahorse's opinionated
profile of you) and ui.py (the look of the shell). Type /help inside Seahorse for every command.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import council
import crew
import treasury
import change
import lobes
import ui
from agency import AGENCY, CONSCIENCE_MIN_WORDS, DEPARTMENTS, FREQUENCY, Agency
from agents import LOBE_BALANCE, LOBE_MIN_WORDS, LOBES, SUB_BRAIN_MIN_WORDS, AgentSet
from builder import build_command, persona_command
from cortex import Cortex, category_color, lens
from memory import CATEGORIES as CATEGORY_NAMES
from memory import Embedder, MemoryStore, WorkingMemory, detect_memory_command, extract_json, guess_category
from personality import CORE_CHARACTER_RULES, CORE_IDENTITY, MODEL_NAME, STRENGTH, Personality
from portrait import PERSONAL_DOMAINS, Profile, behaviour_metrics, stated_quotes
from portrait import SECTIONS as PROFILE_SECTIONS
from skills import CALC_RESULT_PREFIX, SkillSet, calculate, find_calc_blocks, format_results
from ui import BOLD, DIM, RESET, ReplyBox, Spinner

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

CONFIG_DIR = Path.home() / ".seahorse"
HISTORY_DIR = CONFIG_DIR / "chats"
CHATS_DIR_FOR_PROFILE = HISTORY_DIR
SYSTEM_PROMPT_FILE = CONFIG_DIR / "system_prompt.txt"
MAX_CALC_ROUNDS = 3
MAX_CONTINUATIONS = int(os.environ.get("SEAHORSE_MAX_CONTINUATIONS", "8"))  # auto-continue cut-off replies


# Terminal colours and layout live in ui.py
ORANGE, CYAN = ui.CORAL, ui.TEAL


def refresh_palette():
    """Pick up the current theme's colours after /theme or loading settings."""
    global ORANGE, CYAN
    ORANGE, CYAN = ui.CORAL, ui.TEAL


def processing_power(local):
    """The Trident's strength: cores, memory, GPU, and the local models loaded right now."""
    import platform
    power = {"cpu": f"{os.cpu_count() or '?'} cores ({platform.machine() or '?'})", "ram": available_memory_gb()}
    gpu = ""
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                 capture_output=True, text=True, timeout=3).stdout.strip()
            gpu = out.splitlines()[0] if out else ""
        except (OSError, subprocess.SubprocessError):
            gpu = ""
    elif sys.platform == "darwin" and platform.machine() == "arm64":
        gpu = "Apple Silicon (unified memory, Metal)"
    power["gpu"] = gpu or "none detected (CPU only)"
    loaded = []
    try:
        with urllib.request.urlopen(local.base_url + "/api/ps", timeout=1.5) as r:
            for m in json.load(r).get("models", []):
                size, vram = m.get("size", 0) or 0, m.get("size_vram", 0) or 0
                where = "GPU" if size and vram >= size * 0.95 else ("CPU" if not vram else f"{vram / size:.0%} GPU")
                loaded.append(f"{m.get('name')} ({size / 1e9:.1f} GB, {where})")
    except Exception:  # noqa: BLE001 - Ollama may be off
        pass
    power["loaded"] = loaded
    return power


def available_memory_gb():
    """Free (available) RAM in GB, or 0 if it can't be measured."""
    try:
        import psutil  # optional
        return psutil.virtual_memory().available / 1e9
    except ImportError:
        pass
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1e6
    except OSError:
        pass
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=3).stdout
            page = int(re.search(r"page size of (\d+)", out).group(1))
            free = sum(int(re.search(rf"{k}:\s+(\d+)", out).group(1)) for k in ("Pages free", "Pages inactive"))
            return free * page / 1e9
        if os.name == "nt":
            import ctypes

            class MEM(ctypes.Structure):
                _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("avail", ctypes.c_ulonglong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong),
                            ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ae", ctypes.c_ulonglong)]
            m = MEM()
            m.len = ctypes.sizeof(MEM)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.avail / 1e9
    except Exception:  # noqa: BLE001
        pass
    return 0.0


class BackendUnavailable(Exception):
    """Raised when a backend can't be reached (network down, server off, no key)."""


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class Metered:
    """Counts the work each backend does - Poseidon's Trident, the working class (/trident)."""
    calls = 0           # replies started
    chars = 0           # characters produced
    seconds = 0.0       # time spent producing them
    unavailable = 0     # times it couldn't be reached (and the work went elsewhere)

    def stream(self, *args, **kwargs):
        t0, n = time.monotonic(), 0
        self.calls += 1
        try:
            for piece in self._stream(*args, **kwargs):
                n += len(piece)
                yield piece
        except BackendUnavailable:
            self.unavailable += 1
            raise
        finally:
            self.chars += n
            self.seconds += time.monotonic() - t0


class ClaudeBackend(Metered):
    name = "claude"

    def __init__(self, model, api_key, max_tokens=None):
        self.model = model
        self.api_key = api_key
        # Long replies by default; Seahorse also continues automatically if a reply is cut off.
        self.max_tokens = max_tokens or int(os.environ.get("SEAHORSE_MAX_TOKENS", "16000"))
        self.last_stop = None
        self.temperature = None
        self.context_chars = 400_000  # ~200K tokens, leaving room for the reply

    def label(self):
        return f"Claude ({self.model})"

    def _stream(self, system, messages, max_tokens=None, temperature=None, json_mode=False):
        """Stream a reply. The keyword overrides apply to this call only (safe across threads)."""
        temperature = self.temperature if temperature is None else temperature
        self.last_stop = None
        if not self.api_key:
            raise BackendUnavailable("ANTHROPIC_API_KEY is not set")
        body = json.dumps({
            "model": self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "system": system,
            "messages": messages,
            "stream": True,
            **({"temperature": temperature} if temperature is not None else {}),
        }).encode()
        req = urllib.request.Request(
            ANTHROPIC_URL,
            data=body,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            # Auth/request errors are real errors, not "offline"; overload/5xx can fall back.
            if e.code in (429, 500, 502, 503, 504, 529):
                raise BackendUnavailable(f"Claude API returned {e.code}")
            raise RuntimeError(f"Claude API error {e.code}: {detail}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise BackendUnavailable(f"can't reach Claude API ({e})")

        with resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data:
                    continue
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                etype = event.get("type")
                if etype == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        yield delta.get("text", "")
                elif etype == "message_delta":
                    self.last_stop = (event.get("delta") or {}).get("stop_reason")
                elif etype == "error":
                    raise RuntimeError(event.get("error", {}).get("message", "stream error"))


class OllamaBackend(Metered):
    name = "local"

    def __init__(self, model, base_url):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = None
        self.last_stop = None
        self.fixed_ctx = os.environ.get("SEAHORSE_NUM_CTX")
        self.keep_alive = os.environ.get("SEAHORSE_KEEP_ALIVE", "30m")  # how long the model stays loaded
        self.num_ctx = int(self.fixed_ctx or 8192)
        self._sized_for = None

    @property
    def context_chars(self):
        self.size_context()
        return int(self.num_ctx * 3.2)  # rough characters per token, leaving reply room

    def size_context(self):
        """Pick the biggest context window this model and this computer's memory allow (once per model)."""
        if self.fixed_ctx or self._sized_for == self.model:
            return self.num_ctx
        self._sized_for = self.model
        model_max, model_gb = 8192, 5.0
        try:
            req = urllib.request.Request(self.base_url + "/api/show", data=json.dumps({"model": self.model}).encode(),
                                         headers={"content-type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=5) as r:
                info = json.load(r)
            for key, val in (info.get("model_info") or {}).items():
                if key.endswith(".context_length"):
                    model_max = int(val)
            with urllib.request.urlopen(self.base_url + "/api/tags", timeout=5) as r:
                for m in json.load(r).get("models", []):
                    if m.get("name") == self.model or m.get("model") == self.model:
                        model_gb = m.get("size", 5e9) / 1e9
        except Exception:  # noqa: BLE001 - keep the safe default
            pass
        free_gb = available_memory_gb()
        # About 8,000 tokens of context per spare GB for a 7-8B model, fewer for bigger models.
        # Never below 8,192 (the old default, which every common setup handles) unless the model is smaller.
        per_gb = 8000 * min(1.0, 5.0 / max(model_gb, 1.0))
        budget = int(max(0.0, free_gb - model_gb - 2.0) * per_gb) if free_gb else 8192
        self.num_ctx = min(model_max, 131072, max(8192, budget // 1024 * 1024))
        return self.num_ctx

    def label(self):
        return f"Local ({self.model})"

    def available(self):
        try:
            with urllib.request.urlopen(self.base_url + "/api/tags", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def installed_models(self):
        try:
            with urllib.request.urlopen(self.base_url + "/api/tags", timeout=2) as r:
                return [m["name"] for m in json.load(r).get("models", [])]
        except Exception:
            return []

    def _stream(self, system, messages, max_tokens=None, temperature=None, json_mode=False):
        """Stream a reply. The keyword overrides apply to this call only (safe across threads)."""
        temperature = self.temperature if temperature is None else temperature
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system}] + messages,
            "stream": True,
            "keep_alive": self.keep_alive,  # stay loaded between messages
            **({"format": "json"} if json_mode else {}),
            "options": {"num_ctx": self.size_context(), "num_predict": max_tokens or -1,
                        **({"temperature": temperature} if temperature is not None else {})},
        }).encode()
        self.last_stop = None
        req = urllib.request.Request(
            self.base_url + "/api/chat",
            data=body,
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=300)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            if e.code == 404:
                raise RuntimeError(
                    f"Local model '{self.model}' isn't installed. Run: ollama pull {self.model}"
                )
            raise RuntimeError(f"Ollama error {e.code}: {detail}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise BackendUnavailable(
                f"can't reach Ollama at {self.base_url} ({e}). Is `ollama serve` running?"
            )

        with resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "error" in chunk:
                    raise RuntimeError(chunk["error"])
                text = chunk.get("message", {}).get("content", "")
                if text:
                    yield text
                if chunk.get("done"):
                    self.last_stop = chunk.get("done_reason")
                    break


# ---------------------------------------------------------------------------
# Chat session
# ---------------------------------------------------------------------------

class Session:
    def __init__(self, claude, local, mode, persona, extra_instructions="", skills=None, agents=None, memory=None,
                 cortex=None, profile=None, agency=None):
        self.claude = claude
        self.local = local
        self.mode = mode  # "auto" | "claude" | "local"
        self.persona = persona
        self.extra = extra_instructions
        self.skills = skills or SkillSet()
        self.agents = agents or AgentSet()
        self.agent_mode = "auto"     # "auto" routes each message; otherwise an agent name
        self.agent = self.agents.default
        self.active_skills = []
        self.system_override = None  # set by /system for this chat only
        self.messages = []
        self.reflected_upto = 0      # messages already learned from
        self.told_fallback = False
        self.reply_agent = {}        # message index -> agent that wrote it
        self.usage = {}              # agent -> turns handled since the last reflection
        self.memory = memory         # long-term memory (MemoryStore) or None
        self.working = WorkingMemory()
        self.pinned_context = []     # episodes brought back with /revisit
        self.cortex = cortex         # agents' notebooks and the collective summary tree
        self.profile = profile       # Seahorse's opinionated profile of the user
        self.agency = agency         # inner voice (conscience, journal, self-model) and the Bureau of Magic
        self.show_perception = True  # show what each agent noticed in your message
        self.config = dict(ui.DEFAULTS)
        self.started = datetime.now()
        self.apply_persona()

    # ------------------------------------------------------------------ prompts
    def memory_on(self):
        return self.memory is not None

    def system_for(self, agent, active_skills, query=""):
        if self.system_override:
            return self.system_override
        latest = query or " ".join(self.user_texts()[-1:])
        flow = [("character & personality", self.persona.system_prompt(self.extra, agent.traits,
                                                                       self.crew_lines(agent, latest))
                 if agent.persona else CORE_IDENTITY)]
        if agent.persona and self.memory_on():
            flow.append(("memory", self.memory.context(query or " ".join(self.user_texts()[-2:]))))
        if agent.persona and self.cortex:
            flow.append(("notebooks", self.cortex.context_for(agent.name)))
        if agent.persona and self.profile:
            flow.append(("profile of you", self.profile.context()))
        if agent.persona and self.agency and self.agency.self_context():
            flow.append(("inner voice", self.agency.self_context()))
        for ep in self.pinned_context:
            flow.append(("revisited chats", f"Earlier conversation the user asked you to bring back ({ep['date']}, "
                                            f"{ep['title']}):\n{ep['summary']}"))
        if agent.role_prompt():
            flow.append(("role", agent.role_prompt()))
        if agent.persona:
            flow.append(("constitution (amendments)", treasury.constitution_prompt(agent.name, latest, self.agents)))
            flow.append(("the marlin (your goals)", treasury.marlin_prompt()))
            flow.append(("the quarter (season)", treasury.quarter_prompt()))
            flow.append(("oil (scrapped ideas)", treasury.oil_prompt(latest, HISTORY_DIR)))
        if self.skills.prompt(active_skills):
            flow.append(("skills", self.skills.prompt(active_skills)))
        flow = [(label, text) for label, text in flow if text]
        self.last_flow = (agent.name, [(label, len(text)) for label, text in flow])   # the Trident's data flow
        return "\n\n".join(text for _label, text in flow)

    def crew_lines(self, agent, query=""):
        """The crew member's character for this agent, or None to use the captain's."""
        if self.config.get("crew", True) is False:
            return None
        member = crew.get(agent.name)
        if member and member.get("captain"):   # the captain: his own character, plus the pledge and chant
            return self.persona.character_prompt() + crew.oath_lines(captain=True, query=query)
        return crew.prompt(member, self.persona.character, CORE_CHARACTER_RULES, STRENGTH, query)

    def seal_for(self, agent):
        """The crew member's notary seal for this agent's replies, or ''."""
        if self.config.get("seals", True) is False:
            return ""
        return crew.stamp(crew.get(agent.name) or {})

    @property
    def system(self):
        return self.system_for(self.agent, self.active_skills)

    def apply_persona(self, agent=None):
        temp = self.persona.temperature()
        if agent is not None and agent.temperature is not None:
            temp = agent.temperature
        self.claude.temperature = min(temp, 1.0)
        self.local.temperature = temp

    def paint_agent(self, name):
        agent = self.agents.get(name)
        return ui.agent_name(name, agent.color, agent.icon) if agent else name

    def _record(self, agent_name, start):
        """Note which agent wrote the replies added since `start`, and count its turn."""
        for i in range(start, len(self.messages)):
            if self.messages[i]["role"] == "assistant":
                self.reply_agent[i] = agent_name
        self.usage[agent_name] = self.usage.get(agent_name, 0) + 1

    def user_texts(self, messages=None):
        """The user's own messages (not calculator results)."""
        return [m["content"] for m in (messages if messages is not None else self.messages)
                if m["role"] == "user" and not m["content"].startswith(CALC_RESULT_PREFIX)]

    def skills_for(self, agent, texts):
        auto = set(self.skills.select(texts))
        if agent.auto_skills is not None:
            auto &= set(agent.auto_skills)
        wanted = set(agent.skills) | auto
        return sorted(n for n in wanted if n in self.skills.skills and self.skills.skills[n].mode != "off")

    def backends(self, agent=None):
        mode = self.mode
        if mode == "auto" and agent is not None and agent.backend != "auto":
            mode = agent.backend
        if mode == "claude":
            return [self.claude]
        if mode == "local":
            return [self.local]
        return [self.claude, self.local]

    # ------------------------------------------------------------------ talking to models
    def complete(self, prompt, agent=None, system="You analyse text and reply with JSON only.", label="thinking"):
        """One quiet, non-streamed answer from the first backend that works."""
        self.claude.temperature = self.local.temperature = 0.2
        with Spinner(label):
            for backend in self.backends(agent):
                try:
                    return "".join(backend.stream(system, [{"role": "user", "content": prompt}]))
                except (BackendUnavailable, RuntimeError):
                    continue
        return None

    def _stream(self, agent, system, messages):
        """Stream one reply, falling back between backends. Returns (text or None, status)."""
        errors = []
        backends = self.backends(agent)
        base_system, base_messages = system, messages
        for backend in backends:
            reply = []
            system, messages = base_system, base_messages
            if messages is self.messages and backend.context_chars:
                budget = max(4000, backend.context_chars - len(system))
                summary, messages = self.working.fit(messages, budget, self._condense)
                if summary:
                    system += "\n\nEarlier in this conversation (condensed to save space):\n" + summary
            self.apply_persona(agent)
            member = crew.get(agent.name) if self.config.get("crew", True) is not False else None
            title = f"{member['name']} ({agent.name})" if member and member.get("name") else agent.name
            box = ReplyBox(agent.name, backend.label(), agent.color, agent.icon, self.seal_for(agent), title=title)
            spinner = Spinner(f"{agent.name} is thinking").start()
            try:
                for piece in self.pieces(backend, system, messages):
                    spinner.stop()
                    reply.append(piece)
                    box.write(piece)
                spinner.stop()
                box.close()
                return "".join(reply), "ok"
            except BackendUnavailable as e:
                spinner.stop()
                errors.append(f"{backend.label()}: {e}")
                if reply:  # dropped mid-answer: keep what we got
                    box.close("connection lost mid-reply")
                    return "".join(reply), "partial"
                if backend is self.claude and len(backends) > 1 and not self.told_fallback:
                    ui.note(f"Claude unavailable ({e}), so using the local model.")
                    self.told_fallback = True
                continue
            except KeyboardInterrupt:
                spinner.stop()
                if reply:
                    box.close("interrupted")
                else:
                    ui.note("interrupted")
                return ("".join(reply) or None), "interrupted"
            except RuntimeError as e:
                spinner.stop()
                ui.note(f"Error: {e}")
                print()
                return None, "failed"
        ui.note("No model available:")
        for err in errors:
            ui.note(f"  {err}")
        print()
        return None, "failed"

    def pieces(self, backend, system, messages):
        """Stream a reply, continuing automatically if it was cut off by a length limit."""
        so_far = []
        convo = list(messages)
        for _round in range(int(self.config.get("max_continuations", MAX_CONTINUATIONS)) + 1):
            got = []
            for piece in backend.stream(system, convo):
                got.append(piece)
                so_far.append(piece)
                yield piece
            if backend.last_stop not in ("max_tokens", "length") or not got:
                return
            convo = list(messages) + [
                {"role": "assistant", "content": "".join(so_far)},
                {"role": "user", "content": "[continue] Your reply was cut off by a length limit. Continue exactly "
                                            "where it stopped - no repetition, no preamble."}]

    def _condense(self, prompt):
        return self.complete(prompt, system="You write compact, faithful notes.",
                             label="condensing older messages")

    # ------------------------------------------------------------------ sub-agent brains
    def sub_brains_on(self, agent):
        return bool(agent.sub_brains) and self.config.get("sub_brains", {}).get(agent.name, True) is not False

    def show_sub(self, agent, sub, text):
        """Print one sub-agent's notes (the app overrides this to stream them)."""
        tint = ui.c256(sub["color"])
        lines = text.strip().splitlines()
        whose = "" if sub.get("lobe") else f" {DIM}({agent.name}'s brain){RESET}"
        print(f"  {BOLD}{tint}{sub['icon']} {sub['name']}{RESET}{whose}")
        for line in lines[:12]:
            print(f"  {tint}{ui.V}{RESET} {DIM}{line}{RESET}")
        if len(lines) > 12:
            print(f"  {tint}{ui.V}{RESET} {DIM}...{RESET}")

    def _sub_call(self, agent, system, prompt):
        self.apply_persona(agent)
        for backend in self.backends(agent):
            try:
                return "".join(backend.stream(system, [{"role": "user", "content": prompt}])).strip()
            except (BackendUnavailable, RuntimeError):
                continue
        return None

    def inner_council(self, agent, system, messages):
        """Let the agent's sub-agents work on the latest message first. Returns notes for the agent's prompt."""
        texts = self.user_texts(messages)
        if not self.sub_brains_on(agent) or not texts or len(texts[-1].split()) < SUB_BRAIN_MIN_WORDS:
            return ""
        recent = "\n\n".join(f"{m['role'].upper()}: {m['content'][:2500]}" for m in messages[-6:]
                              if not m["content"].startswith(CALC_RESULT_PREFIX))
        notes = []
        for sub in agent.sub_brains:
            earlier = "\n\n".join(f"[{n}]\n{t}" for n, t in notes)
            prompt = (f"You are {sub['name']}, one part of {agent.name}'s mind. Your job: {sub['job']}\n\n"
                      f"Conversation:\n{recent}\n\n" + (f"Notes from the other parts so far:\n{earlier}\n\n" if earlier else "")
                      + "Write your notes for the latest message only: plain, terse bullet points, at most 120 words. "
                        "These are private working notes, not the reply.")
            with Spinner(f"{agent.name}'s {sub['name']} is working"):
                text = self._sub_call(agent, system, prompt)
            if not text:
                break
            notes.append((sub["name"], text))
            self.show_sub(agent, sub, text)
        if not notes:
            return ""
        joined = "\n\n".join(f"[{n}]\n{t}" for n, t in notes)
        return ("\n\nYour inner council has already worked on the latest message. Use their notes, resolve any "
                "disagreement between them, and answer in your own voice (don't mention the council):\n" + joined)

    def lobes_on(self, agent):
        return (agent.name == self.agents.default.name and self.config.get("lobes", True) is not False
                and all(self.agents.get(l["agent"]) for l in LOBES.values()))

    def _quick_call(self, agent, system, prompt, max_tokens):
        """A short, quiet JSON answer for internal votes. Thread-safe: no shared state is changed."""
        temp = agent.temperature if agent.temperature is not None else 0.2
        for backend in self.backends(agent):
            try:
                return "".join(backend.stream(system, [{"role": "user", "content": prompt}], max_tokens=max_tokens,
                                              temperature=min(temp, 1.0), json_mode=True)).strip()
            except (BackendUnavailable, RuntimeError):
                continue
        return None

    def show_vote(self, result):
        """Print the lobe vote (the app overrides show_sub to stream it)."""
        judge = self.agents.get("judge")
        self.show_sub(self.agents.default, {"name": "lobe vote", "icon": ui.icon_for(judge.name, judge.icon) if judge else "⚖",
                                            "color": judge.color if judge else 252, "lobe": True},
                      "\n".join(lobes.summary_lines(result)))

    def lobe_council(self, agent, system, messages):
        """Doc and Fiery Black vote on how the core should answer; returns notes for its prompt."""
        if not self.lobes_on(agent):
            return ""
        if not hasattr(self, "_vote"):
            self._vote = lobes.LobeVote(self._quick_call, self.config)
        self._vote.config = self.config
        result = self._vote.run(self.agents, [m for m in messages if not m["content"].startswith(CALC_RESULT_PREFIX)],
                                self.user_texts(messages), judge_on=self.config.get("judge", True) is not False,
                                show=self.show_vote, spinner=Spinner)
        return lobes.notes_for_core(result, self.config.get("lobe_balance", "even")) if result else ""

    def _agent_turn(self, agent, active_skills, messages):
        """One agent reply, including calculator rounds. Appends to `messages`. Returns final text or None."""
        system = self.system_for(agent, active_skills, " ".join(self.user_texts(messages)[-2:]))
        system += self.inner_council(agent, system, messages)
        system += self.lobe_council(agent, system, messages)
        system += self.pop_relay_notes()
        final = None
        for round_no in range(MAX_CALC_ROUNDS + 1):
            text, status = self._stream(agent, system, messages)
            if not text:
                while messages and messages[-1]["role"] == "user" and \
                        messages[-1]["content"].startswith(CALC_RESULT_PREFIX):
                    messages.pop()
                return final
            messages.append({"role": "assistant", "content": text})
            final = text
            lines = find_calc_blocks(text)
            if status != "ok" or not lines or round_no == MAX_CALC_ROUNDS:
                break
            with Spinner("calculating"):
                results = calculate(lines)
            for r in results:
                print(f"  {ui.KELP}={RESET} {r}")
            print()
            messages.append({"role": "user", "content": format_results(results)})
        return final

    # ------------------------------------------------------------------ the Agency and the Bureau of Magic
    def show_conscience(self, note):
        a = AGENCY["conscience"]
        print(f"  {BOLD}{ui.c256(a['color'])}{a['icon']} on second thought{RESET} {DIM}(his conscience){RESET}")
        print(f"  {ui.c256(a['color'])}{ui.V}{RESET} {note}\n")

    def show_magic(self, dept, gift_id, text):
        d = DEPARTMENTS[dept]
        tint = ui.c256(d["color"])
        print(f"  {BOLD}{tint}{d['icon']} {d['name']}{RESET} {DIM}· Bureau of Magic{RESET}")
        for line in text.strip().splitlines():
            print(f"  {tint}{ui.V}{RESET} {line}")
        if dept == "riddle":
            print(f"  {tint}{ui.V}{RESET} {DIM}(/magic reveal for the answer){RESET}")
        print()

    def about_user(self):
        bits = []
        if self.memory:
            core = self.memory.core_text()
            if core:
                bits.append(core)
            for e in self.memory.recent_episodes(4):
                bits.append(f"- recently talked about: {e['title']}")
            for r in self.memory.active("project")[:5] + self.memory.active("preference")[:5]:
                bits.append(f"- {r['text']}")
        return "\n".join(dict.fromkeys(bits))[:2500]

    def conjure(self, dept=None, recent=""):
        """Ask a Bureau department for a surprise. Returns (dept, id, text) or None."""
        dept = dept or self.agency.pick_department()
        with Spinner(f"the {DEPARTMENTS[dept]['name']} is at work"):
            data = extract_json(self._sub_call(self.agents.default, self.system_for(self.agents.default, [], recent),
                                               self.agency.magic_prompt(dept, self.about_user(), recent)))
        gid = self.agency.store_gift(dept, data) if data else None
        return (dept, gid, data["gift"].strip()) if gid else None

    def after_reply(self, agent, user_text):
        """His conscience re-reads a substantial reply; now and then the Bureau slips in a surprise."""
        if not self.agency or not self.messages or self.messages[-1]["role"] != "assistant":
            return
        reply = self.messages[-1]["content"]
        if self.agency.conscience_on() and len(reply.split()) >= CONSCIENCE_MIN_WORDS:
            from personality import CORE_CHARACTER_RULES
            rules = "\n".join(f"- {r}" for r in CORE_CHARACTER_RULES + list(self.persona.character.get("rules", [])))
            with Spinner("his conscience is re-reading"):
                data = extract_json(self._quiet_complete(self.agency.conscience_prompt(user_text, reply, rules)))
            if isinstance(data, dict) and str(data.get("verdict", "")).lower() == "amend" and data.get("note"):
                note = str(data["note"]).strip()
                self.show_conscience(note)
                self.messages[-1]["content"] = reply + "\n\n*On second thought:* " + note
            if isinstance(data, dict):
                self.agency.record_lesson(data.get("lesson", ""))
        if self.agency.magic_due(user_text, len(self.user_texts())):
            recent = "\n".join(f"{m['role']}: {m['content'][:400]}" for m in self.messages[-4:])
            got = self.conjure(None, recent)
            if got:
                self.show_magic(*got)

    def journal_and_mirror(self, new):
        """After a chat: the diarist writes an entry; every few entries the mirror updates his self-model."""
        transcript = "\n\n".join(f"{m['role'].upper()}: {m['content'][:1500]}" for m in new)
        entry = self._quiet_complete(self.agency.journal_prompt(transcript, self.agency.get("self_model")))
        if entry and not entry.strip().startswith("{"):
            self.agency.add_entry(entry)
        else:
            entry = None
        mirrored = None
        if self.agency.mirror_due():
            mirrored = self.agency.update_self(extract_json(self._quiet_complete(self.agency.mirror_prompt())))
        return entry, mirrored

    def perceive(self, text):
        """Every agent reads the message through its own lens and files notes."""
        if not self.cortex:
            return
        found = self.cortex.perceive(text, list(self.agents.agents),
                                     previous_agent=self.agent.name if self.messages else None)
        if self.show_perception and found:
            chips = []
            for name, hits in found.items():
                agent = self.agents.get(name)
                color = agent.color if agent else 250
                cats = "·".join(dict.fromkeys(f"{ui.c256(category_color(name, c))}{c}{RESET}" for c, _t in hits))
                chips.append(f"{ui.agent_icon(name, color, agent.icon if agent else None)} {cats}")
            print(f"  {DIM}noticed{RESET} " + f"  ".join(chips))
        return found

    def handle_memory_request(self, text):
        """React to 'remember that ...' / 'forget that ...' said in conversation."""
        found = detect_memory_command(text)
        if not found:
            return
        if not self.memory_on():
            ui.note("memory is off")
            return
        kind, payload = found
        if kind == "remember":
            mem_id, action = self.memory.add(f"The user said: {payload}", guess_category(payload), 4,
                                             source="you asked")
            ui.note({"added": f"remembered #{mem_id}: {payload}",
                     "reinforced": f"already knew that, so I strengthened memory #{mem_id}",
                     "blocked": "that looks like a password, key or card number, so it was NOT stored",
                     "invalid": "nothing to remember there"}[action])
        else:
            hits = self.memory.search(payload, 3, min_relevance=0.5)
            if hits:
                r = hits[0][0]
                self.memory.archive(r["id"], "you asked me to forget it")
                ui.note(f"forgot #{r['id']}: {r['text']}  (/restore {r['id']} to undo)")
            else:
                ui.note("couldn't find a memory matching that (try /memories <words>)")

    def ask(self, text):
        agent, text = self.agents.split_mention(text)
        if not text:
            print("Add a message after the agent's name, like: @broca draft a thank-you email\n")
            return
        self.handle_memory_request(text)
        if agent is not None:
            self.agents.router.learn(text, agent.name)  # you picked this agent: routing learns from it
        if agent is None and self.agent_mode == "auto" and detect_memory_command(text):
            agent = self.agents.default  # memory requests go to the hippocampus
        perceived = self.perceive(text) or {}
        if agent is None:
            if self.agent_mode != "auto":
                agent = self.agents.get(self.agent_mode) or self.agents.default
            elif self.config.get("council", True) is not False:
                agent = self.council_turn(text, perceived)
            else:
                agent = self.agents.route(text)
                # Short follow-ups ("make it shorter") stay with the agent already working.
                if agent is self.agents.default and len(text) < 80 and self.messages:
                    agent = self.agent
        active = self.skills_for(agent, self.user_texts() + [text])
        self.agent, self.active_skills = agent, active
        start = len(self.messages)
        paid = treasury.settle(text, str(self.chat_path))   # the last reply is paid what it turned out to be worth
        if paid:
            self.paid_note(*paid)
        self.messages.append({"role": "user", "content": text})
        if self._agent_turn(agent, active, self.messages) is None:
            while self.messages and self.messages[-1]["role"] == "user":
                self.messages.pop()
        else:
            self._record(agent.name, start)
            treasury.record_work(agent.name, text)
            treasury.hold(agent.name, text, str(self.chat_path), text)
            self.after_reply(agent, text)

    def paid_note(self, agent, cents, ledger):
        """A quiet line when the Treasurer pays the last reply."""
        why = ", ".join(w for d, w in ledger[1:]) or "it answered"
        ui.note(f"paid {agent} {change.dollars(cents)} ({why})")

    # ------------------------------------------------------------------ the council (auto mode)
    def busy_with(self, label, agent=None):
        """A 'working on it' indicator (the app shows it its own way)."""
        return Spinner(label)

    def council_turn(self, text, perceived):
        """All ten agents vote on who takes the message; a relay runs if several have a strong claim.
        Returns the agent who delivers the final answer."""
        pick = self.agents.router.predict(text, self.agents.agents)
        d = council.decide(self.agents.agents, text, pick if pick[0] and pick[1] >= 0.5 else None, perceived,
                           previous=self.agent.name if self.messages else None, has_history=bool(self.messages),
                           max_steps=int(self.config.get("council_steps", council.DEFAULTS["council_steps"])),
                           seats=self.config.get("council_seats"))
        council.record(d)
        treasury.record_votes(list(d.votes))   # every ballot is a shilling counted
        self.show_sub(self.agents.default, {"name": "council vote", "icon": "⚑", "color": 252, "lobe": True,
                                            "kind": "council"}, "\n".join(d.lines()))
        if len(d.steps) > 1:
            progress, concerns = self.run_relay(text, d.steps)
            self.relay_notes = council.final_notes(progress, concerns)
        return self.agents.get(d.steps[-1]) or self.agents.default

    def run_relay(self, text, steps):
        """Progressional continuation: each step builds on the last; an approval vote gates every handoff."""
        cfg = self.config
        revisions = int(cfg.get("council_revisions", council.DEFAULTS["council_revisions"]))
        threshold = float(cfg.get("council_threshold", council.DEFAULTS["council_threshold"]))
        approve_on = cfg.get("council_approval", True) is not False
        done, concerns, total = [], [], len(steps)
        for i, name in enumerate(steps[:-1], 1):
            agent, nxt = self.agents.get(name), steps[i]
            system = self.system_for(agent, self.skills_for(agent, [text]), text)
            notes, work = "", None
            for attempt in range(revisions + 1):
                prompt = council.step_prompt(text, i, total, name, nxt, "\n\n".join(done), "\n".join(concerns), notes)
                with self.busy_with(f"step {i}/{total} · {name} is working", agent):
                    work = self._sub_call(agent, system, prompt)
                if not work:
                    break
                self.show_sub(agent, {"name": f"step {i}/{total} · {name}", "icon": ui.icon_for(name, agent.icon),
                                      "color": agent.color, "lobe": True, "kind": "step"}, work)
                if not approve_on:
                    break
                voters = council.approvers(name, nxt, self.config.get("council_seats"))
                judge = self.agents.get("judge") or agent
                with self.busy_with(f"the crew is voting on step {i}", judge):
                    raw = self._quick_call(judge, judge.slim_system(),
                                           council.approval_prompt(text, name, council.PART.get(name, ""), work, nxt,
                                                                   voters), 320)
                votes = council.parse_approval(raw, voters)
                ok = council.approved(votes, voters, threshold)
                last = attempt == revisions
                self.show_sub(agent, {"name": f"approval · step {i}", "icon": "✓", "color": 252, "lobe": True,
                                      "kind": "approval"},
                              council.approval_line(i, name, votes, ok, revised=not ok and last))
                if ok:
                    council.record(approvals=1)
                    break
                notes = "; ".join(f"{a}: {n}" for a, (v, n) in votes.items() if v == "revise" and n) or "tighten it up"
                if last:
                    council.record(carried=1)
                    concerns.append(f"- step {i} ({name}): {notes}")
                else:
                    council.record(sent_back=1)
            if not work:
                break   # the next agent carries on with whatever progress exists
            done.append(f"[step {i} · {name} - {council.PART.get(name, '')}]\n{work}")
            treasury.record_work(name, text, wage=True)   # the work passes on, shilling to shilling, for a nickel
        return "\n\n".join(done), "\n".join(concerns)

    def pop_relay_notes(self):
        notes, self.relay_notes = getattr(self, "relay_notes", ""), ""
        return notes

    def team(self, task):
        """Planner splits the task, specialists do their parts, Seahorse combines the results."""
        planner = self.agents.get("prefrontal") or self.agents.default
        self.perceive(task)
        steps = self.agents.parse_plan(
            self.complete(self.agents.plan_prompt(task), planner, label="planner is splitting up the task"))
        if not steps:
            ui.note("couldn't make a plan, so answering directly")
            return self.ask(task)
        ui.section("team plan")
        for i, (agent, sub) in enumerate(steps, 1):
            print(f"  {ui.SAND}{i}.{RESET} {ui.agent_name(agent.name, agent.color, agent.icon)} {DIM}{sub}{RESET}")
        print()
        work = []
        for i, (agent, sub) in enumerate(steps, 1):
            ui.section(f"step {i}/{len(steps)} · {ui.icon_for(agent.name, agent.icon)} {agent.name}", agent.color)
            earlier = "\n\n".join(f"Result of step {j} ({a.name} - {t}):\n{o}"
                                  for j, (a, t, o) in enumerate(work, 1))
            prompt = f"Overall task: {task}\n\n" + (f"{earlier}\n\n" if earlier else "") + f"Your part: {sub}"
            msgs = [{"role": "user", "content": prompt}]
            out = self._agent_turn(agent, self.skills_for(agent, [sub]), msgs)
            if not out:
                ui.note(f"step {i} didn't finish, so the team stopped here")
                break
            work.append((agent, sub, out))
            self.usage[agent.name] = self.usage.get(agent.name, 0) + 1
        if not work:
            return
        final = work[-1][2]
        if len(work) > 1:
            ui.section("final answer", self.agents.default.color)
            results = "\n\n".join(f"[{a.name} - {t}]\n{o}" for a, t, o in work)
            prompt = (f"Task: {task}\n\nYour specialist agents produced this work:\n\n{results}\n\n"
                      "Write the final answer for the user as one coherent response. Keep the substance, "
                      "apply any critic's feedback, drop repetition, and don't narrate the process.")
            msgs = [{"role": "user", "content": prompt}]
            final = self._agent_turn(self.agents.default, self.skills_for(self.agents.default, [task]), msgs) or final
        self.messages += [{"role": "user", "content": task}, {"role": "assistant", "content": final}]
        self.reply_agent[len(self.messages) - 1] = "team: " + ", ".join(a.name for a, _, _ in work)

    # ------------------------------------------------------------------ growth
    def grow(self, verbose=True):
        """Reflect on the chat since the last reflection and evolve Seahorse's personality."""
        new = [dict(m, agent=self.reply_agent.get(i))
               for i, m in enumerate(self.messages) if i >= self.reflected_upto
               and not (m["role"] == "user" and m["content"].startswith(CALC_RESULT_PREFIX))]
        turns = sum(1 for m in new if m["role"] == "user")
        if turns < 2:
            if verbose:
                ui.note(f"Not enough new conversation to learn from yet."); print()
            return
        signals = {}
        reply = self.complete(self.persona.reflection_prompt(new), label="Seahorse is reflecting on this chat")
        if reply:
            signals, _ = Personality.parse_reflection(reply)
            signals = {self.persona.find_trait(k): v for k, v in signals.items() if self.persona.find_trait(k)}
        elif verbose:
            ui.note("couldn't reach a model to reflect, so this chat only counts as experience")
        agents_used = list(self.usage)
        mem_report = self.file_memories(new, turns, agents_used) if self.memory else None
        cortex_report = self.cortex_review(new) if self.cortex else None
        journal = None
        if self.agency:
            with Spinner("Seahorse is writing in his journal"):
                journal = self.journal_and_mirror(new)
        changes = self.persona.evolve(signals, [], turns=turns,
                                      usage=self.usage, pairings=self.agents.pairings())
        this_chat = ", ".join(f"{self.paint_agent(a)} x{c}"
                              for a, c in sorted(self.usage.items(), key=lambda kv: -kv[1]))
        self.usage = {}
        self.reflected_upto = len(self.messages)
        self.apply_persona()
        core = self.memory.core_text() if self.memory else ""
        ok, msg = self.persona.build_ollama(
            extra="\n".join(x for x in (self.extra, "What you know about the user:\n" + core if core else "") if x))
        if verbose:
            if mem_report:
                ui.section("Seahorse remembered")
                print(f"  {ui.AQUA}episode{RESET}      #{mem_report['episode']} {mem_report['title']}")
                labels = [("added", "+ new", ui.KELP), ("reinforced", "= again", ui.TEAL),
                          ("updated", "~ updated", ui.SAND), ("archived", "- forgot", ORANGE),
                          ("blocked", "x refused", ORANGE)]
                for key, label, color in labels:
                    for mem_id, text in mem_report[key]:
                        tag = f"#{mem_id} " if mem_id else ""
                        print(f"  {color}{label:<12}{RESET} {DIM}{tag}{RESET}{text}")
                if mem_report["blocked"]:
                    ui.note("refused items looked like secrets (passwords, keys, card numbers)")
                cons = mem_report.get("consolidation")
                if cons:
                    ui.note(f"tidied memory: {len(cons['archived'])} faded, {len(cons['merged'])} merged"
                            + (f", {cons['embedded']} indexed by meaning" if cons["embedded"] else ""))
            if cortex_report:
                self.show_cortex_report(cortex_report)
            if journal and journal[0]:
                d = AGENCY["diarist"]
                ui.section("from his journal", d["color"])
                for line in journal[0].strip().splitlines():
                    print(f"  {DIM}{ui.ITALIC}{line}{RESET}")
                if journal[1]:
                    m = AGENCY["mirror"]
                    print(f"\n  {BOLD}{ui.c256(m['color'])}{m['icon']} who he's becoming{RESET} {journal[1][0]}")
            ui.section("Seahorse grew")
            for name, (old, new_v) in changes.items():
                arrow = f"{ui.KELP}↑{RESET}" if new_v > old else f"{ORANGE}↓{RESET}"
                print(f"  {ui.SAND}{name:<12}{RESET} {arrow} {old:.2f} → {new_v:.2f}")
            if this_chat:
                print(f"  {ui.AQUA}agents{RESET}       {this_chat}  {DIM}(their paired traits grew fastest){RESET}")
            if self.persona.shaped_by():
                print(f"  {ui.AQUA}shaped by{RESET}    {self.persona.shaped_by()}  {DIM}(all time){RESET}")
            ui.note(msg)
            print()

    def cortex_review(self, new):
        """Each agent writes deeper notes on the chat; every few chats Seahorse dreams."""
        names = list(self.agents.agents)
        data = extract_json(self.complete(self.cortex.reflection_prompt(new, names),
                                          label="agents are writing their notes"))
        report = {"notes": self.cortex.apply_reflection(data, names)}
        self.cortex.end_chat()
        if self.cortex.due_to_dream():
            report["dream"] = self.dream()
        return report

    def dream(self):
        """Summarize every notebook into the collective tree and generate self-development ideas."""
        spinner = Spinner("Seahorse a dream wid di spirits of di deep" if self.persona.character.get("enabled")
                          else "Seahorse is dreaming").start()

        def complete(prompt, label):
            spinner.label = label
            return self._quiet_complete(prompt)

        try:
            rep = self.cortex.dream(complete, list(self.agents.agents), self.persona)
            rep["traits"] = self.cortex.apply_trait_ideas(self.persona)
        finally:
            spinner.stop()
        if self.profile and self.profile.enabled:
            rep["profile"] = self.update_profile()
        return rep

    def update_profile(self):
        """Re-read the evidence and revise Seahorse's opinionated profile of the user."""
        metrics = behaviour_metrics(CHATS_DIR_FOR_PROFILE)
        if not self.profile.ready(metrics):
            return {"not_ready": metrics.get("user_messages", 0)}
        evidence = []
        if self.cortex:
            root = self.cortex.node("root")
            if root and root["summary"]:
                evidence.append(f"Collective understanding: {root['summary']}")
            for name in self.agents.agents:
                node = self.cortex.node("agent", name)
                if node and node["summary"]:
                    evidence.append(f"{name}'s view: {node['summary']}")
            for agent, cat in (("broca", "tone"), ("broca", "style"), ("prefrontal", "goals"),
                               ("cingulate", "corrections"), ("cingulate", "unresolved"),
                               ("wernicke", "knowledge gaps"), ("hippocampus", "themes")):
                rows = self.cortex.db.execute("SELECT topic, text, count FROM notes WHERE agent=? AND category=? "
                                              "ORDER BY weight DESC LIMIT 4", (agent, cat)).fetchall()
                for r in rows:
                    evidence.append(f"{agent}/{cat} ({r['topic']}, x{r['count']}): {r['text']}")
        if self.memory:
            core = self.memory.core_text()
            if core:
                evidence.append("Known facts:\n" + core)
            for e in self.memory.recent_episodes(6):
                evidence.append(f"Conversation {datetime.fromtimestamp(e['ended']):%Y-%m-%d}: {e['title']} - {e['summary']}")
        with Spinner("forming a view of you"):
            reply = self._quiet_complete(self.profile.update_prompt(metrics, "\n".join(evidence)[:9000]))
        data = extract_json(reply)
        if not data:
            return {"failed": True}
        report = self.profile.apply_update(data)
        domains = self.profile.domains()
        if domains:
            quotes = {d: q for d, q in stated_quotes(domains, CHATS_DIR_FOR_PROFILE).items() if q}
            if quotes:
                with Spinner("reflecting on what you've shared"):
                    reply = self._quiet_complete(self.profile.personal_prompt(quotes))
                report["personal"] = self.profile.apply_personal(extract_json(reply), quotes)
            report["personal_silent"] = [d for d in domains if d not in quotes]
        return report

    def show_profile_report(self, rep):
        if not rep:
            return
        if rep.get("not_ready") is not None:
            ui.note(f"not enough conversation to form a view of you yet ({rep['not_ready']} messages so far)")
            return
        if rep.get("failed"):
            ui.note("couldn't update the profile this time (no model reachable or an unreadable answer)")
            return
        ui.section("Seahorse's view of you")
        labels = [("new", "+ formed", ui.KELP), ("strengthened", "↑ surer", ui.TEAL), ("revised", "~ revised", ui.SAND),
                  ("weakened", "↓ less sure", ui.SAND), ("retired", "- dropped", ORANGE)]
        changed = False
        for key, label, color in labels:
            for oid, section, text in rep.get(key, []):
                changed = True
                print(f"  {color}{label:<12}{RESET} {DIM}#{oid} {section}{RESET} {text}")
        personal = rep.get("personal") or {}
        for key, label, color in labels:
            for oid, section, text in personal.get(key, []):
                changed = True
                print(f"  {color}{label:<12}{RESET} {DIM}#{oid} {LOCK} {section}{RESET} {text}")
        if not changed:
            ui.note("no change - the evidence still fits its current view")
        if rep.get("refused"):
            ui.note(f"{rep['refused']} opinion(s) discarded for using clinical labels")
        if personal.get("refused"):
            ui.note(f"{personal['refused']} personal opinion(s) discarded for not quoting what you actually said")
        if rep.get("personal_silent"):
            ui.note(f"nothing you've said yet about: {', '.join(rep['personal_silent'])}")
        ui.note("/profile to see the whole portrait, /agree or /disagree <id> to set it straight")

    def _quiet_complete(self, prompt):
        """complete() without its own spinner (used inside the dream's spinner)."""
        self.claude.temperature = self.local.temperature = 0.3
        for backend in self.backends():
            try:
                return "".join(backend.stream("You reflect carefully and reply with JSON only.",
                                              [{"role": "user", "content": prompt}]))
            except (BackendUnavailable, RuntimeError):
                continue
        return None

    def show_cortex_report(self, rep):
        notes = rep.get("notes") or {}
        if notes:
            ui.section("agents took notes")
            print("  " + "   ".join(f"{self.paint_agent(a)} +{n}" for a, n in notes.items()))
        dream = rep.get("dream")
        if not dream:
            return
        ui.section("Seahorse dreamed")
        if dream["agents"]:
            print(f"  {ui.AQUA}re-summarised{RESET} {', '.join(self.paint_agent(a) for a in dream['agents'])} "
                  f"{DIM}({dream['branches']} branches){RESET}")
        root = self.cortex.node("root")
        if root and root["summary"]:
            print(f"  {ui.AQUA}understands{RESET}   {root['summary']}")
        for idea in dream["ideas"]:
            who = f"{self.paint_agent(idea['agent'])} " if idea["agent"] else ""
            print(f"  {ui.SAND}idea #{idea['id']:<3}{RESET} {ui.TEAL}{idea['kind']:<9}{RESET} {who}{idea['title']}"
                  f" {DIM}[{idea['status']}]{RESET}")
        for _id, verdict, agent, detail, reason in dream["reviews"]:
            color = ui.KELP if verdict == "adopted" else ORANGE
            print(f"  {color}{verdict:<13}{RESET} {self.paint_agent(agent)} {detail} {DIM}{reason}{RESET}")
        for trait, old, new, reason in dream.get("traits", []):
            print(f"  {ui.AQUA}target{RESET}        {trait} {old:.2f} → {new:.2f} {DIM}{reason}{RESET}")
        if dream["pruned"]:
            ui.note(f"{dream['pruned']} faint notes folded into the tree")
        if dream.get("profile"):
            self.show_profile_report(dream["profile"])

    def file_memories(self, new, turns, agents_used):
        """Review the chat: store an episode, add/update/forget memories, tidy up when due."""
        users = " ".join(m["content"] for m in new if m["role"] == "user")
        related = [r for r, _s, _rel in self.memory.search(users[-4000:], 15, min_relevance=0.15)]
        data = extract_json(self.complete(self.memory.extraction_prompt(new, related),
                                          label="Seahorse is filing memories")) or {}
        ep = data.get("episode") if isinstance(data.get("episode"), dict) else {}
        first = next((m["content"] for m in new if m["role"] == "user"), "conversation")
        title = str(ep.get("title") or first[:60]).strip()
        topics = [str(t) for t in ep.get("topics", []) if t][:8] if isinstance(ep.get("topics"), list) else []
        try:
            importance = int(ep.get("importance", 3))
        except (TypeError, ValueError):
            importance = 3
        ep_id = self.memory.add_episode(self.started.timestamp(), datetime.now().timestamp(), title,
                                        str(ep.get("summary") or ""), topics, agents_used, importance, turns,
                                        self.chat_path)
        report = self.memory.apply_extraction(data, [r["id"] for r in related], ep_id)
        report.update(episode=ep_id, title=title)
        if self.memory.due_for_consolidation():
            with Spinner("tidying long-term memory"):
                report["consolidation"] = self.memory.consolidate()
        return report

    # ------------------------------------------------------------------ files
    @property
    def chat_path(self):
        if not getattr(self, "_chat_path", None):
            base = HISTORY_DIR / f"chat-{self.started:%Y%m%d-%H%M%S}"
            path, n = base.with_suffix(".json"), 1
            while path.exists():  # two chats started in the same second
                n += 1
                path = Path(f"{base}-{n}.json")
            self._chat_path = path
        return self._chat_path

    def save(self):
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        path = self.chat_path
        path.write_text(json.dumps({
            "started": self.started.isoformat(),
            "messages": self.messages,
            "agents": {str(i): a for i, a in self.reply_agent.items()},  # who wrote each reply (for fine-tuning)
        }, indent=2))
        return path

    def load(self, path):
        data = json.loads(Path(path).read_text())
        self.messages = data.get("messages", [])
        self.reflected_upto = len(self.messages)  # don't learn twice from an old chat


HELP = f"""{BOLD}Commands{RESET}
  /mode auto|claude|local   switch backend (auto = Claude, fall back to local)
  /model <name>             set the model for the current backend
  /local-model <name>       set the local Ollama model
  /models                   list installed local models
  /system <text>            override the system prompt for this chat only
  /system reset             go back to Seahorse's own personality

{BOLD}Agents{RESET}
  /agent <name>|auto        stay with one agent, or route each message automatically
  @<agent> <message>        send one message to a specific agent, e.g. @broca ... (old names like @writer work too)
  /team <task>              planner splits the task, agents each do a part, Seahorse combines

{BOLD}Skills{RESET}
  /skills                   list skills and which are active
  /skill <name> on|off|auto always use, never use, or use when relevant
  /calc <expression>        use the calculator directly, e.g. /calc 1250*(1+0.045/12)**60
  /units <n> <from> to <to> convert any unit, e.g. /units 3 furlongs to m · /units list [category]

{BOLD}Mind{RESET}
  /agents                   each agent's purpose, processing skill, note colours and practices
  /notes [agent]            the agents' notebooks as colour-coded trees
  /tree [1-3]               the collective summarization tree
  /dream                    summarise everything and generate self-development ideas now
  /ideas [all]              techniques on trial, proposals, questions, directions
  /adopt <id> | /drop <id>  try or create an idea, or discard it
  /perceive [on|off]        show what each agent notices in your messages

{BOLD}Profile{RESET}  (Seahorse's opinionated view of you)
  /profile                  the portrait: honest take, opinions with confidence, temperament
  /profile update           re-form the view now (it also updates whenever Seahorse dreams)
  /profile why <id>         the evidence behind an opinion
  /agree <id>               confirm an opinion
  /disagree <id> [why]      correct one - it loses confidence and needs new evidence to return
  /profile domains          personal domains: politics, health, sexuality, religion, finances (opt-in)
  /profile domain <name> on|off|wipe   opinions only from what you say about yourself
  /profile drop|history|export [all]|off|on|wipe

{BOLD}Look{RESET}
  /theme [name]             ocean, reef, abyss, kelp, daylight, mono
  /logo [style]             full, compact, minimal, trident, none
  /config [setting value]   the default starting state (name, greeting, spinner, ...)
  /welcome                  show the welcome screen again

{BOLD}Memory{RESET}  (or just say "remember that ..." / "forget that ...")
  /memory                   memory overview
  /memories [words|category]  list what Seahorse knows, or search it
  /remember <fact>          save something now
  /forget <id|words>        forget a memory (it's archived, so /restore can undo)
  /restore <id>             bring back a forgotten memory
  /edit <id> <new text>     correct a memory
  /pin <id> | /unpin <id>   pinned memories are always in mind and never fade
  /episodes [n]             recent conversations
  /recall <words>           search memories and past conversations
  /revisit <episode id>     bring a past conversation's summary into this chat
  /memlog [n]               what changed in memory, and why
  /consolidate              tidy memory now (fade, merge, index)
  /export [file.md]         export all memories as Markdown
  /wipe                     erase all memories (asks first)

{BOLD}Fine-tuning{RESET}
  /finetune                 progress and what's in use
  /board [sub] [...]        the governance board: high council, seats, reef, purse, season on one page;
                            /board seats · laws · law <bottle> · repeal <wreck> · pay · budget · quarters · crew ...
  /pay                      the payroll: every agent's purse in change, and the last payments
  /pay credit|deduct|split|grow|ration ...   the Treasurer's MDAS moves on purses (add, subtract, divide, multiply)
  /zero [Z|E|R|O ...]       ZERO spells MDAS: Zoom the size (x), Even split (/), Reward (+), Owed out (-)
  /orez                     ZERO in reverse: undo the last Treasurer move
  /spine [full]             the spine: every payment a numbered, hash-sealed vertebra, filed in portions of 1,000;
                            checks it (full replays everything from zero)
  /change                   the change: coins, how a reply's worth is counted, each agent's purse
  /finetune plan|extract|outline|build   the Ultimate model, valued in change: plan it, price every reply
                            ($0.00-$1.00), read the dataset's worth, train it
  /finetune prepare         build training data from your chats (corrected replies dropped, praised ones doubled)
  /finetune distill         (optional) Claude answers as each agent, to teach the local model
  /finetune train           train a LoRA on the local model (Apple Silicon or NVIDIA), in the background
  /finetune eval            tuned vs untuned on held-out chats
  /finetune use | revert    run Seahorse on the tuned model, or go back
  /router [reset]           routing that learns from the agents you pick with @name
  /brain [agent on|off]     Doc's and Fiery Black's sub-agent brains
  /lobes [on|off|left|even|right]   Doc (left lobe) and Fiery Black (right lobe) vote on how Seahorse answers
  /lobes stats              how the votes went: agreement, Judge tie-breaks, speed
  /lobes words|timeout|margin <n>   vote on messages of n+ words · time limit · how close counts as a split
  /judge [on|off]           the Judge breaking split votes (talk to him with @judge)

{BOLD}Inner voice and the Bureau of Magic{RESET}
  /journal [n|lessons|all]  his private journal, written after each chat
  /self                     who he's becoming, and the intentions he's holding
  /conscience [on|off]      re-reading his replies and adding "on second thought" corrections
  /magic [story|riddle|idea|gift]   a surprise from the Bureau now
  /magic reveal | history   the last riddle's answer, or past surprises
  /magic often|sometimes|rarely|off   how often surprises appear on their own

{BOLD}Character{RESET}
  /character                the Seahorse: his personality piece (A Lonesome Grim), story, voice, mannerisms and spirit-sense
  /character on|off         play the character, or speak plainly
  /character light|medium|strong   how strong the accent is
  /build [step]             design him step by step: identity, backstory, tale, voice, strength,
                            mannerisms, spirit, rules, greetings, traits, preview (test + save)
  /persona [use|save|delete|new] <name>   saved personas (the Seahorse is built in)
  /council                  how all ten agents voted on who answers (auto mode), and the stats
  /council on|off · steps <n> · approval on|off · threshold <x> · revisions <n>   tune the council
  /treasury                 the treasury: every agent a shilling, the Kraken (the Judge) as Treasurer, the reef
  /law [board:] <text>      throw a message in a bottle (a single amendment) to a cabinet board; all ten shillings vote; ten ayes
     (or /wreck)            make a galleon, sunk into the reef as a shipwreck: a law (boards: state, communications,
                            navigation, works, education, planning, inspection, science, defense, treasury)
  /reef [all] · /law repeal <wreck>   the Reef Courtesy Standard Operation (RCSO, the constitution), set in stone:
                            a numbered index (Wreck 9.01 = board 9, first wreck), hash-chained and append-only;
                            10 shipwrecks per board, a full board is a black pearl (/laws works too)
  /budget                   the marlin is the people: your goals, direction, future - and what's in the budget
  /trident                  Poseidon's Trident, the working class: processing power and how the work is distributed
  /compass                  the NEWS: the horsemen at each point, and lightning strikes on the instruments
  /quarters                 the four seasons and their horsemen: the treasury's books by quarter
  /pockets [words]          treasure pockets, the oil reserves (blood of the gods): ideas scrapped in past chats
  /locker                   Davy Jones' Locker: the core's pulse and the hourglass of the two hemispheres
  /trench                   the Mariana Trench: the undertow, everything held back and how deep it has sunk
  /budget add <goal> · set <n> <share> · drop <n>   share the marlin (100 parts) across your goals
  /council seats            the council table: votes run 01→05 along the top, then 06→10 back; 1+ breaks ties
  /council seat <1-10> <agent>   reseat an agent (swaps with whoever sat there) · /council reseat for the default
  /crew                     his crew: every agent's character (name, post, greeting)
  /crew <agent>             one crew member in full: backstory, tale, voice, spirit...
  /build crew <agent> [step]   build a crew member with the same 11 steps
  /crew reset <agent>       back to the default · /crew on|off  crew voices or the captain's for all
  /crew seals on|off        stamp each reply with the crew member's notary seal
  /crew pledge · /crew chant   the crew's loyalty pledge and chant (by Daryl James-Michael Kennedy)

{BOLD}Personality{RESET}
  /traits [agent]           show Seahorse's traits overall, or as one agent sees them
  /more <trait>             more of a trait now (also raises its target)
  /less <trait>             less of a trait now (also lowers its target)
  /target <trait> <0-1>     set what a trait grows toward
  /newtrait <name> | <low> | <high>   add a trait to grow
  /reflect                  learn from this chat right now
  /rollback                 undo the last personality change
  /modelfile                write the Modelfile and rebuild the Ollama model
  /clear                    start a fresh conversation
  /save                     save this chat to ~/.seahorse/chats
  /load <file>              load a saved chat
  /status                   show what's connected
  /help                     this list
  /quit                     exit
Tip: end a line with \\ to keep typing on the next line."""


def read_input():
    lines = []
    while True:
        line = input(ui.prompt(continuation=bool(lines)))
        if line.endswith("\\"):
            lines.append(line[:-1])
            continue
        lines.append(line)
        return "\n".join(lines)


def status_lines(session):
    ok, no = f"{ui.KELP}●{RESET}", f"{ORANGE}○{RESET}"
    key = session.claude.api_key
    local_up = session.local.available()
    exp = session.persona.state["experience"]
    routing = "auto-routing" if session.agent_mode == "auto" else session.agent_mode
    return [
        ("mode", {"auto": "Claude first, local when offline", "claude": "Claude only",
                  "local": "local only"}[session.mode]),
        ("claude", f"{ok if key else no} {session.claude.model}" + ("" if key else f" {DIM}(no API key){RESET}")),
        ("local", f"{ok if local_up else no} {session.local.model}"
                  + ("" if local_up else f" {DIM}(Ollama not running){RESET}")),
        ("self", f"personality v{session.persona.state['version']} · {exp['chats']} chats of experience"),
        ("agents", f"{len(session.agents.agents)} types · {routing}"),
        ("skills", ", ".join(session.skills.skills) or "none"),
        ("mind", (lambda st: f"{st['notes']} notes · {st['dreams']} dreams · {st['trials']} techniques on trial")
                 (session.cortex.stats()) if session.cortex else "off"),
        ("profile", (f"{len(session.profile.opinions())} opinions about you"
                     + ("" if session.profile.enabled else " (paused)")) if session.profile else "off"),
        ("memory", (f"{session.memory.stats()['active']} memories · {session.memory.stats()['episodes']} conversations"
                    + (" · search by meaning" if session.memory.embedder and session.memory.embedder.ok else ""))
                   if session.memory else "off"),
    ]


def status(session):
    lines = status_lines(session)
    lines.append(("chat", f"{len(session.user_texts())} messages · last agent {session.agent.name}"
                          f" · skills {', '.join(session.active_skills) or 'none'}"))
    ui.panel(lines)


MEMORY_COMMANDS = {"memory", "memories", "remember", "forget", "restore", "edit", "pin", "unpin",
                   "episodes", "recall", "revisit", "memlog", "consolidate", "export", "wipe"}


def memory_command(session, cmd, arg):
    mem = session.memory
    if mem is None:
        ui.note("memory isn't available")
        print()
        return
    if cmd == "memory":
        st = mem.stats()
        cats = ", ".join(f"{k} {v}" for k, v in sorted(st["by_category"].items(), key=lambda kv: -kv[1])) or "none yet"
        emb = mem.embedder
        search = ("meaning + keywords" if emb and emb.ok else
                  f"keywords ({emb.problem})" if emb and emb.problem else "keywords")
        last = st["last_consolidation"]
        ui.panel([
            ("knows", f"{st['active']} memories ({cats})"),
            ("pinned", str(st["pinned"])),
            ("archive", f"{st['archived']} forgotten (restorable)"),
            ("episodes", f"{st['episodes']} past conversations"),
            ("search", search),
            ("tidied", datetime.fromtimestamp(last).strftime("%Y-%m-%d %H:%M") if last else "not yet"),
            ("stored", f"{st['path']} ({st['size_kb']} KB)"),
        ], title="memory")
    elif cmd in ("memories", "notes"):
        if arg in CATEGORY_NAMES:
            rows = mem.active(arg)
        elif arg:
            rows = [r for r, _s, _rel in mem.search(arg, 25, min_relevance=0.15)]
        else:
            rows = mem.active()
        if not rows:
            ui.note("nothing found" if arg else "no memories yet")
        now = time.time()
        for r in sorted(rows, key=lambda r: (r["category"], -mem.strength(r, now))) if not arg or arg in CATEGORY_NAMES \
                else rows:
            print(f"  {ui.SAND}#{r['id']:<4}{RESET} {ORANGE + '* ' + RESET if r['pinned'] else ''}"
                  f"{ui.TEAL}{r['category']:<11}{RESET} {r['text']} {DIM}[{mem.strength(r, now):.2f}]{RESET}")
        print()
    elif cmd == "remember":
        if not arg:
            print("Usage: /remember <something to remember>\n")
            return
        mem_id, action = mem.add(f"The user said: {arg}", guess_category(arg), 4, source="you asked")
        ui.note({"added": f"remembered #{mem_id}", "reinforced": f"already known, strengthened #{mem_id}",
                 "blocked": "looks like a secret (password, key or card number), so NOT stored",
                 "invalid": "nothing to remember"}[action])
        print()
    elif cmd == "forget":
        if arg.lstrip("#").isdigit():
            text = mem.archive(int(arg.lstrip("#")), "you asked me to forget it")
            ui.note(f"forgot #{arg.lstrip('#')}: {text}" if text else "no active memory with that id")
        elif arg:
            hits = mem.search(arg, 5, min_relevance=0.3)
            if not hits:
                ui.note("no matching memory")
            elif len(hits) == 1 or hits[0][2] - hits[1][2] >= 0.2:
                r = hits[0][0]
                mem.archive(r["id"], "you asked me to forget it")
                ui.note(f"forgot #{r['id']}: {r['text']}  (/restore {r['id']} to undo)")
            else:
                ui.note("several memories match; forget one by id:")
                for r, _s, _rel in hits:
                    print(f"    #{r['id']} {r['text']}")
        else:
            print("Usage: /forget <id or words>\n")
            return
        print()
    elif cmd == "restore":
        text = mem.restore(int(arg.lstrip("#"))) if arg.lstrip("#").isdigit() else None
        if text:
            ui.note(f"restored #{arg.lstrip('#')}: {text}")
        else:
            ui.note("usage: /restore <id> (forgotten memories:)")
            for r in mem.archived(10):
                print(f"    #{r['id']} {r['text']} {DIM}({r['archived_reason']}){RESET}")
        print()
    elif cmd == "edit":
        parts = arg.split(None, 1)
        if len(parts) == 2 and parts[0].lstrip("#").isdigit():
            ok = mem.update(int(parts[0].lstrip("#")), parts[1], "edited by you")
            ui.note("updated" if ok else "couldn't update that (unknown id, or it looked like a secret)")
        else:
            ui.note("usage: /edit <id> <new text>")
        print()
    elif cmd in ("pin", "unpin"):
        ok = arg.lstrip("#").isdigit() and mem.pin(int(arg.lstrip("#")), cmd == "pin")
        ui.note(f"{cmd}ned #{arg.lstrip('#')}" if ok else f"usage: /{cmd} <id>")
        print()
    elif cmd == "episodes":
        n = int(arg) if arg.isdigit() else 10
        eps = mem.recent_episodes(n)
        if not eps:
            ui.note("no past conversations yet")
        for e in eps:
            agents = ", ".join(json.loads(e["agents"] or "[]"))
            print(f"  {ui.SAND}#{e['id']:<4}{RESET} {datetime.fromtimestamp(e['ended']):%Y-%m-%d %H:%M}  "
                  f"{BOLD}{e['title']}{RESET} {DIM}({e['turns']} messages{', ' + agents if agents else ''}){RESET}")
            if e["summary"]:
                print(f"        {DIM}{e['summary']}{RESET}")
        print()
    elif cmd == "recall":
        if not arg:
            print("Usage: /recall <words>\n")
            return
        hits = mem.search(arg, 8, min_relevance=0.15)
        eps = mem.search_episodes(arg, 5)
        if not hits and not eps:
            ui.note("nothing comes to mind")
        for r, score, _rel in hits:
            print(f"  {ui.SAND}#{r['id']:<4}{RESET} {r['text']} {DIM}[{score:.2f}]{RESET}")
        for e, score, _rel in eps:
            print(f"  {ui.TEAL}ep {e['id']:<3}{RESET} {datetime.fromtimestamp(e['ended']):%Y-%m-%d} "
                  f"{BOLD}{e['title']}{RESET} {DIM}{e['summary']} [{score:.2f}]{RESET}")
        print()
    elif cmd == "revisit":
        e = mem.episode(int(arg.lstrip("#"))) if arg.lstrip("#").isdigit() else None
        if not e:
            ui.note("usage: /revisit <episode id> (see /episodes)")
        else:
            session.pinned_context.append({"date": datetime.fromtimestamp(e["ended"]).strftime("%Y-%m-%d"),
                                           "title": e["title"], "summary": e["summary"] or "(no summary)"})
            ui.note(f"brought back: {e['title']}")
        print()
    elif cmd == "memlog":
        n = int(arg) if arg.isdigit() else 15
        for row in reversed(mem.recent_log(n)):
            mid = f"#{row['memory_id']} " if row["memory_id"] else ""
            print(f"  {DIM}{datetime.fromtimestamp(row['time']):%m-%d %H:%M}{RESET} {ui.TEAL}{row['action']:<12}{RESET}"
                  f" {mid}{row['detail']}")
        print()
    elif cmd == "consolidate":
        with Spinner("tidying long-term memory"):
            rep = mem.consolidate()
        ui.note(f"{len(rep['archived'])} faded, {len(rep['merged'])} merged, {rep['embedded']} indexed by meaning")
        print()
    elif cmd == "export":
        path = Path(arg).expanduser() if arg else CONFIG_DIR / f"memory-export-{datetime.now():%Y%m%d-%H%M}.md"
        ui.note(f"exported to {mem.export_markdown(path)}")
        print()
    elif cmd == "wipe":
        answer = input("  Erase ALL memories and past-conversation summaries? Type 'wipe' to confirm: ").strip()
        if answer == "wipe":
            mem.wipe()
            ui.note("memory erased")
        else:
            ui.note("cancelled, nothing erased")
        print()


# ---------------------------------------------------------------------------
# Agents, notebooks, the collective tree and self-development
# ---------------------------------------------------------------------------

def show_agents(session):
    routing = "auto-routing" if session.agent_mode == "auto" else f"staying with {session.agent_mode}"
    ui.section(f"agents · {routing}")
    for a in session.agents.agents.values():
        spec = lens(a.name)
        here = f" {ORANGE}← current{RESET}" if a.name == session.agent.name else ""
        alias = f" {DIM}(@{', @'.join(a.aliases)}){RESET}" if a.aliases else ""
        print(f"\n  {ui.agent_name(a.name, a.color, a.icon)}{alias}{here}")
        print(f"    {ui.SAND}purpose{RESET}  {spec['purpose'] or a.description}")
        print(f"    {ui.SAND}skill{RESET}    {spec['skill']}")
        cats = "  ".join(f"{ui.c256(c[0])}■ {name}{RESET}" for name, c in spec["categories"].items())
        print(f"    {ui.SAND}notes{RESET}    {cats}")
        if a.traits:
            print(f"    {ui.SAND}traits{RESET}   " + ", ".join(
                f"{t} {'+' if v > 0 else '-'}{abs(v):.2f}" for t, v in a.traits.items()))
        techs = session.cortex.techniques_for(a.name) if session.cortex else []
        for t in techs:
            print(f"    {ui.SAND}practice{RESET} {t['detail'] or t['title']} {DIM}[{t['status']}]{RESET}")
    print()


def render_notebook(session, name, topics_per_branch=4, notes_per_topic=2):
    cx = session.cortex
    agent = session.agents.get(name)
    book = cx.notebook(name)
    color = agent.color if agent else 250
    print(ui.tree_line([], f"{ui.agent_name(name, color, agent.icon if agent else None)} "
                           f"{DIM}{lens(name)['skill']}{RESET}"))
    if not book:
        print(ui.tree_line([True], f"{DIM}(no notes yet){RESET}"))
        return
    cats = list(book.items())
    for ci, (cat, topics) in enumerate(cats):
        last_c = ci == len(cats) - 1
        tint = ui.c256(category_color(name, cat))
        node = cx.node("branch", name, cat)
        summary = f" {DIM}{node['summary']}{RESET}" if node and node["summary"] else ""
        print(ui.tree_line([last_c], f"{tint}■ {cat}{RESET}{summary}"))
        tlist = list(topics.items())[:topics_per_branch]
        for ti, (topic, notes) in enumerate(tlist):
            last_t = ti == len(tlist) - 1
            print(ui.tree_line([last_c, last_t], f"{tint}{topic}{RESET}"))
            shown = notes[:notes_per_topic]
            for ni, r in enumerate(shown):
                print(ui.tree_line([last_c, last_t, ni == len(shown) - 1],
                                   f"{r['text']} {DIM}x{r['count']} · {r['weight']:.2f}{RESET}"))


def render_tree(session, depth=2):
    cx = session.cortex
    root = cx.node("root")
    print(ui.tree_line([], f"{BOLD}{ORANGE}{ui.TRIDENT} Seahorse{RESET} {ui.SAND}collective understanding{RESET}"))
    print(ui.tree_line([False], f"{root['summary'] if root else DIM + '(not built yet: /dream)' + RESET}"))
    names = [n for n in session.agents.agents if cx.node("agent", n) or cx.notebook(n)]
    directions = cx.directions()
    for i, name in enumerate(names):
        last_a = i == len(names) - 1 and not directions
        agent = session.agents.get(name)
        node = cx.node("agent", name)
        summary = node["summary"] if node else f"{DIM}(notes not summarised yet){RESET}"
        print(ui.tree_line([last_a], f"{ui.agent_name(name, agent.color, agent.icon)} {DIM}·{RESET} {summary}"))
        if depth < 2:
            continue
        cats = [c for c in cx.notebook(name)]
        for ci, cat in enumerate(cats):
            b = cx.node("branch", name, cat)
            text = b["summary"] if b else f"{DIM}{len(cx.notebook(name)[cat])} topics, not summarised{RESET}"
            print(ui.tree_line([last_a, ci == len(cats) - 1],
                               f"{ui.c256(category_color(name, cat))}■ {cat}{RESET} {text}"))
            if depth >= 3:
                topics = list(cx.notebook(name)[cat])[:5]
                for ti, t in enumerate(topics):
                    print(ui.tree_line([last_a, ci == len(cats) - 1, ti == len(topics) - 1], f"{DIM}{t}{RESET}"))
    if directions:
        print(ui.tree_line([True], f"{BOLD}{ui.AQUA}directions{RESET}"))
        for di, d in enumerate(directions):
            print(ui.tree_line([True, di == len(directions) - 1], d))
    print()


IDEA_STATUS_COLORS = {"trial": "KELP", "adopted": "AQUA", "proposed": "SAND", "pending": "SAND",
                      "done": "TEAL", "dropped": "SEA"}


def show_ideas(session, show_all=False):
    cx = session.cortex
    rows = cx.ideas() if show_all else cx.ideas(("trial", "adopted", "proposed", "pending"))
    if not rows:
        ui.note("no ideas yet - they come from dreaming (/dream)")
        return
    for r in rows:
        color = getattr(ui, IDEA_STATUS_COLORS.get(r["status"], "SAND"))
        who = f"{session.paint_agent(r['agent'])} " if r["agent"] else ""
        print(f"  {ui.SAND}#{r['id']:<3}{RESET} {color}{r['status']:<9}{RESET} {ui.TEAL}{r['kind']:<9}{RESET} "
              f"{who}{r['title']}")
        if r["detail"] and r["detail"] != r["title"]:
            print(f"       {DIM}{r['detail']}{RESET}")
    ui.note("/adopt <id> to try or create one, /drop <id> to discard")


def adopt_idea(session, idea_id):
    cx = session.cortex
    idea = cx.idea(idea_id)
    if not idea:
        ui.note("no idea with that id")
        return
    if idea["kind"] in ("skill", "agent"):
        folder = session.skills.folder if idea["kind"] == "skill" else session.agents.folder
        example_path = folder / ("writing.md" if idea["kind"] == "skill" else "wernicke.md")
        example = example_path.read_text() if example_path.exists() else ""
        text = session.complete(cx.draft_prompt(idea, example[:2500]), system="You write configuration files.",
                                label=f"drafting a new {idea['kind']}")
        body = re.sub(r"^```\w*\n|```\s*$", "", (text or "").strip())
        m = re.search(r"(?m)^name:\s*([\w-]+)", body)
        if not body.startswith("---") or not m:
            ui.note("couldn't draft it (no model reachable, or the draft wasn't valid); try again later")
            return
        path = folder / f"{m.group(1).lower()}.md"
        if path.exists():
            ui.note(f"{path.name} already exists, so nothing was overwritten")
            return
        path.write_text(body + "\n", encoding="utf-8")
        if idea["kind"] == "skill":
            session.skills = SkillSet()
        else:
            session.agents = AgentSet()
        cx.adopt(idea_id)
        ui.note(f"created {path} - edit it any time; /{'skills' if idea['kind'] == 'skill' else 'agents'} to see it")
        return
    if idea["kind"] == "trait":
        cx.db.execute("UPDATE ideas SET status='pending' WHERE id=?", (idea_id,))
        cx.db.commit()
        for trait, old, new, _r in cx.apply_trait_ideas(session.persona):
            ui.note(f"{trait} target {old:.2f} → {new:.2f}")
        return
    row = cx.adopt(idea_id)
    ui.note(f"#{idea_id} is now {row['status']}" + (" - the agent will practise it" if row["kind"] == "technique" else ""))


CORTEX_COMMANDS = {"notes", "tree", "dream", "ideas", "adopt", "drop", "perceive"}


def cortex_command(session, cmd, arg):
    cx = session.cortex
    if cx is None:
        ui.note("the cortex isn't available")
        print()
        return
    if cmd == "notes":
        if arg:
            agent = session.agents.get(arg)
            if not agent:
                ui.note(f"usage: /notes [agent]. Agents: {', '.join(session.agents.agents)}")
            else:
                render_notebook(session, agent.name, topics_per_branch=8, notes_per_topic=4)
        else:
            for name in session.agents.agents:
                render_notebook(session, name, topics_per_branch=2, notes_per_topic=1)
                print()
    elif cmd == "tree":
        render_tree(session, int(arg) if arg.isdigit() else 2)
        return
    elif cmd == "dream":
        session.show_cortex_report({"dream": session.dream()})
    elif cmd == "ideas":
        show_ideas(session, show_all=(arg == "all"))
    elif cmd in ("adopt", "drop"):
        if not arg.lstrip("#").isdigit():
            ui.note(f"usage: /{cmd} <idea id> (see /ideas)")
        elif cmd == "adopt":
            adopt_idea(session, int(arg.lstrip("#")))
        else:
            row = cx.drop(int(arg.lstrip("#")))
            ui.note(f"dropped #{row['id']}: {row['title']}" if row else "no idea with that id")
    elif cmd == "perceive":
        if arg in ("on", "off"):
            session.show_perception = arg == "on"
        else:
            session.show_perception = not session.show_perception
        ui.note(f"perception display {'on' if session.show_perception else 'off'} (agents keep noticing either way)")
    print()


# ---------------------------------------------------------------------------
# Seahorse's profile of you
# ---------------------------------------------------------------------------

PROFILE_COMMANDS = {"profile", "agree", "disagree"}
LOCK = "⚿" if ui.UNICODE else "[p]"
SECTION_COLORS = {"thinking": 117, "communication": 141, "drive": 209, "working": 79, "emotional": 213,
                  "values": 180, "strengths": 114, "blind spots": 167}


def _dots(conf):
    filled = round(conf * 5)
    on, off = ("●", "○") if ui.UNICODE else ("#", ".")
    return f"{ui.AQUA}{on * filled}{RESET}{DIM}{off * (5 - filled)}{RESET}"


def show_profile(session):
    pf = session.profile
    rows = pf.opinions()
    take = pf.get_meta("honest_take")
    if not rows and not take:
        metrics = behaviour_metrics(CHATS_DIR_FOR_PROFILE)
        if pf.ready(metrics):
            ui.note("no portrait yet - it forms the next time Seahorse dreams, or run /profile update now")
        else:
            ui.note(f"no portrait yet - Seahorse needs about 8 of your messages first "
                    f"({metrics.get('user_messages', 0)} so far)")
        return
    last = pf.get_meta("last_update")
    ui.section(f"Seahorse's portrait of you · {pf.get_meta('updates', 0)} updates"
               + (f" · last {datetime.fromtimestamp(last):%Y-%m-%d}" if last else ""))
    print(f"  {DIM}Seahorse's own opinions from your conversations: informal and evidence-based, not a clinical "
          f"assessment.{RESET}")
    if take:
        print(f"\n  {BOLD}{ui.FOAM}Honest take{RESET}\n  {take}")
    for sec, title in PROFILE_SECTIONS.items():
        sec_rows = pf.opinions(sec)
        if not sec_rows:
            continue
        print(f"\n  {BOLD}{ui.c256(SECTION_COLORS.get(sec, 250))}■ {title}{RESET}")
        for r in sec_rows:
            v = {"agree": f" {ui.KELP}✓ you agree{RESET}", "disagree": f" {ORANGE}✗ you disagree{RESET}"}.get(r["verdict"], "")
            n_ev = len(json.loads(r["evidence"] or "[]"))
            print(f"    {ui.SAND}#{r['id']:<3}{RESET} {_dots(r['confidence'])} {r['text']} {DIM}({n_ev} evidence){RESET}{v}")
    enabled = pf.domains()
    if enabled:
        print(f"\n  {BOLD}{ui.CORAL}{LOCK} Personal{RESET} {DIM}(only from what you've said yourself){RESET}")
        guidance = pf.get_meta("personal_guidance", {})
        for d in enabled:
            rows = pf.opinions(d)
            print(f"    {BOLD}{ui.SAND}{PERSONAL_DOMAINS[d][0]}{RESET}")
            if not rows:
                print(f"      {DIM}nothing yet - Seahorse waits until you talk about it{RESET}")
            for r in rows:
                v = {"agree": f" {ui.KELP}✓{RESET}", "disagree": f" {ORANGE}✗{RESET}"}.get(r["verdict"], "")
                print(f"      {ui.SAND}#{r['id']:<3}{RESET} {_dots(r['confidence'])} {r['text']}{v}")
            if guidance.get(d):
                print(f"      {ui.TEAL}›{RESET} {DIM}{guidance[d]}{RESET}")
    temp = pf.temperament()
    if temp:
        print(f"\n  {BOLD}{ui.FOAM}Temperament{RESET} {DIM}(informal tendencies, not a test){RESET}")
        for t in temp:
            filled = round(t["score"] * 20)
            bar = ("█" if ui.UNICODE else "#") * filled + ("·" if ui.UNICODE else ".") * (20 - filled)
            print(f"    {ui.SAND}{t['name']:<21}{RESET} {ui.TEAL}{bar}{RESET} {t['score']:.2f} "
                  f"{DIM}confidence {t['confidence']:.2f} - {t['reason']}{RESET}")
    rules = pf.get_meta("guidance", [])
    if rules:
        print(f"\n  {BOLD}{ui.FOAM}How Seahorse works with you{RESET}")
        for r in rules:
            print(f"    {ui.TEAL}›{RESET} {r}")
    note = pf.get_meta("wellbeing_note")
    if note:
        print(f"\n  {BOLD}{ui.CORAL}A gentle note{RESET}\n  {note}")
    m = behaviour_metrics(CHATS_DIR_FOR_PROFILE)
    if m.get("chats"):
        when = ", ".join(f"{k} {v}" for k, v in m["when_chats_start"].items())
        print(f"\n  {DIM}measured: {m['chats']} chats, {m['user_messages']} messages, median "
              f"{m['median_words_per_message']} words, {int(m['requests_share'] * 100)}% requests, "
              f"{int(m['questions_share'] * 100)}% questions, {int(m['corrections_share'] * 100)}% corrections; "
              f"chats start: {when}{RESET}")
    if not pf.enabled:
        ui.note("profiling is paused (/profile on to resume)")
    print(f"\n  {DIM}/profile why <id> · /agree <id> · /disagree <id> [why] · /profile drop <id> · "
          f"/profile history · /profile export{RESET}")


def profile_command(session, cmd, arg):
    pf = session.profile
    if pf is None:
        ui.note("the profile isn't available")
        print()
        return
    if cmd in ("agree", "disagree"):
        parts = arg.split(None, 1)
        if not parts or not parts[0].lstrip("#").isdigit():
            ui.note(f"usage: /{cmd} <opinion id>" + (" [why]" if cmd == "disagree" else ""))
        else:
            row = pf.verdict(int(parts[0].lstrip("#")), cmd, parts[1] if len(parts) > 1 else "")
            if not row:
                ui.note("no opinion with that id")
            elif cmd == "agree":
                ui.note(f"noted - Seahorse is surer of #{row['id']} now ({row['confidence']:.2f})")
            else:
                ui.note(f"noted - #{row['id']} drops to {row['confidence']:.2f}"
                        + (" and is retired" if row["status"] == "retired" else
                           "; it won't climb back without new evidence"))
        print()
        return
    sub, _, rest = arg.partition(" ")
    rest = rest.strip()
    if not sub:
        show_profile(session)
    elif sub == "update":
        if not pf.enabled:
            ui.note("profiling is paused (/profile on to resume)")
        else:
            session.show_profile_report(session.update_profile())
    elif sub == "why":
        row = pf.opinion(int(rest.lstrip("#"))) if rest.lstrip("#").isdigit() else None
        if not row:
            ui.note("usage: /profile why <id>")
        else:
            print(f"  {ui.SAND}#{row['id']}{RESET} {_dots(row['confidence'])} {row['text']}")
            print(f"  {DIM}{row['section']} · confidence {row['confidence']:.2f} · revised {row['revisions']}x · "
                  f"since {datetime.fromtimestamp(row['created']):%Y-%m-%d}{RESET}")
            for e in json.loads(row["evidence"] or "[]"):
                print(f"    {ui.TEAL}›{RESET} {e}")
            if row["verdict"]:
                print(f"  {DIM}you {row['verdict']}{': ' + row['verdict_note'] if row['verdict_note'] else ''}{RESET}")
    elif sub == "drop":
        row = pf.retire(int(rest.lstrip("#"))) if rest.lstrip("#").isdigit() else None
        ui.note(f"dropped #{row['id']}: {row['text']}" if row else "usage: /profile drop <id>")
    elif sub == "history":
        for h in reversed(pf.history(25)):
            oid = f"#{h['opinion_id']} " if h["opinion_id"] else ""
            print(f"  {DIM}{datetime.fromtimestamp(h['time']):%m-%d %H:%M}{RESET} {ui.TEAL}{h['change']:<13}{RESET} "
                  f"{oid}{h['detail']}")
    elif sub == "export":
        include = rest.startswith("all")
        rest = rest[3:].strip() if include else rest
        path = Path(rest).expanduser() if rest else CONFIG_DIR / f"profile-{datetime.now():%Y%m%d-%H%M}.md"
        ui.note(f"exported to {pf.export_markdown(path, include_personal=include)}"
                + ("" if include else " (personal domains left out; /profile export all to include them)"))
    elif sub == "domains":
        on = set(pf.domains())
        for d, (title, _p) in PERSONAL_DOMAINS.items():
            state = f"{ui.KELP}on {RESET}" if d in on else f"{DIM}off{RESET}"
            print(f"  {state} {ui.SAND}{d:<10}{RESET} {title} {DIM}({len(pf.opinions(d))} opinions){RESET}")
        ui.note("/profile domain <name> on|off|wipe - opinions come only from what you say about yourself")
    elif sub == "domain":
        bits = rest.split()
        if len(bits) != 2 or bits[0] not in PERSONAL_DOMAINS or bits[1] not in ("on", "off", "wipe"):
            ui.note(f"usage: /profile domain <{'|'.join(PERSONAL_DOMAINS)}> <on|off|wipe>")
        elif bits[1] == "wipe":
            ui.note(f"erased {pf.wipe_domain(bits[0])} {bits[0]} opinion(s)")
        else:
            pf.set_domain(bits[0], bits[1] == "on")
            ui.note(f"{bits[0]}: {'on - Seahorse will form opinions from what you say about it' if bits[1] == 'on' else 'off - existing opinions are kept but hidden and unused (/profile domain ' + bits[0] + ' wipe to erase)'}")
    elif sub in ("on", "off"):
        pf.set_meta("enabled", sub == "on")
        ui.note("profiling resumed" if sub == "on" else
                "profiling paused - the existing portrait stays but won't change or be used")
    elif sub == "wipe":
        if input("  Erase Seahorse's whole profile of you? Type 'wipe' to confirm: ").strip() == "wipe":
            pf.wipe()
            ui.note("profile erased")
        else:
            ui.note("cancelled, nothing erased")
    else:
        ui.note("usage: /profile [update|why <id>|drop <id>|history|export [all]|domains|domain <name> on|off|wipe|"
                "on|off|wipe]")
    print()


# ---------------------------------------------------------------------------
# Look and starting state
# ---------------------------------------------------------------------------

LOOK_COMMANDS = {"theme", "logo", "config", "welcome"}


def welcome(session):
    """First-run introduction."""
    ui.logo(session.config.get("logo", "full"), "your own AI, growing with you")
    print(f"\n  {BOLD}{ui.FOAM}Welcome to Seahorse.{RESET} Ten parts of one mind will work with you: eight named")
    print("  for brain regions, plus Doc and Fiery Black, his left and right lobes. All of them read every message")
    print("  in their own way, keep their own notes, and grow together as you talk.\n")
    for a in session.agents.agents.values():
        pad = " " * max(1, 13 - len(a.name))
        print(f"   {ui.agent_name(a.name, a.color, a.icon)}{pad}{lens(a.name)['purpose'] or a.description}")
    print()
    ui.panel([
        ("talk", "just type; the best agent answers (or @broca, @parietal ...)"),
        ("remember", 'say "remember that ..." - Seahorse also learns on its own'),
        ("look", "/theme, /logo and /config change how Seahorse looks and starts"),
        ("explore", "/agents, /notes, /tree, /ideas, /profile, /memory, /traits, /help"),
    ], title="getting started")


def look_command(session, cmd, arg):
    cfg = session.config
    if cmd == "theme":
        if arg in ui.THEMES:
            cfg["theme"] = arg
            ui.save_config(cfg)
            ui.apply_config(cfg)
            refresh_palette()
            ui.logo("minimal", f"theme: {arg}")
        else:
            for name in ui.THEMES:
                mark = f" {ORANGE}← current{RESET}" if name == ui.THEME else ""
                print(f"  {ui.theme_swatch(name)}{mark}")
            ui.note("/theme <name> to switch (saved as your default)")
    elif cmd == "logo":
        styles = ["full", "compact", "minimal", "trident", "none"]
        if arg in styles:
            cfg["logo"] = arg
            ui.save_config(cfg)
            ui.logo(arg, "your own AI, growing with you")
            ui.note(f"logo set to {arg} (shown at start)")
        else:
            for style in styles[:-1]:
                ui.note(style)
                ui.logo(style, "your own AI, growing with you")
            ui.note("/logo <full|compact|minimal|trident|none> to choose")
    elif cmd == "config":
        parts = arg.split(None, 1)
        if len(parts) == 2 and parts[0] in ui.DEFAULTS:
            key, value = parts
            try:
                cfg[key] = ui.coerce(key, value) if key != "name" else value.strip()
            except ValueError as e:
                ui.note(f"{key}: {e}")
                print()
                return
            ui.save_config(cfg)
            ui.apply_config(cfg)
            refresh_palette()
            if key == "show_perception":
                session.show_perception = cfg[key]
            ui.note(f"{key} = {cfg[key]} (saved)")
        elif parts and parts[0] == "reset":
            cfg.clear()
            cfg.update(ui.DEFAULTS)
            ui.save_config(cfg)
            ui.apply_config(cfg)
            refresh_palette()
            ui.note("settings reset to the defaults")
        else:
            ui.panel([(k, f"{cfg.get(k)!s:<10} {DIM}default {v!s}{RESET}") for k, v in ui.DEFAULTS.items()],
                     title="starting state · ~/.seahorse/config.json")
            ui.note("/config <setting> <value> to change, /config reset for defaults")
    elif cmd == "welcome":
        welcome(session)
        return
    print()


def agency_command(session, cmd, arg):
    ag = session.agency
    if ag is None:
        ui.note("the Agency isn't available")
        print()
        return
    if cmd == "journal":
        kinds = ("lesson",) if arg == "lessons" else ("entry", "lesson", "mirror") if arg == "all" else ("entry",)
        n = int(arg) if arg.isdigit() else 5
        rows = ag.entries(n if arg.isdigit() else (30 if arg in ("all", "lessons") else 5), kinds)
        if not rows:
            ui.note("no journal entries yet - he writes one at the end of each chat")
        for r in reversed(rows):
            a = AGENCY["diarist" if r["kind"] == "entry" else "conscience" if r["kind"] == "lesson" else "mirror"]
            print(f"\n  {BOLD}{ui.c256(a['color'])}{a['icon']} {datetime.fromtimestamp(r['time']):%Y-%m-%d %H:%M} "
                  f"{r['kind']}{RESET}")
            for line in r["text"].splitlines():
                print(f"  {DIM}{line}{RESET}")
        ui.note("/journal [n] · /journal lessons · /journal all")
    elif cmd == "self":
        model = ag.get("self_model")
        m = AGENCY["mirror"]
        if not model:
            ui.note("his sense of self is still forming - it appears after his first journal entry")
        else:
            print(f"\n  {BOLD}{ui.c256(m['color'])}{m['icon']} who he's becoming{RESET}\n  {model}")
            for i in ag.get("intentions", []):
                print(f"  {ui.TEAL}›{RESET} {i}")
    elif cmd == "conscience":
        if arg in ("on", "off"):
            ag.set("conscience", arg == "on")
        on = ag.conscience_on()
        ui.note(f"conscience {'on - he re-reads replies of ' + str(CONSCIENCE_MIN_WORDS) + '+ words' if on else 'off (faster)'}"
                " · /conscience on|off")
    elif cmd == "magic":
        if arg in FREQUENCY:
            ag.set("magic", arg)
            ui.note(f"surprises: {arg}" + ("" if arg == "off" else " (never when you seem stressed or busy)"))
        elif arg == "reveal":
            r = ag.reveal()
            ui.note(f"answer: {r['answer'] or '(no answer recorded)'}" if r else "no riddle yet - /magic riddle")
        elif arg == "history":
            for g in reversed(ag.gifts(10)):
                d = DEPARTMENTS.get(g["dept"], DEPARTMENTS["gift"])
                print(f"  {ui.c256(d['color'])}{d['icon']}{RESET} {DIM}{datetime.fromtimestamp(g['time']):%m-%d}{RESET} "
                      f"{g['text'][:140]}")
        else:
            dept = {"story": "story", "tale": "story", "riddle": "riddle", "puzzle": "riddle", "idea": "idea",
                    "gift": "gift", "fact": "gift", "wonder": "gift"}.get(arg)
            if arg and not dept:
                ui.note("/magic [story|riddle|idea|gift|reveal|history|often|sometimes|rarely|off]")
            else:
                recent = "\n".join(f"{m['role']}: {m['content'][:400]}" for m in session.messages[-4:])
                got = session.conjure(dept, recent)
                if got:
                    session.show_magic(*got)
                else:
                    ui.note("the Bureau couldn't reach a model just now")
                return
        ui.note(f"surprises {ag.frequency()} · /magic story|riddle|idea|gift · /magic often|sometimes|rarely|off")
    print()


def lobes_command(session, arg):
    cfg = session.config
    if arg in ("on", "off"):
        cfg["lobes"] = arg == "on"
        ui.save_config(cfg)
        ui.note("lobes on - Doc and Fiery Black read substantial messages before Seahorse answers" if arg == "on"
                else "lobes off - Seahorse answers without consulting them (faster)")
    elif arg in LOBE_BALANCE:
        cfg["lobe_balance"] = arg
        ui.save_config(cfg)
        ui.note(f"balance: {arg} - {LOBE_BALANCE[arg]}")
    elif arg == "stats":
        print(lobes.describe_stats())
    elif arg == "stats reset":
        lobes.reset_stats()
        ui.note("vote stats cleared")
    elif arg.startswith(("words ", "timeout ", "margin ")):
        key, _, val = arg.partition(" ")
        conf = {"words": ("lobe_min_words", int, 1, 500), "timeout": ("lobe_timeout", float, 3, 600),
                "margin": ("lobe_margin", float, 0.0, 2.0)}[key]
        try:
            cfg[conf[0]] = max(conf[2], min(conf[3], conf[1](val)))
            ui.save_config(cfg)
            ui.note(f"{key} set to {cfg[conf[0]]}")
        except ValueError:
            ui.note(f"/lobes {key} <number>")
    elif arg in ("parallel on", "parallel off"):
        cfg["lobe_parallel"] = arg.endswith("on")
        ui.save_config(cfg)
        ui.note("the lobes vote at the same time" if cfg["lobe_parallel"] else "the lobes vote one after the other")
    else:
        left, right = session.agents.get(LOBES["left"]["agent"]), session.agents.get(LOBES["right"]["agent"])
        core = session.agents.default
        state = "on" if cfg.get("lobes", True) is not False else "off"
        print()
        print(f"     {ui.agent_name(left.name, left.color, left.icon) if left else 'doc'}   "
              f"{DIM}──{RESET} {ui.agent_name(core.name, core.color, core.icon)} {DIM}──{RESET}   "
              f"{ui.agent_name(right.name, right.color, right.icon) if right else 'fiery-black'}")
        print(f"     {DIM}west · left lobe   the core           east · right lobe{RESET}")
        print(f"     {DIM}blue donkey        stays balanced     red elephant{RESET}")
        print(f"     {DIM}Democrat           between them       Republican{RESET}")
        print(f"     {DIM}analysis, facts    joins both         intuition, big picture,{RESET}")
        print(f"     {DIM}language, logic    into one answer    tone, vigilance{RESET}\n")
        words = cfg.get("lobe_min_words") or LOBE_MIN_WORDS
        ui.note(f"lobes {state} · balance {cfg.get('lobe_balance', 'even')} · they vote on messages of "
                f"{words}+ words that Seahorse himself answers, both at once, and the Judge breaks close splits")
        print(lobes.describe_stats())
        ui.note("/lobes on|off · left|even|right · stats · words <n> · timeout <s> · margin <0-2> · parallel on|off")
    print()


def brain_command(session, arg):
    """Show or switch an agent's sub-agent brain."""
    parts = arg.split()
    agents = [a for a in session.agents.agents.values() if a.sub_brains]
    if len(parts) == 2 and session.agents.get(parts[0]) and parts[1] in ("on", "off"):
        agent = session.agents.get(parts[0])
        if not agent.sub_brains:
            ui.note(f"{agent.name} doesn't have a sub-agent brain")
        else:
            session.config.setdefault("sub_brains", {})[agent.name] = parts[1] == "on"
            ui.save_config(session.config)
            ui.note(f"{agent.name}'s brain {'on - his sub-agents work first' if parts[1] == 'on' else 'off - he answers directly (faster)'}")
    else:
        for a in agents:
            state = "on" if session.sub_brains_on(a) else "off"
            print(f"\n  {ui.agent_name(a.name, a.color, a.icon)} {DIM}brain {state}{RESET}")
            for i, sub in enumerate(a.sub_brains):
                last = i == len(a.sub_brains) - 1
                print(ui.tree_line([last], f"{BOLD}{ui.c256(sub['color'])}{sub['icon']} {sub['name']}{RESET} "
                                           f"{DIM}{sub['job']}{RESET}"))
        print()
        ui.note(f"they work first on messages of {SUB_BRAIN_MIN_WORDS}+ words · /brain <agent> on|off")
    print()


FINETUNE_BACKGROUND = {"prepare", "distill", "train", "eval"}


def finetune_command(session, arg):
    """Run fine-tuning steps; long ones go to the background so chatting continues."""
    import finetune as ft
    parts = arg.split()
    sub = parts[0].lower() if parts else "status"
    sub = {"extract": "prepare", "build": "train"}.get(sub, sub)   # the Ultimate model's steps
    if sub in ("plan", "outline"):
        ui.section("the Ultimate model")
        print("  " + (ft.plan() if sub == "plan" else ft.outline_text()).replace("\n", "\n  "))
    elif sub in ("use", "revert"):
        try:
            ui.note(ft.use(sub == "use"))
        except SystemExit as e:
            ui.note(str(e))
        session.persona.state = type(session.persona).load().state  # pick up the change
        if sub == "use":
            session.local.model = MODEL_NAME
    elif sub in FINETUNE_BACKGROUND:
        running = ft.read_status().get("stage") in ("training", "distilling", "evaluating", "fusing", "importing")
        pid_file = ft.FT / "worker.pid"
        alive = False
        if running and pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), 0)
                alive = True
            except (OSError, ValueError):
                alive = False
        if alive:
            ui.note("a fine-tuning step is already running - /finetune to see its progress")
        elif sub == "prepare":
            summary = ft.prepare(quiet=True)
            ui.note(f"dataset ready: {summary['train']} training and {summary['valid']} held-out examples "
                    f"from {summary['chats']} chats · average reply worth "
                    f"{ft.change.dollars(summary.get('average_worth', 0))} - /finetune outline")
            if not summary["enough"]:
                ui.note(f"aim for {ft.MIN_EXAMPLES}+ training examples before training - keep chatting")
        else:
            ft.FT.mkdir(parents=True, exist_ok=True)
            logf = open(ft.FT / f"{sub}.log", "w")
            cmd = [sys.executable, str(Path(__file__).resolve().parent / "finetune.py"), sub] + parts[1:]
            kwargs = {"start_new_session": True} if os.name != "nt" else {"creationflags": 0x00000200}
            proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, **kwargs)
            pid_file.write_text(str(proc.pid))
            ui.note(f"{sub} started in the background (log: {ft.FT / (sub + '.log')}) - /finetune shows progress")
    else:
        ui.section("fine-tuning")
        print("  " + ft.status_text().replace("\n", "\n  "))
        ui.note("the Ultimate model: /finetune plan · extract · outline · build   then eval · use · revert "
                "(also distill [--max N])")
    print()


def character_command(session, arg):
    c = session.persona.character
    if arg in ("on", "off"):
        c["enabled"] = arg == "on"
        session.persona.save()
        ui.note("character on - Seahorse is himself again" if c["enabled"] else
                "character off - Seahorse speaks plainly (/character on to bring him back)")
    elif arg in ("light", "medium", "strong"):
        c["strength"] = arg
        c["enabled"] = True
        session.persona.save()
        ui.note(f"accent strength: {arg}")
    elif arg == "reset":
        from personality import DEFAULT_CHARACTER
        session.persona.state["character"] = json.loads(json.dumps(DEFAULT_CHARACTER))
        session.persona.save()
        ui.note("character reset to the original")
    else:
        state = f"{'on' if c.get('enabled') else 'off'}, {c.get('strength', 'medium')} accent"
        ui.section(f"character · {c.get('epithet', 'Seahorse')} · {state}")
        if c.get("tale"):
            print(f"\n  {BOLD}{ui.CORAL}the tale{RESET}")
            for line in c["tale"].splitlines():
                print(f"  {ui.SAND}{ui.ITALIC}{line}{RESET}")
        for title, key in (("story", "backstory"), ("voice", "voice"), ("spirit", "spirit")):
            print(f"\n  {BOLD}{ui.CORAL}{title}{RESET}\n  {c[key]}")
        if c.get("mannerisms"):
            print(f"\n  {BOLD}{ui.CORAL}mannerisms{RESET}")
            for m in c["mannerisms"]:
                print(f"    {ui.TEAL}›{RESET} {m}")
        print(f"\n  {BOLD}{ui.CORAL}keeping it useful{RESET}")
        for r in c["rules"]:
            print(f"    {ui.TEAL}›{RESET} {r}")
        ui.note("/character on|off · /character light|medium|strong · /character reset · "
                "edit the 'character' section of ~/.seahorse/personality.json to rewrite him")
    session.persona.build_ollama(extra=session.extra)
    print()


def handle_command(session, line):
    cmd, _, arg = line[1:].partition(" ")
    arg = arg.strip()
    if cmd in ("quit", "exit", "q"):
        raise EOFError
    elif cmd == "help":
        print(HELP + "\n")
    elif cmd == "mode":
        if arg in ("auto", "claude", "local"):
            session.mode = arg
            ui.note(f"mode -> {arg}"); print()
        else:
            print("Usage: /mode auto|claude|local\n")
    elif cmd == "model":
        if not arg:
            print("Usage: /model <name>\n")
        elif session.mode == "local":
            session.local.model = arg
            ui.note(f"local model -> {arg}"); print()
        else:
            session.claude.model = arg
            ui.note(f"Claude model -> {arg}"); print()
    elif cmd == "local-model":
        if arg:
            session.local.model = arg
            ui.note(f"local model -> {arg}"); print()
    elif cmd == "models":
        models = session.local.installed_models()
        print(("  " + "\n  ".join(models)) if models else "  (none found - is Ollama running?)")
        print()
    elif cmd == "system":
        if arg == "reset":
            session.system_override = None
            ui.note(f"back to Seahorse's own personality"); print()
        elif arg:
            session.system_override = arg
            ui.note(f"system prompt overridden for this chat"); print()
        else:
            print(session.system + "\n")
    elif cmd == "agents":
        show_agents(session)
    elif cmd in CORTEX_COMMANDS:
        cortex_command(session, cmd, arg)
    elif cmd in PROFILE_COMMANDS:
        profile_command(session, cmd, arg)
    elif cmd == "character":
        character_command(session, arg)
    elif cmd == "build":
        build_command(session, arg)
    elif cmd == "finetune":
        finetune_command(session, arg)
    elif cmd in ("orez", "undo-pay") or (cmd in ("zero", "pay") and arg.strip().lower() in ("orez", "undo", "reverse")):
        lines = treasury.orez()
        ui.note("OREZ - ZERO in reverse: " + " · ".join(lines) if lines else "nothing to run back - no Treasurer move yet")
        print()
    elif cmd in ("spine", "sequence", "sequencer"):
        print(treasury.spine_text(full=arg.strip().lower() == "full"))
        print()
    elif cmd in ("zero", "cipher", "cypher", "mdas"):
        if arg.strip():
            handle_command(session, "/pay " + arg.strip())
        else:
            print("\n".join(change.zero_key()))
            print("    e.g. /zero Z x1.1 broca · /zero E $1.00 all · /zero R judge 3 quarters · /zero O broca a dime\n")
    elif cmd in ("board", "governance", "gov"):
        board_command(session, arg)
    elif cmd == "change":
        import finetune as ft
        ui.section("the change")
        print("  whole value $1.00 · quarter $0.25 · dime $0.10 · nickel $0.05 · penny $0.01")
        print("  A reply starts at two quarters; praise makes it a whole value, building on it earns a dime, letting it stand a")
        print("  nickel; scrapping it costs a dime, a correction a quarter, asking again the whole half.\n")
        print(ft.outline_text() if ft.WORTH.exists() else "  Nothing priced yet - /finetune extract prices every reply.")
    elif cmd == "brain":
        brain_command(session, arg)
    elif cmd == "lobes":
        lobes_command(session, arg)
    elif cmd == "crew":
        crew_command(session, arg)
    elif cmd == "council":
        council_command(session, arg)
    elif cmd in TREASURY_COMMANDS:
        cmd = TREASURY_COMMANDS[cmd]
        treasury_command(session, cmd, arg)
    elif cmd == "units":
        import units as U
        m = re.match(r"^\s*(-?[\d.]+(?:e-?\d+)?)\s+(.+?)\s+(?:to|in|->)\s+(.+?)\s*$", arg) or \
            re.match(r"^\s*(-?[\d.]+(?:e-?\d+)?)\s+(\S+)\s+(\S+)\s*$", arg)
        if arg.startswith("list") or not arg:
            cat = arg[4:].strip()
            for line in U.list_units(cat or None):
                print(f"  {line}")
            ui.note(f"{U.count()} unit names in {len(U.categories())} categories, plus every SI and binary prefix · "
                    f"/units list <category> · /units 5 mi to km")
        elif m:
            try:
                print(f"  {ui.KELP}={RESET} {U.explain(float(m.group(1)), m.group(2), m.group(3))}")
            except (U.UnitError, ValueError) as e:
                ui.note(str(e))
        else:
            ui.note("usage: /units 5 mi to km · /units 98.6 degF degC · /units list [category]")
        print()
    elif cmd == "judge" and arg in ("on", "off", ""):
        if arg:
            session.config["judge"] = arg == "on"
            ui.save_config(session.config)
        on = session.config.get("judge", True) is not False
        ui.note(f"the Judge {'rules between the lobes' if on else 'stays out of the lobes (faster)'} · "
                f"@judge for a verdict · /judge on|off")
        print()
    elif cmd in ("journal", "self", "conscience", "magic"):
        agency_command(session, cmd, arg)
    elif cmd == "router":
        if arg == "reset":
            session.agents.router.reset()
            ui.note("routing model reset - it will learn again from the agents you pick")
        else:
            ui.section("learned routing")
            print(session.agents.router.describe())
            ui.note("/router reset to start over")
        print()
    elif cmd == "persona":
        persona_command(session, arg)
    elif cmd in LOOK_COMMANDS:
        look_command(session, cmd, arg)
    elif cmd == "agent":
        if arg == "auto":
            session.agent_mode = "auto"
            ui.note(f"routing each message to the best agent"); print()
        elif session.agents.get(arg):
            session.agent = session.agents.get(arg)
            session.agent_mode = session.agent.name
            ui.note(f"now talking to {ui.agent_name(session.agent.name, session.agent.color, session.agent.icon)}{DIM} "
                    f"(/agent auto to switch back)"); print()
        else:
            print(f"Usage: /agent <name>|auto. Agents: {', '.join(session.agents.agents)}\n")
    elif cmd == "team":
        if arg:
            session.team(arg)
        else:
            print("Usage: /team <task>\n")
    elif cmd == "skills":
        print(session.skills.describe(session.active_skills) + "\n")
    elif cmd == "skill":
        parts = arg.split()
        skill = session.skills.get(parts[0]) if parts else None
        if not skill or len(parts) != 2 or parts[1] not in ("on", "off", "auto"):
            print(f"Usage: /skill <name> on|off|auto. Skills: {', '.join(session.skills.skills)}\n")
        else:
            skill.set_mode(parts[1])
            ui.note(f"{skill.name} -> {parts[1]}"); print()
    elif cmd == "calc":
        if arg:
            for r in calculate([arg]):
                print(f"  {r}")
            print()
        else:
            print("Usage: /calc <expression>\n")
    elif cmd == "traits":
        agent = session.agents.get(arg) if arg else None
        if arg and not agent:
            print(f"Usage: /traits [agent]. Agents: {', '.join(session.agents.agents)}\n")
        else:
            print(session.persona.describe(agent.traits if agent else None, agent.name if agent else None) + "\n")
    elif cmd in ("more", "less"):
        name = session.persona.find_trait(arg) if arg else None
        if not name:
            print(f"Usage: /{cmd} <trait>. Traits: {', '.join(session.persona.traits)}\n")
        else:
            old, new = session.persona.nudge(name, 1 if cmd == "more" else -1)
            session.apply_persona()
            ui.note(f"{name}: {old:.2f} → {new:.2f}"); print()
    elif cmd == "target":
        parts = arg.split()
        name = session.persona.find_trait(parts[0]) if parts else None
        try:
            value = float(parts[1])
        except (IndexError, ValueError):
            value = None
        if not name or value is None:
            print("Usage: /target <trait> <0-1>\n")
        else:
            session.persona.set_target(name, value)
            ui.note(f"{name} will now grow toward {value:.2f}"); print()
    elif cmd == "newtrait":
        bits = [b.strip() for b in arg.split("|")]
        if len(bits) != 3 or not all(bits):
            print("Usage: /newtrait <name> | <how it acts when low> | <how it acts when high>\n")
        else:
            session.persona.add_trait(bits[0].lower().replace(" ", "_"), bits[1], bits[2])
            ui.note(f"added trait {bits[0]} (starts at 0.50, grows toward 0.70)"); print()
    elif cmd == "reflect":
        session.grow()
    elif cmd in MEMORY_COMMANDS:
        memory_command(session, cmd, arg)
    elif cmd == "rollback":
        snap = session.persona.rollback()
        session.apply_persona()
        print(f"{DIM}rolled back the change from {snap['time']} ({snap['reason']}){RESET}\n"
              if snap else "Nothing to roll back.\n")
    elif cmd == "modelfile":
        ui.note(f"{session.persona.build_ollama(extra=session.extra)[1]}"); print()
    elif cmd == "clear":
        session.messages = []
        ui.note(f"conversation cleared"); print()
    elif cmd == "save":
        ui.note(f"saved to {session.save()}"); print()
    elif cmd == "load":
        try:
            session.load(arg)
            ui.note(f"loaded {len(session.messages)} messages"); print()
        except Exception as e:
            print(f"Couldn't load: {e}\n")
    elif cmd == "status":
        status(session)
    else:
        print(f"Unknown command /{cmd}. Try /help\n")


def load_extra_instructions():
    """Optional standing instructions from ~/.seahorse/system_prompt.txt, added to the personality."""
    try:
        return SYSTEM_PROMPT_FILE.read_text().strip()
    except OSError:
        return ""


TREASURY_COMMANDS = {c: c for c in ("treasury", "law", "laws", "budget", "trident", "trench", "locker", "compass",
                                     "pockets", "quarters", "pay")}
TREASURY_COMMANDS.update(wreck="law", wrecks="laws", reef="laws", rcso="laws", dollar="budget", marlin="budget",
                         goal="budget", goals="budget", undertow="trench", core="locker", davy="locker", news="compass",
                         oil="pockets", reserves="pockets", payroll="pay", purse="pay", purses="pay", wages="pay", quarter="quarters", seasons="quarters", horsemen="quarters")


BOARD_SUBS = {   # /board <sub> -> the command it runs
    "seats": "council seats", "council": "council", "steps": "council steps", "approval": "council approval",
    "laws": "laws", "reef": "laws", "law": "law", "bottle": "law", "repeal": "law repeal", "treasury": "treasury",
    "pay": "pay", "purses": "pay", "budget": "budget", "goal": "budget add", "quarters": "quarters",
    "horsemen": "quarters", "crew": "crew", "lobes": "lobes", "trident": "trident", "change": "change",
}


def board_text(session):
    """The governance board on one page: who rules, the reef, the purse, the season, the council."""
    cfg = session.config
    seats = cfg.get("council_seats")
    order = council.seating(session.agents.agents, seats)
    threshold = int(cfg.get("law_threshold", treasury.DEFAULTS["law_threshold"]))
    data = treasury._load()
    _key, (season, _m, rider, horse, _c) = treasury.quarter_of()
    riders = treasury._riders()
    lines = ["  ⚖ The governance board - Bamba's crew, governing themselves under the RCSO.", "",
             "  The high council (the four horsemen):"]
    for q in ("Spring", "Summer", "Fall", "Winter"):
        m = riders.get(q)
        if m:
            h = m["horseman"]
            mark = "▸" if q == season else " "
            lines.append(f"   {mark} {h['rider']:<9} {m['name']:<11} {q:<7} at {h['station']}")
    lines += ["", "  The council seats:"] + council.seat_chart(seats)[:2]
    ok, _broken = treasury.verify()
    lines += ["", f"  The reef (RCSO) - a bottle needs {threshold} of {treasury.GALLEON} ayes · the stone is "
                  f"{'sealed and intact' if ok else 'BROKEN - carving is stopped'}:"]
    row = []
    for chair, name in treasury.BOARDS.items():
        n = len(treasury.laws(chair))
        row.append(f"{name} {n}/{treasury.PER_BOARD}{' ◆' if n >= treasury.PER_BOARD else ''}")
    lines += ["    " + " · ".join(row[i:i + 3]) for i in range(0, len(row), 3)]
    purses = data.get("purses", {})
    top = sorted(purses.items(), key=lambda kv: -kv[1]["cents"])[:3]
    lines += ["", f"  The purse - paid out {change.dollars(sum(p['cents'] for p in purses.values()))}"
                  + (" · richest: " + ", ".join(f"{a} {change.dollars(p['cents'])}" for a, p in top) if top else ""),
              f"  The season - {season}, {rider} on {horse}"
              + (f" ({riders[season]['name']})" if season in riders else ""),
              f"  Goals (the marlin) - {len(data['goals'])} · bottles ashore on Atlantizz {len(data['failed'])}",
              "", "  /board <" + " | ".join(dict.fromkeys(BOARD_SUBS)) + "> [...]"]
    return "\n".join(lines)


def board_command(session, arg):
    """/board - the governance board; /board <sub> runs that part of government."""
    words = arg.split(None, 1)
    if not words:
        print(board_text(session))
        return print()
    sub, rest = words[0].lower(), words[1] if len(words) > 1 else ""
    target = BOARD_SUBS.get(sub)
    if not target:
        ui.note(f"no '{sub}' on the board - /board shows the sub-commands")
        return print()
    handle_command(session, f"/{target} {rest}".rstrip())


def pay_command(session, words, order):
    """/pay credit|deduct <agent|all> <amount> · split <amount> <agents|all> · grow|ration <factor> <agent|all>
    (multiply, divide, add and subtract work too: the cipher's MDAS moves)."""
    op = {"multiply": "grow", "divide": "split", "add": "credit", "subtract": "deduct",    # MDAS
          "z": "grow", "e": "split", "r": "credit", "o": "deduct"}.get(words[0].lower(), words[0])   # ZERO
    rest = words[1:]
    if op == "grow" and rest and rest[0].lstrip("x").replace(".", "", 1).isdigit() and float(rest[0].lstrip("x")) < 1:
        op = "ration"            # Z with a factor under 1 rations

    def amount_at_end(ws):
        """The amount is the last word or two ('25c', '3 quarters', 'a penny'); the agents come before it."""
        for k in (2, 1):
            if len(ws) >= k and change.money(" ".join(ws[-k:])) is not None:
                return change.money(" ".join(ws[-k:])), ws[:-k]
        return None, ws

    def amount_at_start(ws):
        for k in (2, 1):
            if len(ws) >= k and change.money(" ".join(ws[:k])) is not None:
                return change.money(" ".join(ws[:k])), ws[k:]
        return None, ws

    def who(names):
        if names == ["all"] or not names:
            return list(order)
        found = [session.agents.get(n) for n in names]
        if not all(found):
            bad = [n for n, a in zip(names, found) if not a]
            raise ValueError(f"no agent called {', '.join(bad)}")
        return [a.name for a in found]
    try:
        if op == "split":
            amount, names = amount_at_start(rest)
            if amount is None:
                raise ValueError("say how much to split: /pay split $1.00 broca judge")
            lines, steps = treasury.transact("split", who(names), amount=amount)
        elif op in ("grow", "ration"):
            factor = float(rest[0].lstrip("x")) if rest else 0
            if factor <= 0 or (op == "grow" and factor < 1) or (op == "ration" and factor > 1):
                raise ValueError("grow takes a factor of 1 or more (x1.1), ration one of 1 or less (x0.5)")
            lines, steps = treasury.transact(op, who(rest[1:]), factor=factor)
        else:
            amount, names = amount_at_end(rest)
            if amount is None:
                raise ValueError(f"say how much: /pay {op} broca 25c")
            lines, steps = treasury.transact(op, who(names), amount=amount)
    except (ValueError, IndexError) as e:
        ui.note(str(e))
        return print()
    ui.note(f"the Treasurer {op}s: " + " · ".join(lines))
    ui.note("worked as a cipher: " + " → ".join(steps[1:] or steps))
    return print()


def treasury_command(session, cmd, arg):
    """/treasury, /reef (/laws), /law <text> (/wreck), /law repeal <wreck>, /budget, /trident."""
    cfg = session.config
    order = council.seating(session.agents.agents, cfg.get("council_seats"))
    threshold = int(cfg.get("law_threshold", treasury.DEFAULTS["law_threshold"]))
    words = arg.split()
    if cmd == "pay":
        if words and words[0].lower() in ("credit", "deduct", "split", "grow", "ration", "multiply", "divide", "add",
                                          "subtract", "z", "e", "r", "o"):
            return pay_command(session, words, order)
        print(treasury.payroll_text(order))
        return print()
    if cmd == "quarters":
        print(treasury.quarters_text(HISTORY_DIR))
        return print()
    if cmd == "pockets":
        print(treasury.pockets_text(HISTORY_DIR, arg.strip()))
        return print()
    if cmd in ("trident", "trench", "locker", "compass"):
        workers = [{"name": b.label(), "calls": b.calls, "chars": b.chars, "seconds": b.seconds,
                    "unavailable": b.unavailable} for b in (session.claude, session.local)]
        if cmd != "trident":
            print(treasury.report(cmd, session.memory, workers))
            return print()
        power = processing_power(session.local)
        try:
            power["ram_total"] = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
        except (ValueError, OSError, AttributeError):
            power["ram_total"] = None
        power["num_ctx"] = session.local.num_ctx
        power["context"] = f"{session.local.num_ctx:,} tokens" + ("" if session.local.fixed_ctx else " (auto-sized)")
        power["parallel"] = session.config.get("lobe_parallel", True) is not False
        print(treasury.trident_text(getattr(session, "last_flow", None), session.memory, power, workers, order))
        return print()
    if cmd == "budget":
        if words[:1] == ["add"] and len(words) > 1:
            g = treasury.add_goal(arg.split(None, 1)[1])
            ui.note(f"added to the marlin: {g['text']}" if g else "the marlin holds up to ten goals")
        elif words[:1] in (["drop"], ["remove"]) and len(words) == 2 and words[1].isdigit():
            g = treasury.drop_goal(int(words[1]))
            ui.note(f"dropped: {g['text']}" if g else "no goal by that number")
        elif words[:1] == ["set"] and len(words) == 3 and words[1].isdigit() and words[2].rstrip("%").isdigit():
            err = treasury.set_cents(int(words[1]), int(words[2].rstrip("%")))
            if err:
                ui.note(err)
        print(treasury.budget_text())
        ui.note("/budget add <goal> · /budget set <n> <share> · /budget drop <n> · the marlin is 100 shares across your goals")
        return print()
    if cmd == "law" and words[:1] == ["repeal"] and len(words) >= 2:
        try:
            gone = treasury.repeal(" ".join(words[1:]))
        except ValueError as e:
            ui.note(str(e))
            return print()
        ui.note(f"Wreck {gone['art']} raised from the reef ({treasury.BOARDS.get(gone['board'])} board): \"{gone['text']}\""
                " - the repeal is carved in stone and the number is retired" if gone
                else "no shipwreck in force by that number (/reef shows them, e.g. 9.01)")
    elif cmd == "laws":
        print(treasury.cabinet_text(show_repealed=arg.strip() in ("all", "history")))
        ui.note(f"/law <board>: <text> throws a message in a bottle · /law repeal <wreck> · /reef all for raised wrecks · "
                f"readable copy: {treasury.STONE_MD}")
    elif cmd == "law" and arg.strip():
        board, bill = treasury.board_for(arg.strip(), session.agents)
        judge = session.agents.get(treasury.TREASURER) or session.agents.default
        with Spinner("all ten shillings are voting"):
            raw = session._quick_call(judge, judge.slim_system(), treasury.law_prompt(bill, order, board), 900)
        votes = treasury.parse_votes(raw, order)
        if not votes:
            ui.note("the council couldn't be reached to vote just now" if raw is None else
                    "the ballots came back unreadable - nothing was counted; try the bottle again")
            return print()
        treasury.record_votes(list(votes), "law ballot")   # a penny a ballot
        try:
            status, _entry = treasury.propose(bill, votes, threshold, board)
        except ValueError as e:
            ui.note(str(e))
            return print()
        session.show_sub(judge, {"name": "the Treasurer's count", "icon": ui.icon_for(judge.name, judge.icon),
                                 "color": judge.color, "lobe": True, "kind": "approval"},
                         "\n".join(treasury.vote_lines(bill, votes, threshold, status, order, board)))
    else:
        print(treasury.describe(order, threshold))
        ui.note("/law [board:] <text> throw a message in a bottle · /law repeal <wreck> · /reef · ten ayes make a galleon, sunk as a shipwreck")
    print()


def council_command(session, arg):
    """/council, /council on|off, /council steps <n>, /council approval on|off, /council threshold <0.5-1>."""
    cfg, words = session.config, arg.split()
    if words in (["on"], ["off"]):
        cfg["council"] = words[0] == "on"
        ui.note("all ten agents vote on who answers in auto mode" if cfg["council"]
                else "council off: auto mode routes by keywords alone")
    elif words[:1] == ["steps"] and len(words) == 2 and words[1].isdigit():
        cfg["council_steps"] = max(1, min(4, int(words[1])))
        ui.note(f"relays use up to {cfg['council_steps']} agents" if cfg["council_steps"] > 1 else "no relays: one agent answers")
    elif words[:1] == ["approval"] and words[1:] in (["on"], ["off"]):
        cfg["council_approval"] = words[1] == "on"
        ui.note("handoffs need the crew's approval" if cfg["council_approval"] else "handoffs pass without a vote")
    elif words[:1] == ["threshold"] and len(words) == 2:
        try:
            cfg["council_threshold"] = max(0.34, min(1.0, float(words[1])))
            ui.note(f"approval needs {cfg['council_threshold']:.0%} of the voters")
        except ValueError:
            ui.note("/council threshold 0.66")
    elif words[:1] == ["revisions"] and len(words) == 2 and words[1].isdigit():
        cfg["council_revisions"] = max(0, min(2, int(words[1])))
        ui.note(f"a step can be sent back {cfg['council_revisions']} time(s)")
    elif words == ["seats"]:
        print("\n".join(council.seat_chart(cfg.get("council_seats"))))
        return print()
    elif words[:1] == ["seat"] and len(words) == 3 and words[1].isdigit() and 1 <= int(words[1]) <= 10:
        agent = session.agents.get(words[2])
        if not agent:
            ui.note("no such agent")
            return print()
        cfg["council_seats"] = council.reseat(cfg.get("council_seats"), int(words[1]), agent.name)
        print("\n".join(council.seat_chart(cfg["council_seats"])))
    elif words == ["seats", "reset"] or words == ["reseat"]:
        cfg.pop("council_seats", None)
        ui.note("seats back to the default")
    elif words == ["stats", "reset"]:
        council.reset_stats()
        ui.note("council stats cleared")
        return print()
    else:
        on = cfg.get("council", True) is not False
        ui.note(f"council {'on' if on else 'off'} (used in auto mode) · relays up to "
                f"{cfg.get('council_steps', 3)} · approval {'on' if cfg.get('council_approval', True) is not False else 'off'} "
                f"at {float(cfg.get('council_threshold', 0.66)):.0%} · {cfg.get('council_revisions', 1)} revision(s)")
        print("\n".join(council.seat_chart(cfg.get("council_seats"))))
        print(council.describe_stats())
        ui.note("/council on|off · steps <1-4> · approval on|off · threshold <0.34-1> · revisions <0-2> · "
                "seats · seat <1-10> <agent> · reseat · stats reset")
        return print()
    ui.save_config(cfg)
    print()


def crew_command(session, arg):
    """/crew, /crew <agent>, /crew reset <agent>, /crew on|off."""
    words = arg.split()
    if words[:1] in (["pledge"], ["chant"]):
        o = crew.oath(words[0])
        print(f"  {BOLD}{o['title']}{RESET}  {DIM}by {o['author']}{RESET}\n")
        for line in o["text"].splitlines():
            print(f"    {line}")
    elif words[:1] == ["seals"] and words[1:] in (["on"], ["off"]):
        session.config["seals"] = words[1] == "on"
        ui.save_config(session.config)
        ui.note("replies are stamped with each crew member's seal" if session.config["seals"] else "seals off")
    elif words and words[0] in ("on", "off"):
        session.config["crew"] = words[0] == "on"
        ui.save_config(session.config)
        ui.note("each agent answers as their crew member" if session.config["crew"]
                else "every agent answers in the captain's own voice")
    elif len(words) == 2 and words[0] == "reset":
        agent = session.agents.get(words[1])
        if agent and crew.reset(agent.name):
            fresh = AgentSet(session.agents.folder).get(agent.name)
            agent.traits = fresh.traits if fresh else agent.traits
            ui.note(f"@{agent.name}'s crew member is back to the default")
        else:
            ui.note("nothing to reset (that crew member hasn't been edited)")
    elif words:
        agent = session.agents.get(words[0])
        member = crew.get(agent.name) if agent else None
        print(crew.show(agent.name, member) if member else "  no such crew member (/crew lists them)")
    else:
        on = session.config.get("crew", True) is not False
        print(crew.describe(session.agents.agents, ui.paint_color))
        ui.note(f"crew voices are {'on' if on else 'off'} (/crew on|off)")
    print()


def apply_model_settings(config, claude, local):
    """Settings from the app's Settings tab. Environment variables, when set, still win."""
    if config.get("claude_model") and not os.environ.get("CLAUDE_MODEL"):
        claude.model = config["claude_model"]
    if config.get("max_tokens") and not os.environ.get("SEAHORSE_MAX_TOKENS"):
        claude.max_tokens = int(config["max_tokens"])
    if config.get("num_ctx") and not os.environ.get("SEAHORSE_NUM_CTX"):
        local.fixed_ctx, local.num_ctx = str(config["num_ctx"]), int(config["num_ctx"])
    elif not config.get("num_ctx") and not os.environ.get("SEAHORSE_NUM_CTX"):
        local.fixed_ctx, local._sized_for = None, None   # back to automatic sizing
    if config.get("keep_alive") and not os.environ.get("SEAHORSE_KEEP_ALIVE"):
        local.keep_alive = config["keep_alive"]


def build_session(mode_override=None):
    """Create a fully wired Session (models, personality, memory, cortex, profile). Returns (session, first_run)."""
    config, first_run = ui.load_config()
    ui.apply_config(config)
    refresh_palette()
    mode = mode_override or config.get("backend_mode", "auto")
    if mode not in ("auto", "claude", "local"):
        mode = "auto"
    claude = ClaudeBackend(
        model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5"),
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
    )
    persona = Personality.load()
    extra = load_extra_instructions()
    local = OllamaBackend(
        model=persona.state.get("base_model", "llama3.1:8b"),
        base_url=os.environ.get("OLLAMA_URL", "http://localhost:11434"),
    )
    apply_model_settings(config, claude, local)
    installed = local.installed_models()
    if os.environ.get("LOCAL_MODEL"):
        local.model = os.environ["LOCAL_MODEL"]
    elif config.get("local_model"):          # chosen in the app's Settings tab
        local.model = config["local_model"]
    elif any(m.split(":")[0] == MODEL_NAME for m in installed):
        local.model = MODEL_NAME
    elif installed and persona.state["base_model"] in installed:
        # First run with Ollama available: build the seahorse model now.
        ok, _ = persona.build_ollama(extra=extra)
        if ok:
            local.model = MODEL_NAME
    memory = None
    try:
        memory = MemoryStore(embedder=Embedder(local.base_url))
        if installed:
            memory.embedder.probe()
        else:
            memory.embedder.ok = False
        if persona.notes:  # bring over notes from older versions of Seahorse
            memory.migrate_notes(persona.notes)
            persona.state["notes"] = []
            persona.save()
    except Exception as e:  # noqa: BLE001 - Seahorse still works without memory
        ui.note(f"memory unavailable: {e}")
    cortex = None
    try:
        cortex = Cortex()
    except Exception as e:  # noqa: BLE001 - Seahorse still works without the cortex
        ui.note(f"cortex unavailable: {e}")
    profile = None
    try:
        profile = Profile()
    except Exception as e:  # noqa: BLE001 - Seahorse still works without the profile
        ui.note(f"profile unavailable: {e}")
    agency = None
    try:
        agency = Agency()
    except Exception as e:  # noqa: BLE001 - Seahorse still works without it
        ui.note(f"the Agency is unavailable: {e}")
    session = Session(claude, local, mode, persona, extra, memory=memory, cortex=cortex, profile=profile, agency=agency)
    session.config = config
    session.show_perception = bool(config.get("show_perception", True))
    start_agent = session.agents.get(config.get("agent_mode", "auto"))
    if start_agent:
        session.agent, session.agent_mode = start_agent, start_agent.name
    return session, first_run


def main():
    p = argparse.ArgumentParser(description="Seahorse - hybrid local AI chat")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--local", action="store_true", help="always use the local model")
    g.add_argument("--claude", action="store_true", help="always use Claude")
    p.add_argument("--load", help="resume a saved chat file")
    args = p.parse_args()

    session, first_run = build_session("local" if args.local else "claude" if args.claude else None)
    config = session.config
    persona = session.persona
    if args.load:
        session.load(args.load)

    if first_run:
        welcome(session)
    else:
        ui.banner("your own AI, growing with you",
                  status_lines(session) if config.get("status_panel", True) else (), config.get("logo", "full"))
        if config.get("greeting", True):
            print(f"  {ui.SAND}{ui.greeting(config.get('name', ''), persona.character)}{RESET}")
    ui.note("type a message, /help for commands, /quit to leave")
    print()

    while True:
        try:
            line = read_input().strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line.startswith("/"):
            try:
                handle_command(session, line)
            except EOFError:
                break
            continue
        session.ask(line)

    if session.messages:
        print()
        try:
            session.grow()
        except KeyboardInterrupt:
            ui.note("skipped learning from this chat")
        ui.note(f"chat saved to {session.save()}")
    print(f"\n  {ORANGE}{ui.TRIDENT}{RESET} {ui.SAND}{ui.ITALIC}"
          f"{ui.farewell(persona.character)}{RESET}\n")


if __name__ == "__main__":
    main()
