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
        except Exception as e:
            import logging
            logging.getLogger("runtime.input").warning(
                "March7th 输入后端不可用（%s）——降级 win32", e, exc_info=True)
            try:
                from runtime.input.win32_backend import Win32Backend
                return Win32Backend()
            except Exception as e2:
                # 7×24 防御：MockBackend 全部假成功——真机上静默假输入
                # 是误操作源头。显式记录（当前无调用方，仅防御未来误用）
                import logging
                logging.getLogger("runtime.input").critical(
                    "输入后端全部不可用（%s）——回退 MockBackend（假输入！）", e2)
                return MockBackend()
    if name == "march7th":
        from runtime.drivers.march7th.input import March7thInputBackend
        return March7thInputBackend()
    if name == "win32":
        from runtime.input.win32_backend import Win32Backend
        return Win32Backend()
    return MockBackend()
