"""阶段1.1 CAR-T 数据平台 —— 统一开发环境。

模块划分：
  config   环境与常量（含 LLM 计价口径）
  db       PostgreSQL 连接与批次管理
  storage  Raw Data 目录规范、校验和、来源登记
  llm      Claude 调用 + 结构化抽取 + 用量计费打点
"""
__version__ = "0.1.0"
