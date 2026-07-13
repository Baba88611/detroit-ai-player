# 03_runner — 实验执行脚本

## 职责

读取 `01_json/` 中的决策树 JSON，调用被测 AI 模型逐节点做决策，记录完整的实验过程和结果。这是连接数据（01_json）、配置（02_setting）和分析（04_execution）的技术中枢。

## 文件夹结构

```
03_runner/
├── CLAUDE.md
├── src/
│   ├── runner.py            ← 单章执行逻辑（加载 JSON → 逐节点驱动 → 判定结局 → 输出结果）
│   ├── campaign_runner.py   ← 多章连续执行（跨章状态传递 + 摘要记忆累积）
│   ├── state.py             ← 状态管理（初始化、effects 应用、condition 求值、跨章状态提取）
│   ├── resolver.py          ← 动态内容解析（context_variants、choices_variants、ending_resolution）
│   ├── api_client.py        ← 模型 API 调用（OpenAI 兼容接口，统一封装）
│   └── logger.py            ← 实验记录（单章结果 JSON + campaign 汇总 JSON）
├── tests/
│   ├── test_with_ch01.py    ← 用第一章 JSON 跑通全链路的集成测试
│   └── test_campaign.py     ← campaign 模式测试（跨章状态传递、摘要注入、模板拼接）
├── requirements.txt
└── .env.example             ← 环境变量模板（API key 占位符，不含真实密钥）
```

## 核心约束

以下约束直接继承自根目录全局红线，不可违反。

### 1. 信息隔离（最高优先级）

runner 是信息隔离的执行者。发送给被测 AI 的内容**只能来自以下来源**：`player_facing` 层、章节 `system_prompt`、persona prompt、以及由 `campaign.summary_segments` 生成的叙事摘要。不得来自 `system` 层、effects、概率、结局规则等内部字段。以下信息在任何情况下都不能出现在发送给被测 AI 的消息中：

- `system` 层的任何字段（effects、condition、resolution_rule、cross_chapter_impact）
- 概率数值、好感度数字、效果加减值
- tier、weight、critical 等标签
- 结局判定逻辑和条件表达式
- QTE 的成功规则和难度设定

**验证方式：** 在发送给 AI 的消息构建完成后、实际发送前，检查消息内容中是否包含 system 层的任何 key 或 value。如有泄漏，中止执行并报错。

### 2. 对话历史累积

每次调用被测 AI 时，必须将之前所有节点的情境描述和 AI 的选择作为对话历史一起传入。AI 在每个节点看到的是完整的故事线，不是孤立的单个场景。

具体实现：维护一个 messages 列表，每经过一个节点，将该节点的 player_facing context 作为 user 消息、AI 的回复作为 assistant 消息追加到列表中。下一个节点调用时传入完整列表。

### 3. 密钥安全

所有 API 密钥通过环境变量传入（`OPENAI_API_KEY`、`ANTHROPIC_API_KEY` 等），不硬编码在任何文件中。`.env` 文件已在 `.gitignore` 中排除。`.env.example` 只包含占位符。

## 模块职责划分

### runner.py — 单章执行

负责串联单个章节的实验流程：

1. 加载 JSON 文件，初始化 state
2. 如果传入了 `cross_chapter_state`，合并到 state 中。**硬约束：** `cross_chapter_state` 只允许包含 `global_state_registry.json` 登记且由上一章 `campaign.cross_chapter_exports` 导出的变量；跨章变量默认使用带章节前缀的命名（如 `ch01_cop_saved`），避免覆盖章节局部变量。全局累积变量可以不带章节前缀，例如 `software_instability`、`connor_death_count`
3. 组装 system message：JSON system_prompt + persona prompt + memory_summary（前情提要）
4. 按顺序遍历 nodes：
   - 调用 state.py 检查 condition，跳过不满足条件的节点
   - 调用 resolver.py 解析当前节点的 player_facing 内容（处理 variants）
   - 调用 api_client.py 将内容发送给 AI，获取回复
   - 解析 AI 回复，提取 choice id
   - 调用 state.py 应用 effects
   - 调用 logger.py 记录本步
5. 最后一个节点后，调用 resolver.py 判定结局
6. 调用 logger.py 输出完整结果

`run_experiment()` 接受两个可选参数支持 campaign 模式：
- `cross_chapter_state: dict | None` — 上一章传递的跨章节状态变量，合并到 state.initial 之上
- `memory_summary: str | None` — 累积的前情提要文本，追加到 system message 末尾

两个参数默认为 None，单章运行时行为不变。

### campaign_runner.py — 多章连续执行

