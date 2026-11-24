"""One entry point for the whole pipeline.

    python -m pipeline validate        check storyboard.json against the schema
    python -m pipeline narration       TTS for every line (cached: only changed lines regenerate)
    python -m pipeline radio           narration + placeholder music on black (user test 1)
    python -m pipeline all             everything above, in order
"""
from __future__ import annotations

import argparse
import sys

from pipeline.storyboard import StoryboardError, load


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m pipeline")
    p.add_argument("command", choices=["validate", "narration", "radio", "all"])
    p.add_argument("--shot", type=int, help="narration: only regenerate this shot")
    args = p.parse_args()

    try:
        sb = load()
    except StoryboardError as e:
        sys.exit(str(e))
    print(f"[validate] storyboard.json OK: '{sb['title']}' {sb['version']}, {len(sb['shots'])} shots")
    if args.command == "validate":
        return

    if args.command in ("narration", "all"):
        from pipeline import narration
        print("[narration]")
        narration.run(only_shot=args.shot)

    if args.command in ("radio", "all"):
        from pipeline import radio_cut
        print("[radio cut]")
        radio_cut.run()


if __name__ == "__main__":
    main()
