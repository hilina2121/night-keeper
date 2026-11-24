"""One entry point for the whole pipeline.

    python -m pipeline validate        check storyboard.json against the schema
    python -m pipeline narration       TTS (cached: only changed narration regenerates)
    python -m pipeline radio           narration + placeholder music on black (user test 1)
    python -m pipeline refs            character reference candidates (pick one per character)
    python -m pipeline keyframes       one image per shot (cached: only changed shots regenerate)
    python -m pipeline keyframes --shot 5 --variants 3   candidates for one shot; pick = set its seed
    python -m pipeline all             everything above that is ready, in order
"""
from __future__ import annotations

import argparse
import sys

from pipeline.storyboard import StoryboardError, load


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m pipeline")
    p.add_argument("command", choices=["validate", "narration", "radio", "refs", "keyframes", "all"])
    p.add_argument("--shot", type=int, help="narration/keyframes: only regenerate this shot")
    p.add_argument("--character", help="refs: only this character")
    p.add_argument("--variants", type=int, help="keyframes --shot N: make this many candidates to pick from")
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

    if args.command == "refs":
        from pipeline import keyframes
        print("[reference sheet]")
        keyframes.run_refs(only=args.character)

    if args.command in ("keyframes", "all"):
        from pipeline import keyframes
        print("[keyframes]")
        if args.variants and args.shot:
            keyframes.run_variants(args.shot, args.variants)
        else:
            keyframes.run(only_shot=args.shot)


if __name__ == "__main__":
    main()
