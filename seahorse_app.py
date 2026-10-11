#!/usr/bin/env python3
"""
seahorse_app.py - Seahorse as a standalone desktop application.

    python3 seahorse_app.py            open the app (launcher -> chat / image generator)
    python3 seahorse_app.py --browser  open it in your normal browser instead of an app window
    python3 seahorse_app.py --port N   use a specific port

Everything runs on your own computer. A small private server listens only on
127.0.0.1 and serves the app's three screens:

    Launcher   checks your environment (Ollama, models, Claude key, SymPy,
               image engines), can start Ollama, download models and build the
               seahorse model, then opens the other screens.
    Chat       the full Seahorse: agents with their colours and icons, memory,
               notebooks, profile, character, calculator, and every /command.
    Images     a local image generator. It drives whichever engine you have:
                 - Stable Diffusion WebUI (AUTOMATIC1111 or Forge) at :7860, started with --api
                 - ComfyUI at :8188
                 - built-in diffusers (pip install diffusers torch transformers accelerate),
                   SDXL-Turbo by default
               "Ask Seahorse" improves a prompt, and "Portrait" turns the 11 steps
               of the current character (identity, backstory, tale, voice, strength,
               mannerisms, spirit, rules, greetings, traits, preview) into a portrait prompt.
               Images are saved in ~/.seahorse/images with their settings.

The app shares one Seahorse with the terminal version: same memory, notebooks,
profile, personality and character.

Opens in its own window using pywebview if installed (pip install pywebview),
otherwise Chrome / Edge / Chromium / Brave in app mode, otherwise your browser.
Requests need a per-run secret token and a 127.0.0.1 host, so other websites
can't talk to it.
"""

import argparse
import base64
import contextlib
import importlib.util
import io
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ui  # noqa: E402

ui.Spinner.start = lambda self: self  # no terminal animations inside the app
ui.Spinner.stop = lambda self: None

import seahorse as sh  # noqa: E402
from cortex import category_color, lens  # noqa: E402
from memory import WorkingMemory  # noqa: E402
from personality import character_title  # noqa: E402
import crew  # noqa: E402
import change  # noqa: E402
import treasury  # noqa: E402
import lobes  # noqa: E402
import settings as settings_mod  # noqa: E402
from skills import CALC_RESULT_PREFIX, calculate, find_calc_blocks, format_results  # noqa: E402

STATIC = HERE / "app"
IMAGES_DIR = Path.home() / ".seahorse" / "images"
TOKEN = secrets.token_urlsafe(24)
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|[\x01\x02]")
BLOCKED_COMMANDS = {"build", "quit", "exit", "q", "wipe", "load"}
LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------

xterm_hex = ui.xterm_hex


def plain(text):
    return ANSI.sub("", text).replace("\r", "")


# ---------------------------------------------------------------------------
# A Session that streams to the app instead of the terminal
# ---------------------------------------------------------------------------

