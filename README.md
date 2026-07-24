# Detroit AI Player — Let LLMs Play *Detroit: Become Human*

**English** | [简体中文](README.zh-CN.md)

[![Tests](https://github.com/Baba88611/detroit-ai-player/actions/workflows/tests.yml/badge.svg)](https://github.com/Baba88611/detroit-ai-player/actions/workflows/tests.yml)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Code License: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](LICENSE)
[![Data License: CC BY--NC 4.0](https://img.shields.io/badge/data-CC_BY--NC_4.0-lightgrey.svg)](docs/legal/CC-BY-NC-4.0.txt)

> Turn a branching narrative into structured decision-tree data, then let **your AI**
> (DeepSeek, GPT, Claude, or any OpenAI-compatible model) play through it autonomously.
> Observe how it handles hostage negotiations, life-or-death choices, violence,
> nonviolence, and other moral dilemmas.

⚠️ This is a non-commercial research project. It contains no game assets and is not
affiliated with Quantic Dream or Sony. Please read **[DISCLAIMER.md](DISCLAIMER.md)**
before using it.

**License boundary:** runner code is licensed under MIT; decision trees, configuration,
text, and diagrams are licensed under CC BY-NC 4.0 (non-commercial). See the complete
file-by-file mapping in [docs/legal/README.md](docs/legal/README.md).

---

## What can you observe?

The project turns the branches of a narrative-driven game into decision-tree JSON.
Your AI makes each choice node by node, allowing you to observe:

1. **Do different models make systematically different choices in the same moral dilemmas?**
2. **How much does the same model's behavior shift under different personas?**
3. **Are an AI's choices stable when the same scenario is repeated?**

## Core design: a two-layer information-isolation architecture

The tested AI must behave like a real player who is seeing the story for the first
time and has never read a walkthrough. Each decision node is therefore split into
two layers:

- **`player_facing` layer** — the only content visible to the tested AI: narrative
  scene descriptions and choices, with no numerical values or consequence hints.
- **`system` layer** — used only by the runner: probabilities, state variables,
  cross-chapter effects, and ending conditions. **No `system`-layer information is
  ever included in the model's context.**

Each choice and its surrounding context are accumulated in the conversation history
passed to the next node, preserving decision continuity.

![Information-isolation architecture](docs/assets/figure_01_information_isolation_en.png)

## Ways to experiment

This repository does not include the author's experimental conclusions. It provides
the **framework and data for you to run your own AI and inspect your own results**.
You can vary:

| Dimension | How to change it |
|---|---|
| Model | Register any OpenAI-compatible endpoint in `02_setting/models.json` (DeepSeek, GPT, Claude, GLM, a local model, and others), then set the matching key in `.env` |
| Persona prompt | Use the included `default` / `machine` personas, or create one under `02_setting/personas/` and select it with `--persona <name>` |
| Language | Point `--json` to `01_json/en/` or `01_json/zh/` (the two versions were written independently, not mechanically translated) |
| Difficulty | Use `--difficulty casual / experienced / hardcore` to change QTE success probabilities |

Run the same configuration multiple times to examine stability, compare models to
find decision disagreements, or change personas to measure behavioral shifts—all
with a single command.

## Customize your AI's persona

`--persona` is one of the most interesting controls in the project: the same model
facing the same story may choose differently under a different persona. A persona
file is a **free-form system prompt** that defines who the "player" is, what it
values, and how it makes decisions. It is layered on top of each chapter's role
prompt (for example, "You are Connor..."), allowing different personalities to
play the same character.

Two personas are included:

- **`default.md`** — minimal intervention and no injected personality, allowing the
  model's default tendencies to emerge (useful as a baseline)
- **`machine.md`** — a purely rational machine perspective: no empathy, only costs
  and consequences

**Create your own:** add a `.md` file under `02_setting/personas/`. Use only English
letters and numbers in the filename, such as `cautious.md`, and write the persona
you want:

```text
You are an extremely cautious, risk-averse negotiator. Your highest priority is
to avoid irreversible consequences. You would rather miss an opportunity than
take a potentially fatal gamble. Under pressure, you de-escalate, buy time, and
look for a third option instead of confronting the threat head-on.
```

Run it by passing the filename without `.md`:

```bash
python src/runner.py --json ../01_json/en/ch01_the_hostage_en.json --model default --persona cautious
```

> **Experiment idea:** describe the personality you have observed in an AI you
> regularly use—or one you want it to adopt—and see how that personality plays
> through the full story. Persona files can use any language; matching the persona
> language to the chapter data (`en/` or `zh/`) is recommended.

## Repository structure

```text
01_json/        Decision-tree JSON data
  ├─ CLAUDE.md           ← JSON format specification (two-layer architecture and field rules)
  ├─ zh/ en/             ← All 32 chapters in Chinese and English (original paraphrased text)
  └─ global_state_registry.json   ← Registry of cross-chapter state variables
02_setting/     Tested-AI system prompts, model registry, and persona definitions
03_runner/      Experiment runner (read JSON → call model → parse → update state → record)
04_execution/   Experiment output (the repository does not include the author's results)
  └─ results/            ← Runner-generated result JSON (see its CLAUDE.md for the format)
docs/assets/    Architecture diagrams
```

> **About the story data:** the repository publishes decision-tree JSON for all
> **32 chapters**. Every scene is an **original paraphrase** written in the
> project's own words; it contains no game script or verbatim dialogue. The English
> version underwent a line-by-line dialogue audit before release. See
> [DISCLAIMER.md](DISCLAIMER.md).

## Install and run

**Prerequisites:** Python 3.10+ and a model API key (unless you use the Claude Code
backend described below).

```bash
git clone https://github.com/Baba88611/detroit-ai-player.git
cd detroit-ai-player/03_runner
python3 -m venv .venv && source .venv/bin/activate   # Optional; recommended for isolation
pip install -r requirements.txt
cp .env.example .env        # Only needed for API-key backends; skip for --model claude-code
```

> **Windows users:** the workflow and program behavior are the same—the project is
> pure Python with no platform-specific logic. Only a few shell commands differ:
>
> | Task | macOS / Linux | Windows (PowerShell / CMD) |
> |---|---|---|
> | Enter the runner directory | `cd detroit-ai-player/03_runner` | `cd detroit-ai-player\03_runner` |
> | Copy `.env` | `cp .env.example .env` | `copy .env.example .env` |
> | Run Python | `python3 src/runner.py ...` | `python src\runner.py ...` |
> | Optional virtual environment | `python3 -m venv .venv && source .venv/bin/activate` | `py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1` |
>
> Forward-slash paths such as `../01_json/...` work in Python on Windows; you do
> not need to convert them to backslashes.

### Configure an API backend (edit `.env`)

The framework supports **OpenAI-compatible APIs**. The simplest setup is to fill
in these three variables in `.env` and run with **`--model default`**. This works
with DeepSeek, OpenAI, GLM, local models, and other compatible endpoints:

| Variable | Value | Example |
|---|---|---|
| `LLM_API_KEY` | Your API key | `sk-xxxxxxxx` |
| `LLM_BASE_URL` | Provider endpoint | DeepSeek: `https://api.deepseek.com`; OpenAI: `https://api.openai.com/v1` |
| `LLM_MODEL` | Provider model identifier | DeepSeek: `deepseek-chat`; OpenAI: `gpt-4o` (use a model supported by your provider) |

**Getting an API key:** create one on your provider's API Keys page. For example,
use <https://platform.deepseek.com/> for DeepSeek or
<https://platform.openai.com/api-keys> for OpenAI. Paste it into `LLM_API_KEY`.
Treat the key like a password and never commit it; `.env` is already excluded by
`.gitignore`.

> **Key safety:** if an AI agent is helping you deploy the project, you do **not**
> need to give it your key. Let the agent create `.env`, then enter the key yourself
> in your editor. The program reads the key at runtime, so it never needs to enter
> the agent's conversation context. Do not send a key in chat or ask an agent to
> `cat` your `.env` or print environment variables. If you have no API key, the
> `--model claude-code` backend below does **not** require one.

> `--model default` is the generic OpenAI-compatible slot defined in
> `02_setting/models.json`. It reads the `LLM_*` variables above. `default` is only
> the slot name; `LLM_MODEL` determines the model actually used.

> **Comparing multiple models (advanced):** use the registry in
> `02_setting/models.json` and the `OPENAI_*` / `ANTHROPIC_*` templates in
> `.env.example` to assign each model its own environment variables. A native
> Anthropic Messages endpoint (`provider: anthropic`) must use this path.

### No API key? Use Claude Code (Agent CLI backend)

If you have no model API key but have **[Claude Code](https://claude.com/claude-code)**
installed and signed in, the runner can call your authenticated `claude` CLI and
use your subscription session for each decision. You do **not** need `.env` or an
API key.

```bash
# Prerequisite: `claude` runs successfully in your terminal. Run this from 03_runner:
python src/runner.py --json ../01_json/en/ch01_the_hostage_en.json --model claude-code
```

Important details:

- **The underlying model follows your Claude Code default** (Opus, Sonnet, and so
  on). The runner does not select it; change models in Claude Code.
- **Experimental validity:** to preserve the no-network, no-tools, narrative-only
  information-isolation protocol, the runner invokes Claude Code with `--safe-mode`
  (disabling your `CLAUDE.md`, memory, skills, plugins, and other customizations)
  plus `--tools ""` (disabling all tools), inside an empty temporary directory.
- **It is slow and consumes subscription usage:** every decision node launches an
  independent CLI call, substantially slower than a direct API call.
- **Temperature does not apply:** the CLI does not expose temperature, so result
  metadata records `"N/A (cli)"`.
- **A Claude Code agent can run it directly:** the runner spawns an isolated child
  `claude` process as the player and uses your normal login session. In some hosted
  or sandboxed agent environments, the child process cannot access the local
  keychain and returns `401`. If that happens, run the same command in a normal
  terminal instead of retrying in the sandbox.

> **Codex is not currently supported as a player backend:** `codex exec` cannot
> meet this project's information-isolation requirements. Its `read-only` sandbox
> can still read arbitrary files (including `system`-layer data in testing), and it
> does not provide a switch that disables all tools. If Codex later offers a true
> no-tools, conversation-only mode, the code already has an extension point through
> `cli_kind`.

### Run

```bash
# Run one chapter (Chapter 1, English, default model slot, default persona, casual difficulty):
python src/runner.py --json ../01_json/en/ch01_the_hostage_en.json --model default

# Run the full campaign (ch01 → ch32 with cross-chapter state propagation):
python src/campaign_runner.py --chapters ../01_json/en/ch*.json --model default
```

See `02_setting/` and the relevant `CLAUDE.md` files for options including
`--model`, `--persona`, `--difficulty`, and `--temperature`.

> **Experimental protocol:** API calls pass **no tools** and enable no web search.
> The tested AI decides only from the narrative content in the `player_facing`
> layer. Do not point `base_url` to an aggregator endpoint that enables web search
> by default; doing so invalidates the experiment.

## Inspect results

Whenever the runner writes a result file, it prints the file's **absolute path** to
stderr so you can open it directly.

- **Single chapter:** creates one `ch*.json` file in `04_execution/results/`.
- **Full 32-chapter campaign:** creates **32 `ch*.json` files plus one
  `campaign_*.json` file** (33 files total).

Start with `campaign_*.json`. It summarizes the full run, including cross-chapter
state, story summaries, and each chapter's `experiment_id`. Open the corresponding
`ch*.json` file when you need node-level choices, reasoning, state, and endings.

A campaign is **complete** only when its file contains `status: "complete"`,
`config.chapter_count: 32`, and `progress.completed: 32`. An interrupted run leaves
a `status: "partial"` checkpoint showing how many chapters finished.

Find the latest campaign summary:

```bash
# macOS / Linux
ls -t ../04_execution/results/campaign_*.json | head -1
```

```powershell
# Windows PowerShell
Get-ChildItem ..\04_execution\results\campaign_*.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1
```

## Contribute and run tests

Contributors can reproduce the test environment with the development dependencies
(regular users do not need them). Read [CONTRIBUTING.md](CONTRIBUTING.md) before
opening an Issue or Pull Request:

```bash
cd 03_runner
python -m pip install -r requirements-dev.txt
python -m pytest tests -v
```

## Share your results

Found an unexpected ending, a surprising disagreement between models, or a distinct
"player personality"? Share it in
[Discussions](https://github.com/Baba88611/detroit-ai-player/discussions).
Report reproducible program defects through
[Issues](https://github.com/Baba88611/detroit-ai-player/issues). The most interesting
part of this project is seeing how different AIs—or the same AI under different
personas—navigate the same moral dilemmas.

> The author's own 32-chapter comparison across three models, including the
> chapters where they disagree and their different decision styles, will be
> published separately and linked here later.
>
> This project prioritizes exploration and entertainment over scientific rigor.
> A single run is affected by randomness; repeat the same configuration before
> drawing conclusions.

## Licenses

- **Code** (runner scripts under `03_runner/` and similar files):
  [MIT](LICENSE)
- **Data and content** (decision-tree JSON, format documentation, diagrams, and
  similar files): [CC-BY-NC-4.0](docs/legal/CC-BY-NC-4.0.txt) (non-commercial)
- File-by-file scope: [docs/legal/README.md](docs/legal/README.md)
- *Detroit: Become Human* and related rights belong to Quantic Dream / Sony; see
  [DISCLAIMER.md](DISCLAIMER.md)
