"""Draft the catalog labels of a new brand image for a person to confirm.

    python -m evals.asset_labels.draft <png> \
        --references <xiao-sai full body>,<sai-xiansheng full body> \
        [--model qwen3-vl-plus] \
        [--materials-root /root/projects/edu-ai-lead-agent/private/brand-materials]

Prints a `visual-assets.metadata.json` entry keyed by the image's path relative to the
materials root, with `approved: false`. It never writes the private files: copy the entry in
after checking the characters and the prop, then rebuild the manifest with
`scripts/build_brand_asset_manifest.py`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from evals.asset_labels.client import DashScopeVL, label_image
from evals.asset_labels.labels import metadata_draft
from evals.asset_labels.runner import REFERENCES_HELP, split_references

DEFAULT_ROOT = Path("/root/projects/edu-ai-lead-agent/private/brand-materials")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--references", required=True, help=REFERENCES_HELP)
    parser.add_argument("--model", default="qwen3-vl-plus")
    parser.add_argument("--materials-root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    root = args.materials_root.resolve()
    references = split_references(args.references, root, parser)
    image = args.image.resolve()
    try:
        key = image.relative_to(root).as_posix()
    except ValueError:
        key = image.name
    model = DashScopeVL(args.model)
    try:
        outcome = label_image(model, image, references=[root / p for p in references])
    finally:
        model.close()
    if outcome.labels is None:
        print(f"no valid labels after {outcome.calls} calls: {outcome.error}", file=sys.stderr)
        return 1
    entry = {key: metadata_draft(outcome.labels, model=args.model)}
    print(json.dumps(entry, ensure_ascii=False, indent=2))
    if outcome.labels.note:
        print(f"# basis: {outcome.labels.note}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
