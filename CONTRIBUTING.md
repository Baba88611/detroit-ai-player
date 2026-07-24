# Contributing

**English** | [简体中文](CONTRIBUTING.zh-CN.md)

Thank you for helping improve Detroit AI Player. Every contribution must preserve
reproducibility, information isolation, and copyright boundaries.

## Choose the right channel

- For deployment questions, model usage, and experiment-result sharing, use
  [Discussions](https://github.com/Baba88611/detroit-ai-player/discussions).
- For reproducible program defects, use the Bug report Issue template.
- For new features or research-design proposals, start with the Feature request
  template and explain the motivation and boundaries.
- For security issues or possible secret exposure, use the private reporting
  channel described in [SECURITY.md](SECURITY.md).

## Local development

```bash
git clone https://github.com/Baba88611/detroit-ai-player.git
cd detroit-ai-player/03_runner
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest tests -v
```

On Windows PowerShell, activate the environment with
`.\.venv\Scripts\Activate.ps1`.

## Keep both documentation languages in sync

- `README.md` and `README.zh-CN.md` form one pair; `CONTRIBUTING.md` and
  `CONTRIBUTING.zh-CN.md` form another.
- A substantive change to either file in a pair must update its counterpart in
  the same Pull Request.
- Commands, paths, configuration names, information-isolation requirements, key
  safety rules, and license boundaries must remain equivalent in both languages.
  A spelling or wording correction may update only the affected language.

## Pull Request requirements

1. Keep each PR focused on one problem and describe the user-visible change.
2. Add tests for new behavior. For a bug fix, prefer a regression test that
   reproduces the previous failure.
3. Preserve existing directory responsibilities: `01_json` for data,
   `02_setting` for configuration, `03_runner` for the runner, and `04_execution`
   for result documentation.
4. Do not commit `.env`, API keys, tokens, personal experiment results, or logs
   that contain secrets.
5. Do not give the tested model tools, network access, or `system`-layer data.
   Any change that may alter the `player_facing` / `system` isolation boundary
   must be explained separately in the PR and covered by tests.
6. Do not commit the original game script, verbatim dialogue, screenshots, audio,
   video, or other third-party game assets.
7. Confirm which license applies to your changes; see
   [docs/legal/README.md](docs/legal/README.md).

Before submitting, run:

```bash
cd 03_runner
python -m pytest tests -v
```
