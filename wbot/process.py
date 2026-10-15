"""显式参数列表执行子进程；不使用shell拼接命令。"""
import subprocess


def run(args, *, timeout=60, cwd=None, env=None, check=True, encoding="utf-8"):
    if not isinstance(args, (list, tuple)) or not args or not all(isinstance(x, str) for x in args):
        raise ValueError("args 必须是非空字符串列表，例如 ['python', '--version']")
    return subprocess.run(args, timeout=timeout, cwd=cwd, env=env, check=check,
                          capture_output=True, text=True, encoding=encoding, shell=False,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
