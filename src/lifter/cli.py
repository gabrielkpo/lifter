"""Command line entry point."""

import argparse

from lifter import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lifter", description=__doc__)
    parser.add_argument("--version", action="version", version=f"lifter {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0
