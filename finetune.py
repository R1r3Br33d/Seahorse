#!/usr/bin/env python3
"""
finetune.py - fine-tune Seahorse's local model on your own conversations.

Seahorse learns from every chat you have (unless it's incognito). This turns
those chats into training data and trains a LoRA adapter on the local model,
so the local brain itself picks up the Seahorse's voice, how each agent
answers, and how you like things done - not just through instructions in the
prompt.

    python3 finetune.py prepare            build the dataset from your chats
    python3 finetune.py distill [--max N]  (optional) have Claude write model answers to learn from
    python3 finetune.py train              train the adapter (runs for a while)
    python3 finetune.py eval               compare tuned vs untuned on held-out chats
    python3 finetune.py use | revert       switch Seahorse to the tuned model, or back
    python3 finetune.py status             progress of the current run

Or inside Seahorse: /finetune (status), /finetune prepare, distill, train, eval,
use, revert. Long steps run in the background, so you can keep chatting.

THE DATASET
    Every assistant reply in your saved chats becomes an example, with the
    system prompt of the agent who wrote it (personality, character, role and
    skills) and up to the six messages before it, so the model learns each
    agent's voice separately. Filters:
      - incognito chats are never used
      - replies you corrected next ("no, actually...", "that's wrong") are dropped
      - replies you thanked or praised count twice
      - anything containing a password, key or card number is dropped
      - calculator round-trips are folded into the final answer
      - exact duplicates are removed
    90% of chats go to training and 10% are held out for evaluation (split by
    chat, so the model is tested on conversations it never saw).

DISTILLATION (optional, uses your Claude API key)
    Claude, playing each agent with the same system prompt, answers the
    questions from your chats. Those answers become extra training examples, so
    the small local model learns to answer more like Claude does, in Seahorse's
    voice. Capped with --max (default 200 answers).

TRAINING (needs suitable hardware)
    Mac with Apple Silicon:  pip install mlx-lm
        LoRA with MLX, then fused and imported into Ollama (quantised to q4_K_M).
    NVIDIA GPU:              pip install torch transformers peft trl datasets accelerate bitsandbytes
        LoRA with PEFT/TRL (4-bit when bitsandbytes is available), imported into
        Ollama as an ADAPTER on the same base model.
    Without either, training is refused (a CPU would take days); preparing and
    distilling still work so the data is ready when you have the hardware.
    Defaults: rank 16, 2 epochs, learning rate 1e-4 (CUDA) / 1e-5 (MLX),
    prompt tokens masked so only the replies are learned.

USING IT
    `use` switches Seahorse's Modelfile to the tuned weights, so the regular
    `seahorse` model (and everything built on it) runs on them. `revert` goes
    back. Your personality, character, memory and agents keep working the same.

Everything stays on your computer in ~/.seahorse/finetune/.
"""

import argparse
import hashlib
import json
import math
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

HOME = Path.home() / ".seahorse"
CHATS = HOME / "chats"
FT = HOME / "finetune"
DATA = FT / "data"
RUNS = FT / "runs"
STATUS = FT / "status.json"
CALC_PREFIX = "[calculator results]"
CONTEXT_MESSAGES = 6
MIN_EXAMPLES = 50
TUNED_NAME = "seahorse-tuned"

# Ollama tag -> (MLX model, Hugging Face model for CUDA training)
BASE_MODELS = {
    "llama3.1:8b": ("mlx-community/Meta-Llama-3.1-8B-Instruct-4bit", "unsloth/Meta-Llama-3.1-8B-Instruct"),
    "llama3.2:3b": ("mlx-community/Llama-3.2-3B-Instruct-4bit", "unsloth/Llama-3.2-3B-Instruct"),
    "llama3.2:1b": ("mlx-community/Llama-3.2-1B-Instruct-4bit", "unsloth/Llama-3.2-1B-Instruct"),
    "qwen2.5:7b": ("mlx-community/Qwen2.5-7B-Instruct-4bit", "Qwen/Qwen2.5-7B-Instruct"),
    "mistral:7b": ("mlx-community/Mistral-7B-Instruct-v0.3-4bit", "mistralai/Mistral-7B-Instruct-v0.3"),
    "gemma2:9b": ("mlx-community/gemma-2-9b-it-4bit", "google/gemma-2-9b-it"),
}

