"""本地服务启动器：挑空闲端口、打开浏览器、跑 Flask。

之所以只监听 127.0.0.1，是因为排班数据属于科室内网资料，
不应暴露到局域网。
"""

import os
import socket
import threading
import webbrowser
from pathlib import Path

from .app import create_app

NO_BROWSER_ENV = "MEDSHIFT_NO_BROWSER"  # 置 1 可禁止自动开浏览器（自动化/CI 用）


def find_free_port(preferred: int = 8765, *, tries: int = 30) -> int:
    """从 ``preferred`` 开始，返回第一个可用端口。

    Raises:
        RuntimeError: 连续 ``tries`` 个端口都被占用。
    """
    for offset in range(tries):
        port = preferred + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(
        f"{preferred}—{preferred + tries - 1} 之间没有可用端口，"
        "请用 --port 指定其它起始端口。"
    )


def serve(
    config_dir: str | Path,
    assignments_file: str | Path | None = None,
    *,
    port: int = 8765,
    open_browser: bool = True,
    export_dir: str | Path | None = None,
    host: str = "127.0.0.1",
) -> None:
    """启动图形界面（阻塞，直到用户 Ctrl+C）。"""
    app = create_app(config_dir, assignments_file, export_dir=export_dir)
    actual = find_free_port(port)
    url = f"http://{host}:{actual}/"

    if open_browser and not os.environ.get(NO_BROWSER_ENV):
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    print("=" * 58)
    print("  medshift 图形界面已启动")
    print(f"  浏览器访问：{url}")
    if not open_browser:
        print("  （未自动打开浏览器，请手动复制上面的地址）")
    print("  关闭本窗口或按 Ctrl+C 退出")
    print("=" * 58)

    try:
        app.run(host=host, port=actual, debug=False, use_reloader=False, threaded=True)
    except KeyboardInterrupt:  # pragma: no cover - 交互式退出
        print("\n已退出。")
