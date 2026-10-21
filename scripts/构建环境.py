"""限制打包器的 DLL 搜索范围，防止收集其他软件的同名库。"""

import os
from pathlib import Path


def build_environment(environ, executable, base_prefix):
    result = dict(environ)
    system = Path(environ.get("SystemRoot", "C:/Windows"))
    result["PATH"] = os.pathsep.join(map(str, [Path(executable).parent, Path(base_prefix), Path(base_prefix) / "DLLs", system / "System32", system]))
    for key in ("PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH"):
        result.pop(key, None)
    return result
