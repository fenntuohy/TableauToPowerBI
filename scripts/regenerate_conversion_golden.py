#!/usr/bin/env python3
"""Regenerate ``tests/golden/conversion_counts.json``.

Migrates every sample in ``examples/tableau_samples`` into a temp directory,
records the source and output object counts, the loss-check status, and the
number of BLANK() DAX stubs, and writes the golden.

Run after an intentional conversion change, then review the diff before
committing. The golden is a review record, not an auto-accept: a changed
count is a behaviour change and should be explained in the commit.

    .venv/bin/python scripts/regenerate_conversion_golden.py
"""

import glob
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from powerbi_import.loss_report import (  # noqa: E402
    _placed_worksheets, build_loss_report, count_output, count_source,
)

SAMPLES = os.path.join(ROOT, "examples", "tableau_samples")
GOLDEN = os.path.join(ROOT, "tests", "golden", "conversion_counts.json")


def _project_dir(out_root):
    for d in sorted(glob.glob(os.path.join(out_root, "*"))):
        if os.path.isdir(d) and not os.path.basename(d).startswith("."):
            return d
    return None


def main():
    golden = {}
    for twb in sorted(glob.glob(os.path.join(SAMPLES, "*.twb"))):
        name = os.path.splitext(os.path.basename(twb))[0]
        out = tempfile.mkdtemp(prefix="golden_")
        subprocess.run(
            [sys.executable, os.path.join(ROOT, "migrate.py"), twb,
             "--output-dir", out, "--no-verify-open", "--quiet"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proj = _project_dir(out)
        if not proj:
            print(f"{name}: no project generated, skipped")
            continue
        src = count_source(twb)
        src["worksheets"] = _placed_worksheets(twb, src["worksheets"])
        stubs = 0
        for tmdl in glob.glob(os.path.join(proj, "*.SemanticModel", "definition", "tables", "*.tmdl")):
            with open(tmdl, encoding="utf-8", errors="ignore") as fh:
                stubs += fh.read().count("DAX conversion failed")
        golden[name] = {
            "loss_status": build_loss_report(twb, proj)["status"],
            "source": src,
            "output": count_output(proj),
            "dax_stubs": stubs,
        }
        print(f"{name}: {golden[name]['loss_status']}")
    with open(GOLDEN, "w", encoding="utf-8") as fh:
        json.dump(golden, fh, indent=2, sort_keys=True)
    print(f"wrote {GOLDEN} ({len(golden)} workbooks)")


if __name__ == "__main__":
    main()
