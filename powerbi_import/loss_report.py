"""Source-vs-output loss report.

Reads the Tableau workbook XML (``.twb``, or the ``.twb`` inside a ``.twbx``)
as the source of truth and compares object counts with the generated PBIP
project. Every drop is reported. A drop is *unexplained* unless the object is
listed in ``degradations`` in ``migration_metadata.json`` or a known
exemption applies.

The check is deliberately count-based. It answers "did objects disappear?",
not "is each formula correct?". Formula correctness is covered by the DAX and
M gates.

Public API:
    count_source(twb_path) -> dict
    count_output(project_dir) -> dict
    build_loss_report(twb_path, project_dir) -> dict
    write_loss_report(report, project_dir) -> str
"""

from __future__ import annotations

import glob
import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from typing import Dict, List, Optional

LOSS_REPORT_FILE = "loss_report.json"

# Objects whose count is compared. Each value is (source key, output key).
COMPARED = (
    "worksheets",
    "dashboards",
    "calculated_fields",
    "parameters",
    "filters",
    "relations",
    "hyper_extracts",
)

# Max tolerated fraction of objects lost before the check fails outright.
# Below this a drop is still reported, but it is a warning rather than an error.
WARN_LOSS_FRACTION = 0.0


def _locate_twb(path: str) -> Optional[str]:
    """Return the .twb to parse. For .twbx, extract the .twb to a temp dir."""
    if path.lower().endswith(".twb"):
        return path if os.path.isfile(path) else None
    if path.lower().endswith(".twbx") and zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            members = [m for m in zf.namelist() if m.lower().endswith(".twb")]
            if not members:
                return None
            tmp = tempfile.mkdtemp(prefix="loss_report_")
            zf.extract(members[0], tmp)
            return os.path.join(tmp, members[0])
    return None


def _calc_key(col) -> str:
    """Identity of a calc: its caption, falling back to its internal name."""
    return str(col.get("caption") or col.get("name") or "").strip()


def sibling_hyper_files(twb_path: str) -> List[str]:
    """Hyper extracts that sit beside an unpacked .twb (``Data/Extracts/*.hyper``).

    A ``.twb`` read on its own never sees these; they are only discovered when
    the source is the ``.twbx`` archive. Returning them lets the loss check
    count them against the output.
    """
    base = os.path.dirname(os.path.abspath(twb_path))
    return sorted(glob.glob(os.path.join(base, "**", "*.hyper"), recursive=True))


def count_source(twb_path: str) -> Dict[str, int]:
    """Count objects in a Tableau workbook XML.

    Only counts that map to an output object are included, so the comparison
    does not penalise objects that never had an output form.
    """
    root = ET.parse(twb_path).getroot()
    columns = list(root.iter("column"))

    # Calculated fields only. Bins and groups are a separate construct and are
    # not counted here (the output counts them under "groups", not measures).
    calc_fields = [c for c in columns if c.find("calculation") is not None
                   and c.find("calculation").get("class")
                   not in ("categorical-bin", "quantitative-bin")]
    # Tableau 'measure' calcs become DAX measures. 'dimension' calcs become
    # calculated columns, so they are compared against columns, not measures.
    calc_measures = [c for c in calc_fields if c.get("role") == "measure"]
    calc_dimensions = [c for c in calc_fields if c.get("role") != "measure"]
    parameters = [c for c in columns if c.get("param-domain-type")]
    # A <relation type='table'> is a single-table binding to a connection, not
    # a join. Real relationships are joins (a <relation> with a join attribute)
    # or object-graph <relationship> entries. Counting bindings as relations
    # would report every single-table workbook as having lost its relations.
    relations = [r for r in root.iter("relation") if r.get("join")]
    relations += list(root.iter("relationship"))
    # Hyper: the <connection class='hyper'> that backs an extract. A .twb that
    # sits beside a Data/Extracts folder also carries the .hyper files there.
    hyper = [c for c in root.iter("connection") if c.get("class") == "hyper"]
    hyper_files = sibling_hyper_files(twb_path)
    hyper_count = max(len(hyper), len(hyper_files))

    return {
        "worksheets": len(list(root.iter("worksheet"))),
        "dashboards": len(list(root.iter("dashboard"))),
        # Total calcs (measure + dimension role). The output side is also a
        # total (measures + calculated columns), so a calc that the converter
        # reclassified from measure to column is not counted as lost.
        # Count unique calcs. Tableau repeats a calc across datasource views
        # (HR_Analytics: 9 entries, 4 unique), and the converter emits one
        # measure or column per unique calc, so entries overstate the source.
        "calculated_fields": len({_calc_key(c) for c in calc_fields}),
        "parameters": len(parameters),
        "filters": len(list(root.iter("filter"))),
        "relations": len(relations),
        "hyper_extracts": hyper_count,
    }


