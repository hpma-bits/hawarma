"""
Playground Replay Recorder

记录并回放游戏过程。

输入: EpisodeResult.history
输出: JSON 回放文件 / CLI 交互式回放
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playground.core.episode import EpisodeResult


@dataclass
class ReplayEntry:
    """单步回放记录"""
    time: float
    action_type: str | None
    action_details: dict | None


def save_replay(result: EpisodeResult, filepath: str) -> None:
    """保存回放为 JSON"""
    # 简化：只保存关键信息，不保存完整的 state 对象（太大）
    entries = []
    for time, state, action in result.history:
        entry = {
            "time": time,
            "action": {
                "type": type(action).__name__ if action else None,
                "details": _action_to_dict(action) if action else None,
            },
            "state_summary": _summarize_state(state),
        }
        entries.append(entry)

    data = {
        "seed": result.seed,
        "strategy": result.strategy_name,
        "total_reward": result.total_reward,
        "steps": result.steps,
        "actions_taken": result.actions_taken,
        "entries": entries,
    }

    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_replay(filepath: str) -> dict:
    """加载回放 JSON"""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def replay_cli(filepath: str) -> None:
    """CLI 交互式回放"""
    data = load_replay(filepath)
    entries = data["entries"]

    print(f"Replay: {data['strategy']} | seed={data['seed']} | reward={data['total_reward']}")
    print(f"Steps: {data['steps']} | Actions: {data['actions_taken']}")
    print("Commands: [n]ext, [p]revious, [j]ump <time>, [q]uit")
    print("-" * 60)

    idx = 0
    while True:
        if 0 <= idx < len(entries):
            entry = entries[idx]
            print(f"\n[{idx+1}/{len(entries)}] t={entry['time']:.1f}s")
            if entry["action"]["type"]:
                print(f"  Action: {entry['action']['type']}")
                if entry["action"]["details"]:
                    for k, v in entry["action"]["details"].items():
                        print(f"    {k}: {v}")
            else:
                print("  Action: None")

            summary = entry["state_summary"]
            print(f"  Orders: {summary['orders']}")
            print(f"  Cookers: {summary['cookers']}")
            print(f"  Assembly: {summary['assembly']}")

        cmd = input("\n> ").strip().lower()
        if cmd == "n" or cmd == "":
            idx = min(idx + 1, len(entries) - 1)
        elif cmd == "p":
            idx = max(idx - 1, 0)
        elif cmd.startswith("j "):
            try:
                target_time = float(cmd[2:])
                # 找到最接近的时间点
                closest = min(range(len(entries)), key=lambda i: abs(entries[i]["time"] - target_time))
                idx = closest
            except ValueError:
                print("Usage: j <time>")
        elif cmd == "q":
            break
        else:
            print("Unknown command")


def _action_to_dict(action):
    """将 Action 转换为可序列化的 dict"""
    from dataclasses import asdict
    try:
        return {k: v for k, v in asdict(action).items() if v is not None}
    except TypeError:
        return {}


def _summarize_state(state):
    """提取 state 的关键摘要"""
    return {
        "orders": sum(1 for o in state.orders if o is not None),
        "cookers": sum(1 for c in state.cookers.values() if c.busy),
        "assembly": len(state.assembly.ingredients_cookers),
        "stockpile": sum(s.count for s in state.stockpile.values()),
    }
