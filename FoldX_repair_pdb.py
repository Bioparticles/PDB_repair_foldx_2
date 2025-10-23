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

service = Service(
    name="FoldX tool to prepare a protein PDB file for other FoldX tools",
    contact={
        "name": "Andrew Wardene",
        "email": "andrew.warden@csiro.au",
    },
    license={
        "name": "Academic",
        "url": "",
    },
)

#====================================
# Tool global variables
#====================================

# Dictionary to convert three-letter amino acid codes to single-letter codes
aa_dict = {
    'ALA': 'A', 'CYS': 'C', 'ASP': 'D', 'GLU': 'E', 'PHE': 'F', 'GLY': 'G', 'HIS': 'H',
    'ILE': 'I', 'LYS': 'K', 'LEU': 'L', 'MET': 'M', 'ASN': 'N', 'PRO': 'P', 'GLN': 'Q',
    'ARG': 'R', 'SER': 'S', 'THR': 'T', 'VAL': 'V', 'TRP': 'W', 'TYR': 'Y'
}

#====================================
# Request/Result schemas
#====================================

class Request(BaseModel):
    jschema: str = Field("urn:sd:schema.foldx_repair_pdb.request.1", alias="$schema")
    pdb_file: str = Field(description="Path to PDB file to be repaired")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "$schema": "urn:sd:schema.foldx_repair_pdb.request.1",
            "pdb_file": "/scratch3/war391/sciansa_apps/foldx/example.pdb"
        }
    })

class Result(BaseModel):
    jschema: str = Field("urn:sd:schema.foldx_repair_pdb.1", alias="$schema")
    pdb_file: str = Field(description="Path to PDB file to be repaired")
    repaired_pdb_file: str = Field(description="Path to repaired DB file")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "$schema": "urn:sd:schema.foldx_repair_pdb.1",
            "pdb_file": "/scratch3/war391/sciansa_apps/foldx/example.pdb",
            "repaired_pdb_file": "/scratch3/war391/sciansa_apps/foldx/example_prep_Repair.pdb"
        }
    })

#====================================
# Tool Functions
#====================================

def repair_pdb_with_foldx(work_dir, pdb_file, base): # This 'prepares' the file for 'repair'
    print(f'{work_dir}/{pdb_file}....{base}')
    with open(f'{work_dir}/{pdb_file}', 'r') as f:
        h = open(f'{work_dir}/{base}_prep.pdb', 'w')
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
        print(f'COMMAND LINE = {work_dir}/foldx_20251231 --command=RepairPDB --output-dir={work_dir} --pdb={work_dir}/{base}_prep.pdb\n\n')
    subprocess.run(f'{work_dir}/foldx_20251231 --command=RepairPDB --output-dir={work_dir} --pdb={base}_prep.pdb --pdb-dir={work_dir} -d true', shell=True)

#====================================
# Sciansa wrapper function
#====================================

@ivcap_ai_tool("/", opts=ToolOptions(tags=["FoldX repair PDB"]))
def foldx_repair_pdb(req: Request, jobCtxt: JobContext) -> Result:
    """
    Repairs a PDB file for FoldX and other protein structure manipulations
    """
    pdb_file = req.pdb_file
    jobCtxt.report.step_started("main", f"Repairing '{pdb_file}'")

    base = os.path.basename(pdb_file)
    work_dir = base.replace(f'{pdb_file}', '{base}')

    repair_pdb_with_foldx(work_dir, pdb_file, base) # calling the real function

    jobCtxt.report.step_finished("main", f"Repaired PDB file is {repaired_pdb_file}")
    return Result(pdb_file=pdb_file, repaired_pdb_file=repaired_pdb_file)

if __name__ == "__main__":
    start_tool_server(service)




