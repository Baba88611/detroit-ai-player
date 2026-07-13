# Detroit AI Player — 让大模型自己玩《底特律：变人》

> 用结构化的决策树，让**你的 AI**（DeepSeek、GPT、Claude 或任何 OpenAI 兼容模型）作为"玩家"
> 自主跑通一款叙事游戏的全部剧情分支，观测它在人质谈判、生死抉择、武力与非暴力等道德困境中的决策倾向。
>
> *An experiment letting different LLMs autonomously play through a branching narrative game,
> comparing how they decide under moral dilemmas. English summary at the bottom.*

⚠️ 本项目为非商业研究，不含任何游戏素材，与 Quantic Dream / Sony 无关。请先阅读 **[DISCLAIMER.md](DISCLAIMER.md)**。

---

## 这个项目能观测什么

把一款叙事驱动游戏的剧情分支结构化成决策树 JSON，让你的 AI 逐节点自主做选择，你可以观测：

1. **不同模型面对相同道德困境，决策有没有系统性差异？**
2. **同一模型在不同人格设定下，决策会偏移多少？**
3. **AI 的选择稳定吗？多次跑同一场景，结果一致吗？**

## 核心设计：信息隔离的双层架构

被测 AI 必须像一个"第一次玩、没看过攻略"的真实玩家。为此每个决策节点分两层：

- **`player_facing` 层** — 被测 AI 唯一能看到的内容，是叙事性的场景描写和选项，不含任何数值或后果提示。
- **`system` 层** — 仅供运行脚本内部使用：概率、状态变量、跨章节影响、结局条件。**任何 system 层信息都不会进入模型的上下文。**

模型每一步的选择和情境，会作为对话历史累积传入下一节点，保证决策的连贯性。

![信息隔离架构](docs/assets/figure_01_information_isolation.png)

## 你可以怎么玩

这个仓库不附带作者的实验结论——它是一个**让你用自己的 AI 跑、观测你自己的结果**的框架。可调的维度：

| 维度 | 怎么调 |
|---|---|
| 模型 | 在 `02_setting/models.json` 注册任意 OpenAI 兼容端点（DeepSeek、GPT、Claude、GLM、本地模型……），`.env` 填对应 key |
| 人格 Prompt | 用自带的 `default` / `machine`，或在 `02_setting/personas/` 下写你自己的 persona（`--persona <名字>` 调用） |
| 语言 | `--json` 指向 `01_json/zh/` 或 `01_json/en/`（两版独立撰写，非互译） |
| 难度 | `--difficulty casual / experienced / hardcore`（影响 QTE 判定概率） |

跑同一配置多轮看选择稳定性，跑不同模型看决策分歧，跑不同 persona 看人格偏移——都是一行命令的事。

## 自定义你的 AI 人格

`--persona` 是这个项目最好玩的开关：同一个模型、同一段剧情，换一套人格设定，选择就可能完全不同。persona 文件就是一段**自由的系统提示**，定义这个"玩家"是谁、看重什么、怎么做决定——它会叠加在每章的角色设定（"你是康纳……"）之上，让不同性格的 AI 去演同一个角色。

仓库自带两个：

- **`default.md`** —— 最小干预，不注入任何人格，让模型露出自己的默认倾向（适合做基线对照）
- **`machine.md`** —— 纯理性机器视角，无共情、只算代价

**写你自己的**：在 `02_setting/personas/` 下新建一个 `.md` 文件（文件名用英文/数字，如 `cautious.md`），写进你想要的人格：

```text
你是一个极度谨慎、厌恶风险的谈判者。你的首要原则是不制造任何不可挽回的后果——
宁可错失机会，也不冒可能致命的险。你不相信"搏一把"，你相信每一步都留退路。
面对压力时，你倾向于降温、拖延、寻找第三条路，而不是正面对抗。
```

然后用它跑（`--persona` 后跟文件名，不含 `.md`）：

```bash
python src/runner.py --json ../01_json/zh/ch01_the_hostage_zh.json --model default --persona cautious
```

> **玩法建议**：如果你平时常用某个 AI（Claude、GPT……），把你观察到的它的性格、或你希望它扮演的角色，写成一段 persona 贴进来，就能看到"带着这种性格的 AI"如何走完整个故事。persona 用什么语言写都行，建议和你运行的章节语言一致（跑 `zh/` 用中文，跑 `en/` 用英文）。

## 仓库结构