class WebSession(sh.Session):
    emit = staticmethod(lambda event: None)

    def paid_note(self, agent, cents, ledger):
        """The Treasurer paid the last reply: show it on that reply as a coin chip."""
        why = ", ".join(w for _d, w in ledger[1:]) or "it answered"
        self.emit({"type": "paid", "agent": agent, "cents": cents, "dollars": change.dollars(cents), "why": why})

    def _stream(self, agent, system, messages):
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
            self.emit({"type": "thinking", "agent": agent.name})
            try:
                started = False
                for piece in self.pieces(backend, system, messages):
                    if not started:
                        self.emit(self.start_event(agent, backend))
                        started = True
                    reply.append(piece)
                    self.emit({"type": "token", "text": piece})
                if not started:
                    self.emit(self.start_event(agent, backend))
                self.emit({"type": "end"})
                return "".join(reply), "ok"
            except sh.BackendUnavailable as e:
                errors.append(f"{backend.label()}: {e}")
                if reply:
                    self.emit({"type": "end", "note": "connection lost mid-reply"})
                    return "".join(reply), "partial"
                if backend is self.claude and len(backends) > 1 and not self.told_fallback:
                    self.emit({"type": "note", "text": f"Claude unavailable ({e}), so using the local model."})
                    self.told_fallback = True
            except RuntimeError as e:
                self.emit({"type": "error", "text": str(e)})
                return None, "failed"
        self.emit({"type": "error", "text": "No model available: " + "; ".join(errors)})
        return None, "failed"

    def start_event(self, agent, backend):
        """The 'start' event: who is answering, with their crew name and notary seal."""
        ev = {"type": "start", "agent": agent.name, "backend": backend.label()}
        member = crew.get(agent.name) if self.config.get("crew", True) is not False else None
        if member and not member.get("captain"):
            ev["crew"] = member.get("name", "")
        if self.config.get("seals", True) is not False and member:
            sign, motto = crew.seal(member)
            ev["seal"] = {"sign": sign, "motto": motto, "name": member.get("name", ""), "stamp": crew.stamp(member)}
        return ev

    def show_conscience(self, note):
        from agency import AGENCY
        a = AGENCY["conscience"]
        self.emit({"type": "conscience", "icon": a["icon"], "color": xterm_hex(a["color"]), "text": note})

    def show_magic(self, dept, gift_id, text):
        from agency import DEPARTMENTS
        d = DEPARTMENTS[dept]
        self.emit({"type": "magic", "dept": dept, "name": d["name"], "icon": d["icon"],
                   "color": xterm_hex(d["color"]), "text": text})

    def show_sub(self, agent, sub, text):
        icon = ui.APP_ICONS.get(sub["name"].split(" ")[0], sub["icon"]) if sub.get("lobe") else sub["icon"]
        self.emit({"type": "sub", "agent": agent.name, "name": sub["name"], "icon": icon, "lobe": bool(sub.get("lobe")),
                   "kind": sub.get("kind", ""), "color": xterm_hex(sub["color"]), "text": text})

    def busy_with(self, label, agent=None):
        self.emit({"type": "thinking", "agent": agent.name if agent else "hippocampus", "label": label})
        return contextlib.nullcontext()

    def _agent_turn(self, agent, active_skills, messages):
        system = self.system_for(agent, active_skills, " ".join(self.user_texts(messages)[-2:]))
        if self.sub_brains_on(agent) and len((self.user_texts(messages) or [""])[-1].split()) >= sh.SUB_BRAIN_MIN_WORDS:
            self.emit({"type": "thinking", "agent": agent.name, "label": f"{agent.name}'s brain is working"})
        system += self.inner_council(agent, system, messages)
        min_words = int(self.config.get("lobe_min_words") or sh.LOBE_MIN_WORDS)
        if self.lobes_on(agent) and len((self.user_texts(messages) or [""])[-1].split()) >= min_words:
            self.emit({"type": "thinking", "agent": agent.name, "label": "the lobes are voting"})
        system += self.lobe_council(agent, system, messages)
        system += self.pop_relay_notes()
        final = None
        for round_no in range(sh.MAX_CALC_ROUNDS + 1):
            text, status = self._stream(agent, system, messages)
            if not text:
                while messages and messages[-1]["role"] == "user" and \
                        messages[-1]["content"].startswith(CALC_RESULT_PREFIX):
                    messages.pop()
                return final
            messages.append({"role": "assistant", "content": text})
            final = text
            lines = find_calc_blocks(text)
            if status != "ok" or not lines or round_no == sh.MAX_CALC_ROUNDS:
                break
            results = calculate(lines)
            self.emit({"type": "calc", "results": results})
            messages.append({"role": "user", "content": format_results(results)})
        return final

    def perceive(self, text):
        if not self.cortex:
            return
        found = self.cortex.perceive(text, list(self.agents.agents),
                                     previous_agent=self.agent.name if self.messages else None)
        chips = []
        for name, hits in found.items():
            agent = self.agents.get(name)
            for cat in dict.fromkeys(c for c, _t in hits):
                chips.append({"agent": name, "icon": ui.icon_for(name, agent.icon if agent else None),
                              "color": xterm_hex(agent.color if agent else 250), "category": cat,
                              "catColor": xterm_hex(category_color(name, cat))})
        if chips:
            self.emit({"type": "noticed", "chips": chips})
        return found

    def handle_memory_request(self, text):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            super().handle_memory_request(text)
        for line in plain(out.getvalue()).splitlines():
            line = line.strip().lstrip("~").strip()
            if line:
                self.emit({"type": "note", "text": line})


def make_session(mode=None):
    with contextlib.redirect_stdout(io.StringIO()):
        session, _first = sh.build_session(mode)
    session.__class__ = WebSession
    return session


def reset_chat(session):
    session.messages = []
    session.reflected_upto = 0
    session.reply_agent = {}
    session.usage = {}
    session.pinned_context = []
    session.working = WorkingMemory()
    session.started = datetime.now()
    session._chat_path = None


