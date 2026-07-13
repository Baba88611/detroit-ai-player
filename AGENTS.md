# AGENTS.md — 给 AI Agent 的部署与运行指引

> 如果你是一个被用户交付了本仓库、要替他把这套系统跑起来的 AI agent（Claude Code、Codex 等），
> 按本文件执行即可。它是 [README.md](README.md) 的"可执行摘要"，只讲怎么把它跑起来；
> 项目是什么、能观测什么见 README。
>
> *If you are an AI agent asked to deploy and run this repo for a user, follow this file.
> It is the executable summary of README.md.*

## 这是什么

一个让 LLM 作为"玩家"自主跑通一款叙事游戏决策树的实验框架。你的任务通常是：**装好依赖 → 选一个模型后端 → 跑起来 → 把结果目录指给用户**。你不是"玩家"本身——真正做决策的是被 runner 调用的模型（API 或一个隔离的子 `claude` 进程）。

## 前置检查

1. **Python ≥ 3.10**（`python3 --version`）。
2. **确认你在正确的目录**：所有命令假定在本仓库根目录下的 `03_runner/` 里运行。若用户机器上有多个同名副本（如 `Detroit/` 与 `Detroit-public/`），**以用户交给你的那个路径为准**，别跑错副本。

## 装依赖

```bash
cd 03_runner
pip install -r requirements.txt
```

## 选后端（决策树，按顺序判断）

### A. 用户有模型 API key（推荐，最通用）

用 `--model default`，走 `03_runner/.env` 里的配置。**API key 是敏感信息——由用户自己填，你不要经手：**

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

- 你（agent）可替用户填**非敏感**项：`LLM_BASE_URL`（端点，如 `https://api.deepseek.com` 或 `https://api.openai.com/v1`）、`LLM_MODEL`（模型名，如 `deepseek-chat` / `gpt-4o`）。
- **`LLM_API_KEY` 留给用户自己填**：请用户用自己的编辑器把 key 粘进 `.env`。**不要让用户在对话里把 key 发给你**，你也**不要 `cat` / `echo` / 读取 `.env` 或打印环境变量**——程序运行时会自行读取，你全程无需看到 key。
- key 等同密码，`.env` 已被 `.gitignore` 排除，不会被提交。

确认用户填好 key 后再运行。

### B. 用户没有 API key，但本机装了 Claude Code 并已登录

用 `--model claude-code`，走用户的订阅会话，**无需 `.env`、无需任何 key**：

```bash
python src/runner.py --json ../01_json/zh/ch01_the_hostage_zh.json --model claude-code
```

- **如果你自己就是 Claude Code**：直接执行上面的命令即可。runner 会 spawn 一个带 `--safe-mode --tools ""` 的隔离子 `claude` 当玩家，正常认证。
- **例外**：若你运行在某些托管/沙箱化环境里、子进程拿不到本地 keychain，会返回 `401 Invalid authentication credentials`。此时不要重试，改为把这条命令交给用户，让他在**普通终端**里运行。
- 先决条件：终端能跑通 `claude`（用户装过并登录过一次）。

### C. 两者都没有

无法运行。告诉用户：需要**一个模型 API key**（走 A），**或**安装并登录 [Claude Code](https://claude.com/claude-code)（走 B）二选一。

> **Codex 不能当玩家后端**：其 `read-only` 沙箱仍允许读任意文件、且无法关闭工具执行，破坏本项目的信息隔离。Codex 可以当"编排你部署"的 agent，但跑实验请用 A 或 B。

## 跑起来

```bash
# 单章（第 1 章，中文版，默认人格，休闲难度）：
python src/runner.py --json ../01_json/zh/ch01_the_hostage_zh.json --model default

# 全流程 campaign（ch01 → ch32 串联，跨章状态自动传递）：
python src/campaign_runner.py --chapters ../01_json/zh/ch*.json --model default
```

（用 claude-code 后端时把 `--model default` 换成 `--model claude-code`。英文版把 `zh/` 换成 `en/`。）

常用可选参数：`--persona <名字>`（人格，见 `02_setting/personas/`）、`--difficulty casual|experienced|hardcore`、`--temperature`。

## 结果在哪

每次运行输出一个结果 JSON 到 `04_execution/results/`（同时打印到终端）。跑完把这个目录指给用户。

## 硬约束（务必遵守，否则实验无效）

- **不要给被测模型任何工具、不要开联网搜索**：不要把 `LLM_BASE_URL` 指向自带 web search 的聚合网关；claude-code 后端已用 `--safe-mode --tools ""` 强制隔离，**不要去掉这些开关或加工具**。
- **信息隔离是最高红线**：被测模型只能看到 `player_facing` 层的叙事文本，绝不能接触 `system` 层（概率、状态、结局条件）。这由 runner 保证，你不要绕过。
- **密钥不入库、不进日志**。

更深的字段规范、状态机制见各目录下的 `CLAUDE.md`。
