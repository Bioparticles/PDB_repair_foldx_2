import glob
import os
import subprocess, sys, time
import concurrent.futures
import math
from pydantic import BaseModel, Field
from pydantic import BaseModel, ConfigDict
from ivcap_service import getLogger, Service, JobContext
from ivcap_ai_tool import start_tool_server, ToolOptions, ivcap_ai_tool, logging_init

logging_init()
logger = getLogger("app")
work_dir = '' # Not sure where to put this

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

#====================================
# Request/Result schemas
#====================================

class Request(BaseModel):
    jschema: str = Field("urn:sd:schema.foldx_repair_pdb.request.1", alias="$schema")
    pdb_file: str = Field(description="Path to PDB file to be repaired")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "$schema": "urn:sd:schema.foldx_repair_pdb.request.1",
            "pdb_file": "{work_dir}/example.pdb"
        }
    })

class Result(BaseModel):
    jschema: str = Field("urn:sd:schema.foldx_repair_pdb.1", alias="$schema")
    pdb_file: str = Field(description="Path to PDB file to be repaired")
    repaired_pdb_file: str = Field(description="Path to repaired DB file")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "$schema": "urn:sd:schema.foldx_repair_pdb.1",
            "pdb_file": "{work_dir}/example.pdb",
            "repaired_pdb_file": "{work_dir}/example_prep_Repair.pdb"
        }
    })

#====================================
# Tool Functions
#====================================

def repair_pdb_with_foldx(work_dir, pdb_file, base):
    print(f'{work_dir}/{pdb_file}....{base}')
    with open(pdb_file, 'r') as f:  # <-- FIXED
        h = open(os.path.join(work_dir, f'{base}_prep.pdb'), 'w')
        lines = f.readlines()
        for line in lines:
            newline = line.replace('HIE', 'HIS').replace('HID', 'HIS').replace('CYX', 'CYS').replace('CYP', 'CYS')
            newline = newline[:21] + 'A' + newline[22:]
            if 'TER' in line:
                h.write('TER\n')
                break
            h.write(newline)
        h.close()
        time.sleep(1)
        logger.info(f'COMMAND LINE = {work_dir}/foldx_20251231 --command=RepairPDB...')

    subprocess.run(
        f'{work_dir}/foldx_20251231 --command=RepairPDB --output-dir={work_dir} --pdb={base}_prep.pdb --pdb-dir={work_dir} -d true',
        shell=True
    )


#====================================
# Sciansa wrapper function
#====================================

@ivcap_ai_tool("/", opts=ToolOptions(tags=["FoldX repair PDB"]))
def foldx_repair_pdb(req: Request, jobCtxt: JobContext) -> Result:
    """
    Repairs a PDB file for FoldX and other protein structure manipulations
    """
    pdb_file = req.pdb_file
    base = os.path.basename(pdb_file).replace('.pdb', '')
    work_dir = os.path.dirname(pdb_file)
    repaired_pdb_file = os.path.join(work_dir, f"{base}_prep_Repair.pdb")

    if os.path.isfile(repaired_pdb_file):
        logger.info(f'Found existing _Repair.pdb file...')
        jobCtxt.report.step_started("main", {"message": f"Found existing repaired file. Exiting."})
        jobCtxt.report.step_finished("main", {"message": f"Repaired PDB file is {repaired_pdb_file}"})
        return Result(pdb_file=pdb_file, repaired_pdb_file=repaired_pdb_file)
    else:

        jobCtxt.report.step_started("main", {"message": f"Repairing '{pdb_file}'"})

        repair_pdb_with_foldx(work_dir, pdb_file, base)

        repaired_pdb_file = os.path.join(work_dir, f"{base}_prep_Repair.pdb")

        jobCtxt.report.step_finished("main", {"message": f"Repaired PDB file is {repaired_pdb_file}"})
        return Result(pdb_file=pdb_file, repaired_pdb_file=repaired_pdb_file)


if __name__ == "__main__":
    start_tool_server(service)