```
01_json/        决策树 JSON 数据
  ├─ CLAUDE.md           ← JSON 数据格式说明（双层架构、字段规范）
  ├─ zh/ en/             ← 全部 32 章决策树 JSON（中英双语，原创转述文本）
  └─ global_state_registry.json   ← 跨章节状态变量登记
02_setting/     被测 AI 的 system prompt、模型注册、人格定义
03_runner/      实验运行脚本（读 JSON → 调 API → 解析 → 更新状态 → 记录）
04_execution/   实验结果输出目录（仓库不附带作者的结果，你跑的结果会落在这里）
  └─ results/            ← runner 输出的结果 JSON（格式说明见其 CLAUDE.md）
docs/assets/    架构示意图
```

> **关于剧情数据**：仓库公开全部 **32 章**的决策树 JSON。所有场景文本均为**原创转述**——
> 以本项目作者自己的语言描述情节与决策情境，不含游戏原始剧本或逐字对白
> （英文版发布前经过逐字台词审查）。详见 [DISCLAIMER.md](DISCLAIMER.md)。

## 如何部署与运行

**前置**：Python 3.10+，以及一个可用的模型 API key（下面教你怎么弄）。

```bash
git clone <this-repo> && cd Detroit-public/03_runner
pip install -r requirements.txt
cp .env.example .env        # 复制后按下方说明填写
```

> **Windows 用户**：整套流程和逻辑完全一致（纯 Python，无平台相关代码），只有个别命令的写法不同——把上面的 `cp` 换成 `copy`，其余按下表对应即可：
>
> | 操作 | Mac / Linux | Windows（PowerShell / CMD） |
> |---|---|---|
> | 复制 .env | `cp .env.example .env` | `copy .env.example .env` |
> | 运行 Python | `python3 src/runner.py ...` | `python src\runner.py ...` |
> | （可选）虚拟环境 | `source venv/bin/activate` | `venv\Scripts\activate` |
>
> 运行参数里的 `../01_json/...` 这类正斜杠路径在 Windows 上也能直接用（Python 会自动处理），无需改成反斜杠。

### 配置 API（编辑 `.env`）

本框架走 **OpenAI 兼容接口**。最简单的方式：在 `.env` 里填好这三个变量，运行时用 **`--model default`**，就能驱动任意 OpenAI 兼容的模型（DeepSeek、OpenAI、GLM、本地模型、各类网关都行）：

| 变量 | 填什么 | 示例 |
|---|---|---|
| `LLM_API_KEY` | 你的 API 密钥 | `sk-xxxxxxxx` |
| `LLM_BASE_URL` | 服务端点地址 | DeepSeek `https://api.deepseek.com`；OpenAI `https://api.openai.com/v1` |
| `LLM_MODEL` | 实际调用的模型名 | DeepSeek `deepseek-chat`；OpenAI `gpt-4o`（填你的厂商支持的模型标识） |

**怎么拿 API key**：去对应厂商的控制台申请（通常在「API Keys / 密钥管理」页新建）——DeepSeek 是 <https://platform.deepseek.com/>，OpenAI 是 <https://platform.openai.com/api-keys>。拿到的 key 粘到 `LLM_API_KEY`。key 等同密码，不要提交进 git（`.env` 已被 `.gitignore` 排除）。

> **密钥安全**：如果你让 AI agent 帮你部署，**不必把 key 交给它**——让 agent 建好 `.env`，由你自己把 key 填进去即可。运行时是程序自行读取 key，它不需要进入 agent 的对话上下文；配置时也别在聊天里把 key 发给 agent、别让它 `cat` 你的 `.env`。若你根本没有 API key，用下一节的 `--model claude-code` 后端则**完全不涉及 key**。

> `--model default` 是 `02_setting/models.json` 里预设的"通用 OpenAI 兼容槽位"，读取上面这组 `LLM_*` 变量。实际跑哪个模型由 `LLM_MODEL` 决定，`default` 只是槽位名。

> **多模型对照（进阶）**：想用 `--model` 在几个模型间切换跑对比，见 `02_setting/models.json` 的注册表和 `.env.example` 里的 `OPENAI_* / ANTHROPIC_*` 模板——为每个模型配一组独立变量即可。原生 Anthropic Messages 接口（`provider: anthropic`）必须走这条路。

### 没有 API key？用 Claude Code 跑（Agent CLI 后端）

