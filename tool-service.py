import os
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


def repair_pdb_with_foldx(work_dir, pdb_file, base):

    # 1. Check for cached conversion
    ivcap = ctxt.ivcap
    cl = list(ivcap.list_aspects(entity=req.document, schema=Result.SCHEMA, limit=1))
    cached = cl[0] if cl else None
    if cached:
        content = cached.content
        logger.info(f"Using cached document: {content['markdown_urn']}")
        return Result(**content) # should be able to simply return "cached"
 
    # 2. Download the source document
    doc = ivcap.get_artifact(req.document)
    doc_f = doc.as_file()

    # 3. Convert the document to markdown
    converter = MarkItDown(enable_plugins=True)
    cres = converter.convert(doc_f, stream_info=StreamInfo(mimetype=doc.mime_type))
    if not cres:
        raise ValueError(f"Failed to convert document '{req.document}' to markdown.")
    md = cres.markdown

    # 4.Upload the generated markdown to IVCAP storage
    ms = io.BytesIO(md.encode("utf-8"))
    cart = ivcap.upload_artifact(
        name=f"{doc.name}.md",
        io_stream=ms,
        content_type="text/markdown",
        content_size=len(md),
        policy=req.policy,
    )
    logger.info(f"Uploaded markdown to {cart.urn}")

    # 5. Return the URI of the artifact containing the markdown conversion
    result = Result(id=req.document, markdown_urn=cart.urn, policy=req.policy)
    return resultth_foldx(pdb_path: Path, foldx_binary: Path) -> Path:
        base_name = pdb_path.stem
        prep_path = pdb_path.with_name(f"{base_name}_prep.pdb")

        logger.info("Preparing PDB '%s' for FoldX repair", pdb_path.name)
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
            f"--output-dir={pdb_path.parent}",
            f"--pdb={prep_path.name}",
            f"--pdb-dir={pdb_path.parent}",
            "-d",
            "true",
        ]
        logger.info("Running FoldX: %s", " ".join(foldx_cmd))
        subprocess.run(foldx_cmd, cwd=pdb_path.parent, check=True)

        repaired_path = pdb_path.with_name(f"{base_name}_prep_Repair.pdb")
        if not repaired_path.exists():
            raise FileNotFoundError(
                f"FoldX did not produce repaired file at '{repaired_path}'"
            )
        return repaired_path

def download_artifact_to_path(artifact, target_path: Path) -> None:
    data_href = getattr(artifact, "_data_href", None)
    if not data_href:
        artifact.refresh()
        data_href = getattr(artifact, "_data_href", None)
    if not data_href:
        raise ValueError(f"Artifact '{artifact.id}' does not expose downloadable data.")

    client = artifact._ivcap._client.get_httpx_client()
    timeout = httpx.Timeout(60.0, connect=10.0, read=60.0)
    try:
        with client.stream("GET", data_href, timeout=timeout) as response:
            response.raise_for_status()
            with target_path.open("wb") as out_file:
                for chunk in response.iter_bytes():
                    if chunk:
                        out_file.write(chunk)
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
    Mirrors the artifact-centric workflow used by the markdown conversion service.
    """
    ivcap = jobCtxt.ivcap
    input_urn = req.pdb_artifact

    # Step 1: Check for cached repair
    jobCtxt.report.step_started("cache-check", {"message": f"Checking cache for '{input_urn}'"})
    cached = list(ivcap.list_aspects(entity=input_urn, schema=Result.SCHEMA, limit=1))
    if cached:
        content = cached[0].content
        logger.info("Using cached repair '%s'", content["repaired_pdb_urn"])
        jobCtxt.report.step_finished(
            "cache-check",
            {"message": f"Using cached repair '{content['repaired_pdb_urn']}'"},
        )
        return Result(**content)
    jobCtxt.report.step_finished(
        "cache-check", {"message": f"No cached repair found for '{input_urn}'"}
    )

    # Step 2: Download artifact content
    jobCtxt.report.step_started("download", {"message": f"Fetching '{input_urn}'"})
    artifact = ivcap.get_artifact(input_urn)

    foldx_binary = Path(__file__).resolve().parent / "foldx_20251231"
    if not foldx_binary.exists():
        raise FileNotFoundError(f"FoldX binary not found at '{foldx_binary}'")

    with tempfile.TemporaryDirectory() as tmp_dir:
        work_dir = Path(tmp_dir)
        input_name = artifact.name or "input.pdb"
        input_path = work_dir / input_name

        download_artifact_to_path(artifact, input_path)
        jobCtxt.report.step_finished(
            "download", {"message": f"Downloaded artifact to '{input_path.name}'"}
        )

        # Step 3: Run FoldX repair
        jobCtxt.report.step_started(
            "repair", {"message": f"Running FoldX repair for '{input_path.name}'"}
        )
        repaired_path = repair_pdb_with_foldx(input_path, foldx_binary)
        jobCtxt.report.step_finished(
            "repair", {"message": f"Repaired file '{repaired_path.name}' created"}
        )

        # Step 4: Upload repaired artifact
        jobCtxt.report.step_started(
            "upload",
            {"message": f"Uploading repaired artifact '{repaired_path.name}'"},
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

    # Step 5: Return result referencing repaired artifact URN
    result = Result(
        id=input_urn,
        repaired_pdb_urn=uploaded.urn,
        policy=stored_policy,
    )
    return result


if __name__ == "__main__":
    start_tool_server(service)
