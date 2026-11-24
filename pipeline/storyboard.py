"""Load and validate storyboard.json, the contract between all stages.

Validation has two layers:
1. JSON Schema (schema/storyboard.schema.json): types, required fields, ranges.
2. Cross-field checks the schema cannot express (shot ids in order, cues point at real shots,
   characters used in a shot exist in the character sheet).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from pipeline.common import ROOT

STORYBOARD = ROOT / "storyboard.json"
SCHEMA = ROOT / "schema" / "storyboard.schema.json"


class StoryboardError(Exception):
    pass


def load(path: Path = STORYBOARD) -> dict:
    sb = json.loads(path.read_text(encoding="utf-8"))
    validate(sb)
    return sb


def validate(sb: dict) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(sb), key=lambda e: list(e.path))
    problems = [f"{'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in errors]

    if not problems:
        ids = [s["id"] for s in sb["shots"]]
        if ids != list(range(1, len(ids) + 1)):
            problems.append(f"shots: ids must be 1..{len(ids)} in order, got {ids}")
        for cue in sb["music"]["cues"]:
            if not (1 <= cue["from_shot"] <= cue["to_shot"] <= len(ids)):
                problems.append(f"music cue '{cue['id']}': shot range {cue['from_shot']}-{cue['to_shot']} is invalid")
        for s in sb["shots"]:
            for c in s.get("characters", []):
                if c not in sb["characters"]:
                    problems.append(f"shot {s['id']}: character '{c}' is not in the character sheet")

    if problems:
        raise StoryboardError("storyboard.json is invalid:\n  - " + "\n  - ".join(problems))


def input_hash(*parts) -> str:
    """Stable short hash of a stage's inputs. Same inputs -> same file name -> cache hit."""
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:10]