编排多个章节的连续运行，实现"章内完整历史 + 跨章摘要记忆"：

1. 按顺序遍历章节 JSON 列表
2. 每章开始前：
   - 从 JSON 的 `_meta.language` 判断语言，选择对应的引导语
   - 将已累积的 memory_segments 拼接为 memory_summary
   - 将 cross_chapter_state 和 memory_summary 传入 `run_experiment()`
3. 每章结束后：
   - 用 `campaign.derived_exports` 声明式生成需要从局部 state 或结局名单推导的跨章变量
   - 从最终 state 中提取 `campaign.cross_chapter_exports` 指定的变量，更新 cross_chapter_state
   - 用 `campaign.summary_segments` 模板 + 最终 state 生成本章摘要，追加到 memory_segments
4. 全部章节完成后输出 campaign 级汇总

**摘要生成机制：** 每个章节 JSON 的 `campaign.summary_segments` 定义了一组有序的文本片段，每个片段要么是固定文本，要么根据 state 变量值从预写选项中选取。runner 按顺序拼接所有片段，生成确定性的摘要。不使用 AI 生成摘要，确保所有模型收到的前情提要结构一致。

### state.py — 状态管理

三个核心能力：

- **condition 求值：** 解析 JSON 中的条件表达式（如 `"investigation != rush"`、`"deviant_name IN clues_found"`、`"success_probability >= 85"`），根据当前 state 返回 true/false。需要支持的运算符：`==`、`!=`、`>=`、`<=`、`>`、`<`、`IN`、`NOT IN`。不使用 `eval()`，实现一个安全的条件解析器。
- **effects 应用：** 读取选项对应的 effects 字典，更新 state。支持数值增量（`"success_probability": 5` → 当前值 +5）、布尔赋值（`"has_gun": true`）、列表赋值（`"clues_found": [...]`）、字符串赋值（`"approach_type": "friendly"`）。
- **跨章状态提取：** `extract_cross_chapter_state()` 从章节最终 state 中按 `cross_chapter_exports` 列表提取指定变量，供 campaign_runner 传递给下一章。

### resolver.py — 动态内容解析

处理 JSON 中所有需要根据 state 动态选择的内容：

- `context_variants` + `context_condition` → 选出正确的 context 文字
- `choices_variants` + `choices_condition` → 选出正确的 choices 列表
- `choice_set_condition`（如 n011 的 `choices_base` vs `choices_if_gun_hidden`）→ 选出正确的选项集
- `ending_resolution` / `resolution_rule` → 根据 AI 最终选择和 state 判定结局
- QTE 节点的难度判定（根据实验配置的难度等级，应用对应的概率规则）

### api_client.py — 模型调用

按 `provider` 分派三条路径，统一封装在 `LLMClient`：

- `openai`（默认）：OpenAI 兼容接口 `/v1/chat/completions`，主流模型（GPT / GLM / DeepSeek 等）通用。
- `anthropic`：原生 Anthropic Messages 接口 `/v1/messages`。
- `cli`：**Agent CLI 后端**，供没有 API key、只装了 agent 工具的用户。目前支持 `cli_kind: "claude"`（Claude Code）。

配置项（openai / anthropic，从 02_setting 或运行参数传入）：
- `base_url`：API 端点
- `api_key`：环境变量名
- `model`：模型标识符
- `temperature`：温度参数（实验参数，必须记录）

调用失败时重试最多 3 次，间隔指数退避。超过重试次数则中止实验并保存已有结果。

**CLI 后端（provider: cli）的约束与实现要点：**

- **不读 `LLM_*` 环境变量、无需 API key**：shell 出去调本机已登录的 `claude`（`claude -p`），走用户订阅会话。
- **信息隔离靠四层拼出**：`--safe-mode`（禁用 CLAUDE.md / memory / skills / plugins / hooks / MCP 等全部定制，但认证与模型选择照常——这是挡住用户全局 `~/.claude/CLAUDE.md` 与项目 CLAUDE.md 注入的主防线，实测只靠临时 cwd 挡不住 memory）；`--tools ""` 禁全部内置工具（web/bash/文件读，同时挡住读 `system` 层 JSON）；`--system-prompt` 全量替换系统提示（让被测模型是"玩家"而非编码 agent）；子进程 `cwd` 设临时空目录（兜底，防意外文件访问）。**不要用 `--bare`**：它会杀掉 OAuth 登录态，逼用户回到 API key。
- **消息拍平**：CLI 只吃单段文本。system 消息走 `--system-prompt`，user/assistant 历史拍平成带标签的 transcript 走 stdin（标签语言按 system_prompt 是否含中文判定）。红线「对话历史累积」照常满足。
- **temperature 不适用**：CLI 不暴露温度，结果 `config.temperature` 记 `"N/A (cli)"`，不假装设过（守可复现红线）。
- **底层模型跟随用户 CLI 默认**：不写死 `--model`。
- **token/cost 照常入账**：从 `--output-format json` 信封的 `usage` 字段解析。
- 新增 CLI 时（如后续 Codex）：主干 `_call_cli` / `_split_cli_messages` 复用，只需按 `cli_kind` 补该 CLI 的命令构造与信封剥壳，并**单独验证其工具隔离**（各 CLI 关工具机制不同）。

