from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# 事件流：runner 在每个节点前后发出的结构化事件，供 05_viewer 实时展示。
# 事件只是 system 层数据的另一个"给人看"的出口，绝不进入被测 AI 的上下文。
#
# 事件类型（type 字段）：
#   campaign_start  {campaign_id, config, chapters:[{index,id,title,title_zh}]}
#   chapter_start   {experiment_id, chapter_index?, chapter:{id,title,title_zh,protagonist}, language, config}
#   node_shown      {node_id, phase, node_type, context, choices:[{id,text}]}   —— 调 AI 之前发出
#   decision        {node_id, choice_id, choice_text, reasoning, raw, latency_ms,
#                    resolution_result, effects_applied, state_after}
#   narrative       {node_id, resolution_result, effects_applied, state_after}   —— 无选项节点
#   chapter_end     {experiment_id, ending, all_endings, token_usage, result_file}
#   campaign_end    {campaign_id, status, chapters:[{index,id,ending_id,ending_title,tier}]}
#   error           {message, node_id?}

EventSink = Callable[[dict[str, Any]], None]


class JsonlEventWriter:
    """把事件逐行追加到 JSONL 文件。每次 emit 立即 flush，便于另一个进程轮询读取。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.seq = 0
        self._file = self.path.open("a", encoding="utf-8")

    def __call__(self, event: dict[str, Any]) -> None:
        self.emit(event)

    def emit(self, event: dict[str, Any]) -> None:
        self.seq += 1
        record = {
            "seq": self.seq,
            "ts": datetime.now(timezone.utc).isoformat(),
            **event,
        }
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


def read_events(path: str | Path, after_seq: int = 0) -> list[dict[str, Any]]:
    """读取 seq 大于 after_seq 的事件。文件不存在时返回空列表；忽略尚未写完整的末行。"""
    file_path = Path(path)
    if not file_path.exists():
        return []

    events: list[dict[str, Any]] = []
    with file_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("seq", 0) > after_seq:
                events.append(record)
    return events


def emit(on_event: EventSink | None, event_type: str, **payload: Any) -> None:
    """安全发事件：sink 为 None 时是空操作，保证不传 on_event 的旧调用路径行为不变。"""
    if on_event is None:
        return
    on_event({"type": event_type, **payload})
