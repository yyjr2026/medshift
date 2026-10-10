"""medshift 图形界面（本地 Web 版）。

最简用法::

    medshift gui -c examples/radiology

或者直接用 Python::

    from medshift.gui import serve
    serve("examples/radiology")

浏览器会自动打开 ``http://127.0.0.1:<port>``。
本模块依赖 Flask，安装方式：``pip install "medshift[gui]"``。
"""

from .app import create_app
from .server import find_free_port, serve

__all__ = ["create_app", "find_free_port", "serve"]