def run_captured(fn, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        fn(*args)
    return plain(out.getvalue()).strip("\n")


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

def http_json(url, payload=None, timeout=5, method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"content-type": "application/json"},
                                 method=method or ("POST" if data else "GET"))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def environment(session):
    local = session.local
    installed = local.installed_models()
    running = local.available()
    base = session.persona.state.get("base_model", "llama3.1:8b")
    embed = session.memory.embedder.model if session.memory and session.memory.embedder else "nomic-embed-text"

    def has(model):
        return any(m == model or m.split(":")[0] == model.split(":")[0] for m in installed)

    checks = [
        {"id": "python", "label": "Python", "ok": sys.version_info >= (3, 9),
         "detail": sys.version.split()[0], "required": True},
        {"id": "ollama", "label": "Ollama installed", "ok": bool(shutil.which("ollama")) or running,
         "detail": shutil.which("ollama") or ("running" if running else "not found - get it from ollama.com"),
         "required": True},
        {"id": "ollama_running", "label": "Ollama running", "ok": running, "detail": local.base_url,
         "action": None if running else "start_ollama", "required": True},
        {"id": "base_model", "label": f"Local brain ({base})", "ok": has(base),
         "detail": "installed" if has(base) else "not downloaded", "action": None if has(base) else "pull:" + base,
         "required": True},
        {"id": "seahorse_model", "label": "Seahorse model built", "ok": has(sh.MODEL_NAME),
         "detail": "ready" if has(sh.MODEL_NAME) else "built from your personality and character",
         "action": None if has(sh.MODEL_NAME) or not has(base) else "build_model", "required": False},
        {"id": "embed", "label": f"Memory search by meaning ({embed})", "ok": has(embed),
         "detail": "installed" if has(embed) else "optional - keyword search works without it",
         "action": None if has(embed) else "pull:" + embed, "required": False},
        {"id": "claude", "label": "Claude (when online)", "ok": bool(session.claude.api_key),
         "detail": session.claude.model if session.claude.api_key else "optional - set ANTHROPIC_API_KEY",
         "required": False},
        {"id": "sympy", "label": "Exact maths (SymPy)", "ok": importlib.util.find_spec("sympy") is not None,
         "detail": "installed" if importlib.util.find_spec("sympy") else "optional - pip install sympy",
         "required": False},
    ]
    engines = image_engines()
    any_engine = any(e["available"] for e in engines)
    checks.append({"id": "images", "label": "Image engine", "ok": any_engine,
                   "detail": ", ".join(e["name"] for e in engines if e["available"]) or
                   "optional - start Stable Diffusion WebUI (--api) or ComfyUI, or install diffusers",
                   "required": False})
    data = Path.home() / ".seahorse"
    size = sum(f.stat().st_size for f in data.rglob("*") if f.is_file()) if data.exists() else 0
    return {"checks": checks, "ready": all(c["ok"] for c in checks if c["required"]) or
            bool(session.claude.api_key), "data_dir": str(data), "data_mb": round(size / 1e6, 1),
            "mode": session.mode}


def start_ollama():
    exe = shutil.which("ollama")
    if not exe:
        return False, "Ollama isn't installed - get it from ollama.com"
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # detached, new process group
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([exe, "serve"], **kwargs)
    for _ in range(30):
        time.sleep(0.5)
        try:
            http_json(SESSION.local.base_url + "/api/tags", timeout=1)
            return True, "Ollama is running"
        except Exception:  # noqa: BLE001
            continue
    return False, "Ollama didn't start in time"


# ---------------------------------------------------------------------------
# Image engines
# ---------------------------------------------------------------------------

A1111_URL = os.environ.get("SEAHORSE_A1111_URL", "http://127.0.0.1:7860")
COMFY_URL = os.environ.get("SEAHORSE_COMFY_URL", "http://127.0.0.1:8188")
DIFFUSERS_MODEL = os.environ.get("SEAHORSE_DIFFUSERS_MODEL", "stabilityai/sdxl-turbo")
_PIPE = {}


def image_engines():
    engines = []
    try:
        models = http_json(A1111_URL + "/sdapi/v1/sd-models", timeout=1.5)
        engines.append({"id": "a1111", "name": "Stable Diffusion WebUI", "available": True,
                        "models": [m.get("title") for m in models], "url": A1111_URL})
    except Exception:  # noqa: BLE001
        engines.append({"id": "a1111", "name": "Stable Diffusion WebUI", "available": False, "models": [],
                        "url": A1111_URL, "hint": "start it with --api"})
    try:
        info = http_json(COMFY_URL + "/object_info/CheckpointLoaderSimple", timeout=1.5)
        ckpts = info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
        engines.append({"id": "comfy", "name": "ComfyUI", "available": True, "models": ckpts, "url": COMFY_URL})
    except Exception:  # noqa: BLE001
        engines.append({"id": "comfy", "name": "ComfyUI", "available": False, "models": [], "url": COMFY_URL})
    has_diffusers = importlib.util.find_spec("diffusers") is not None and importlib.util.find_spec("torch") is not None
    engines.append({"id": "diffusers", "name": "Built-in (diffusers)", "available": has_diffusers,
                    "models": [DIFFUSERS_MODEL], "hint": "pip install diffusers torch transformers accelerate"})
    return engines


