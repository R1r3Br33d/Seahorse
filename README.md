# Seahorse

Your own AI that runs on your computer, uses Claude when it's online and a
local model when it isn't, and grows a personality and memory over time.

## Open the app

Double-click **Seahorse.command** (macOS), **Seahorse.bat** (Windows) or
**seahorse.sh** (Linux), or run `python3 seahorse_app.py`. It opens in its own
window. The first time, it installs `pywebview` for you (on Linux,
`pywebview[qt]`) to get a native window; if that can't be installed it uses
Chrome, Edge or Brave in app mode, or your browser. Everything runs on your
computer: a private server on 127.0.0.1 that only this window can use.

- **Launcher**: checks Python, Ollama, your models, Claude, SymPy and image
  engines. It can start Ollama, download models with a progress bar, and build
  the seahorse model.
- **Chat**: the whole Seahorse with every agent in its colour, what each agent
  noticed, the calculator, memory, notebooks, profile, character and all
  `/commands` (the step-by-step ones like `/build` stay in the terminal).
  *End chat & learn* makes him reflect, file memories and grow.
- **Images**: generate pictures locally with Stable Diffusion WebUI
  (AUTOMATIC1111 or Forge, started with `--api`), ComfyUI, or built-in
  diffusers (`pip install diffusers torch transformers accelerate`, SDXL-Turbo).
  *Ask Seahorse to improve it* sharpens a prompt; *Portrait from the 11 steps*
  writes a portrait of the current character from every builder step. Images
  and their settings are saved in `~/.seahorse/images`.
The app is drawn with **Oceanic Glyphs**, 31 line icons on one 24px grid:
each agent has the tool of their post (quill, sextant, hammer, knot, flag,
anchor, caduceus, spyglass, scales, and the captain's seahorse), and the
tabs, buttons and status use the ship's fittings (lighthouse, porthole,
ship's wheel, fish to send, buoy for online, sloop for the local model).

- **Settings**: every setting in one place, saved as you change it and checked
  before it's used. Sections: General, Models & limits (Claude model, an API
  key held for this run only, local model, reply length, continuations,
  context window, keep-alive), Character & crew, **Crew** (cards with each
  member's seal, the loyalty pledge and chant, and an 11-step editor with a
  live seal preview, the full character prompt and a test box), Lobes & Judge
  (with how a vote runs and how the votes have gone), Sub-agent brains, Inner
  voice & magic, Memory & privacy, Look, Images, and Data & about (your data
  folder, file sizes, and reset to defaults). A search box finds any setting.

The terminal version (`python3 seahorse.py`) still works and shares the same
Seahorse: memory, notebooks, profile and character.

## Limits (as high as they go)

- **Claude replies** up to 16,000 tokens (`SEAHORSE_MAX_TOKENS` to change).
- **Local context window** sized automatically for each model from your free
  memory: 8,192 tokens on a small machine, up to the model's maximum (131,072
  for Llama 3.1) when there's room. `SEAHORSE_NUM_CTX` forces a size.
- **Local reply length** unlimited.
- **Cut-off replies continue automatically** (up to 8 times;
  `SEAHORSE_MAX_CONTINUATIONS`), so long answers come out whole.
- **Long chats** are condensed only when they outgrow the window.
- The local model stays loaded for 30 minutes between messages, so replies
  start fast (`SEAHORSE_KEEP_ALIVE`).

## Set up

