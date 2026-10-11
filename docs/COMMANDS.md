# Seahorse commands

Every command Seahorse has, read from its code on 2026-10-11: 82 commands and 37 aliases. Type `/` in the app to see them as you type, or `/help` in the terminal. Refresh this page with `python3 atlas.py --commands docs/COMMANDS.md`.

**Sections:** [Basics](#basics) · [Agents](#agents) · [Skills](#skills) · [Mind](#mind) · [Profile](#profile) · [Look](#look) · [Memory](#memory) · [Fine-tuning](#fine-tuning) · [Inner voice and the Bureau of Magic](#inner-voice-and-the-bureau-of-magic) · [Character](#character) · [Personality](#personality) · [Governance: the council, the reef and the board](#governance-the-council-the-reef-and-the-board) · [The purse: pay, change and the spine](#the-purse-pay-change-and-the-spine) · [The sea: what powers Seahorse](#the-sea-what-powers-seahorse) · [Seahorse's map](#seahorses-map)

## Basics

| Command | What it does | Also |
|---|---|---|
| `/local-model <name>` | set the local Ollama model |  |
| `/mode auto/claude/local` | switch backend (auto = Claude, fall back to local) |  |
| `/model <name>` | set the model for the current backend |  |
| `/models` | list installed local models |  |
| `/system <text>` | override the system prompt for this chat only |  |

## Agents

| Command | What it does | Also |
|---|---|---|
| `/agent <name>/auto` | stay with one agent, or route each message automatically |  |
| `/team <task>` | planner splits the task, agents each do a part, Seahorse combines |  |

## Skills

| Command | What it does | Also |
|---|---|---|
| `/calc <expression>` | use the calculator directly, e.g. /calc 1250*(1+0.045/12)**60 |  |
| `/skill <name> on/off/auto` | always use, never use, or use when relevant |  |
| `/skills` | list skills and which are active |  |
| `/units <n> <from> to <to>` | convert any unit, e.g. /units 3 furlongs to m · /units list [category] |  |

## Mind

| Command | What it does | Also |
|---|---|---|
| `/adopt <id> / /drop <id>` | try or create an idea, or discard it |  |
| `/agents` | each agent's purpose, processing skill, note colours and practices |  |
| `/dream` | summarise everything and generate self-development ideas now |  |
| `/adopt <id> / /drop <id>` | try or create an idea, or discard it |  |
| `/ideas [all]` | techniques on trial, proposals, questions, directions |  |
| `/notes [agent]` | the agents' notebooks as colour-coded trees |  |
| `/perceive [on/off]` | show what each agent notices in your messages |  |
| `/tree [1-3]` | the collective summarization tree |  |

## Profile

| Command | What it does | Also |
|---|---|---|
| `/agree <id>` | confirm an opinion |  |
| `/disagree <id> [why]` | correct one - it loses confidence and needs new evidence to return |  |
| `/profile` | the portrait: honest take, opinions with confidence, temperament |  |

## Look

| Command | What it does | Also |
|---|---|---|
| `/config [setting value]` | the default starting state (name, greeting, spinner, ...) |  |
| `/logo [style]` | full, compact, minimal, trident, none |  |
| `/theme [name]` | ocean, reef, abyss, kelp, daylight, mono |  |
| `/welcome` | show the welcome screen again |  |

## Memory

| Command | What it does | Also |
|---|---|---|
| `/consolidate` | tidy memory now (fade, merge, index) |  |
| `/edit <id> <new text>` | correct a memory |  |
| `/episodes [n]` | recent conversations |  |
| `/export [file.md]` | export all memories as Markdown |  |
| `/forget <id/words>` | forget a memory (it's archived, so /restore can undo) |  |
| `/memlog [n]` | what changed in memory, and why |  |
| `/memories [words/category]` | list what Seahorse knows, or search it |  |
| `/memory` | memory overview |  |
| `/pin <id> / /unpin <id>` | pinned memories are always in mind and never fade |  |
| `/recall <words>` | search memories and past conversations |  |
| `/remember <fact>` | save something now |  |
| `/restore <id>` | bring back a forgotten memory |  |
| `/revisit <episode id>` | bring a past conversation's summary into this chat |  |
| `/pin <id> / /unpin <id>` | pinned memories are always in mind and never fade |  |
| `/wipe` | erase all memories (asks first) |  |

## Fine-tuning

| Command | What it does | Also |
|---|---|---|
| `/brain [agent on/off]` | Doc's and Fiery Black's sub-agent brains |  |
| `/finetune` | progress and what's in use ($0.00-$1.00), read the dataset's worth, train it |  |
| `/router [reset]` | routing that learns from the agents you pick with @name |  |

## Inner voice and the Bureau of Magic

| Command | What it does | Also |
|---|---|---|
| `/journal [n/lessons/all]` | his private journal, written after each chat | `/self` `/conscience` `/magic` |

## Character

| Command | What it does | Also |
|---|---|---|
| `/build [step]` | design him step by step: identity, backstory, tale, voice, strength, mannerisms, spirit, rules, greetings, traits, preview (test + save) |  |
| `/character` | the Seahorse: his personality piece (A Lonesome Grim), story, voice, mannerisms and spirit-sense |  |
| `/persona [use/save/delete/new] <name>` | saved personas (the Seahorse is built in) |  |

## Personality

| Command | What it does | Also |
|---|---|---|
| `/clear` | start a fresh conversation |  |
| `/help` | this list |  |
| `/load <file>` | load a saved chat |  |
| `/modelfile` | write the Modelfile and rebuild the Ollama model |  |
| `/more <trait>` | more of a trait now (also raises its target) | `/less` |
| `/newtrait <name> / <low> / <high>` | add a trait to grow |  |
| `/quit` | exit | `/exit` `/q` |
| `/reflect` | learn from this chat right now |  |
| `/rollback` | undo the last personality change |  |
| `/save` | save this chat to ~/.seahorse/chats |  |
| `/status` | show what's connected |  |
| `/target <trait> <0-1>` | set what a trait grows toward |  |
| `/traits [agent]` | show Seahorse's traits overall, or as one agent sees them |  |

## Governance: the council, the reef and the board

| Command | What it does | Also |
|---|---|---|
| `/board [sub] [...]` | the governance board: high council, seats, reef, purse, season on one page; /board seats · laws · law <bottle> · repeal <wreck> · pay · budget · quarters · crew ... | `/governance` `/gov` |
| `/budget` | the marlin is the people: your goals, direction, future - and what's in the budget | `/dollar` `/goal` `/goals` `/marlin` |
| `/council` | how all ten agents voted on who answers (auto mode), and the stats |  |
| `/crew` | his crew: every agent's character (name, post, greeting) |  |
| `/judge [on/off]` | the Judge breaking split votes (talk to him with @judge) |  |
| `/law [board:] <text>` | throw a message in a bottle (a single amendment) to a cabinet board; all ten shillings vote; ten ayes make a galleon, sunk into the reef as a shipwreck: a law (boards: state, communications, navigation, works, education, planning, inspection, science, defense, treasury) | `/wreck` |
| `/laws` | the Reef Courtesy Standard Operation (RCSO, the constitution), set in stone: a numbered index (Wreck 9.01 = board 9, first wreck), hash-chained and append-only; 10 shipwrecks per board, a full board is a black pearl (/laws works too) | `/rcso` `/reef` `/wrecks` |
| `/lobes [on/off/left/even/right]` | Doc (left lobe) and Fiery Black (right lobe) vote on how Seahorse answers |  |
| `/quarters` | the four seasons and their horsemen: the treasury's books by quarter | `/horsemen` `/quarter` `/seasons` |
| `/treasury` | the treasury: every agent a shilling, the Kraken (the Judge) as Treasurer, the reef |  |

`/board` runs any of these as a sub-command: `/board approval` = `/council approval`, `/board bottle` = `/law`, `/board budget` = `/budget`, `/board change` = `/change`, `/board council` = `/council`, `/board crew` = `/crew`, `/board goal` = `/budget add`, `/board horsemen` = `/quarters`, `/board law` = `/law`, `/board laws` = `/laws`, `/board lobes` = `/lobes`, `/board pay` = `/pay`, `/board purses` = `/pay`, `/board quarters` = `/quarters`, `/board reef` = `/laws`, `/board repeal` = `/law repeal`, `/board seats` = `/council seats`, `/board steps` = `/council steps`, `/board treasury` = `/treasury`, `/board trident` = `/trident`.

## The purse: pay, change and the spine

| Command | What it does | Also |
|---|---|---|
| `/change` | the change: coins, how a reply's worth is counted, each agent's purse |  |
| `/orez` | ZERO in reverse: undo the last Treasurer move | `/undo-pay` |
| `/pay` | the payroll: every agent's purse in change, and the last payments | `/payroll` `/purse` `/purses` `/wages` |
| `/spine [full]` | the spine: every payment a numbered, hash-sealed vertebra, filed in portions of 1,000; checks it (full replays everything from zero) | `/sequence` `/sequencer` |
| `/zero [Z/E/R/O ...]` | ZERO spells MDAS: Zoom the size (x), Even split (/), Reward (+), Owed out (-) | `/cipher` `/cypher` `/mdas` |

## The sea: what powers Seahorse

| Command | What it does | Also |
|---|---|---|
| `/compass` | the NEWS: the horsemen at each point, and lightning strikes on the instruments | `/news` |
| `/locker` | Davy Jones' Locker: the core's pulse and the hourglass of the two hemispheres | `/core` `/davy` |
| `/pockets [words]` | treasure pockets, the oil reserves (blood of the gods): ideas scrapped in past chats | `/oil` `/reserves` |
| `/trench` | the Mariana Trench: the undertow, everything held back and how deep it has sunk | `/undertow` |
| `/trident` | Poseidon's Trident, the working class: processing power and how the work is distributed |  |

## Seahorse's map

| Command | What it does | Also |
|---|---|---|
| `/map [commands/tree/usage]` | Seahorse's own map, read from its code: every command, the module tree, what you use | `/atlas` `/architecture` |

## Anywhere in a message

| Write | What happens |
|---|---|
| `@octopus draft a letter` | sends one message to an agent by crew name, agent name or alias |
| `remember that ...` / `forget that ...` | saves or removes a memory |
| a line ending in `\` | keeps typing on the next line (terminal) |