def generate_a1111(req):
    payload = {"prompt": req["prompt"], "negative_prompt": req.get("negative", ""), "width": req["width"],
               "height": req["height"], "steps": req["steps"], "cfg_scale": req["cfg"], "seed": req["seed"]}
    if req.get("model"):
        payload["override_settings"] = {"sd_model_checkpoint": req["model"]}
    out = http_json(A1111_URL + "/sdapi/v1/txt2img", payload, timeout=600)
    info = json.loads(out.get("info") or "{}")
    return base64.b64decode(out["images"][0]), info.get("seed", req["seed"])


def generate_comfy(req, engines):
    ckpts = next(e for e in engines if e["id"] == "comfy")["models"]
    model = req.get("model") if req.get("model") in ckpts else (ckpts[0] if ckpts else None)
    if not model:
        raise RuntimeError("ComfyUI has no checkpoints installed")
    seed = req["seed"] if req["seed"] >= 0 else secrets.randbelow(2 ** 32)
    wf = {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": model}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": req["width"], "height": req["height"], "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": req["prompt"], "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": req.get("negative", ""), "clip": ["4", 1]}},
        "3": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": req["steps"], "cfg": req["cfg"],
                                                   "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0,
                                                   "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
                                                   "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "seahorse", "images": ["8", 0]}},
    }
    pid = http_json(COMFY_URL + "/prompt", {"prompt": wf, "client_id": str(uuid.uuid4())}, timeout=30)["prompt_id"]
    for _ in range(1200):
        time.sleep(0.5)
        hist = http_json(f"{COMFY_URL}/history/{pid}", timeout=10)
        if pid in hist:
            for node in hist[pid].get("outputs", {}).values():
                for img in node.get("images", []):
                    q = urllib.parse.urlencode({"filename": img["filename"], "subfolder": img.get("subfolder", ""),
                                                "type": img.get("type", "output")})
                    with urllib.request.urlopen(f"{COMFY_URL}/view?{q}", timeout=60) as r:
                        return r.read(), seed
            raise RuntimeError("ComfyUI finished without an image")
    raise RuntimeError("ComfyUI took too long")


def generate_diffusers(req):
    import torch
    from diffusers import AutoPipelineForText2Image
    model = req.get("model") or DIFFUSERS_MODEL
    if model not in _PIPE:
        device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        dtype = torch.float16 if device != "cpu" else torch.float32
        pipe = AutoPipelineForText2Image.from_pretrained(model, torch_dtype=dtype)
        _PIPE.clear()
        _PIPE[model] = (pipe.to(device), device)
    pipe, device = _PIPE[model]
    seed = req["seed"] if req["seed"] >= 0 else secrets.randbelow(2 ** 32)
    gen = torch.Generator(device="cpu").manual_seed(seed)
    turbo = "turbo" in model.lower()
    image = pipe(prompt=req["prompt"], negative_prompt=req.get("negative") or None,
                 num_inference_steps=min(req["steps"], 4) if turbo else req["steps"],
                 guidance_scale=0.0 if turbo else req["cfg"], width=req["width"], height=req["height"],
                 generator=gen).images[0]
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue(), seed


def generate_image(req):
    engines = image_engines()
    wanted = req.get("engine") or next((e["id"] for e in engines if e["available"]), None)
    engine = next((e for e in engines if e["id"] == wanted), None)
    if not engine or not engine["available"]:
        raise RuntimeError("No image engine is running. Start Stable Diffusion WebUI with --api, start ComfyUI, "
                           "or install diffusers (see the launcher).")
    req = {"prompt": str(req.get("prompt", "")).strip(), "negative": str(req.get("negative", "")),
           "width": int(req.get("width", 768)) // 8 * 8, "height": int(req.get("height", 768)) // 8 * 8,
           "steps": max(1, min(150, int(req.get("steps", 25)))), "cfg": float(req.get("cfg", 6.5)),
           "seed": int(req.get("seed", -1)), "model": req.get("model") or ""}
    if not req["prompt"]:
        raise RuntimeError("Write a prompt first")
    started = time.time()
    if engine["id"] == "a1111":
        png, seed = generate_a1111(req)
    elif engine["id"] == "comfy":
        png, seed = generate_comfy(req, engines)
    else:
        png, seed = generate_diffusers(req)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", req["prompt"].lower())[:40].strip("-") or "image"
    name = f"{datetime.now():%Y%m%d-%H%M%S}-{slug}"
    (IMAGES_DIR / f"{name}.png").write_bytes(png)
    meta = dict(req, seed=seed, engine=engine["name"], seconds=round(time.time() - started, 1),
                created=datetime.now().isoformat(timespec="seconds"), file=f"{name}.png")
    (IMAGES_DIR / f"{name}.json").write_text(json.dumps(meta, indent=2))
    return meta


