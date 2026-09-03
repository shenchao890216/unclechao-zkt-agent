"""pip 安装后的命令入口:zkt 的模块是平铺导入的,先把包目录挂上 sys.path。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli import main  # noqa: E402


def run() -> int:
    sys.exit(main())
