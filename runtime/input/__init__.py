from runtime.input.base import InputBackend
from runtime.input.mock_backend import MockBackend

BACKENDS = {
    "mock": MockBackend,
    "march7th": None,  # 延迟导入（依赖 March7th）
    "win32": None,
}
_cached = {}


def get_backend(name="auto"):
    if name in _cached:
        return _cached[name]
    backend = _create(name)
    _cached[name] = backend
    return backend


def _create(name):
    if name == "auto":
        try:
            from runtime.input.march7th_backend import March7thBackend
            b = March7thBackend()
            b.ensure_auto()
            return b
        except Exception:
            try:
                from runtime.input.win32_backend import Win32Backend
                return Win32Backend()
            except Exception:
                return MockBackend()
    if name in ("march7th", "win32"):
        from importlib import import_module
        mod = import_module(f"runtime.input.{name}_backend")
        cls = getattr(mod, {"march7th": "March7thBackend", "win32": "Win32Backend"}[name])
        b = cls()
        if name == "march7th":
            b.ensure_auto()
        return b
    return MockBackend()