def gallery():
    items = []
    for meta_path in sorted(IMAGES_DIR.glob("*.json"), reverse=True)[:200]:
        try:
            meta = json.loads(meta_path.read_text())
            if (IMAGES_DIR / meta["file"]).exists():
                items.append(meta)
        except (OSError, json.JSONDecodeError, KeyError):
            continue
    return items


# ---------------------------------------------------------------------------
# Prompts: improve, and a portrait from the 11 steps of the character
# ---------------------------------------------------------------------------

def character_steps(session):
    """The current character, laid out as the builder's 11 steps."""
    c = session.persona.character
    traits = ", ".join(f"{n} {t['value']:.2f}->{t['target']:.2f}" for n, t in session.persona.traits.items())
    return [
        ("identity", character_title(c)),
        ("backstory", c.get("backstory", "")),
        ("tale", c.get("tale", "")),
        ("voice", c.get("voice", "")),
        ("strength", c.get("strength", "")),
        ("mannerisms", "; ".join(c.get("mannerisms", []))),
        ("spirit", c.get("spirit", "")),
        ("rules", "; ".join(c.get("rules", []))),
        ("greetings", "; ".join(c.get("greetings", [])[:3] + c.get("farewells", [])[:2])),
        ("traits", traits),
        ("preview", "how he is presented as a whole"),
    ]


def portrait_template(session):
    c = session.persona.character
    name = c.get("epithet") or c.get("name") or "Seahorse"
    looks = []
    text = " ".join([c.get("backstory", ""), c.get("tale", ""), c.get("spirit", "")]).lower()
    for word, phrase in [("pirate", "a weathered lone pirate captain"), ("1600", "17th-century sailor's clothes"),
                         ("port royal", "Caribbean harbour at dusk"), ("knife", "a knife at his belt"),
                         ("rum", "a small rum cask beside him"), ("hum", "a faint glowing hum in the air"),
                         ("duppies", "ghostly spirits drifting over dark water"), ("helm", "at the helm of a small sloop"),
                         ("lantern", "lantern light"), ("sea", "moody sea and night sky")]:
        if word in text:
            looks.append(phrase)
    prompt = (f"portrait of {name}, " + ", ".join(looks or ["an enigmatic sea spirit"]) +
              ", raised brow, no smile, dignified, painterly, cinematic lighting, highly detailed, oil painting")
    return {"prompt": prompt, "negative": "cartoon, caricature, blurry, low quality, extra fingers, text, watermark",
            "source": "template"}


def portrait_prompt(session):
    steps = character_steps(session)
    listing = "\n".join(f"{i}. {name}: {value or '(empty)'}" for i, (name, value) in enumerate(steps, 1))
    ask = f"""Here is a character, described in the 11 steps of a character builder:
{listing}

Write ONE image-generation prompt for a portrait of this character that draws on every step: who he is (identity),
his era, place and life (backstory, tale), the feeling of how he speaks (voice, strength), his habits (mannerisms),
his uncanny side (spirit), and the mood of his traits. Depict any culture with dignity, never as a caricature.
Also write a negative prompt.
Return ONLY JSON: {{"prompt": "<at most 80 words, comma-separated visual details>", "negative": "<things to avoid>"}}"""
    data = sh.extract_json(SESSION.complete(ask, system="You write precise prompts for image models."))
    if isinstance(data, dict) and data.get("prompt"):
        return {"prompt": str(data["prompt"]).strip(), "negative": str(data.get("negative", "")).strip(),
                "source": "seahorse", "steps": [n for n, _v in steps]}
    out = portrait_template(session)
    out["steps"] = [n for n, _v in steps]
    return out


def improve_prompt(session, prompt):
    ask = (f"Improve this image-generation prompt so it gives a striking, detailed image. Keep the user's idea, add "
           f"subject detail, setting, lighting, style and composition. Prompt: {prompt}\n"
           f'Return ONLY JSON: {{"prompt": "<at most 80 words>", "negative": "<things to avoid>"}}')
    data = sh.extract_json(session.complete(ask, system="You write precise prompts for image models."))
    if isinstance(data, dict) and data.get("prompt"):
        return {"prompt": data["prompt"], "negative": data.get("negative", "")}
    return {"prompt": prompt, "negative": "", "note": "couldn't reach a model to improve it"}


# ---------------------------------------------------------------------------
# State for the front end
# ---------------------------------------------------------------------------

