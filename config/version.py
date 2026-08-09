"""版本单点（Bug 194）：全项目版本号唯一来源。"""
import importlib.metadata

APP_NAME = "world-executor"

try:
    APP_VERSION = importlib.metadata.version(APP_NAME)
except Exception:
    APP_VERSION = "dev"

# 知识包 schema 版本（与 runtime.knowledge_loader 同步——单点避免双写漂移）
KNOWLEDGE_SCHEMA_VERSION = 1

# 点位数据版本（archive 写入 points_meta.json）
POINTS_VERSION = "1.1"
