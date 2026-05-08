import argparse
import os
import sys


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="jamarr-tui", description="Terminal UI for Jamarr"
    )
    parser.add_argument(
        "--server",
        default=os.environ.get("JAMARR_URL"),
        help=(
            "Jamarr server URL. If omitted, you will be prompted on the "
            "login screen. Env: JAMARR_URL."
        ),
    )
    parser.add_argument(
        "--username",
        default=os.environ.get("JAMARR_USERNAME"),
        help="Username (otherwise prompted on the login screen)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    server = args.server.rstrip("/") if args.server else None

    from jamarr_tui.screens.app import JamarrTuiApp

    try:
        JamarrTuiApp(server=server, username=args.username).run()
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    return 0