def count_output(project_dir: str) -> Dict[str, int]:
    """Count the matching objects in a generated PBIP project."""
    report_name = _report_name(project_dir)
    sm = os.path.join(project_dir, f"{report_name}.SemanticModel", "definition")
    rpt = os.path.join(project_dir, f"{report_name}.Report", "definition")

    # Count measures that correspond to a source calc. The converter also adds
    # generated measures (Formatted helpers, date and parameter helpers); those
    # are not source calcs and would inflate the total, hiding a real loss.
    source_calcs = _source_calc_captions(project_dir)
    measures = 0
    for tmdl in glob.glob(os.path.join(sm, "tables", "*.tmdl")):
        with open(tmdl, encoding="utf-8", errors="ignore") as fh:
            for name in re.findall(r"^\tmeasure '?([^'=\n]+?)'?\s*=", fh.read(), re.M):
                if name.strip() in source_calcs:
                    measures += 1

    rels_file = os.path.join(sm, "relationships.tmdl")
    relations = 0
    if os.path.isfile(rels_file):
        with open(rels_file, encoding="utf-8", errors="ignore") as fh:
            relations = len(re.findall(r"^relationship ", fh.read(), re.M))

    pages = glob.glob(os.path.join(rpt, "pages", "*", "page.json"))
    # Count visuals that are bound to a worksheet. Textboxes and images are
    # not worksheets, so they are excluded.
    worksheets_out = 0
    for vis in glob.glob(os.path.join(rpt, "pages", "*", "visuals", "*", "visual.json")):
        try:
            with open(vis, encoding="utf-8") as fh:
                vtype = json.load(fh).get("visual", {}).get("visualType", "")
        except (OSError, json.JSONDecodeError):
            continue
        if vtype not in ("textbox", "image", "shape", "actionButton"):
            worksheets_out += 1

    meta = _load_metadata(project_dir)
    hyper_out = len(meta.get("hyper_extracts", []) or [])

    # Calculated columns are emitted two ways: a DAX column with an expression,
    # or an M Table.AddColumn step in PowerQuery. Count both, or the check
    # undercounts columns that the converter moved into Power Query.
    calc_cols = 0
    for tmdl in glob.glob(os.path.join(sm, "tables", "*.tmdl")):
        with open(tmdl, encoding="utf-8", errors="ignore") as fh:
            calc_cols += len(re.findall(r"^\tcolumn .* = ", fh.read(), re.M))
    # Only count M steps that the source defines as calcs. Generated helper
    # columns (Calendar date parts, etc.) are not source calcs and inflate the
    # total, which would hide a real calc loss.
    source_calc_captions = _source_calc_captions(project_dir)
    for pq in glob.glob(os.path.join(project_dir, "PowerQuery", "*.pq")):
        with open(pq, encoding="utf-8", errors="ignore") as fh:
            names = re.findall(r'Table\.AddColumn\([^,]+,\s*"([^"]+)"', fh.read())
        calc_cols += sum(1 for n in names if n in source_calc_captions)

    return {
        "worksheets": worksheets_out,
        "dashboards": len(pages),
        "calculated_fields": measures + calc_cols,
        "parameters": int((meta.get("objects_converted") or {}).get("parameters", 0)),
        "filters": int((meta.get("objects_converted") or {}).get("filters", 0)),
        "relations": relations,
        "hyper_extracts": hyper_out,
    }


