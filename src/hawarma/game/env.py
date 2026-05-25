"""
游戏环境模块

GameEnv 是真实游戏的状态追踪器，由 Runner 调用。
不定义 ABC — 真实环境和模拟环境本质不同，通过 UnifiedState + Action 共享数据契约。

输入：Scanner（订单检测）、Operator（UI 操作）
输出：UnifiedState（供 Strategy 决策）

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""