import subprocess
import tempfile
from pathlib import Path
from typing import ClassVar, Optional
from pydantic import BaseModel, ConfigDict, Field

from ivcap_service import JobContext, Service, getLogger
from ivcap_ai_tool import ToolOptions, ivcap_ai_tool, logging_init, start_tool_server
from ivcap_client import Artifact

logging_init()
logger = getLogger("app")

service = Service(
    name="FoldX tool to prepare a protein PDB file for other FoldX tools",
    contact={
        "name": "Andrew Warden",
        "email": "andrew.warden@csiro.au",
    },
    license={
        "name": "Academic",
        "url": "",
    },
)

# ====================================
# Request/Result schemas
# ====================================

class Request(BaseModel):
    SCHEMA: ClassVar[str] = "urn:sd:schema.foldx_repair_pdb.request.2"
    jschema: str = Field(SCHEMA, alias="$schema")
    pdb_artifact: str = Field(description="URN of the PDB artifact to be repaired")
    policy: Optional[str] = Field(
        None, alias="$policy", description="Policy for the repaired artifact"
    )
    output_name: Optional[str] = Field(
        None, description="Desired filename for the repaired artifact"
    )

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "$schema": SCHEMA,
                "pdb_artifact": "urn:ivcap:artifact:example-input",
                "output_name": "example_prep_Repair.pdb",
            }
        },
    )

class Result(BaseModel):
    SCHEMA: ClassVar[str] = "urn:sd:schema.foldx_repair_pdb.2"
    jschema: str = Field(SCHEMA, alias="$schema")
    id: str = Field(..., alias="$id", description="URN of the input PDB artifact")
    repaired_pdb_urn: str = Field(
        description="URN of the repaired PDB artifact stored in Data Fabric"
    )
    policy: Optional[str] = Field(
        None, alias="$policy", description="Policy applied to the repaired artifact"
    )

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "$schema": SCHEMA,
                "$id": "urn:ivcap:artifact:example-input",
                "repaired_pdb_urn": "urn:ivcap:artifact:example-output",
                "$policy": "urn:ivcap:policy:ivcap.base.artifact",
            }
        },
    )


# ====================================
# Helper functions
# ====================================

def download_and_clean(artifact: Artifact, tmp_dir: Path) -> Path:
    pdp_path = tmp_dir / "pdb_file.pdb"
    with artifact.open() as src:
        with pdp_path.open("w", encoding="utf-8") as dst:
            for line in src:
                newline = (
                    line.replace("HIE", "HIS")
                    .replace("HID", "HIS")
                    .replace("CYX", "CYS")
                    .replace("CYP", "CYS")
                )
                newline = f"{newline[:21]}A{newline[22:]}"
                if "TER" in line:
                    dst.write("TER\n")
                    break
                dst.write(newline)
    return pdp_path

def repair_pdb_with_foldx(pdb_path: Path, tmp_dir: str) -> Path:
    foldx_binary = Path(__file__).resolve().parent / "foldx_20251231"
    if not foldx_binary.exists():
        raise FileNotFoundError(f"FoldX binary not found at '{foldx_binary}'")

    foldx_cmd = [
        str(foldx_binary),
        "--command=RepairPDB",
        f"--pdb={pdb_path.name}",
        f"--screen=false",
    ]
    logger.info("Running FoldX: %s", " ".join(foldx_cmd))
    try:
        subprocess.run(foldx_cmd, cwd=tmp_dir, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"FoldX repair failed with exit code {e.returncode}") from e

    repaired_path = pdb_path.with_name(f"{pdb_path.stem}_Repair.pdb")
    if not repaired_path.exists():
        raise FileNotFoundError(
            f"FoldX did not produce repaired file at '{repaired_path}'"
        )
    return repaired_path

# ====================================
# Sciansa wrapper function
# ====================================

@ivcap_ai_tool("/", opts=ToolOptions(tags=["FoldX repair PDB"]))
def foldx_repair_pdb(req: Request, jobCtxt: JobContext) -> Result:
    """
    Repairs a PDB file with FoldX and stores the repaired structure as a new artifact.
    Mirrors the artifact-centric workflow used by the markdown conversion service.
    """
    ivcap = jobCtxt.ivcap
    input_urn = req.pdb_artifact

    # Step 1: Check for cached repair
    with jobCtxt.report.step("cache-check", message=f"Checking cache for '{input_urn}'") as step:
        cached = list(ivcap.list_aspects(entity=input_urn, schema=Result.SCHEMA, limit=1))
        if cached:
            content = cached[0].content
            logger.info("Using cached repair '%s'", content["repaired_pdb_urn"])
            jobCtxt.report.step_finished(
                "cache-check",
                message=f"Using cached repair '{content['repaired_pdb_urn']}'",
            )
            return Result(**content)
        step.finished(message=f"No cached repair found for '{input_urn}'")

    # No chached repair found; proceed with repair
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_dir_path = Path(tmp_dir)

        # Step 2: Download artifact content
        with jobCtxt.report.step("download", message=f"Fetching '{input_urn}'") as step:
            artifact = ivcap.get_artifact(input_urn)
            pdp_path = download_and_clean(artifact, tmp_dir_path)

        # Step 3: Run FoldX repair
        with jobCtxt.report.step("repair") as step:
            repaired_path = repair_pdb_with_foldx(pdp_path, tmp_dir)

         # Step 4: Upload repaired artifact
        with jobCtxt.report.step("upload", message=f"Uploading repaired artifact '{repaired_path.name}'") as step:
            output_name = req.output_name or repaired_path.name
            uploaded = ivcap.upload_artifact(
                name=output_name,
                file_path=str(repaired_path),
                content_type="chemical/x-pdb",
                policy=req.policy,
            )
            stored_policy = req.policy or getattr(uploaded, "policy", None)
            step.finished(message=f"Repaired artifact stored as '{uploaded.urn}'")

    # Step 5: Return result referencing repaired artifact URN
    result = Result(
        id=input_urn,
        repaired_pdb_urn=uploaded.urn,
        policy=stored_policy,
    )
    return result

if __name__ == "__main__":
    start_tool_server(service)
