---
name: migrating-tableau-workbook-to-powerbi
version: 1.0.0
description: Run a Tableau workbook through the migrate, repair, compile, publish, refresh and validate pipeline into the Power BI Tableau Migration workspace. Use for "migrate this Tableau workbook to Power BI", "publish Tableau to Power BI", "run the tableau migration pipeline", or when asked to move a workbook off Tableau.
triggers:
  - migrate this Tableau workbook to Power BI
  - run the tableau migration pipeline
  - publish Tableau workbook to Power BI
  - migrate datasources from Tableau
---

# Tableau workbook → Power BI pipeline

Converts one Tableau workbook into a published, **refreshable** Power BI report.
The pipeline is fiddly: the tool is a vendored fork with known failure modes, and
several stages look successful while producing something empty. This skill encodes
the gates that catch that.

> **The failure mode that matters.** A "successful" migration can publish a report
> that renders **completely blank** and still reports a successful refresh. Every
> gate below exists to prevent that specific outcome. Never publish on a green log
> alone.

## Working directory

All paths are relative to `<repo>/tableau-migration/`.

| Piece | Path |
|---|---|
| Converter (vendored fork) | `tools/cyphou-tableau-to-powerbi/` |
| PBIP → PBIX compiler | `tools/pbip-compiler/` (source copy, no packaging metadata) |
| Validator | `tools/validate_pbip.py` |
| Tableau credentials | **`<repo>/.env`** at the repo root — not in `tableau-migration/` |
| Output | `output/run_<n>/<Workbook Name>/` |

## Step 0 — Credentials

Credentials live in the **repo root** `.env` (easy to miss; there is no
`tableau-migration/.env`). Required keys:

```
TABLEAU_SERVER_URL=https://<region>.online.tableau.com
TABLEAU_TOKEN_NAME=<pat name>
TABLEAU_TOKEN_SECRET=<pat secret>
```

Verify before doing anything else — a bad token otherwise surfaces as a confusing
empty migration:

```bash
cd tools/cyphou-tableau-to-powerbi && set -a && source ../../../.env && set +a && \
.venv/bin/python -c "
import os
from tableau_export.server_client import TableauServerClient
c=TableauServerClient(server_url=os.environ['TABLEAU_SERVER_URL'],
    token_name=os.environ['TABLEAU_TOKEN_NAME'],
    token_secret=os.environ['TABLEAU_TOKEN_SECRET'], site_id='<site>')
c.sign_in(); print('OK', len(c.list_workbooks()), 'workbooks'); c.sign_out()"
```

## Step 1 — Identify the real datasources

**Do not trust local extracts.** `tableau_export/*.json` may belong to a different
workbook entirely. Query Tableau for the workbook's actual upstream datasources:

- `tableau_get-workbook` with the workbook LUID → `upstreamDatasources[]`
- The URL form `.../workbooks/<N>` is a **numeric id, not a LUID** — resolve first
  (`list_workbooks`), do not assume.

Report the datasource list to the user and confirm scope before migrating.

## Step 2 — Migrate

```bash
cd tools/cyphou-tableau-to-powerbi
.venv/bin/python migrate.py migrate "<path/to/workbook.twb>" \
  --output-dir ../../../output/run_<n>
```

To download fresh from Tableau instead of a local file:

```bash
.venv/bin/python migrate.py server "$TABLEAU_SERVER_URL" "<Workbook Name>" \
  --output-dir ../../../output/run_<n> --site <site>
```

### Hard gates — all must be true before continuing

1. `Openability: ✓ project will open in PBI Desktop`
2. `PBI Desktop Validation: ✓ No issues detected`
3. `python3 tools/validate_pbip.py "<output>/<Workbook>"` → `✅ No known issues`

Then inspect the generated `PowerQuery/*.pq` for these — a green migration log does
**not** imply any of them:

```bash
cd "<output>/<Workbook>"
grep -l "TODO: Replace with actual" PowerQuery/*.pq   # Hyper stub = BLANK REPORT
grep -n 'IN {' PowerQuery/*.pq                        # invalid M, fails refresh
grep -n '>>=\|#"WHERE' PowerQuery/*.pq                # broken SQL literal
grep -n 'try\s*$\|otherwise' PowerQuery/*.pq          # fallback masking errors
```

Any hit is a real defect. See "Known defect classes" below.

## Step 3 — Compile PBIP → PBIX

**This step is mandatory.** A PBIP folder is TMDL + PBIR text. The Power BI Import
API needs a compiled `.pbix` with a binary VertiPaq `DataModel`. Zipping the folder
produces something that *looks* like a pbix and is rejected with
`RequestedFileIsEncryptedOrCorrupted`.

One-time setup (isolated venv; do not pollute the converter venv):

```bash
uv venv /tmp/pbipc-venv --python 3.12
uv pip install --python /tmp/pbipc-venv/bin/python pbix-mcp
```

Compile:

```bash
cd <repo>/tableau-migration
PYTHONPATH=tools/pbip-compiler /tmp/pbipc-venv/bin/python -m pbip_compiler.cli \
  --pbip "output/run_<n>/<Workbook>" --output /tmp/<Workbook>.pbix
```

