"""依赖隔离层（目标 1：安全审计闭环——从临时防护升级为系统级机制）。

所有入口（smoke_test/live_monitor/live_probe/click_test/coords_calibrate/
runtime driver）统一 `from security.quarantine import ...`——单一实现，
任何新入口不会漏防护。

1. install_pylnk3_stub()——pylnk3 投毒包拦截（DisabledLnk：不伪装完整对象）。
   注意（审计修正）：stub 只保证 `from pylnk3 import Lnk` 成功；module/config/
   __init__.py 同行的 base64 exec payload 仍会执行（已解码审计：检查
   %ProgramData%/March7thAssistant/disclaimer 与 sponsor.jpg MD5，不匹配
   sys.exit(0)——防破解/免责声明校验，无网络/无数据窃取）。真防线是
   March7th 自带资产匹配；本进程每次注入时打印审计警告。
   长期解（记录）：vendor 内 fork March7th 或 stub module.config 模块。
2. require_m7_path()——M7 路径注入 sys.path 前的存在性校验（防路径注入面）。
3. sanitize_text()——报告/日志脱敏（用户名路径替换），导出 issue 时调用。
"""
import sys
import types
from pathlib import Path


def install_pylnk3_stub(verbose=True):
    """注入 pylnk3 stub，防止安装/加载 PyPI 被投毒包。

    幂等：已注入则直接返回。返回注入的 stub 模块。
    #20-3.1：Lnk 用 DisabledLnk——不伪装完整对象（silent wrong behavior 比
    crash 更危险）：path/arguments/work_dir 三个 March7th 已知会用到的属性
    返回占位，其余属性访问 raise 明确失败。
    """
    if sys.modules.get("pylnk3"):
        return sys.modules["pylnk3"]
    stub = types.ModuleType("pylnk3")
    class Lnk:
        """#33：get_link_target 用 path/arguments/work_dir；其余属性明确失败。"""
        def __init__(self, f=None):
            self.path = ""
            self.arguments = ""
            self.work_dir = ""
            if f is not None:
                f.read()  # 消费流，不解析（.lnk 解析链路禁用）

        def __getattr__(self, name):
            raise RuntimeError(
                f"Lnk parsing disabled in test environment (attribute '{name}')")
    stub.Lnk = Lnk
    sys.modules["pylnk3"] = stub
    if verbose:
        print("[security] pylnk3 stub 已注入（跳过被投毒包）")
        print("[security] 注意：module/config 内混淆 payload 仍会执行，"
              "已解码审计（防破解校验，非数据窃取）；若进程无故退出请检查 "
              "March7th assets 完整性")
    return stub


def require_m7_path(m7_root):
    """校验 March7th 根目录结构有效后才允许注入 sys.path（防路径注入面）。"""
    m7 = Path(m7_root)
    if not (m7 / "module").is_dir():
        raise RuntimeError(f"March7th 目录结构异常（缺 module/）: {m7}")
    if not (m7 / "config.yaml").exists() and not (m7 / "assets").is_dir():
        # 未初始化（无 config.yaml）时 assets 必须在，否则后面 FileNotFoundError
        pass
    return m7


def sanitize_text(text):
    """报告脱敏：Windows 用户名路径 → C:\\Users\\<USER>\\。"""
    if not text:
        return text
    try:
        user = Path.home().name
        if user:
            # 用 str.replace 而非 re.sub：Windows 路径含 `\U` 等反斜杠序列，
            # re.escape(3.7+) 不转义反斜杠会产出非法正则（bad escape）
            text = text.replace("C:\\Users\\" + user, "C:\\Users\\<USER>")
            text = text.replace("C:/Users/" + user, "C:/Users/<USER>")
    except Exception:
        pass
    return text


def sanitize_mapping(mapping):
    """递归脱敏 dict/list 中的路径字符串。"""
    if isinstance(mapping, dict):
        return {k: sanitize_mapping(v) for k, v in mapping.items()}
    if isinstance(mapping, (list, tuple)):
        return [sanitize_mapping(v) for v in mapping]
    if isinstance(mapping, str):
        return sanitize_text(mapping)
    return mapping
