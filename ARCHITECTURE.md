# Hawarma 项目架构

## 📁 目录结构

```
hawarma/
├── hawarma/           # 核心代码
│   ├── agent/         # Agent决策逻辑
│   ├── bridge/        # 桥接层
│   ├── services/      # 服务层
│   └── utils/         # 工具函数
├── scripts/           # 脚本文件
├── experiments/       # 实验代码和报告
├── docs/              # 文档
├── configs/           # 配置文件
├── data/              # 数据文件
└── static/            # 静态资源
```

## 📄 关键目录说明

### `experiments/`
- **地位**: 实验代码和报告
- **功能**: 保存基准测试脚本和实验历史
- **关键文件**:
  - `benchmark_agent.py`: 基准测试脚本
  - `README.md`: 实验记录

### `docs/`
- **地位**: 项目文档
- **功能**: 游戏规则、策略设计、架构说明
- **关键文件**:
  - `game_rules.md`: 游戏规则
  - `agent_strategy.md`: Agent策略和实验结果
  - `agent_architecture.md`: Agent架构设计

### `hawarma/`
- **地位**: 核心代码
- **功能**: Agent、环境、桥接层

## ⚠️ 重要原则

**文档优先原则**：
- 把 `docs/` 作为真实信息源
- 思考问题从文档出发
- 代码与文档保持一致

详见 `AGENTS.md`
