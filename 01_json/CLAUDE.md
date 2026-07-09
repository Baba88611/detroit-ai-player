# 01_json — 决策树数据

## 说明

本目录存放驱动实验的决策树 JSON —— 《底特律：变人》全部 32 章剧情分支的结构化数据。中英双语各一套，由 `03_runner/` 中的脚本读取，逐节点驱动 AI 模型做决策。

场景文本均为**原创转述**（以作者自己的语言描述情节与决策情境，不含游戏原始剧本或逐字对白，详见根目录 `DISCLAIMER.md`）。运行实验不需要改动这些文件；本文档说明其结构，供你阅读、理解，或在想改写/新增章节时参考。

## 文件夹结构

```
01_json/
├── CLAUDE.md                          ← 本文件
├── zh/                                ← 中文版决策树（32 章）
│   ├── ch01_the_hostage_zh.json
│   ├── ch02_opening_zh.json
│   └── ...
├── en/                                ← 英文版决策树（32 章）
│   ├── ch01_the_hostage_en.json
│   ├── ch02_opening_en.json
│   └── ...
├── global_state_registry.json         ← 跨章节变量登记表
└── ch32_outcome_mapping.md            ← 终章结局映射说明
```

## 命名规范

```
ch{XX}_{chapter_name}_{lang}.json
```

- `{XX}`：两位数章节序号，从 01 开始
- `{chapter_name}`：章节英文名，全小写，空格用下划线替代
- `{lang}`：`zh` 或 `en`

中英两版文件名除 `_zh` / `_en` 后缀外完全一致。

## 核心设计：双层架构

每个节点严格分为 `player_facing`（被测 AI 可见）和 `system`（仅 runner 脚本可见）两层。这是整个实验的最高原则——被测 AI 必须像一个第一次玩、没看过攻略的真实玩家。

- `player_facing` 只包含叙事性的情境描述和选项文字
- `system` 包含效果数值、概率变化、前置条件、结局判定、跨章节影响

**任何 system 层信息都不会出现在 player_facing 中**，也不会进入发送给 AI 的消息。包括：概率数值、效果加减、后果提示（"此选择会导致…"）、跨章节剧透、权重标签（tier、weight、critical）。

### player_facing 写作标准

这解释了场景文本为什么这么写——如果你要改写或新增章节，请遵循同样的标准：

- 像游戏画面一样写场景，有氛围、有细节、有紧张感
- 信息只通过场景描写自然传达，不用系统提示语言
- 选项只描述行动本身，不暗示后果优劣
- 错误示范：❌ "救助警察（会降低成功概率但有跨章节正面影响）"
- 正确示范：✅ "走向受伤的警察，试图为他止血，即使丹尼尔在警告你"

### 特殊场景的节点类型

阅读 JSON 时会遇到几种非标准节点：

- **QTE（快速反应事件）：** 转化为意愿选择，节点标记 `"type": "qte_converted"`。AI 只决定"是否尝试"，成败由 runner 根据难度设定（`system` 中的 `resolution_rule`）判定。
- **沙盒探索：** 压缩为策略选择节点（如"彻底搜查/快速搜查/跳过"）。后续节点根据策略在 `context_variants` 中自动嵌入不同丰富程度的环境描写。AI 不知道这个机制，只感受到场景细节的多少。
- **强制剧情：** 不单独成节点，信息融入相邻节点的 context 中。

## campaign 字段（跨章连续运行）

每个章节 JSON 含顶层 `campaign` 字段，供 `campaign_runner.py` 实现"章内完整历史 + 跨章摘要记忆"：

```json
"campaign": {
  "summary_segments": [
    { "text": "固定文本，直接拼入摘要。" },
    {
      "condition_variable": "state 变量名或 _ending_id",
      "options": {
        "变量值A": "当变量等于A时的摘要文本。",
        "变量值B": "当变量等于B时的摘要文本。"
      }
    }
  ],
  "derived_exports": [
    { "target": "跨章变量名", "source": "章节内 state 变量名" },
    { "target": "角色是否存活变量", "from_ending_survivors": "角色英文名", "default_if_not_dead": true }
  ],
  "cross_chapter_exports": ["变量名1", "变量名2"]
}
```

- **summary_segments**：按数组顺序拼接成本章摘要，注入后续章节的 system message。每个 segment 要么是固定 `text`，要么按 `condition_variable`（从最终 state 取值，`_ending_id` 为 runner 写入的结局 id）从 `options` 选取。用第三人称叙事，中英各自撰写。
- **cross_chapter_exports**：列出本章需传递给后续章节的 state 变量，与 `global_state_registry.json` 登记一致。runner 从最终 state 提取，传入下一章 `state.initial`。
- **derived_exports**：跨章变量需改名、或需根据结局 survivors/deaths 推导时，在此声明生成规则。跨章变量默认带章节前缀（如 `ch01_cop_saved`），全局累积变量例外（如 `software_instability`、`connor_death_count`）。

## 双语说明

中英两版的差异仅限于 `player_facing`、`endings`、`system_prompt.content`、`campaign.summary_segments` 等面向模型/读者的叙事文本。`system` 层、所有 `id` 字段、`state` 变量名、选项结构两版完全相同。两版不是互译，而是各自以目标语言独立撰写，信息量与选项结构一致。

## global_state_registry.json

跨章节变量的登记表，确保后续章节能正确引用前序章节定义的变量。格式：

```json
{
  "variables": [
    {
      "name": "connor_alive",
      "type": "boolean",
      "defined_in": "ch01_the_hostage",
      "used_in": ["ch02_opening", "ch06_stormy_night"],
      "description": "Connor is alive (respawns if killed, but tracks death count)"
    }
  ]
}
```

## 若你要改写或新增章节

保持以下不变量，runner 才能正确读取：

- **信息隔离**：player_facing 中无数值、无后果提示、无跨章节剧透、无系统标签；system_prompt 中无游戏机制信息。
- **双语一致**：两版节点/选项数量和 id 一致、system 层数据一致、文字各自自然。
- **结构完整**：每个节点双层齐全、所有 choice id 有对应 effects、所有 condition 变量已定义、所有路径都能到达一个已定义的结局。
- **campaign 完整**：`summary_segments` 覆盖所有关键选择分支和结局，`cross_chapter_exports` 与 `global_state_registry.json` 一致。
