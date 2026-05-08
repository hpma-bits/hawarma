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

### `architecture_redesign.md`
- **地位**: 架构重构设计方案
- **状态**: ✅ 当前有效
- **功能**:
  - 重构前的架构问题诊断
  - 目标架构设计原则和层次图
  - Phase 1-3 的分步实施计划
  - 甜点平台扩展预留方案
  - 命名规范和文件变更清单

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

## 📝 已归档文档

以下文档已被清理，内容已整合到 `agent_strategy.md` 和 `architecture_redesign.md`：

| 文档名 | 原因 |
|--------|------|
| `agent_architecture.md` | 旧架构设计（Runner 时代），已由 architecture_redesign.md 替代 |
| `playground_plan.md` | Playground 已建成，计划已执行完毕 |
| `assembly_deadlock_analysis.md` | 事件分析已收录到旧版 agent_strategy.md，修复方案已实施 |

## 🔗 文档关系

```
game_rules.md (基础)
    ↑
    ├── agent_strategy.md (策略+基准)
    ├── architecture_redesign.md (架构设计)
    ├── real_game_implementation.md (实现)
    └── dessert_station.md (甜点站点设计)
```

## 📝 文档维护规范

1. **新增文档**: 必须在本文件中添加条目
2. **删除文档**: 必须从本文件中移除条目
3. **重命名文档**: 必须更新本文件中的文件名
