# FoldX PDB Repair Service

This service prepares and repairs protein structure files (`.pdb`) using the FoldX
`RepairPDB` command. The service runs inside the IVCAP platform, fetches the
input structure from the Data Fabric, writes any intermediate files to a
temporary workspace in the container, and finally uploads the repaired structure
back to the Data Fabric. The response returns the URN of that repaired artifact
so downstream tools can continue the workflow without touching the local
filesystem.

## Request payload

```json
{
  "$schema": "urn:sd:schema.foldx_repair_pdb.request.2",
  "pdb_artifact": "urn:ivcap:artifact:<input>",
  "output_name": "optional-output-name.pdb",
  "$policy": "urn:ivcap:policy:ivcap.base.artifact"
}
```

- `pdb_artifact` (required) must reference an existing artifact in the Data
  Fabric that contains a PDB file.
- `output_name` (optional) lets you control the filename stored with the new
  artifact. When omitted the generated FoldX filename is used.
- `$policy` (optional) allows overriding the default policy for the uploaded
  artifact.

See `tests/request.json` for a template payload.

## Local testing

1. Install dependencies with `poetry install --no-root`.
2. Start the development server:
   ```bash
   poetry ivcap run
   ```
3. In a separate terminal, invoke the service with a Data Fabric URN that is
   accessible from your configured IVCAP context:
   ```bash
   curl -i -X POST \
     -H "content-type: application/json" \
     --data @tests/request.json \
     http://localhost:8078
   ```

The response will contain a JSON document that includes the URN of the repaired
structure.

## Implementation highlights

- `tool-service.py` defines the service entrypoint. The `foldx_repair_pdb`
  handler uses `JobContext.ivcap` to retrieve the input artifact, stores it in a
  temporary directory, runs FoldX, and uploads the repaired file.
- `repair_pdb_with_foldx` prepares the `*_prep.pdb` input file, executes the
  FoldX binary bundled with the container image, and validates the presence of
  the repaired output.
- Progress updates are surfaced through `jobCtxt.report.step_*` to provide
  visibility during job execution.
- The result schema returns the input URN (via `$id`) together with the URN of
  the repaired artifact and any policy that was applied.

## Deployment

Use `poetry ivcap deploy` to build the container image, register the service,
and publish the tool description to your target IVCAP platform. Update the
Makefile variables and service metadata as required for your deployment.