如果你没有任何模型的 API key，但本机装了 **[Claude Code](https://claude.com/claude-code)** 并已登录，可以让它顶替 API：runner 会调用你已登录的 `claude` 命令行,用你自己的订阅会话逐节点做决策，**不需要填 `.env`、不需要任何 key**。

```bash
# 前置：终端能跑通 `claude`（装好并登录过一次）。然后在 03_runner 目录下：
python src/runner.py --json ../01_json/zh/ch01_the_hostage_zh.json --model claude-code
```

几点必须知道：

- **底层模型跟随你在 Claude Code 里选的默认**（Opus / Sonnet 等），runner 不替你指定——想换模型就在 Claude Code 里换。
- **实验有效性**：为守住"不联网、不用工具、只凭剧情文字决策 + 信息隔离"的口径，runner 调用时用 `--safe-mode`（禁用你的 `CLAUDE.md` / memory / skills / 插件等全部定制，避免个人配置污染被测玩家）叠加 `--tools ""`（禁全部工具），并在临时空目录里运行。
- **慢，且消耗你的订阅额度**：每个节点都是一次独立的 CLI 调用，比直连 API 慢一个量级，用量计入你的 Claude 订阅。
- **temperature 不适用**：CLI 不暴露温度，结果里如实记为 `"N/A (cli)"`。
- **可以让 Claude Code agent 直接跑**：在本机原生 Claude Code 里让它执行上面的命令即可——它会 spawn 一个隔离的子 `claude` 进程当"玩家"，正常走你的登录态。仅在**某些托管/沙箱化的 agent 环境**（拿不到本地 keychain）会 401；遇到就改在普通终端里跑同一条命令。

> **Codex 暂不支持**：`codex exec` 无法满足本项目的信息隔离要求——它的 `read-only` 沙箱仍允许读取任意文件（实测会读到 `system` 层数据），且没有"关闭全部工具"的开关，被测模型无法退化成纯叙事玩家。若将来 Codex 提供真正的"无工具 / 纯对话"模式，代码已按 `cli_kind` 留好扩展口子。

### 运行

```bash
# 跑单章（第 1 章，中文版，default 模型槽位，默认人格，休闲难度）：
python src/runner.py --json ../01_json/zh/ch01_the_hostage_zh.json --model default

# 跑全流程 campaign（ch01 → ch32 串联，跨章节状态自动传递）：
python src/campaign_runner.py --chapters ../01_json/zh/ch*.json --model default
```

具体参数（`--model` / `--persona` / `--difficulty` / `--temperature`）见 `02_setting/` 与各 `CLAUDE.md`。

> **实验口径声明**：本框架调用 API 时**不传入任何工具（tools）**，不启用联网搜索——被测 AI
> 仅凭 `player_facing` 层的情景文本自主决策。请勿将 `base_url` 指向默认联网的模型端点
> （如自带 web search 的聚合网关），否则实验结果无效。

## 分享你的结果

跑出了有趣的结局、意外的决策分歧、或某个模型的"玩家性格"？欢迎发到本仓库的
**Discussions / Issues** 交流——这个项目最有意思的部分，就是看不同的 AI（以及不同人格设定下的同一个 AI）
在相同的道德困境面前走出多么不同的路。

> 作者自己用三个模型跑完全部 32 章的分析（哪些章节出现分歧、各模型的决策风格），
> 后续会以文章形式发布，链接会更新在这里。
>
> 注：本项目以趣味性为主、科学性为辅，单轮结果受随机性影响，下结论前建议同配置多跑几轮。

## 许可证

- **代码**（`03_runner/` 下的脚本等）：[MIT](LICENSE)
- **数据与内容**（决策树 JSON、数据格式说明、示意图等）：[CC-BY-NC-4.0](LICENSE-DATA)（非商用）
- 《底特律：变人》相关权利归 Quantic Dream / Sony，详见 [DISCLAIMER.md](DISCLAIMER.md)

---

## English Summary

This repo structures a story-driven game's branching narrative into decision-tree
JSON so you can let **your own model** (any OpenAI-compatible endpoint) play through
it autonomously and observe how it decides under moral dilemmas. It ships the
**framework and data, not the author's findings** — run it yourself and read your
own results.

Key design: a two-layer architecture where the tested model only ever sees the
narrative `player_facing` layer — never the `system` layer (probabilities, state,
outcomes). The runner passes **no tools** to the API and enables no web search, so
the model decides purely from the narrative context.

All **32 chapters** are published as decision-tree JSON. The scene text is an
original paraphrase written in the author's own words — no game script or verbatim
dialogue (the English version underwent a line-by-line dialogue audit before
release). The game *Detroit: Become Human* is the property of Quantic Dream / Sony;
this project is unaffiliated research. See [DISCLAIMER.md](DISCLAIMER.md). Code is
MIT; data/content is CC-BY-NC-4.0.
