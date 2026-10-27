"""Explicit generation/verification entrypoints; never launches SWAN itself."""

import argparse
from contextlib import redirect_stdout, redirect_stderr
import json
import os

from .stages import generate, verify, StageError


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="phase", required=True)
    generation = sub.add_parser("generate")
    generation.add_argument("--destination", default="/work/run")
    verification = sub.add_parser("verify")
    verification.add_argument("--source", default="/work/run")
    verification.add_argument("--report", default="/work/report")
    args = parser.parse_args()
    try:
        with (
            open(os.devnull, "w") as quiet,
            redirect_stdout(quiet),
            redirect_stderr(quiet),
        ):
            if args.phase == "generate":
                raw = os.environ.pop("ROMPY_HANDOFF_JSON", "")
                result = generate(raw, args.destination)
            else:
                if os.environ.get("DATAMESH_TOKEN") or os.environ.get(
                    "ROMPY_HANDOFF_JSON"
                ):
                    raise StageError("credential_or_handoff_env_in_verification")
                result = verify(args.source, args.report)
        print(json.dumps({"phase": result["phase"]}))
        return 0
    except Exception as error:
        reason = str(error) if isinstance(error, StageError) else "stage_failure"
        print(json.dumps({"phase": "failed", "reason": reason}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
