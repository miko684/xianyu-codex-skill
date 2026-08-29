"""Create local runtime state for xianyusj-phonecontrol without overwriting it."""

from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path


MEMORY_TEMPLATE = """# phonecontrol memory\n\n## 公共动作卡\n\n## 应用适配器\n\n## 任务 SOP\n\n## 待分类经验\n\n新发现先记录在这里；跨两个不同任务或应用成功复用后，才晋升为公共动作。\n"""

LOG_HEADER = [
    "date", "task_id", "app", "task_key", "action_id", "action_name",
    "method_id", "start", "end", "duration_ms", "timing_status", "result",
    "retry_count", "failure_reason", "evidence", "knowledge_class",
    "promoted_to_shared", "notes",
]


def ensure_state(runtime_dir: Path) -> tuple[Path, Path]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    memory_path = runtime_dir / "phonecontrol_memory.md"
    log_path = runtime_dir / "task_execution_log.csv"
    seed_path = Path(__file__).resolve().parent.parent / "references" / "phonecontrol_memory_seed.md"

    if not memory_path.exists():
        if seed_path.exists():
            shutil.copyfile(seed_path, memory_path)
        else:
            memory_path.write_text(MEMORY_TEMPLATE, encoding="utf-8")

    if not log_path.exists():
        with log_path.open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerow(LOG_HEADER)

    return memory_path, log_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", type=Path, default=Path(".xianyusj"))
    args = parser.parse_args()
    memory_path, log_path = ensure_state(args.runtime_dir)
    print(f"runtime_dir={args.runtime_dir}")
    print(f"memory={memory_path}")
    print(f"log={log_path}")


if __name__ == "__main__":
    main()
