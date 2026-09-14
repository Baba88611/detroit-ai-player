# 05_viewer — 可视化界面

## 职责

让人（而不是被测 AI）看到实验的全过程：每一步 AI 面对的情境、可选项、AI 的选择与思考、选择之后的效果与判定，以及章节结局。支持三种用法：

1. **本地实时**：`python 05_viewer/serve.py` 起本机服务器，在浏览器里配置并开一局，逐步观看。
2. **本地回放**：同一页面列出 `04_execution/results/` 里已有的结果文件，点开回放；也可拖入任意结果 JSON。
3. **静态回放**（GitHub Pages）：没有服务器时页面自动退化为只读模式，只能回放 `samples/` 里的样例。

## 文件夹结构

```
05_viewer/
├── CLAUDE.md
├── serve.py               ← 本地服务器（仅 Python 标准库）：静态页 + /api + 拉起 runner
├── index.html             ← 单文件前端（vanilla JS，内联 CSS，无构建步骤）
└── samples/
    ├── build_index.py     ← 重建 index.json（静态模式的结果清单）
    ├── index.json
    └── *.json             ← 样例结果（必须用当前 01_json 生成，见下）
```

## 核心约束

### 1. 零依赖

服务器只用标准库，前端不引入任何框架、打包器或 npm 依赖。玩家 clone 仓库后 `python 05_viewer/serve.py` 一条命令即可打开界面。若某功能非要依赖才能做，先在这里改规范再动手。

### 2. 信息隔离不因 UI 松动

UI 展示的效果数值、判定结果、结局条件来自 runner 的事件流（`03_runner/src/events.py`），是 system 层数据"给人看"的出口。它们只经由服务器进入浏览器，绝不进入被测 AI 的上下文。`serve.py` 不改动 runner 与模型之间的任何消息。

### 3. 密钥不过浏览器

`/api/meta` 只报告某个模型"是否已配置"（所需环境变量是否存在 / CLI 是否在 PATH 上），永不返回变量值。API key 由 runner 子进程自己从 `03_runner/.env` 读取。服务器只监听 `127.0.0.1`，不提供通用静态目录服务，`POST` 只接受 `application/json`。

### 4. 结果文件仍是权威

UI 开的一局与命令行开的一局产出完全相同的 `04_execution/results/*.json`。事件流 `04_execution/runs/<run_id>/events.jsonl` 只是实时展示用的副本，不入库、不作分析依据。

### 5. 样例来源

`samples/` 里的结果文件必须由**当前**仓库的 `01_json/` 生成。旧版决策树（英文版去逐字台词改写之前）跑出的结果，其 `context_shown` 含旧文本，不得放进来。新增样例后运行 `python 05_viewer/samples/build_index.py` 重建清单。

## serve.py 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | `index.html` |
| GET | `/samples/<name>.json` | 样例文件（名字白名单校验） |
| GET | `/api/meta` | 模型（含 `configured` / `missing` / `experimental_backend`）、persona、章节（按 zh/en）、难度枚举 |
| GET | `/api/runs` | 本机历史运行（`04_execution/runs/*/meta.json`）及状态 |
| POST | `/api/runs` | 开一局：`{mode, model, persona, difficulty, language, chapter_ids, temperature, dry_run}`；参数全部走白名单，章节 id 在服务器侧映射为文件路径 |
| GET | `/api/runs/<id>` | 单局元数据 + stderr 尾部 |
| GET | `/api/runs/<id>/events?after=<seq>` | 增量事件（前端每秒轮询） |
| POST | `/api/runs/<id>/stop` | 终止子进程 |
| GET | `/api/results` | `04_execution/results/` 清单（读文件内 `config`，不解析文件名） |
| GET | `/api/results/<name>.json` | 结果文件内容 |

运行状态：`running` / `finished` / `failed` / `interrupted`（服务器重启后仍标 running 的旧记录）。

## 事件流（由 runner 产出，UI 消费）

`type` 取值与字段见 `03_runner/src/events.py` 顶部注释。前端把结果 JSON 也转换成同一套事件序列后渲染，实时与回放共用一条渲染路径；改事件 schema 时两侧同步。

## 验证

```bash
# 服务器与事件流测试（含 dry-run 全链路）
cd 03_runner && python -m pytest tests/test_events.py tests/test_viewer_server.py -v

# 手动：起服务器，用 dry-run 开一局，确认卡片逐步出现、结局卡出现、results/ 多出一个 scripted 结果
python 05_viewer/serve.py

# 静态模式：无 /api，应退化为样例清单 + 拖拽回放
python -m http.server 8766 --directory 05_viewer
```