_CORRECTION = re.compile(r"^\s*(no[,.!]|nope|wrong|that'?s (?:wrong|not right|incorrect)|not what i (?:meant|asked)|"
                         r"you (?:misunderstood|got it wrong|forgot)|actually,? (?:no|i said))", re.I)
_PRAISE = re.compile(r"\b(thanks|thank you|thx|perfect|great|awesome|exactly|love it|nailed it|that works|"
                     r"that'?s right|spot on)\b", re.I)


# ---------------------------------------------------------------------------
# Status (shared with Seahorse so /finetune can show progress)
# ---------------------------------------------------------------------------

def set_status(**kw):
    FT.mkdir(parents=True, exist_ok=True)
    cur = read_status()
    cur.update(kw, updated=datetime.now().isoformat(timespec="seconds"))
    STATUS.write_text(json.dumps(cur, indent=2))
    return cur


def read_status():
    try:
        return json.loads(STATUS.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def log(msg):
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    st = read_status()
    tail = (st.get("log") or [])[-30:] + [line]
    set_status(log=tail)


# ---------------------------------------------------------------------------
# Seahorse context (system prompts per agent)
# ---------------------------------------------------------------------------

def load_seahorse():
    from agents import AgentSet
    from personality import Personality
    from skills import SkillSet
    persona = Personality.load()
    extra = ""
    try:
        extra = (HOME / "system_prompt.txt").read_text().strip()
    except OSError:
        pass
    return persona, AgentSet(), SkillSet(), extra


def agent_system(persona, agents, skills, extra, agent_name):
    """The stable part of an agent's system prompt (memory and notes are left out: they change every chat)."""
    agent = agents.get(agent_name) or agents.default
    parts = [persona.system_prompt(extra, agent.traits)]
    if agent.role_prompt():
        parts.append(agent.role_prompt())
    active = [s for s in agent.skills if s in skills.skills]
    if active:
        parts.append(skills.prompt(active))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# PREPARE
# ---------------------------------------------------------------------------

def clean_messages(messages, agent_map):
    """Fold calculator round-trips into the final answer; keep each reply's agent."""
    out = []
    for i, m in enumerate(messages):
        role, text = m.get("role"), m.get("content", "")
        if role == "user" and text.startswith(CALC_PREFIX):
            continue
        if role == "assistant" and "```calc" in text and i + 1 < len(messages) and \
                messages[i + 1].get("content", "").startswith(CALC_PREFIX):
            continue  # the intermediate "let me calculate" turn
        out.append({"role": role, "content": text, "agent": agent_map.get(str(i))})
    return out


def chat_examples(path, persona, agents, skills, extra, contains_secret):
    data = json.loads(path.read_text())
    if data.get("incognito"):
        return [], {"incognito": 1}
    msgs = clean_messages(data.get("messages", []), data.get("agents", {}))
    stats = {"replies": 0, "corrected": 0, "secret": 0, "praised": 0}
    examples = []
    for i, m in enumerate(msgs):
        if m["role"] != "assistant" or not m["content"].strip() or i == 0:
            continue
        stats["replies"] += 1
        nxt = msgs[i + 1]["content"] if i + 1 < len(msgs) and msgs[i + 1]["role"] == "user" else ""
        if nxt and _CORRECTION.search(nxt):
            stats["corrected"] += 1
            continue
        context = msgs[max(0, i - CONTEXT_MESSAGES):i]
        while context and context[0]["role"] != "user":
            context = context[1:]
        if not context:
            continue
        convo = [{"role": c["role"], "content": c["content"]} for c in context] + \
                [{"role": "assistant", "content": m["content"]}]
        if any(contains_secret(c["content"]) for c in convo):
            stats["secret"] += 1
            continue
        agent = m.get("agent") or "hippocampus"
        agent = agent if not agent.startswith("team:") else "hippocampus"
        system = agent_system(persona, agents, skills, extra, agent)
        ex = {"messages": [{"role": "system", "content": system}] + convo,
              "meta": {"agent": agent, "chat": path.stem, "source": "chat"}}
        weight = 2 if nxt and _PRAISE.search(nxt) else 1
        stats["praised"] += weight - 1
        examples += [ex] * weight
    return examples, stats


def split_of(chat_stem):
    return "valid" if int(hashlib.sha1(chat_stem.encode()).hexdigest(), 16) % 10 == 0 else "train"


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({"messages": r["messages"]}, ensure_ascii=False) + "\n")