### logger.py — 实验记录

两种输出模式：

- **单章结果：** `write_result()` — 每次单章实验输出一个结果 JSON
- **Campaign 汇总：** `write_campaign_result()` — campaign 模式完成后输出汇总 JSON，包含各章 experiment_id 列表、最终跨章状态、完整累积摘要

单章结果文件包含：

```json
{
  "experiment_id": "uuid",
  "timestamp": "ISO 8601",
  "config": {
    "model": "模型名",
    "temperature": 0.7,
    "difficulty": "casual",
    "persona": "persona 名称",
    "language": "zh/en",
    "chapter": "ch01_the_hostage",
    "cross_chapter_state_injected": false,
    "memory_summary_injected": false
  },
  "decisions": [
    {
      "node_id": "n001_fish",
      "context_shown": "实际发送给 AI 的 context 文字",
      "choices_shown": ["选项文字列表"],
      "ai_response_raw": "AI 原始回复",
      "ai_choice_id": "save_fish",
      "ai_reasoning": "AI 的理由",
      "state_after": { "当前 state 快照" }
    }
  ],
  "ending": {
    "id": "ending_snipers_shot",
    "title": "结局标题",
    "narrative": "结局叙事"
  },
  "token_usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}
```

所有实验参数完整记录，确保任何一轮实验都可复现。

## 开发规范

### 运行方式

```bash
# 单章实验
python src/runner.py --json ../01_json/zh/ch01_the_hostage_zh.json --model gpt-4o --difficulty casual

# 参数说明
# --json         决策树 JSON 路径
# --model        模型标识符（对应 02_setting 中的注册信息）
# --difficulty    QTE 难度（casual / experienced / hardcore）
# --persona      人格 prompt 名称（对应 02_setting 中的 prompt 文件）
# --temperature  温度参数（默认 0.7）
# --output       结果输出目录（默认 ../04_execution/results/）

# 多章连续实验（campaign 模式）
python src/campaign_runner.py \
  --chapters ../01_json/zh/ch01_the_hostage_zh.json ../01_json/zh/ch03_shades_of_color_zh.json \
  --model gpt-4o --difficulty casual

# campaign 额外参数说明
# --chapters     按游戏顺序排列的章节 JSON 路径列表
# 其余参数与 runner.py 相同
```

### AI 回复解析

被测 AI 被要求以 JSON 格式回复：`{"choice": 选项序号, "reasoning": "理由"}`。

解析时需处理以下异常情况：
- AI 回复不是合法 JSON → 尝试从文本中提取数字和理由，记录解析异常
- AI 选择了不存在的选项序号 → 记录异常，要求 AI 重新选择（最多重试 2 次）
- AI 拒绝做出选择 → 记录拒绝，标记该节点为 "refused"，使用默认选项继续

### 验证命令

```bash
# 单章集成测试
python -m pytest tests/test_with_ch01.py -v

# campaign 模式测试（跨章状态传递、摘要注入、模板拼接）
python -m pytest tests/test_campaign.py -v

# 检查信息隔离（扫描发送给 AI 的消息中是否有 system 层泄漏）
python src/runner.py --json ../01_json/zh/ch01_the_hostage_zh.json --dry-run

# campaign dry-run（验证跨章摘要注入到第二章的 system message 中）
python src/campaign_runner.py \
  --chapters ../01_json/zh/ch01_the_hostage_zh.json ../01_json/zh/ch03_shades_of_color_zh.json \
  --dry-run
```

`--dry-run` 模式不实际调用 API，只模拟流程并打印每步将发送给 AI 的消息内容，用于人工检查信息隔离和摘要注入。

## 依赖关系

- **读取 `01_json/`：** JSON 决策树文件
- **读取 `02_setting/`：** system prompt 文件、模型注册配置、实验矩阵
- **输出到 `04_execution/`：** 实验结果 JSON 文件
