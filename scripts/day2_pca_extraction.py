#!/usr/bin/env python
"""Week1 Day2: select the actual fifth PC from dated factor data.

Use extract_pc5.py for the pinned 300-stock / 768D handoff. This compatibility
entry accepts the older dated matrix and never relabels another PC as PC5.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.extract_pc5 import prepare_dataset, write_dataset  # noqa: E402


def run_pca_pipeline(
    input_file: Path = ROOT / "data/week1_pca/factors_for_pca.csv",
    output_dir: Path | None = None,
    n_components: int = 5,
    *,
    fit_end: str | None = None,
):
    output = output_dir or ROOT / "data/processed/pc5_component" / datetime.now(
        timezone.utc
    ).strftime("day2-%Y%m%dT%H%M%S%fZ")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {output}")
    dataset = {
        "id": "day2",
        "input": str(input_file),
        "kind": "dated_factors",
        "n_components": n_components,
        "fit_end": fit_end,
        "limitations": [
            "Feature availability is not verified; extraction alone is not an OOS evaluation."
        ],
    }
    result = prepare_dataset(dataset)
    summary = write_dataset(result, output)
    print(f"selected=PC05\noutput={output.resolve()}")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=ROOT / "data/week1_pca/factors_for_pca.csv"
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--n-components",
        type=int,
        default=5,
        help="Number retained, >=5; target remains PC5",
    )
    parser.add_argument(
        "--fit-end",
        help="Optional inclusive training date; later rows only use the frozen basis",
    )
    args = parser.parse_args()
    run_pca_pipeline(
        args.input, args.output_dir, args.n_components, fit_end=args.fit_end
    )


if __name__ == "__main__":
    main()