def _source_calc_captions(project_dir: str) -> set:
    """Captions of the source calcs, recorded in the project's metadata."""
    meta = _load_metadata(project_dir)
    names = set(meta.get("calc_captions", []) or [])
    return names


def _report_name(project_dir: str) -> str:
    pbip = glob.glob(os.path.join(project_dir, "*.pbip"))
    if pbip:
        return os.path.splitext(os.path.basename(pbip[0]))[0]
    return os.path.basename(os.path.normpath(project_dir))


def _load_metadata(project_dir: str) -> dict:
    path = os.path.join(project_dir, "migration_metadata.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def build_loss_report(twb_or_twbx: str, project_dir: str) -> dict:
    """Compare a source workbook to its generated project.

    Returns a dict with per-object counts, the drops, and an overall status:
    ``pass`` (no drops), ``warn`` (drops explained by ``degradations``), or
    ``fail`` (unexplained drops).
    """
    twb = _locate_twb(twb_or_twbx)
    if not twb:
        return {"status": "not_run",
                "reason": f"no readable .twb in {twb_or_twbx}"}

    src = count_source(twb)
    # A worksheet not placed on any dashboard produces no visual (the converter
    # builds one page per dashboard). Expect only the placed ones.
    src["worksheets"] = _placed_worksheets(twb, src["worksheets"])
    out = count_output(project_dir)
    meta = _load_metadata(project_dir)
    degradations = meta.get("degradations") or {}

    rows: List[dict] = []
    unexplained = 0
    for key in COMPARED:
        s, o = src[key], out[key]
        drop = s - o
        row = {"object": key, "source": s, "output": o, "drop": drop}
        if drop > 0:
            explained_by = _explanations(key, degradations)
            row["explained_by"] = explained_by
            if not explained_by:
                unexplained += 1
                row["status"] = "fail"
            else:
                row["status"] = "warn"
        else:
            row["status"] = "pass"
        rows.append(row)

    if unexplained:
        status = "fail"
    elif any(r["status"] == "warn" for r in rows):
        status = "warn"
    else:
        status = "pass"

    return {
        "status": status,
        "source_file": os.path.basename(twb_or_twbx),
        "unexplained_drops": unexplained,
        "rows": rows,
    }


def _placed_worksheets(twb_path: str, total: int) -> int:
    """Worksheets actually placed on a dashboard (the ones that yield visuals)."""
    root = ET.parse(twb_path).getroot()
    names = {w.get("name") for w in root.iter("worksheet")}
    placed = set()
    for dash in root.iter("dashboard"):
        for zone in dash.iter("zone"):
            if zone.get("name") in names:
                placed.add(zone.get("name"))
    # With no dashboards the converter emits one page per worksheet.
    if not list(root.iter("dashboard")):
        return total
    return len(placed)


def _explanations(key: str, degradations: dict) -> List[str]:
    """Degradation entries that account for a drop in ``key``."""
    mapping = {
        "worksheets": ["worksheets_not_placed", "unplaced_worksheets"],
        "calculated_fields": ["fallback_partitions", "dax_failures"],
        "relations": ["relations_not_mapped", "self_relations"],
        "hyper_extracts": ["hyper_unread"],
        "filters": ["filters_not_mapped"],
        "parameters": ["parameters_not_mapped"],
        "dashboards": [],
    }
    found = []
    for name in mapping.get(key, []):
        if degradations.get(name):
            found.append(name)
    return found


def write_loss_report(report: dict, project_dir: str) -> str:
    path = os.path.join(project_dir, LOSS_REPORT_FILE)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    return path
