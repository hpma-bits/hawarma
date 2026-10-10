# docs 目录架构

## 📁 目录概述

此目录包含 hawarma 项目的真实游戏设计文档和使用说明。

## ⚠️ 重要提示

**一旦本目录有变化（新增/删除/重命名文件），请立即更新本文档！**

## 📄 文件列表

### `game_rules.md`
- **地位**: 游戏规则说明（唯一依据）
- **状态**: ✅ 当前有效
- **功能**:
  - 定义游戏的核心规则，作为模拟环境和验证的唯一依据
  - 订单系统、评分机制、操作约束
  - 坐标确定规则（灶台、食材区、调料区）

### `agent_strategy.md`
- **地位**: Agent 策略设计与基准测试文档
- **状态**: ✅ 当前有效
- **功能**:
  - 策略架构说明（三层模型：core/agent/game）
  - 各策略基准测试排名（100局平均）
  - 策略切换方式
  - 核心优化总结

### `real_game_implementation.md`
- **地位**: 真实游戏交互实现文档
- **状态**: ✅ 当前有效
- **功能**:
  - 梳理当前与真实游戏交互的技术栈、数据结构、算法
  - 列出与 game_rules.md 的对应实现关系
  - 总结已实施的性能优化策略

### `dessert_station.md`
- **地位**: 甜点站点架构设计文档
- **状态**: ✅ 当前有效
- **功能**:
  - 甜点模式与 Gastronome 模式的区别
  - 甜点流程和约束
  - 数据结构设计（MixingBowlState、Action 类型）
  - Env 接口扩展
  - DessertStrategy 实现
  - 配置结构和文件组织
  - 实现步骤和测试策略

### `glossary.md`
- **地位**: 术语表
- **状态**: ✅ 当前有效
- **功能**:
  - 定义项目中常用的术语
  - 统一概念理解
  - 包含游戏领域、架构、策略、操作、配置等术语

### `tui_guide.md`
- **地位**: TUI 使用指南
- **状态**: ✅ 当前有效
- **功能**:
  - TUI 仪表板的使用说明（配方选择、配置面板、游戏控制、日志）

### `tui_summary.md`
- **地位**: TUI 改造总结（实现记录）
- **状态**: ✅ 历史记录
- **功能**:
  - 记录 TUI 从 cli.py 改造过程中的实现决策

### `code_review.md`
- **地位**: 外部视角代码评审记录
- **状态**: ✅ 历史记录
- **功能**:
  - 对仓库架构意图（模拟、策略隔离、桥接抽象）的外部评审观察

### `adr/`
- **地位**: 架构决策记录（ADR）
- **状态**: ✅ 当前有效
- **功能**:
  - `0001-scoring-metrics-split-and-action-increment.md` — 度量抽离与 Action 三增量决策

## 📝 已归档文档

以下文档已被清理，内容已整合到 `agent_strategy.md`（架构现状见 `src/hawarma/ARCHITECTURE.md`）：

| 文档名 | 原因 |
|--------|------|
| `agent_architecture.md` | 旧架构设计（Runner 时代），内容已由 agent_strategy.md 收录，架构现状见 `src/hawarma/ARCHITECTURE.md` |
| `architecture_redesign.md` | 重构计划已全部执行完毕，架构现状见 `src/hawarma/ARCHITECTURE.md` |
| `playground_plan.md` | Playground 已建成，计划已执行完毕 |
| `assembly_deadlock_analysis.md` | 事件分析已收录到旧版 agent_strategy.md，修复方案已实施 |

## 🔗 文档关系

```
game_rules.md (基础)
    ↑
    ├── agent_strategy.md (策略+基准)
    ├── real_game_implementation.md (实现)
    ├── dessert_station.md (甜点站点设计)
    └── glossary.md (术语表)
```

## 📝 文档维护规范

1. **新增文档**: 必须在本文件中添加条目
2. **删除文档**: 必须从本文件中移除条目
3. **重命名文档**: 必须更新本文件中的文件名
