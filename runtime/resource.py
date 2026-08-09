"""Bug 120：统一资源生命周期管理（轻量）。

进程级注册表 + atexit 清理——线程/子进程/句柄等长生命周期资源
统一登记，退出时保证释放（防长时间运行句柄/内存泄漏）。
"""
import atexit
import logging
import threading

_log = logging.getLogger("runtime.resource")
_lock = threading.Lock()
_cleanups = []  # [(name, callable)]


def register(name, cleanup):
    """注册退出清理回调。name 用于去重（重复注册只保留最后）。"""
    with _lock:
        for i, (n, _) in enumerate(_cleanups):
            if n == name:
                _cleanups[i] = (name, cleanup)
                return
        _cleanups.append((name, cleanup))


def unregister(name):
    with _lock:
        _cleanups[:] = [(n, c) for n, c in _cleanups if n != name]


def _shutdown():
    """atexit 清理：倒序执行（后注册的先清理），单次异常不阻断。"""
    with _lock:
        pending = list(reversed(_cleanups))
    for name, cleanup in pending:
        try:
            cleanup()
        except Exception:
            _log.exception("resource cleanup failed: %s", name)


atexit.register(_shutdown)
