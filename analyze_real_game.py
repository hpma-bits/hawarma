"""
Real Game Performance Analyzer
"""

import re
from collections import defaultdict


def analyze_log(filepath: str) -> dict:
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    scan_durations = []
    action_intervals = []
    serve_total_times = []
    move_after_cook_delays = []
    none_streaks = []
    animation_windows = []

    last_action_time = None
    last_action_name = None
    none_streak_start = None

    cooker_done = {}
    serve_decision_time = None

    for i, line in enumerate(lines):
        m = re.search(r"Scan completed: \d+ detected, duration=(\d+\.\d+)ms", line)
        if m:
            scan_durations.append(float(m.group(1)))

        m_decision = re.search(r"\[t=([\d.]+)s\] step: strategy returned (\w+)", line)
        if m_decision:
            t = float(m_decision.group(1))
            action_type = m_decision.group(2)
            if action_type == "None":
                if none_streak_start is None:
                    none_streak_start = t
            else:
                if none_streak_start is not None:
                    duration = t - none_streak_start
                    if duration > 0.3:
                        none_streaks.append(duration)
                    none_streak_start = None
            if "Serve" in action_type:
                serve_decision_time = t

        m_exec = re.search(r"\[t=([\d.]+)s\] (Cooking|Moved|Served|Pulled|Added|Cleared|Stored)", line)
        if m_exec:
            t = float(m_exec.group(1))
            action_name = m_exec.group(2)

            if last_action_time is not None:
                interval = t - last_action_time
                action_intervals.append((interval, last_action_name, action_name))
            last_action_time = t
            last_action_name = action_name

            if action_name == "Cooking":
                m_cooker = re.search(r"on (\w+)$", line.strip())
                if m_cooker:
                    cooker = m_cooker.group(1)
                    m_dur = re.search(r"\(([\d.]+)s\)", line)
                    if m_dur:
                        duration = float(m_dur.group(1))
                        cooker_done[cooker] = t + duration

            if action_name == "Moved" and "from" in line and "assembly" in line:
                m_cooker = re.search(r"from (\w+) to", line)
                if m_cooker:
                    cooker = m_cooker.group(1)
                    if cooker in cooker_done:
                        delay = t - cooker_done[cooker]
                        if 0 <= delay < 10:
                            move_after_cook_delays.append(delay)
                        del cooker_done[cooker]

        if "Serve succeeded" in line or "Serve verification failed" in line:
            m = re.search(r"\[t=([\d.]+)s\]", line)
            if m and serve_decision_time:
                t = float(m.group(1))
                serve_total_times.append(t - serve_decision_time)
                serve_decision_time = None

        if "set_animation_window" in line:
            m = re.search(r"\[t=([\d.]+)s\]", line)
            if m:
                anim_start = float(m.group(1))
                for j in range(i + 1, min(i + 50, len(lines))):
                    if "Scan completed" in lines[j]:
                        m2 = re.search(r"\[t=([\d.]+)s\]", lines[j])
                        if m2:
                            scan_t = float(m2.group(1))
                            if scan_t > anim_start:
                                animation_windows.append(scan_t - anim_start)
                                break
                        break

    def stats(arr):
        if not arr:
            return {}
        arr_sorted = sorted(arr)
        n = len(arr)
        return {
            "count": n,
            "mean": sum(arr) / n,
            "min": min(arr),
            "max": max(arr),
            "p50": arr_sorted[n // 2],
            "p90": arr_sorted[int(n * 0.9)] if n >= 10 else arr_sorted[-1],
        }

    return {
        "scan": stats(scan_durations),
        "action_interval": stats([x[0] for x in action_intervals]),
        "move_after_cook_delay": stats(move_after_cook_delays),
        "serve_total_time": stats(serve_total_times),
        "none_streak": stats(none_streaks),
        "animation_window": stats(animation_windows),
        "raw_action_intervals": action_intervals,
        "raw_none_streaks": none_streaks,
    }


def print_report(data: dict):
    print("=" * 60)
    print("Real Game Performance Report")
    print("=" * 60)

    print("\n[1. Scan Duration]")
    s = data["scan"]
    if s:
        print(f"  Count:    {s['count']}")
        print(f"  Mean:     {s['mean']:.0f}ms")
        print(f"  P50:      {s['p50']:.0f}ms")
        print(f"  P90:      {s['p90']:.0f}ms")
        print(f"  Max:      {s['max']:.0f}ms")
        print(f"  Scans/sec: {1000/s['mean']:.1f}")

    print("\n[2. UI Action Interval]")
    s = data["action_interval"]
    if s:
        print(f"  Count:    {s['count']}")
        print(f"  Mean:     {s['mean']:.2f}s")
        print(f"  P50:      {s['p50']:.2f}s")
        print(f"  P90:      {s['p90']:.2f}s")
        print(f"  Max:      {s['max']:.2f}s")

    print("\n[3. Delay: Cook Done -> Move to Assembly]")
    s = data["move_after_cook_delay"]
    if s:
        print(f"  Count:    {s['count']}")
        print(f"  Mean:     {s['mean']:.2f}s")
        print(f"  P50:      {s['p50']:.2f}s")
        print(f"  P90:      {s['p90']:.2f}s")
        print(f"  Max:      {s['max']:.2f}s")
        over2 = sum(1 for x in data["move_after_cook_delay"] if x > 2.0)
        print(f"  >2s:      {over2}/{s['count']} ({over2/s['count']*100:.0f}%)")
    else:
        print("  No data")

    print("\n[4. Serve Total Time (decision -> verify)]")
    s = data["serve_total_time"]
    if s:
        print(f"  Count:    {s['count']}")
        print(f"  Mean:     {s['mean']:.2f}s")
        print(f"  P50:      {s['p50']:.2f}s")
        print(f"  P90:      {s['p90']:.2f}s")
    else:
        print("  No data")

    print("\n[5. Agent Idle Streaks (consecutive None > 0.3s)]")
    s = data["none_streak"]
    if s:
        print(f"  Count:    {s['count']}")
        print(f"  Mean:     {s['mean']:.2f}s")
        print(f"  P50:      {s['p50']:.2f}s")
        print(f"  P90:      {s['p90']:.2f}s")
        print(f"  Max:      {s['max']:.2f}s")
        total_none = sum(data["raw_none_streaks"])
        print(f"  Total idle: {total_none:.1f}s ({total_none/103.6*100:.1f}% of game)")
    else:
        print("  No data")

    print("\n[6. Animation Window Recovery]")
    s = data["animation_window"]
    if s:
        print(f"  Count:    {s['count']}")
        print(f"  Mean:     {s['mean']:.2f}s")
        print(f"  P50:      {s['p50']:.2f}s")
        print(f"  P90:      {s['p90']:.2f}s")
    else:
        print("  No data")

    print("\n[7. Action Interval by Type (top 10)]")
    intervals = defaultdict(list)
    for dur, from_action, to_action in data["raw_action_intervals"]:
        key = f"{from_action} -> {to_action}"
        intervals[key].append(dur)

    for key, arr in sorted(intervals.items(), key=lambda x: -len(x[1]))[:10]:
        avg = sum(arr) / len(arr)
        print(f"  {key:25s}: n={len(arr):2d}, avg={avg:.2f}s")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    data = analyze_log("logs/game_20260427_185810.log")
    print_report(data)
