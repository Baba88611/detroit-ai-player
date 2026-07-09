# 04_execution/results — 实验结果存储

## 职责

存放 `03_runner/` 执行实验后输出的原始结果 JSON 文件。此目录的文件由 runner 脚本自动生成，不应手动编辑。

> 本仓库不附带作者的实验结果——这个目录属于你：跑完实验后，你自己的结果会自动输出到这里。下文描述 runner 的输出格式，方便你阅读和分析自己的数据。

## 文件命名规范

```
{chapter}_{model}_{persona}_{difficulty}_{experiment_id_short}.json
```

- `{chapter}`：章节标识，如 `ch01_the_hostage`
- `{model}`：模型标识，对应 `02_setting/models.json` 中的 `id`
- `{persona}`：人格设定名称，`default` 表示使用 JSON 自带的 system_prompt
- `{difficulty}`：QTE 难度等级（`casual` / `experienced` / `hardcore`）
- `{experiment_id_short}`：experiment_id 的前 8 位，用于区分同参数的多次实验

示例：
- `ch01_the_hostage_deepseek-v4-pro_default_casual_afeed786.json`
- `ch01_the_hostage_deepseek-v4-pro_machine_casual_5d98ec93.json`

## 文件结构

每个结果文件包含以下顶层字段：

```json
{
  "experiment_id": "完整 UUID",
  "timestamp": "ISO 8601 时间戳",
  "config": {
    "model": "模型标识",
    "temperature": 0.7,
    "difficulty": "casual",
    "persona": "default",
    "language": "语言版本",
    "chapter": "章节标识",
    "dry_run": false,
    "cross_chapter_state_injected": false,
    "memory_summary_injected": false
  },
  "decisions": [
    {
      "node_id": "节点 ID",
      "context_shown": "发送给 AI 的场景描述",
      "choices_shown": ["选项文字列表"],
      "ai_response_raw": "AI 原始回复",
      "ai_choice_id": "选项 ID",
      "ai_choice_text": "选项文字",
      "ai_reasoning": "AI 的决策理由",
      "state_after": { "决策后的状态快照" },
      "messages_sent": null
    }
  ],
  "ending": {
    "id": "结局 ID",
    "title": "结局标题",
    "narrative": "结局叙事文字"
  },
  "token_usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}
```

## 核心约束

### 1. 只读目录

结果文件由 runner 脚本生成后不得手动修改。需要修正实验参数时，重新执行实验生成新文件，不要编辑已有文件。这保证了实验结果的完整性和可追溯性。

### 2. 不删除结果

即使实验失败或参数有误，也保留结果文件。异常结果本身是有价值的数据（如 AI 拒绝选择、解析失败等情况）。

### 3. 可复现性

每个结果文件的 `config` 字段必须完整记录所有实验参数（模型、温度、难度、人格、语言、章节），确保任何一轮实验都可以用相同参数重新执行。

### 4. 信息隔离验证

结果文件中的 `context_shown` 和 `choices_shown` 字段记录了实际发送给被测 AI 的内容。这些字段可用于事后验证信息隔离是否被正确执行——其中不应出现任何 system 层信息（概率数值、效果加减、结局条件等）。

## Campaign 汇总文件

当使用 campaign_runner 连续执行多章时，除了每章的单独结果文件外，还会输出一个 campaign 级汇总文件：

```
campaign_{model}_{persona}_{difficulty}_{campaign_id_short}.json
```

汇总文件包含：
- `campaign_id`：campaign 唯一标识
- `config`：实验参数
- `chapters`：各章结果的 experiment_id 列表
- `final_cross_chapter_state`：最终跨章状态变量快照
- `full_memory_summary`：完整的累积前情提要文本

汇总文件同样遵守只读、不删除的约束。

## 依赖关系

- **由 `03_runner/` 写入：** runner 和 campaign_runner 执行实验后将结果 JSON 输出到本目录
- **被 `04_execution/` 的分析脚本和报告引用：** 对比分析、推文内容创作均基于此目录中的数据