def app_state(session):
    import council
    order = council.seating(session.agents.agents, session.config.get("council_seats"))
    purses = treasury.load_purses()
    agents = []
    for a in session.agents.agents.values():
        spec = lens(a.name)
        member = crew.get(a.name) or {}
        sign, motto = crew.seal(member)
        agents.append({"name": a.name, "icon": ui.APP_ICONS.get(a.name) or ui.icon_for(a.name, a.icon),
                       "color": xterm_hex(a.color),
                       "crew": member.get("name", ""), "epithet": member.get("epithet", ""),
                       "penny": f"{order.index(a.name) + 1:02d}" if a.name in order else "",   # its shilling number
                       "seal": {"sign": sign, "motto": motto},
                       "horseman": member.get("horseman") or None,           # the four high-ranking council members
                       "purse": purses.get(a.name, 0),                        # cents paid so far
                       "description": a.description, "purpose": spec.get("purpose") or a.description,
                       "skill": spec.get("skill", ""), "aliases": a.aliases})
    c = session.persona.character
    t = ui.THEMES.get(ui.THEME if ui.THEME != "mono" else "ocean")
    history = []
    for i, m in enumerate(session.messages):
        if m["role"] == "user" and m["content"].startswith(CALC_RESULT_PREFIX):
            continue
        history.append({"role": m["role"], "content": m["content"], "agent": session.reply_agent.get(i)})
    return {
        "token": TOKEN,
        "agents": agents,
        "agentMode": session.agent_mode,
        "character": {"name": c.get("name") or "Seahorse", "epithet": c.get("epithet", ""),
                      "enabled": bool(c.get("enabled")),
                      "greeting": ui.greeting(session.config.get("name", ""), c),
                      "farewell": ui.farewell(c)},
        "theme": {k: xterm_hex(t[k]) for k in ("foam", "aqua", "teal", "sea", "deep", "coral", "sand", "kelp")},
        "logo": {"art": ui.SEAHORSE_ART, "title": ui._title_rows()},
        "history": history,
        "mode": session.mode,
    }


def settings_payload():
    return {**settings_mod.describe(SESSION), "crew": settings_mod.crew_state(SESSION)}


def crew_test(agent_name, text):
    """One short reply from a crew member, for the Settings preview."""
    agent = SESSION.agents.get(agent_name)
    if not agent:
        raise settings_mod.SettingError("no such agent")
    system = SESSION.system_for(agent, []) if agent.persona else agent.slim_system()
    reply = SESSION.complete((text or "Who are you, and what do you do aboard?")[:500], agent=agent, system=system,
                             label="testing")
    return {"reply": reply or "(no model reachable for a test)"}


def _set_image_url(name):
    def hook(value):
        if not os.environ.get(f"SEAHORSE_{name.upper()}_URL"):
            globals()[f"{name.upper()}_URL"] = (value or settings_mod.DEFAULTS[f"{name}_url"]).rstrip("/")
    return hook


IMAGE_HOOKS = {"a1111_url": _set_image_url("a1111"), "comfy_url": _set_image_url("comfy")}


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

SESSION = None
PORT = 0


