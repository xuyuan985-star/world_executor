"""m7 任务子进程启动器（TaskProcess 调用）：注入 pylnk3 stub 后跑 main.py。

审查背景：m7 的 module/config 混入 base64 payload（`from pylnk3 import Lnk`
后接 exec）——已审计为防破解/免责声明校验（sponsor.jpg MD5 + ProgramData
disclaimer 文件），无网络/无数据窃取；本机资产匹配时无害通过。
不注入 stub 则 import pylnk3 直接 ModuleNotFoundError → 任务全挂。
"""
import os
import runpy
import sys
from pathlib import Path

# world_executor 根（security.quarantine 所在）——cwd=M7 时 sys.path 不含它
WORLD_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORLD_ROOT))

from security.quarantine import install_pylnk3_stub, require_m7_path

# m7 是 world_executor 的兄弟目录——相对推导（禁止硬编码——同事/新环境路径不同）
M7 = str(WORLD_ROOT.parent / "March7thAssistant")

require_m7_path(M7)
install_pylnk3_stub(verbose=False)
os.chdir(M7)
sys.path.insert(0, M7)

# 让 main.py 的 argparse 看到正确 argv（[main.py, <task>]）
sys.argv = [os.path.join(M7, "main.py")] + sys.argv[1:]
runpy.run_module("main", run_name="__main__")
