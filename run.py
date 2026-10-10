"""开发环境启动入口：python run.py [--browser]"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
