"""Read-only NALE input audit; invoke with ``python -m tools.audit_nale_alpha_inputs``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from src.data.nale_alpha_input_gate import audit_input_gate
from src.data.nale_alpha_input_loader import load_input_frames


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit NALE input integrity and structure, not authenticity")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--minimum-stocks", required=True, type=int)
    parser.add_argument("--minimum-days", required=True, type=int)
    args = parser.parse_args(argv)
    if args.minimum_stocks < 1 or args.minimum_days < 1:
        parser.error("minimum-stocks and minimum-days must be positive")
    loaded = load_input_frames(args.manifest, args.data_root)
    if loaded.status != "LOADED_PROVENANCE_UNVERIFIED" or loaded.frames is None:
        report = {
            "status": "BLOCKED",
            "load_status": loaded.status,
            "gate_status": "NOT_RUN",
            "issues": list(loaded.issues),
            "verified_sha256": loaded.verified_sha256,
            "historical_authenticity": "UNVERIFIED",
        }
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 2
    gated = audit_input_gate(
        args.manifest,
        args.data_root,
        loaded.frames,
        minimum_stocks=args.minimum_stocks,
        minimum_days=args.minimum_days,
    )
    report = {
        "status": gated.status,
        "load_status": loaded.status,
        "gate_status": gated.status,
        "manifest_status": gated.manifest_status,
        "structure_status": gated.structure_status,
        "issues": list(gated.issues),
        "verified_sha256": gated.verified_sha256,
        "historical_authenticity": "UNVERIFIED",
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 3 if gated.status == "PENDING_PROVENANCE_REVIEW" else 2


if __name__ == "__main__":
    raise SystemExit(main())
