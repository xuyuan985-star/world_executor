"""全局热键（对齐 M7：用 keyboard 库——RegisterHotKey/nativeEvent 在此环境不可靠）。

keyboard.on_press_key 后台线程回调 → Qt 信号（QueuedConnection）到主线程。
"""
import threading

from PySide6.QtCore import QObject, Signal


class GlobalHotkey(QObject):
    pressed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._handlers = {}
        self._lock = threading.Lock()

    def register(self, key, callback):
        """注册全局热键：key='f10'；回调在主线程（信号投递）。"""
        import keyboard
        with self._lock:
            if key in self._handlers:
                return
            handler = keyboard.on_press_key(
                key, lambda e: self.pressed.emit(key), suppress=False)
            self._handlers[key] = handler

    def unregister_all(self):
        import keyboard
        with self._lock:
            for k, h in list(self._handlers.items()):
                try:
                    keyboard.unhook(h)
                except Exception:
                    pass
            self._handlers.clear()