def prepare(quiet=False):
    from memory import contains_secret
    persona, agents, skills, extra = load_seahorse()
    chats = sorted(CHATS.glob("chat-*.json"))
    rows, totals = [], {"chats": 0, "incognito": 0, "replies": 0, "corrected": 0, "secret": 0, "praised": 0}
    seen = {}
    for path in chats:
        try:
            ex, st = chat_examples(path, persona, agents, skills, extra, contains_secret)
        except (OSError, json.JSONDecodeError):
            continue
        totals["chats"] += 1
        for k, v in st.items():
            totals[k] = totals.get(k, 0) + v
        for e in ex:
            key = hashlib.sha1(json.dumps(e["messages"][1:]).encode()).hexdigest()
            if key in seen and seen[key] is not e:  # the same exchange from another chat: skip
                totals["duplicates"] = totals.get("duplicates", 0) + 1
                continue
            seen[key] = e  # (a praised reply appears twice as the same object, on purpose)
            rows.append(e)
    distilled = []
    dpath = DATA / "distilled.jsonl"
    if dpath.exists():
        for line in dpath.read_text(encoding="utf-8").splitlines():
            try:
                distilled.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    train = [r for r in rows if split_of(r["meta"]["chat"]) == "train"] + \
            [d for d in distilled if split_of(d.get("meta", {}).get("chat", "")) == "train"]
    valid = [r for r in rows if split_of(r["meta"]["chat"]) == "valid"]
    if not valid and len(train) > 10:  # tiny datasets: hold out a few examples anyway
        random.Random(7).shuffle(train)
        valid, train = train[:max(1, len(train) // 10)], train[max(1, len(train) // 10):]
    random.Random(42).shuffle(train)
    write_jsonl(DATA / "train.jsonl", train)
    write_jsonl(DATA / "valid.jsonl", valid)
    by_agent = {}
    for r in train:
        a = r.get("meta", {}).get("agent", "?")
        by_agent[a] = by_agent.get(a, 0) + 1
    summary = dict(totals, train=len(train), valid=len(valid), distilled=len(distilled), by_agent=by_agent,
                   enough=len(train) >= MIN_EXAMPLES, data=str(DATA))
    (DATA / "summary.json").write_text(json.dumps(summary, indent=2))
    set_status(stage="prepared", dataset=summary)
    if not quiet:
        print(json.dumps(summary, indent=2))
    return summary


# ---------------------------------------------------------------------------
# DISTILL (optional)
# ---------------------------------------------------------------------------

def distill(max_answers=200):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("Distillation needs ANTHROPIC_API_KEY (it asks Claude to answer as each agent).")
    import seahorse as sh
    claude = sh.ClaudeBackend(os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5"), key, max_tokens=2048)
    persona, agents, skills, extra = load_seahorse()
    from memory import contains_secret
    set_status(stage="distilling", done=0, total=max_answers, log=[])
    out_path = DATA / "distilled.jsonl"
    DATA.mkdir(parents=True, exist_ok=True)
    have = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            try:
                have.add(json.loads(line)["meta"]["key"])
            except (json.JSONDecodeError, KeyError):
                continue
    done = 0
    with open(out_path, "a", encoding="utf-8") as f:
        for path in sorted(CHATS.glob("chat-*.json"), reverse=True):
            if done >= max_answers:
                break
            if split_of(path.stem) == "valid":
                continue  # never distill on the held-out chats
            try:
                ex, _st = chat_examples(path, persona, agents, skills, extra, contains_secret)
            except (OSError, json.JSONDecodeError):
                continue
            for e in ex:
                if done >= max_answers:
                    break
                k = hashlib.sha1(json.dumps(e["messages"][:-1]).encode()).hexdigest()
                if k in have:
                    continue
                have.add(k)
                system, convo = e["messages"][0]["content"], e["messages"][1:-1]
                try:
                    answer = "".join(claude.stream(system, convo)).strip()
                except Exception as err:  # noqa: BLE001
                    log(f"Claude error, stopping: {err}")
                    return done
                if not answer or contains_secret(answer):
                    continue
                row = {"messages": e["messages"][:-1] + [{"role": "assistant", "content": answer}],
                       "meta": {"agent": e["meta"]["agent"], "chat": path.stem, "source": "claude", "key": k}}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                done += 1
                set_status(done=done)
    log(f"distilled {done} answers from Claude")
    set_status(stage="distilled")
    prepare(quiet=True)
    return done


# ---------------------------------------------------------------------------
# TRAIN
# ---------------------------------------------------------------------------

def detect_trainer():
    if sys.platform == "darwin" and platform.machine() == "arm64":
        try:
            import mlx_lm  # noqa: F401
            return "mlx", None
        except ImportError:
            return None, "On this Mac, install MLX first:  pip install mlx-lm"
    try:
        import torch
        if torch.cuda.is_available():
            for mod in ("transformers", "peft", "trl", "datasets"):
                __import__(mod)
            return "cuda", None
        return None, ("No NVIDIA GPU (CUDA) or Apple Silicon found. Training on a CPU would take days, so it's off. "
                      "Your dataset is ready for when you have the hardware.")
    except ImportError as e:
        return None, (f"Missing {e.name}. For an NVIDIA GPU install:  pip install torch transformers peft trl "
                      f"datasets accelerate bitsandbytes   (on a Mac with Apple Silicon: pip install mlx-lm)")


def count_lines(path):
    try:
        return sum(1 for _ in open(path, encoding="utf-8"))
    except OSError:
        return 0


def run_logged(cmd, env=None):
    log("$ " + " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        print(line, flush=True)
        m = re.search(r"Iter (\d+)", line)
        if m:
            set_status(step=int(m.group(1)))
        if re.search(r"(loss|Iter|error|Error|it/s|Saved)", line):
            log(line[:200])
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} exited with {proc.returncode}")


def train(base=None, epochs=2.0, rank=16, lr=None, hf_model=None):
    persona, *_ = load_seahorse()
    base = base or persona.state.get("base_model", "llama3.1:8b")
    summary = prepare(quiet=True)
    n = summary["train"]
    if n < 10:
        raise SystemExit(f"Only {n} training examples. Chat with Seahorse more first "
                         f"(at least {MIN_EXAMPLES} replies is a good start).")
    if n < MIN_EXAMPLES:
        log(f"warning: only {n} examples; results will be modest (aim for {MIN_EXAMPLES}+)")
    trainer, problem = detect_trainer()
    if not trainer:
        set_status(stage="needs hardware", error=problem)
        raise SystemExit(problem)
    mlx_id, hf_id = BASE_MODELS.get(base, (None, None))
    model_id = hf_model or (mlx_id if trainer == "mlx" else hf_id)
    if not model_id:
        raise SystemExit(f"Don't know the Hugging Face version of {base}. Pass --hf-model <repo id>.")
    run = RUNS / datetime.now().strftime("%Y%m%d-%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    steps = max(20, math.ceil(epochs * n))
    set_status(stage="training", run=str(run), trainer=trainer, base=base, model=model_id, step=0, steps=steps,
               started=datetime.now().isoformat(timespec="seconds"), error=None, log=[])
    log(f"training {trainer} LoRA on {model_id} with {n} examples for {steps} steps")
    try:
        if trainer == "mlx":
            adapter = run / "adapter"
            run_logged([sys.executable, "-m", "mlx_lm", "lora", "--model", model_id, "--train",
                        "--data", str(DATA), "--iters", str(steps), "--batch-size", "1",
                        "--num-layers", "16", "--learning-rate", str(lr or 1e-5), "--mask-prompt",
                        "--adapter-path", str(adapter), "--steps-per-report", "10",
                        "--steps-per-eval", str(max(50, steps // 4)), "--save-every", str(max(100, steps // 2))])
            fused = run / "fused"
            set_status(stage="fusing")
            run_logged([sys.executable, "-m", "mlx_lm", "fuse", "--model", model_id, "--adapter-path", str(adapter),
                        "--save-path", str(fused), "--de-quantize"])
            tuned = {"kind": "fused", "path": str(fused)}
        else:
            adapter = run / "adapter"
            cuda_train(model_id, adapter, epochs, rank, lr or 1e-4)
            tuned = {"kind": "adapter", "path": str(adapter)}
        tuned.update(base=base, model=model_id, run=str(run), examples=n, trained=datetime.now().isoformat(timespec="seconds"))
        (run / "tuned.json").write_text(json.dumps(tuned, indent=2))
        set_status(stage="importing")
        ok, msg = import_to_ollama(tuned)
        if ok:
            tuned["ollama"] = TUNED_NAME
            (run / "tuned.json").write_text(json.dumps(tuned, indent=2))
        log(msg)
        set_status(stage="trained" if ok else "import failed", tuned=tuned, error=None if ok else msg)
        if ok:
            log("done - run `/finetune eval` to compare, then `/finetune use` to switch Seahorse to it")
        return tuned
    except Exception as e:  # noqa: BLE001
        set_status(stage="failed", error=str(e))
        log(f"failed: {e}")
        raise


def cuda_train(model_id, adapter_dir, epochs, rank, lr):
    """LoRA with PEFT + TRL. Written against current TRL; falls back for older argument names."""
    import torch
    from datasets import load_dataset
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer, TrainerCallback
    from trl import SFTConfig, SFTTrainer

    tok = AutoTokenizer.from_pretrained(model_id)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    kwargs = {"torch_dtype": torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
              "device_map": "auto"}
    try:
        from transformers import BitsAndBytesConfig
        import bitsandbytes  # noqa: F401
        kwargs["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                           bnb_4bit_compute_dtype=kwargs["torch_dtype"])
        log("loading in 4-bit (bitsandbytes)")
    except ImportError:
        log("bitsandbytes not installed - loading in 16-bit (needs more GPU memory)")
    model = AutoModelForCausalLM.from_pretrained(model_id, **kwargs)
    ds = load_dataset("json", data_files={"train": str(DATA / "train.jsonl"), "validation": str(DATA / "valid.jsonl")})
    lora = LoraConfig(r=rank, lora_alpha=rank * 2, lora_dropout=0.05, task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])

    class Progress(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kw):
            set_status(step=state.global_step, steps=state.max_steps)
            if logs:
                log(", ".join(f"{k} {v:.4g}" if isinstance(v, float) else f"{k} {v}" for k, v in logs.items()))

    cfg = dict(output_dir=str(adapter_dir.parent / "checkpoints"), num_train_epochs=epochs,
               per_device_train_batch_size=1, gradient_accumulation_steps=8, learning_rate=lr,
               lr_scheduler_type="cosine", warmup_ratio=0.05, logging_steps=5, save_strategy="no",
               bf16=kwargs["torch_dtype"] == torch.bfloat16, fp16=kwargs["torch_dtype"] == torch.float16,
               gradient_checkpointing=True, report_to=[])
    try:
        args = SFTConfig(**cfg, max_length=4096, assistant_only_loss=True)
    except TypeError:
        args = SFTConfig(**cfg, max_seq_length=4096)
    try:
        trainer = SFTTrainer(model=model, args=args, train_dataset=ds["train"], eval_dataset=ds["validation"],
                             peft_config=lora, processing_class=tok, callbacks=[Progress()])
    except TypeError:
        trainer = SFTTrainer(model=model, args=args, train_dataset=ds["train"], eval_dataset=ds["validation"],
                             peft_config=lora, tokenizer=tok, callbacks=[Progress()])
    trainer.train()
    trainer.model.save_pretrained(str(adapter_dir))
    tok.save_pretrained(str(adapter_dir))
    log(f"adapter saved to {adapter_dir}")


# ---------------------------------------------------------------------------
# IMPORT, EVAL, USE
# ---------------------------------------------------------------------------

def tuned_from_line(tuned):
    return f"FROM {tuned['path']}" if tuned["kind"] == "fused" else f"FROM {tuned['base']}\nADAPTER {tuned['path']}"


def import_to_ollama(tuned, name=TUNED_NAME):
    if not shutil.which("ollama"):
        return False, "Ollama isn't installed, so the tuned model couldn't be imported"
    persona, *_ = load_seahorse()
    mf = Path(tuned["run"]) / "Modelfile"
    body = persona.modelfile().split("\n")
    body = [tuned_from_line(tuned) if line.startswith("FROM ") else line for line in body]
    mf.write_text("\n".join(body))
    cmd = ["ollama", "create", name, "-f", str(mf)]
    if tuned["kind"] == "fused":
        cmd += ["--quantize", "q4_K_M"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return False, f"ollama create failed: {(r.stderr or r.stdout).strip()[:400]}"
    return True, f"imported into Ollama as '{name}'"


def ollama_chat(model, system, messages, base_url):
    import urllib.request
    body = json.dumps({"model": model, "stream": False, "options": {"temperature": 0.4},
                       "messages": [{"role": "system", "content": system}] + messages}).encode()
    req = urllib.request.Request(base_url + "/api/chat", data=body, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["message"]["content"]


def evaluate(n=20):
    """Tuned vs untuned on held-out conversations, judged blind (Claude if available, else the base model)."""
    import seahorse as sh
    base_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    persona, *_ = load_seahorse()
    base = persona.state.get("base_model", "llama3.1:8b")
    rows = [json.loads(l) for l in open(DATA / "valid.jsonl", encoding="utf-8")][:n] if (DATA / "valid.jsonl").exists() else []
    if not rows:
        raise SystemExit("No held-out examples yet - run prepare (and chat more) first.")
    key = os.environ.get("ANTHROPIC_API_KEY")
    judge = sh.ClaudeBackend(os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5"), key, 512) if key else None
    set_status(stage="evaluating", done=0, total=len(rows), log=[])
    wins = {"tuned": 0, "base": 0, "tie": 0}
    rng = random.Random(1)
    for i, r in enumerate(rows):
        system, convo, reference = r["messages"][0]["content"], r["messages"][1:-1], r["messages"][-1]["content"]
        try:
            a = ollama_chat(TUNED_NAME, system, convo, base_url)
            b = ollama_chat(base, system, convo, base_url)
        except Exception as e:  # noqa: BLE001
            raise SystemExit(f"Couldn't run the models: {e}")
        flip = rng.random() < 0.5
        first, second = (b, a) if flip else (a, b)
        question = (f"Conversation so far:\n{json.dumps(convo)[-3000:]}\n\nThe persona and instructions:\n{system[:2500]}\n\n"
                    f"The user's actual preferred style is shown by this past reply:\n{reference[:1500]}\n\n"
                    f"Reply 1:\n{first[:2000]}\n\nReply 2:\n{second[:2000]}\n\n"
                    "Which reply is better: more helpful and accurate, and more in character? Answer only 1, 2 or tie.")
        try:
            verdict = "".join(judge.stream("You judge replies fairly.", [{"role": "user", "content": question}])) \
                if judge else ollama_chat(base, "You judge replies fairly. Answer only 1, 2 or tie.",
                                          [{"role": "user", "content": question}], base_url)
        except Exception as e:  # noqa: BLE001
            raise SystemExit(f"Judge failed: {e}")
        v = verdict.strip().lower()
        pick = "tie" if "tie" in v else ("1" if v.startswith("1") else "2" if v.startswith("2") else "tie")
        if pick == "tie":
            wins["tie"] += 1
        else:
            tuned_won = (pick == "1") != flip
            wins["tuned" if tuned_won else "base"] += 1
        set_status(done=i + 1)
    total = sum(wins.values())
    report = dict(wins, total=total, tuned_win_rate=round(wins["tuned"] / max(1, total - wins["tie"]), 2),
                  judge="Claude" if judge else f"{base} (less reliable)", at=datetime.now().isoformat(timespec="seconds"))
    set_status(stage="evaluated", eval=report)
    log(f"tuned won {wins['tuned']}, untuned won {wins['base']}, ties {wins['tie']} (judge: {report['judge']})")
    return report


def latest_tuned():
    st = read_status()
    if st.get("tuned"):
        return st["tuned"]
    runs = sorted(RUNS.glob("*/tuned.json"))
    return json.loads(runs[-1].read_text()) if runs else None


def use(on=True):
    persona, *_ = load_seahorse()
    if on:
        tuned = latest_tuned()
        if not tuned:
            raise SystemExit("No tuned model yet - run train first.")
        persona.state["tuned"] = tuned
        msg = f"Seahorse now runs on the tuned model ({tuned['examples']} examples, {tuned['trained'][:10]})"
    else:
        persona.state.pop("tuned", None)
        msg = "Seahorse is back on the untuned base model"
    persona.save()
    ok, built = persona.build_ollama()
    return f"{msg}. {built}"


def status_text():
    st = read_status()
    if not st:
        return "No fine-tuning yet. Start with /finetune prepare."
    lines = [f"stage: {st.get('stage', '?')}  (updated {st.get('updated', '?')})"]
    ds = st.get("dataset")
    if ds:
        lines.append(f"dataset: {ds['train']} training + {ds['valid']} held-out examples from {ds['chats']} chats "
                     f"({ds['corrected']} corrected replies dropped, {ds['secret']} with secrets dropped, "
                     f"{ds['praised']} praised counted twice, {ds['distilled']} from Claude)")
        if ds.get("by_agent"):
            lines.append("by agent: " + ", ".join(f"{a} {c}" for a, c in sorted(ds["by_agent"].items(), key=lambda x: -x[1])))
        if not ds.get("enough"):
            lines.append(f"tip: {MIN_EXAMPLES}+ training examples give noticeably better results")
    if st.get("stage") == "training":
        lines.append(f"training: step {st.get('step', 0)} of {st.get('steps', '?')} on {st.get('model')} ({st.get('trainer')})")
    if st.get("stage") == "distilling":
        lines.append(f"distilling: {st.get('done', 0)} of {st.get('total', '?')} answers")
    if st.get("stage") == "evaluating":
        lines.append(f"evaluating: {st.get('done', 0)} of {st.get('total', '?')}")
    if st.get("eval"):
        e = st["eval"]
        lines.append(f"last eval: tuned won {e['tuned']}, untuned {e['base']}, ties {e['tie']} "
                     f"(win rate {int(e['tuned_win_rate'] * 100)}%, judge {e['judge']})")
    if st.get("error"):
        lines.append(f"problem: {st['error']}")
    try:
        from personality import Personality
        t = Personality.load().state.get("tuned")
        lines.append(f"in use: {'tuned model from ' + t['trained'][:10] if t else 'base model (untuned)'}")
    except Exception:  # noqa: BLE001
        pass
    if st.get("log"):
        lines.append("recent:")
        lines += ["  " + l for l in st["log"][-6:]]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Fine-tune Seahorse's local model on your conversations")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("prepare")
    d = sub.add_parser("distill")
    d.add_argument("--max", type=int, default=200)
    t = sub.add_parser("train")
    t.add_argument("--base")
    t.add_argument("--epochs", type=float, default=2.0)
    t.add_argument("--rank", type=int, default=16)
    t.add_argument("--lr", type=float)
    t.add_argument("--hf-model")
    e = sub.add_parser("eval")
    e.add_argument("--n", type=int, default=20)
    sub.add_parser("use")
    sub.add_parser("revert")
    sub.add_parser("status")
    args = ap.parse_args()
    if args.cmd == "prepare":
        prepare()
    elif args.cmd == "distill":
        distill(args.max)
    elif args.cmd == "train":
        train(args.base, args.epochs, args.rank, args.lr, args.hf_model)
    elif args.cmd == "eval":
        print(json.dumps(evaluate(args.n), indent=2))
    elif args.cmd == "use":
        print(use(True))
    elif args.cmd == "revert":
        print(use(False))
    else:
        print(status_text())


if __name__ == "__main__":
    main()
