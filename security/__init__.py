"""安全隔离层（Part 4 目标1）：依赖 quarantine + 脱敏 + 路径校验。

对外接口（Bug 68）：quarantine/sanitize/path 校验统一从这里导出。
"""
from security.quarantine import (  # noqa: F401
    install_pylnk3_stub,
    install_security_stubs,
    require_m7_path,
    sanitize_mapping,
    sanitize_text,
)
