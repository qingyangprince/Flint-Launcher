# flint/__main__.py
from __future__ import annotations

import argparse
import sys

from . import __version__
from .app import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="flint", description="Flint - 快速、原生加速的 Minecraft 启动器"
    )
    parser.add_argument("--version", action="version", version=f"Flint {__version__}")
    parser.add_argument("--debug", action="store_true", help="开启 DEBUG 日志")
    parser.add_argument("--instance", metavar="NAME", help="直接启动指定实例")
    args = parser.parse_args(argv)

    if args.instance:
        print(f"warning: 实例启动尚未接入，忽略 --instance={args.instance}", file=sys.stderr)

    return run(debug=args.debug)


if __name__ == "__main__":
    sys.exit(main())