class Handler(BaseHTTPRequestHandler):
    server_version = "Seahorse"

    def log_message(self, *args):
        pass

    # -------------------------------------------------- helpers
    def _host_ok(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _auth(self):
        return self._host_ok() and secrets.compare_digest(self.headers.get("X-Seahorse-Token", ""), TOKEN)

    def _send(self, code, body, ctype="application/json", extra=None):
        data = body if isinstance(body, bytes) else (json.dumps(body) if ctype == "application/json" else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 2_000_000:
            raise ValueError("request too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def _stream_start(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

    def _write(self, event):
        try:
            self.wfile.write((json.dumps(event) + "\n").encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    # -------------------------------------------------- GET
    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden"})
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            html = (STATIC / "index.html").read_text(encoding="utf-8").replace("__SEAHORSE_TOKEN__", TOKEN)
            return self._send(200, html, "text/html; charset=utf-8",
                              {"Content-Security-Policy": "default-src 'self'; img-src 'self' data:; "
                                                          "style-src 'self' 'unsafe-inline'; script-src 'self'"})
        if path in ("/app.js", "/settings.js", "/glyphs.js", "/style.css", "/settings.css"):
            ctype = "text/javascript" if path.endswith(".js") else "text/css"
            return self._send(200, (STATIC / path[1:]).read_bytes(), f"{ctype}; charset=utf-8")
        if path.startswith("/images/"):
            name = Path(urllib.parse.unquote(path[8:])).name
            f = IMAGES_DIR / name
            if f.suffix == ".png" and f.exists():
                return self._send(200, f.read_bytes(), "image/png")
            return self._send(404, {"error": "not found"})
        if not self._auth():
            return self._send(403, {"error": "forbidden"})
        with LOCK:  # one thread at a time touches Seahorse's databases
            return self._get_api(path)

    def _get_api(self, path):
        if path == "/api/state":
            return self._send(200, app_state(SESSION))
        if path == "/api/env":
            return self._send(200, environment(SESSION))
        if path == "/api/images":
            return self._send(200, {"images": gallery(), "engines": image_engines()})
        if path == "/api/character":
            return self._send(200, {"steps": character_steps(SESSION)})
        if path == "/api/settings":
            return self._send(200, settings_payload())
        return self._send(404, {"error": "not found"})

    # -------------------------------------------------- POST
    def do_POST(self):
        if not self._auth():
            return self._send(403, {"error": "forbidden"})
        path = urllib.parse.urlparse(self.path).path
        try:
            body = self._body()
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {"error": "bad request"})
        try:
            if path == "/api/chat":
                return self.chat(body)
            if path == "/api/command":
                return self._send(200, self.run_command(str(body.get("line", ""))))
            if path == "/api/end":
                return self._send(200, self.end_chat())
            if path == "/api/agent":
                name = str(body.get("agent", "auto"))
                with LOCK:
                    if name == "auto":
                        SESSION.agent_mode = "auto"
                    elif SESSION.agents.get(name):
                        SESSION.agent = SESSION.agents.get(name)
                        SESSION.agent_mode = SESSION.agent.name
                return self._send(200, {"agentMode": SESSION.agent_mode})
            if path == "/api/ollama/start":
                ok, msg = start_ollama()
                return self._send(200, {"ok": ok, "message": msg})
            if path == "/api/ollama/pull":
                return self.pull(str(body.get("model", "")))
            if path == "/api/model/build":
                ok, msg = SESSION.persona.build_ollama(extra=SESSION.extra)
                return self._send(200, {"ok": ok, "message": msg})
            if path == "/api/images/generate":
                return self._send(200, generate_image(body))
            if path == "/api/images/improve":
                return self._send(200, improve_prompt(SESSION, str(body.get("prompt", ""))))
            if path == "/api/images/portrait":
                return self._send(200, portrait_prompt(SESSION))
            if path.startswith(("/api/settings", "/api/crew", "/api/lobes")):
                return self.settings_post(path, body)
        except Exception as e:  # noqa: BLE001 - report errors to the app
            return self._send(500, {"error": str(e)})
        return self._send(404, {"error": "not found"})

    # -------------------------------------------------- settings
    def settings_post(self, path, body):
        with LOCK:
            try:
                notes = []
                if path == "/api/settings":
                    changes = body.get("changes")
                    if not isinstance(changes, dict) or not changes:
                        raise settings_mod.SettingError("nothing to change")
                    notes = settings_mod.apply(SESSION, changes, IMAGE_HOOKS)
                elif path == "/api/settings/reset":
                    settings_mod.reset(SESSION, IMAGE_HOOKS)
                    notes = ["settings are back to their defaults"]
                elif path == "/api/crew":
                    settings_mod.save_crew(SESSION, str(body.get("agent", "")), body.get("member") or {})
                    notes = ["saved - they'll answer this way from your next message"]
                elif path == "/api/crew/reset":
                    settings_mod.reset_crew(SESSION, str(body.get("agent", "")))
                    notes = ["back to the default"]
                elif path == "/api/crew/oath":
                    settings_mod.save_oath(str(body.get("kind", "")), body)
                    notes = ["saved"]
                elif path == "/api/crew/test":
                    return self._send(200, crew_test(str(body.get("agent", "")), str(body.get("text", ""))))
                elif path == "/api/lobes/stats/reset":
                    lobes.reset_stats()
                    notes = ["vote stats cleared"]
                else:
                    return self._send(404, {"error": "not found"})
            except settings_mod.SettingError as e:
                return self._send(400, {"error": str(e)})
            return self._send(200, {**settings_payload(), "notes": notes, "state": app_state(SESSION)})

    # -------------------------------------------------- actions
    def chat(self, body):
        text = str(body.get("text", "")).strip()
        self._stream_start()
        if not text:
            self._write({"type": "error", "text": "empty message"})
            return
        with LOCK:
            SESSION.emit = self._write
            try:
                SESSION.ask(text)
                SESSION.save()
            except Exception as e:  # noqa: BLE001
                self._write({"type": "error", "text": str(e)})
            finally:
                SESSION.emit = lambda event: None
        self._write({"type": "done", "agentMode": SESSION.agent_mode})

    def run_command(self, line):
        line = line.strip()
        cmd = line[1:].split(" ", 1)[0].lower()
        arg = line[len(cmd) + 1:].strip().lower()
        if cmd in BLOCKED_COMMANDS or "wipe" in arg.split() or (cmd == "persona" and arg.startswith("new")):
            return {"output": f"/{cmd} needs the terminal version (python3 seahorse.py) because it asks you to "
                              f"confirm or answer questions step by step."}
        if cmd == "end":
            return self.end_chat()
        with LOCK:
            subs = []      # vote counts and other sub-panels a command shows (e.g. /law): fold them into the output
            if cmd == "team":
                SESSION.emit = lambda event: None
            else:
                SESSION.emit = lambda event: subs.append(event) if event.get("type") == "sub" else None
            out = run_captured(sh.handle_command, SESSION, line)
            shown = [f"{e['icon']} {e['name']}\n{plain(e['text'])}" for e in subs]
            out = "\n\n".join(x for x in [*shown, out] if x and x.strip())
            SESSION.save() if SESSION.messages else None
        if cmd in ("theme", "config"):
            ui.apply_config(SESSION.config)
        return {"output": out or "(done)", "state": app_state(SESSION)}

    def end_chat(self):
        with LOCK:
            if not SESSION.messages:
                return {"output": "Nothing to learn from yet."}
            out = run_captured(SESSION.grow)
            SESSION.save()
            reset_chat(SESSION)
        return {"output": out or "Saved.", "state": app_state(SESSION)}

    def pull(self, model):
        self._stream_start()
        if not re.fullmatch(r"[\w.:/-]{1,100}", model or ""):
            self._write({"error": "bad model name"})
            return
        req = urllib.request.Request(SESSION.local.base_url + "/api/pull",
                                     data=json.dumps({"model": model, "stream": True}).encode(),
                                     headers={"content-type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=3600) as r:
                for raw in r:
                    try:
                        self._write(json.loads(raw))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:  # noqa: BLE001
            self._write({"error": str(e)})
        self._write({"status": "done"})


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------

def find_chromium():
    candidates = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
                  "brave-browser", "chrome"]
    for c in candidates:
        if shutil.which(c):
            return shutil.which(c)
    mac = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
           "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
           "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
           "/Applications/Chromium.app/Contents/MacOS/Chromium"]
    win = [os.path.expandvars(p) for p in (
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        r"%LocalAppData%\Google\Chrome\Application\chrome.exe")]
    for p in mac + win:
        if os.path.exists(p):
            return p
    return None


def ensure_pywebview():
    """Install pywebview (the native app window) the first time, if it's missing. Returns True if available."""
    if importlib.util.find_spec("webview"):
        return True
    flag = Path.home() / ".seahorse" / ".pywebview-tried"
    if flag.exists():
        return False  # tried before and it didn't work; use the browser window instead
    print("Setting up the Seahorse window (one time): pip install pywebview ...", flush=True)
    package = "pywebview[qt]" if sys.platform.startswith("linux") else "pywebview"
    for extra in ([], ["--user"], ["--user", "--break-system-packages"]):
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", package, *extra],
                           capture_output=True, text=True)
        if r.returncode == 0:
            importlib.invalidate_caches()
            if importlib.util.find_spec("webview"):
                print("pywebview installed.", flush=True)
                return True
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("pip install pywebview failed; using a browser window instead\n")
    print("Couldn't install pywebview, so Seahorse will open in a browser window instead.", flush=True)
    return False


def open_window(url, use_browser=False):
    """Returns a blocking function to run (pywebview) or None (window opened in another process)."""
    if not use_browser and ensure_pywebview():
        import webview
        webview.create_window("Seahorse", url, width=1240, height=820, min_size=(820, 560),
                              background_color="#061a26")
        return webview.start
    exe = None if use_browser else find_chromium()
    if exe:
        profile = Path.home() / ".seahorse" / "appwindow"
        subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1240,820",
                          "--no-first-run", "--no-default-browser-check"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return None
    webbrowser.open(url)
    return None


def free_port(preferred=0):
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", preferred))
        except OSError:
            s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    global SESSION, PORT
    ap = argparse.ArgumentParser(description="Seahorse desktop app")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--browser", action="store_true", help="open in your normal browser")
    ap.add_argument("--no-window", action="store_true", help="just run the server (for testing)")
    ap.add_argument("--local", action="store_true", help="local model only")
    args = ap.parse_args()

    SESSION = make_session("local" if args.local else None)
    for key, hook in IMAGE_HOOKS.items():   # image engine addresses from Settings
        if SESSION.config.get(key):
            hook(SESSION.config[key])
    PORT = free_port(args.port or 47110)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Seahorse app running at {url}  (Ctrl+C to stop)", flush=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    runner = None if args.no_window else open_window(url, args.browser)
    try:
        if runner:
            runner()  # pywebview window: returns when the window closes
        else:
            while thread.is_alive():
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        if SESSION.messages:
            with LOCK:
                run_captured(SESSION.grow)
                SESSION.save()
        server.shutdown()
        print("Walk good.")


if __name__ == "__main__":
    main()
