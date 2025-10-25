import subprocess
import tempfile
from pathlib import Path
from typing import ClassVar, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field

from ivcap_service import JobContext, Service, getLogger
from ivcap_ai_tool import ToolOptions, ivcap_ai_tool, logging_init, start_tool_server

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
        None, alias="$policy", description="Policy to apply to the repaired artifact"
    )
    output_name: Optional[str] = Field(
        None, description="Optional filename for the repaired artifact"
    )

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "$schema": SCHEMA,
                "pdb_artifact": "urn:ivcap:artifact:d152a27c-42ab-4af1-9d1c-6e73d3a6c9fd",
                "output_name": "example_repaired.pdb",
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
                "$id": "urn:ivcap:artifact:d152a27c-42ab-4af1-9d1c-6e73d3a6c9fd",
                "repaired_pdb_urn": "urn:ivcap:artifact:4f72825b-6c93-4673-90c9-3b2c49fe1e6a",
                "$policy": "urn:ivcap:policy:ivcap.base.artifact",
            }
        },
    )


# ====================================
# Tool Functions
# ====================================


def repair_pdb_with_foldx(
    pdb_path: Path, working_dir: Path, foldx_binary: Path
) -> Path:
    base_name = pdb_path.stem
    prep_path = working_dir / f"{base_name}_prep.pdb"

    with pdb_path.open("r", encoding="utf-8") as source, prep_path.open(
        "w", encoding="utf-8"
    ) as prepared:
        for line in source:
            newline = (
                line.replace("HIE", "HIS")
                .replace("HID", "HIS")
                .replace("CYX", "CYS")
                .replace("CYP", "CYS")
            )
            newline = f"{newline[:21]}A{newline[22:]}"
            if "TER" in line:
                prepared.write("TER\n")
                break
            prepared.write(newline)

    foldx_cmd = [
        str(foldx_binary),
        "--command=RepairPDB",
        f"--output-dir={working_dir}",
        f"--pdb={prep_path.name}",
        f"--pdb-dir={working_dir}",
        "-d",
        "true",
    ]
    logger.info("Running FoldX: %s", " ".join(foldx_cmd))
    subprocess.run(foldx_cmd, cwd=working_dir, check=True)

    repaired_path = working_dir / f"{base_name}_prep_Repair.pdb"
    if not repaired_path.exists():
        raise FileNotFoundError(
            f"FoldX did not produce repaired file at '{repaired_path}'"
        )
    return repaired_path


def download_artifact(artifact, target_path: Path) -> None:
    data_href = getattr(artifact, "_data_href", None)
    if not data_href:
        artifact.refresh()
        data_href = getattr(artifact, "_data_href", None)
    if not data_href:
        raise ValueError(f"Artifact '{artifact.id}' does not expose a data href for download.")

    client = artifact._ivcap._client.get_httpx_client()
    timeout = httpx.Timeout(60.0, connect=10.0, read=60.0)
    try:
        with client.stream("GET", data_href, timeout=timeout) as response:
            response.raise_for_status()
            with target_path.open("wb") as out_f:
                for chunk in response.iter_bytes():
                    if chunk:
                        out_f.write(chunk)
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"Failed to download artifact '{artifact.id}' from '{data_href}'"
        ) from exc


# ====================================
# Sciansa wrapper function
# ====================================


@ivcap_ai_tool("/", opts=ToolOptions(tags=["FoldX repair PDB"]))
def foldx_repair_pdb(req: Request, jobCtxt: JobContext) -> Result:
    """
    Repairs a PDB file with FoldX and stores the repaired structure as a new artifact.
    """
    input_urn = req.pdb_artifact
    ivcap = jobCtxt.ivcap

    jobCtxt.report.step_started("download", {"message": f"Fetching '{input_urn}'"})
    artifact = ivcap.get_artifact(input_urn)

    foldx_binary = Path(__file__).resolve().parent / "foldx_20251231"
    if not foldx_binary.exists():
        raise FileNotFoundError(f"FoldX binary not found at '{foldx_binary}'")

    with tempfile.TemporaryDirectory() as tmp_dir:
        work_dir = Path(tmp_dir)
        input_name = artifact.name or "input.pdb"
        input_path = work_dir / input_name

        download_artifact(artifact, input_path)

        jobCtxt.report.step_finished(
            "download", {"message": f"Downloaded artifact to '{input_path.name}'"}
        )
        jobCtxt.report.step_started(
            "repair", {"message": f"Running FoldX repair for '{input_path.name}'"}
        )

        repaired_path = repair_pdb_with_foldx(input_path, work_dir, foldx_binary)

        jobCtxt.report.step_finished(
            "repair", {"message": f"Repaired file '{repaired_path.name}' created"}
        )
        jobCtxt.report.step_started(
            "upload", {"message": f"Uploading repaired artifact '{repaired_path.name}'"}
        )

        output_name = req.output_name or repaired_path.name
        uploaded = ivcap.upload_artifact(
            name=output_name,
            file_path=str(repaired_path),
            content_type="chemical/x-pdb",
            policy=req.policy,
        )

        stored_policy = req.policy or getattr(uploaded, "policy", None)
        jobCtxt.report.step_finished(
            "upload",
            {"message": f"Repaired artifact stored as '{uploaded.urn}'"},
        )

    return Result(
        id=input_urn,
        repaired_pdb_urn=uploaded.urn,
        policy=stored_policy,
    )


if __name__ == "__main__":
    start_tool_server(service)
