# Converter provenance

`tools/cyphou-tableau-to-powerbi/` is the Tableau → Power BI converter that the
migration pipeline runs (`migrate.py`). This file records where it came from and
how to tell which version produced a given output.

## What was verified from the repository

| Item | Value | How verified |
|---|---|---|
| Local repo | `tools/cyphou-tableau-to-powerbi/` (own git repo) | `git rev-parse` |
| Remote `fork` | `https://github.com/fenntuohy/TableauToPowerBI` | `git remote -v` |
| Declared upstream | `https://github.com/cyphou/Tableau-To-PowerBI` (named in its README) | README |
| Upstream reachable | **No.** `git ls-remote` returns "Repository not found" from this machine | `git ls-remote` |
| Imported base | `93d6e7a` "Tableau to Power BI migration engine" (2026-09-17, Pierre DOUDET) | `git log --reverse` |
| Local work on top | 18 commits on `enpal/local-migration-hardening` past `main` | `git rev-list --count main..enpal/...` |
| Branch at audit | `enpal/local-migration-hardening` @ `fe1f86d` | `git rev-parse` |

Because the upstream cannot be fetched here, the exact upstream commit the base
was taken from is **not recorded and not verified**. Do not cite an upstream
hash in reviews until it is confirmed against the upstream repository.

## Local patches that matter for output

These changes are on top of the imported base and change what is generated.
Each one must survive any re-vendoring.

- Power Query and M: `Table.AddColumn`-based calc columns, `#table` placeholder
  injection (`powerbi_import/self_healing_v3.py`).
- Migration gates added for this pipeline: `loss_report.py` (source-vs-output
  counts), the fidelity block in `migrate.py` (`--allow-fidelity-fail`), the
  BLANK-stub and placeholder-M checks in `openability.py`, and the
  equivalence-aware scorecard in `preceptor.py`.
- Visual field coverage: name matching for humanised and calc-caption fields
  (`equivalence_tester_v2.py`, `_resolve_model_name`).

## Pinning the converter version in run output

Every `migration_metadata.json` should say which converter produced it. The
converter records:

- `converter_commit`: the output of `git rev-parse --short HEAD` in this repo
- `converter_branch`: the output of `git branch --show-current`
- `converter_dirty`: whether the working tree had uncommitted changes

Those three fields make an output traceable to a commit. `converter_dirty: true`
means the output cannot be reproduced from the commit alone.

## Companion: pbip-compiler

`tools/pbip-compiler/` is a source copy with no `pyproject.toml`. It is not
under this file's scope. `PIPELINE.md` records the three fixes that must be
ported on any re-vendoring (calculated partitions, relationship parsing,
`isActive`/cardinality).

## Re-vendoring checklist

1. Confirm the new upstream commit exists in `cyphou/Tableau-To-PowerBI`.
2. Re-apply the local patches listed above.
3. Run the test suite and compare against the recorded baseline failures.
4. Regenerate `tests/golden/conversion_counts.json` and review the diff.
5. Record the new base commit in the table at the top of this file.