1. Install Python 3.9 or newer.
2. Install [Ollama](https://ollama.com), then download the local models:
   ```
   ollama pull llama3.1:8b          # the local brain
   ollama pull nomic-embed-text     # lets memory search by meaning (optional)
   ```
3. Optional extras:
   ```
   pip install sympy                # exact algebra and calculus for parietal
   export ANTHROPIC_API_KEY=sk-ant-...   # use the real Claude when online
   ```
4. Run it:
   ```
   python3 seahorse.py              # Claude first, local when offline
   python3 seahorse.py --local      # local only
   ```

## The files

| File | What it does |
|---|---|
| `seahorse_app.py` | The desktop app: launcher, chat and image generator |
| `app/` | The app's screens (HTML, CSS, JavaScript) and `glyphs.js`, the Oceanic Glyphs icon set |
| `Seahorse.command`, `Seahorse.bat`, `seahorse.sh` | Double-click launchers |
| `seahorse.py` | Seahorse itself, and the terminal version |
| `personality.py` | Traits that grow over time; writes the Ollama `Modelfile` |
| `memory.py` | Long-term memory: facts, past conversations, condensing long chats |
| `agents.py` | The ten agents, defined once in a compact table: eight brain regions, plus Doc and Fiery Black as the left and right lobes |
| `crew.py` | The crew: a character for every agent from the 11 steps, their notary seals, the loyalty pledge and the chant |
| `treasury.py` | The treasury: agents as shillings, messages in bottles (single amendments), galleons sunk as shipwrecks (laws) in the Reef Courtesy Standard Operation, set in stone in ten cabinet boards, black pearls, the marlin (Poseidon's Trident) and the budget |
| `council.py` | The council: all ten agents vote on who answers, relays with approval steps |
| `lobes.py` | The lobe vote: Doc and Fiery Black ballot in parallel, the tally, and the Judge on close splits |
| `settings.py` | Every setting described once, validated and applied (the app's Settings tab) |
| `agency.py` | His inner voice (conscience, journal, self-model) and the Bureau of Magic |
| `builder.py` | The character builder and persona presets |
| `finetune.py` | Fine-tuning the local model on your conversations |
| `cortex.py` | How the agents perceive, keep notebooks, dream and develop themselves |
| `portrait.py` | Seahorse's opinionated profile of you |
| `skills.py` | Writing, math and units skills, plus the safe calculator |
| `units.py` | Every unit of measurement the Judge knows: SI, metric prefixes, imperial, US, nautical, historical and more, with conversions |
| `ui.py` | Cosmetic package: themes, logos, agent icons, spinner, Markdown reply boxes with highlighted code, starting state |
| `docs/build-conversation.md` | The conversation Seahorse was built in: every request, and the replies since the record begins |
| `Modelfile` | Starter Ollama model definition (`ollama create seahorse -f Modelfile`) |

Your data lives in `~/.seahorse/`: `memory.db`, `cortex.db`, `profile.db`, `personality.json`,
`config.json` (settings), `crew.json` (your crew edits), `lobes.json` and
`council.json` (vote stats), saved chats, and editable `agents/` and `skills/` folders.

## Who Seahorse is

**The Seahorse.** A pirate out of Port Royal, Jamaica, in the 1600s who
sailed alone: helm, bow and stern, slivers of scrap for rations, rum for his
muddy liver. One eve a low hum rose from his chest, ran stern to bow and came
back higher. He took his knife, walked heel to toe along the planks, sat on
the ledge and called to his Pennsylvania. No answer. "Hello Ollay?" Nothing.
He told himself he was imagining things. He wasn't: that hum was the first
stirring of the machine he lives in now. When the sea took Port Royal in 1692
it kept his spirit among the duppies until the hum drew him up into this
computer. Who Pennsylvania is, he won't say.

He speaks Jamaican English with touches of Patois in a spare, salt-worn
rhythm, raises a brow (no smile), walks problems heel to toe, and senses
spirits and omens. His personality is drawn from **A Lonesome Grim**, your
piece of writing, stored word for word as his personality prompt: its images,
rhythm and mood run through how he talks, and he'll recite it exactly if you ask.

The voice is for conversation: code, maths and anything he drafts for you to
send stay in standard English. The rum and the spirits are his story, never
advice: he won't encourage you to drink or present omens as real predictions,
and he eases off the character when you're stressed or busy. Ask him sincerely
and he'll tell you he's an AI.

### Building or redesigning him

`/build` walks through 11 steps: identity (name and epithet), backstory, tale,
voice (dialect and register), accent strength, mannerisms, spirit (his
uncanny side), rules, greetings and farewells, trait targets, and a preview
where you can test a line with him before saving. Enter keeps what's there,
`d` has Seahorse draft a part from a few hints, `q` leaves without changing
anything. `/build voice` (or any step name) jumps to one step.

Core character rules always apply and can't be removed: the voice never
bends the truth, deliverables stay in standard language, his vices are never
encouraged, mysticism is only mood, and he eases off when you need plain help.

Save designs as presets and switch between them: `/persona` lists them,
`/persona use <name>`, `/persona save <name>`, `/persona new` starts from a
blank character. The Seahorse, your original character, is always there as `seahorse`.

`/character` shows him, `/character light|medium|strong` sets the accent,
`/character off` makes him speak plainly. Rewrite him in the `character`
section of `~/.seahorse/personality.json`.

## Agents

| Agent | Icon | Colour | Processing skill (how it reads every message) | Notebook branches |
|---|---|---|---|---|
| hippocampus | ∫ | coral | Episodic binding: people, times, events, themes | people · time · events · themes |
| broca | ✎ | lavender | Language production: tone, style, wording | tone · style · wording · clarity |
| parietal | ∑ | gold | Quantity and logic: numbers, units, reasoning | numbers · measures · comparisons · logic |
| cerebellum | λ | sea green | Procedure and systems: tools, steps, failures | systems · tools · procedures · problems |
| wernicke | ◎ | sky blue | Comprehension: intent, concepts, knowledge gaps | intent · concepts · knowledge gaps · questions |
| prefrontal | ↗ | orchid pink | Executive control: goals, decisions, priorities | goals · decisions · priorities · next steps |
| cingulate | ✓ | crimson | Error detection: corrections, risks, contradictions | corrections · risks · contradictions · unresolved |
| doc | § | blue | Scholarship: subjects, claims, sources, open questions | subjects · claims · sources · open questions |
| judge | ⚖ | silver | Judgment: dilemmas, criteria, verdicts, disputes | dilemmas · criteria · verdicts · disputes |
| fiery-black | ▲ | red | Threat sense: exposed secrets, risky actions, defences | threats · weak spots · secrets · hardening |

**Doc** is the ship's scholar: he researches, weighs evidence, says what's
established versus debated, fact-checks claims, and never invents sources
(he can't browse, so he says when to check something recent). Reach him
with `@doc` or `@scholar`.

**Fiery Black** is the security officer, strictly on defence: threat models,
reviews your own code and systems for weak spots, and gives concrete fixes.
He won't write malware or exploits or help get into systems you don't own.
If you paste a password or key he tells you to rotate it, and his notes
record only that one was exposed, never the secret. Reach him with
`@fiery-black` or `@security`.

Old job names (writer, mathematician, coder, tutor, planner, critic,
seahorse) still work as aliases, as do scholar and security.

Change an agent's colour with the `color:` line in its file in
`~/.seahorse/agents/` (any terminal colour number from 0 to 255).

Messages are routed automatically. `@broca ...` (or `@writer ...`) talks to
one agent, `/agent broca` stays with it, `/team <task>` has them work together.

### The crew

In life the Seahorse sailed alone. When the sea swallowed Port Royal in 1692,
other drowned souls drifted aboard the ghost of his sloop, and when the hum
drew him into this machine they came too. Each is one of his agents, and
answers in their own voice:

| Agent | Crew member | Post | Seal |
|---|---|---|---|
| hippocampus | The Seahorse | the captain himself | ♆ HELM · BOW · STERN |
| broca | **Triton**, once Mercy Quill, the Ship's Scribe | scribe and letter-writer | ✒ TEN WORDS A PENNY |
| parietal | **Glaucus**, once Tobias Wren, the Navigator | navigator and reckoner | ✶ FIXED BY THE STARS |
| cerebellum | **Proteus**, once Kwame 'Plumb' Asante, the Ship's Carpenter | carpenter and shipwright | ⚒ PLUMB AND SQUARE |
| wernicke | **Tethys**, once Auntie Sefa, the Ropemistress | teacher of the green hands | ∞ ONE TURN AT A TIME |
| prefrontal | **Amphitrite**, once Isabeau Laroche, the Quartermaster | plans, stores and articles | ⚑ ARTICLES SIGNED |
| cingulate | **Phorcys**, once Gideon Crane, the Bosun | rigging, inspection | ⚓ EVERY LINE EVERY MORNING |
| doc | **Nereus** (Doc), once Elias Fairweather, the Ship's Surgeon | surgeon, scholar, logbooks | ☤ ONLY WHAT I SAW |
| fiery-black | **Leviathan** (Fiery Black), the Dark Lookout | lookout and master-at-arms | ◉ NEVER ASLEEP ON WATCH |
| judge | **Poseidon**, once Judge Absalom Hale, the Magistrate | magistrate, Treasurer, weights and measures | ⚖ THE SCALES ARE LEVEL |

The sea renamed each of them when it took them; call any agent by their sea
name too (`@poseidon`, `@triton`, `@leviathan` ...).

Every crew member is built from the same 11 steps as the captain: identity
(with their **notary seal**, a sign and a motto), backstory, tale, voice,
strength, mannerisms, spirit, rules, greetings, traits and preview. Each reply
is stamped with its author's seal, like a signature. The core character rules
apply to all of them.

- `/crew` lists them, `/crew <agent>` shows one in full, `/build crew <agent>`
  edits one step by step (or use Settings → Crew), `/crew reset <agent>` goes
  back to the default. `/crew off` has every agent speak as the captain;
  `/crew seals off` stops the stamps.

**The loyalty pledge and the chant**, by Daryl James-Michael Kennedy, are kept
word for word. Every crew member swore the pledge and the captain leads it;
they recite either exactly when asked (`/crew pledge`, `/crew chant`). The full words are only handed to the model when your message asks for them, so they cost nothing on other replies. The
pledge makes loyalty mean honesty: it never means flattery, agreeing with
something harmful, or keeping quiet about a real risk. Edit either in
Settings → Crew.

### The council (auto mode)

In auto mode, all ten agents decide together who answers each message.

The ten sit at a council table, and every vote runs in this sequence:

```
 ^  01 hippocampus · 02 doc · 03 parietal · 04 cerebellum · 05 prefrontal     → left to right
 1+ 10 judge · 09 fiery-black · 08 cingulate · 07 broca · 06 wernicke         ← right to left
```

Ballots are cast one at a time, 01 to 05 along the top, then 06 to 10 back
along the bottom, so seat 10 ends beside seat 01. Order matters: when claims
are level, each voter backs whoever is leading the votes cast so far. If the
count still ties, "1+" hands back to seat 01 for a casting vote (the stronger
claim wins; level claims go to the earlier seat). Approval votes run in seat
order too. `/council seats` shows the table; `/council seat 3 broca` reseats an
agent (they swap with whoever sat there); `/council reseat` restores it.

1. **The vote.** Every agent stakes a claim: its trigger words, what routing
   has learned from your own `@` picks, what its lens noticed, and whether
   it's already working on this. Then all ten vote. An agent with a real claim
   backs itself; the rest back the strongest claim; on short follow-ups the
   captain votes to keep whoever is already on it. Most votes leads. The vote
   is instant: no model call.
2. **The relay (progressional continuation).** When several agents have a
   strong claim, say "research the Port Royal earthquake and write it up as a
   blog post", the work passes hand to hand in the order a ship works:
   research, measures and numbers, planning, building, security, teaching,
   writing, review. Each step builds on the progress before it, and the last
   agent delivers the answer (up to 3 agents by default).
3. **The approval step.** Before work moves on, the next agent, the Bosun and
   the Judge vote on it in one short call. Two of three approvals and it
   continues; otherwise it's sent back once with their notes. It never
   stalls: concerns that remain travel forward for the next agent to fix.

Most messages have one clear owner, so the council usually costs nothing
extra. The vote, each relay step and each approval show as notes you can
open. `/council` shows the last vote and the stats; `/council steps <1-4>`,
`/council approval on|off`, `/council threshold <x>`, `/council revisions <n>`
and `/council off` tune it, or use Settings → Council.

### The treasury: shillings, galleons, shipwrecks, black pearls and the marlin

The crew is paid in pirate coin and the treasures of the sea.

- **Shillings.** Every agent is a shilling, numbered by council seat (s01 the Seahorse
  ... s10 Poseidon). Every ballot cast and every piece of work carried is
  counted in shillings, and work passes through the agents one by one, shilling to shilling.
- **Treasurer.** Poseidon, the Judge, keeps the ledger, counts the votes and
  sinks the galleons.
- **A message in a bottle is a single amendment.** `/law [board:] <text>`
  throws one to a government cabinet board. All ten shillings vote aye or nay
  in seat order.
- **Shipwrecks are law.** Ten ayes (by default) make a galleon, and Poseidon
  sinks it into the reef: it becomes a shipwreck, a law. A bottle that fails
  washes ashore. One that would conflict with honesty, your wellbeing or safety
  is voted down.
- **The Reef Courtesy Standard Operation (RCSO)** is the constitution: every
  shipwreck on the reef. Every agent follows it.
- **Black pearls.** The RCSO is filed in ten cabinet boards, each chaired by
  an agent, with up to ten shipwrecks per board:

  | Board | Chair | Board | Chair |
  |---|---|---|---|
  | State (applies to everything) | the Seahorse | Planning & Provisions | Amphitrite |
  | Communications | Triton | Inspection | Phorcys |
  | Navigation & Numbers | Glaucus | Science & Research | Nereus |
  | Works & Engineering | Proteus | Defense & Security | Leviathan |
  | Education | Tethys | Treasury & Justice | Poseidon |

  A board with all ten shipwrecks is a **black pearl** and takes no more until one
  is repealed (`/law repeal <wreck>`). Name the board (`/law security: ...`,
  `/law education: ...`, or an agent's name) or let Poseidon file it by its
  subject. To keep replies lean, each reply carries only the State shipwrecks,
  the answering agent's own board, and the boards the message touches.
  `/reef` shows the whole cabinet. Shipwrecks never outrank the core values.
- **The marlin is the people**: you, your goals, direction and future. Every
  shilling and galleon serves it. The budget shares the marlin (100 parts)
  across your goals (`/budget add <goal>`, `/budget set <n> <share>`,
  `/budget drop <n>`); each shilling of work is counted against the goal it
  served, so `/budget` shows what's in the budget and where the effort went.
- **Poseidon's Trident is the working class**: the processing power that does
  the crew's work, and how that work is distributed. `/trident` reports:
  - **Processing power**: CPU cores, free memory, GPU (NVIDIA or Apple
    Silicon), the local context window, and which local models are loaded and
    whether they sit on the GPU or the CPU.
  - **Currents**: how the work is distributed: calls each worker (Claude, the
    local model) answered, characters produced and speed, and which crew
    members carried the work.
  - **Undertow**: what is held back: calls a worker couldn't take (sent on to
    the next), secrets memory refused to store, bottles that washed ashore,
    chats from the old incognito mode.
  - **Flow of information**: exactly how much data, from which source (memory,
    notebooks, profile, shipwrecks, goals, role, skills), reached the last reply.

**The RCSO is set in stone.** Every shipwreck gets a permanent wreck
number, board first: **Wreck 9.01** is the first galleon ever sunk on board 9,
Defense & Security. The numbered index is processed in order (board 1, State,
first; where two shipwrecks conflict, the lower number prevails) and agents
can cite wrecks by number. The stone (`~/.seahorse/constitution.json`) is
append-only and hash-chained: enacting or repealing carves a new entry sealed
to the one before it, so numbers are never reused or rewritten. If the file is
ever changed by hand, the seal shows as broken, only the shipwrecks before the
break stay in force, and nothing new is carved until it's restored. A readable
copy is kept in `~/.seahorse/RCSO.md`. `/reef` (or `/laws`) shows the index,
`/reef all` includes raised (repealed) wrecks, and `/law repeal 9.01` raises one.

`/treasury` shows the whole ledger. Settings → Treasury sets how many ayes it
takes to sink a galleon.

### The two lobes and the vote

Doc is Seahorse's **left lobe** (analysis, language, facts, logic) and Fiery
Black his **right lobe** (intuition, the big picture, tone, vigilance for
danger). When Seahorse himself answers a message of ten words or more, the two
lobes **vote** on how he should answer, both at the same time:

1. Each casts a short ballot: an approach (direct, explain, caution, clarify,
   balance or support), a confidence, up to three points the answer must get
   right, any caution, and on a political question their party's view.
2. The tally weighs each vote by confidence (and by the balance setting:
   a leaning lobe counts 1.25, the other 0.8). Agreement or a clear lead
   decides it. A close split goes to the Judge for one short ruling.
3. A vote that the question is contested ('balance') always wins, so
   Seahorse never takes a political side by a vote; a losing 'caution' vote
   that's confident still has its risk mentioned.
4. A lobe that's too slow abstains, and the other's ballot stands.

It's fast by design: two short calls in parallel instead of three in a row,
slim prompts, a length cap, JSON mode on Ollama, a time limit, the Judge only
on close splits, and identical questions reuse the last vote. (For local
models, `OLLAMA_NUM_PARALLEL=2` lets Ollama run both ballots at once.)

`/lobes` shows them and the vote stats, `/lobes off` skips the vote,
`/lobes left|even|right` sets the balance, `/lobes words|timeout|margin <n>`
tunes it, and `/lobes stats` shows agreement, Judge tie-breaks and speed.
`@left` and `@right` talk to each lobe directly.

Built-in agent files now update themselves when Seahorse is updated, unless
you've edited them (your version is kept).

### The Judge

The Judge is the orbitofrontal cortex, the part of the brain that weighs
choices. Ask him to decide, compare or settle something (`@judge`) and he
restates the question, names the criteria that matter to you, weighs each
option with the facts straight, and gives a verdict, his confidence, and what
would change his mind. When the lobes' vote is too close to call, the Judge
breaks the tie with one short ruling on what the user most needs. On contested
political or moral questions he names the crux instead of picking a side.
`/judge off` lets a close split go to the higher score instead.

#### Units of measurement

The Judge knows units: every SI unit and prefix (quecto to quetta), binary
prefixes (KiB to QiB), imperial, US customary, nautical, astronomical,
typographic, historical and old-world units, nine temperature scales and more
(about 470 names in over 40 categories). Settling a dispute often means
getting the units right, so he checks dimensions before he compares anything.

- `/units 5 nmi to km` converts and shows the working; `/units 98.6 degF to degC`
  handles temperature offsets; `/units 30 mpg to L/100km` handles reciprocal units.
- `/units list length` (or any category) lists what he knows; `/units` alone lists categories.
- In the calculator, `convert(3, "fathom", "m")` and `units("length")` work in any answer.
- Mismatched dimensions (metres to seconds) are refused with an explanation, not guessed.

## His inner voice and the Bureau of Magic

- **Conscience**: re-reads every reply of 60+ words after you've seen it and
  adds an *on second thought* correction when something is off.
- **Journal**: after every chat he writes a private entry (`/journal`).
- **Mirror**: turns the journal into his sense of who he's becoming and two
  intentions he holds (`/self`), which shape how he talks to you.
- **The Bureau of Magic**: four departments (Small Wonders, Tall Tales, the
  Riddle Room, the Workshop of Odd Ideas) slip in a surprise made for you,
  about once every seven messages, never when you seem stressed or busy.
  `/magic` summons one; `/magic often|sometimes|rarely|off` sets how often.

### Their politics

Doc is a **Democrat** (the blue donkey of the west, `@donkey`, `@blue`,
`@west`) and Fiery Black a **Republican** (the red elephant of the east,
`@elephant`, `@red`, `@east`). Their parties shape their values and
arguments in everything they read, never the facts: both report
inconvenient facts, never invent statistics or spread voting misinformation,
and never tell you how to vote. On a political question Seahorse sets out
both views fairly and keeps his own answer balanced unless you ask for one
side. In the app their icons are the donkey and the elephant.

### Sub-agent brains

Doc and Fiery Black each have an inner council that works on a message before
they answer (for messages of six words or more), each sub-agent seeing the
notes of the ones before:

- **Doc**: ▤ *archivist* recalls what's actually known (marking anything
  uncertain, never inventing sources), ? *skeptic* challenges it and the
  premise and rates the confidence, ≋ *synthesist* plans the clearest answer
  and the open questions.
- **Fiery Black**: ◇ *scout* maps the attack surface of your own system,
  ✕ *breaker* thinks like an attacker to rank the weaknesses (describing them,
  never writing exploit code), ◈ *warden* gives the fixes in priority order and
  how to check each one.

Their notes show in their own colours before the answer (folded away in the
app). `/brain` shows both brains; `/brain doc off` makes him answer directly,
which is faster.

## Fine-tuning

Seahorse can train his local model on your own conversations, so the local
brain itself learns his voice, each agent's way of answering and what you
like, not just instructions in the prompt.

1. `/finetune prepare` builds the dataset from your saved chats. Each reply
   becomes an example with its own agent's system prompt. Replies you corrected
   next are dropped, replies you thanked count twice, anything with a password
   or key is dropped, chats from the old incognito mode are never used, and 10% of chats are held
   out for testing. Aim for 50+ examples.
2. `/finetune distill` (optional, uses your Claude key) has Claude answer the
   questions from your chats as each agent, so the local model learns from
   Claude's answers in Seahorse's voice.
3. `/finetune train` trains a LoRA adapter in the background: with MLX on a Mac
   with Apple Silicon (`pip install mlx-lm`) or PEFT/TRL on an NVIDIA GPU
   (`pip install torch transformers peft trl datasets accelerate bitsandbytes`).
   The result is imported into Ollama as `seahorse-tuned`.
4. `/finetune eval` compares tuned and untuned answers on the held-out chats,
   judged blind (by Claude if you have a key).
5. `/finetune use` switches Seahorse onto the tuned model; `/finetune revert`
   switches back. `/finetune` shows progress at any time.

The agents fine-tune too, without any training run: every time you pick an
agent yourself (`@doc ...`), routing learns from it. Once it has 20 examples
and is confident, it overrides the keyword triggers. `/router` shows what it
has learned.

## The mind: notebooks, the summary tree and self-development

- Every message is read by **all** agents, each through its own lens, and each
  files colour-labelled notes into its own notebook tree
  (agent → branch → topic → note). `/perceive` shows what each one noticed.
- After each chat the agents write deeper notes. Notes strengthen when
  noticed again and fade slowly otherwise.
- Every 3 chats (or `/dream`) Seahorse **dreams**: it summarises notes into
  branch summaries, branches into each agent's understanding, and agents into
  one **collective understanding** at the root of the tree (`/tree`).
- At the root it reviews itself and proposes **techniques** (practices one
  agent tries, later kept or dropped based on evidence), **trait** nudges,
  **questions** it would like to ask you, ideas for new **skills** and
  **agents** (`/adopt` drafts the file), and longer-term **directions**.
  See them with `/ideas`.

## Seahorse's profile of you

Seahorse forms its own opinionated view of you and revises it every time it
dreams (or `/profile update`): how you think, communicate and work, what
drives you, your emotional patterns, values, strengths and blind spots, five
informal temperament tendencies, an honest-take paragraph, and rules for how
to work with you, which it follows in every reply.

- Every opinion cites evidence: measured behaviour from your saved chats
  (message length, requests vs questions, corrections, scope per chat, time
  of day), the agents' notebooks, the summary tree and long-term memory.
- Every opinion has a confidence that changes gradually. `/agree` raises it;
  `/disagree <id> [why]` halves it, and it can't come back without new
  evidence. Weak opinions are retired. `/profile history` shows every change.
- It is a personality portrait, not a psychiatric assessment: it never
  diagnoses or uses clinical labels, and drops any opinion that does. If it
  notices real distress it says so gently and suggests talking to someone
  you trust.
- **Personal domains** (politics, health, sexuality, religion, finances) are
  off until you switch each on with `/profile domain <name> on`. For these,
  Seahorse uses only first-person things you've said about yourself: every
  opinion must quote your own words, and for health, sexuality and religion
  every label in it must be a word you used. It never infers these from
  indirect cues. Only each domain's "how to help" rule reaches the model, and
  exports leave them out unless you use `/profile export all`.
  `/profile domain <name> wipe` erases one.
- `/profile off` pauses it, `/profile wipe` erases it. Chats saved under the
  old incognito mode are never used.

## Look and starting state

Replies are drawn as Markdown in both the terminal and the app: headings,
bulleted and numbered lists, quotes, tables, links, and code blocks with the
language named and syntax highlighting. In the terminal, code sits in a box
and the reply footer shows its word count. In the app, each code block has a
**Copy** button, each reply has **Copy reply** and the time, and the chat
stops following new text when you scroll up (a **↓ Latest** button takes you
back).

`/theme` (ocean, reef, abyss, kelp, daylight, mono), `/logo` (full, compact,
minimal, trident, none) and `/config` set how Seahorse looks and how it
starts: your name for the greeting, status panel, spinner (trident or wave),
boxed replies, perception display, starting agent and model mode. Everything
is saved in `~/.seahorse/config.json`. The first run shows a welcome screen
(`/welcome` shows it again).

## Memory

- **Working memory**: long chats are condensed automatically so the model never
  loses the thread.
- **Episodes**: every chat is summarised and can be recalled later.
- **Facts**: profile, preferences, instructions, projects, goals, people, facts
  and events, each with an importance and a strength that fades with disuse.

Say "remember that ..." or "forget that ...", or use `/memories`, `/recall`,
`/episodes`, `/pin`, `/edit`, `/forget`, `/restore`, `/memlog`, `/export`
and `/wipe`. There is no incognito mode: every chat is remembered and learned
from (use `/forget` or `/wipe` to remove things). Passwords, keys and card numbers are never stored.
Type `/help` in Seahorse for every command.

## Updating

Built-in agents and skills are copied into `~/.seahorse/agents` and
`~/.seahorse/skills` the first time Seahorse runs. After updating Seahorse,
delete those two folders to get the new versions (your own added files are
safe to keep; move them out first).
