# FoldX PDB Repair Service

This service prepares and repairs protein structure files (`.pdb`) using the FoldX
`RepairPDB` command. The workflow mirrors the reference markdown-conversion
service and relies entirely on IVCAP artifacts instead of container file paths:

1. **Cache lookup** – check the Data Fabric for a previous repair result attached
   to the requested artifact.
2. **Download** – stream the PDB artifact into a temporary workspace inside the
   container.
3. **Repair** – run the bundled `foldx_20251231` binary to create the repaired
   structure.
4. **Upload** – store the repaired output as a new artifact (respecting any
   supplied policy and filename) and report its URN in the result.

## Request payload

```json
{
  "$schema": "urn:sd:schema.foldx_repair_pdb.request.2",
  "pdb_artifact": "urn:ivcap:artifact:<input>",
  "output_name": "optional-output-name.pdb",
  "$policy": "urn:ivcap:policy:ivcap.base.artifact"
}
```

- `pdb_artifact` (required) must reference an existing PDB artifact in the Data
  Fabric.
- `output_name` (optional) sets the filename recorded with the repaired
  artifact.
- `$policy` (optional) overrides the policy applied when uploading the repaired
  artifact.

See `tests/request.json` for a template payload.

## Local testing

1. Install dependencies with `poetry install --no-root`.
2. Ensure your IVCAP CLI context points to a deployment that contains the input
   artifact (`ivcap context list`, `ivcap context set ...`).
3. Start the development server:
   ```bash
   poetry ivcap run
   ```
4. In a separate terminal, call the service with `make test-local` or curl:
   ```bash
   curl -i -X POST \
     -H "content-type: application/json" \
     --data @tests/request.json \
     http://localhost:8078
   ```

The JSON response includes the URN of the repaired artifact. If the same input
artifact is requested again, the cached aspect is returned immediately without
re-running FoldX.

## Implementation notes

- `tool-service.py` orchestrates the repair:
  - Step 1 uses `JobContext.ivcap.list_aspects` to detect prior repairs (matching
    the pattern from the markdown-conversion service).
  - Step 2 downloads the artifact by following the internal `data-href`. The
    helper uses the existing authenticated HTTP client to stream the file to a
    temporary directory.
  - Step 3 calls `foldx_20251231` in that workspace and validates the expected
    `_prep_Repair.pdb` output.
  - Step 4 uploads the repaired structure via `ivcap.upload_artifact`, returning
    the resulting URN in the service response (`$id` ties the aspect back to the
    original artifact).
- Progress updates are emitted through `jobCtxt.report.step_*` so job logs show
  cache hits, download, repair, and upload phases.

## Deployment

Use `poetry ivcap deploy` to build the container image, register the service,
and publish the tool description to your target IVCAP platform. Adjust the
Makefile variables and service metadata to match your deployment conventions.