`pbip-compiler` is a **source copy with no `pyproject.toml`** — it must be run via
`PYTHONPATH`, not `uv pip install -e`.

Read the `[data]` lines. They are the truth about refreshability:

```
[data] Extract: M preserved → refreshable (Refresh in Power BI loads the data)
[warn] Exclusion List: no partition M → empty table
```

`[warn] … no partition M` is **expected** for DAX/parameter tables (they are
computed, not queried). It is **not** acceptable for a fact/dimension table.

Verify the M actually survived the ABF rebuild — the compiler overwrites pbix-mcp's
placeholder partition query, and this is where corruption historically appeared:

```bash
/tmp/pbipc-venv/bin/python -c "
import zipfile
from pbix_mcp.formats.datamodel_roundtrip import decompress_datamodel
from pbix_mcp.formats import abf_rebuild
z=zipfile.ZipFile('/tmp/<Workbook>.pbix')
abf=decompress_datamodel(z.read('DataModel'))
def inspect(conn):
    for t,p,q in conn.execute('SELECT t.Name,p.Name,length(p.QueryDefinition) FROM Partition p JOIN [Table] t ON p.TableID=t.ID WHERE t.Name NOT LIKE \"H\$%\"'):
        print(f'{t:45} {p:30} M={q}')
abf_rebuild.rebuild_abf_with_modified_sqlite(abf, inspect)"
```

An M length of a few hundred characters is a stub; thousands is a real query.

## Step 4 — Publish

```bash
TOKEN=$(az account get-access-token --resource https://analysis.windows.net/powerbi/api \
  --query accessToken -o tsv)
WS=<workspace id>   # resolve with: GET /v1.0/myorg/groups
curl -X POST "https://api.powerbi.com/v1.0/myorg/groups/$WS/imports?datasetDisplayName=<Name>&nameConflict=CreateOrOverwrite" \
  -H "Authorization: Bearer $TOKEN" -F "file=@/tmp/<Workbook>.pbix"
```

**Pace REST calls.** The API needs ~5 minutes to cool down between attempts; a
failed-then-immediate-retry loop burns quota and returns misleading errors. On a
failure, wait, then re-check state rather than re-posting.

Poll the import until `succeeded` (or read the `error`):

```bash
curl -s "https://api.powerbi.com/v1.0/myorg/groups/$WS/imports/<importId>" \
  -H "Authorization: Bearer $TOKEN"
```

## Step 5 — Monitor refresh, then validate again

A published dataset is **not** a working dataset. Refresh is where SQL and M errors
surface.

1. Confirm Snowflake credentials are bound to the **new** dataset. Credentials on a
   previous dataset do not carry over.
2. Trigger refresh; poll `.../datasets/<id>/refreshes` until terminal.
3. A refresh that succeeds **with zero rows** is a failure. Check row counts.

```bash
curl -s "https://api.powerbi.com/v1.0/myorg/groups/$WS/datasets/<dsId>/refreshes?\$top=1" \
  -H "Authorization: Bearer $TOKEN"
```

Re-run the Step 2 gates against the published artifact, then report:
datasource list, gates passed, refresh outcome, row counts, and anything still
unverified.

## Known defect classes

These were all found on real workbooks. Check for them explicitly.

| Symptom | Cause | Fix |
|---|---|---|
| `Token ',' expected` | `#"..."` (M identifier escape) inside a `Value.NativeQuery` string literal | normalise SQL before it becomes an M literal |
| SQL has `>>=` / `<<=` | Tableau stores `&gt;&gt;=` (XML encoded twice) | un-double-encode; a bare `>>` is a legit bit-shift — leave it |
| `if [x] IN {"a" then "b"}` | `_split_dax_args` not tracking `{}`, so set-literal commas split as arguments | make the arg splitter brace-aware → `List.Contains` |
| Fact table is `#table({...}, {})` | Hyper extract the tool cannot read → schema-only stub | rebind to the live source table when one exists in the same datasource |
| Blank report, "successful" refresh | `try ... otherwise #table(...)` fallback swallowing a connection error | guards are a **no-op** by design; if one appears, it is stale output |
| Wrong datasources in the extract | using stale `tableau_export/*.json` from another workbook | re-extract; never reuse |

## Version hygiene

The converter is a **fork**. Before a run, confirm what you are running:

```bash
cd tools/cyphou-tableau-to-powerbi
git status --short      # uncommitted local patches are common and change behaviour
git log --oneline -3
git rev-list --left-right --count HEAD...origin/main   # behind/ahead
```

Upstream (`cyphou/TableauToPowerBI`) carries security fixes this fork may lack
(upload confinement, webhook redirect blocking). If the fork is behind, say so
before publishing.

## Reporting

Always state, explicitly:
- which datasources were migrated (name + underlying table)
- which gates passed, and which you skipped and why
- refresh outcome **and** row counts
- what remains unverified

Do not describe a migration as complete if only the structural gates passed.
