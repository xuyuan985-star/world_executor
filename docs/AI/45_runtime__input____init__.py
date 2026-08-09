# runtime/input/__init__.py

```python
from runtime.input.base import InputBackend
from runtime.input.mock_backend import MockBackend

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
            from runtime.drivers.march7th.input import March7thInputBackend
            return March7thInputBackend()
        except Exception:
            try:
                from runtime.input.win32_backend import Win32Backend
                return Win32Backend()
            except Exception:
                return MockBackend()
    if name == "march7th":
        from runtime.drivers.march7th.input import March7thInputBackend
        return March7thInputBackend()
    if name == "win32":
        from runtime.input.win32_backend import Win32Backend
        return Win32Backend()
    return MockBackend()

```
