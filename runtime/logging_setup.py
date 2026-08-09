"""Bug 458/462/465：统一日志初始化——动态级别 + 轮转 + UTC 时间。

所有入口（GUI/工具/CLI）调 setup_logging() 获得一致的日志行为。
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from runtime.timeutil import iso_utc

DEFAULT_LOG = Path(__file__).resolve().parent.parent / "logs" / "app.log"


class _UtcFormatter(logging.Formatter):
    """Bug 465：日志时间统一 UTC ISO8601。"""

    def formatTime(self, record, datefmt=None):
        return iso_utc(record.created)


def setup_logging(level="INFO", log_path=None, console=True):
    """初始化 root logger：轮转文件（Bug 462）+ 可选控制台 + UTC 格式。"""
    root = logging.getLogger()
    if getattr(root, "_we_setup", False):
        return root
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    fmt = _UtcFormatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    path = Path(log_path or DEFAULT_LOG)
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(str(path), maxBytes=10 * 1024 * 1024,
                             backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if console:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        root.addHandler(ch)
    root._we_setup = True
    return root


def set_log_level(level):
    """Bug 458：运行期动态调整日志级别（排查问题无需重启）。"""
    root = logging.getLogger()
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))


def get_log_level():
    return logging.getLevelName(logging.getLogger().getEffectiveLevel())
