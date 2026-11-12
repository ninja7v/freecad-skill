## Description:

Create, edit, inspect, verify and export parametric 3D CAD models in FreeCAD from structured JSON operations: parts,
PartDesign bodies with parameter-driven sketches (including threaded holes), text, assemblies with a bill of
materials, mass properties, DXF drawings and linear stress analysis. Closed
meshes (STL, OBJ, 3MF) in the workspace can be imported as solids and modified.

This skill is ready for commercial/non-commercial use.

## Publisher:

[ninja7v](https://clawhub.ai/user/ninja7v)

### License/Terms of Use:

MIT-0

## Use Case:

Developers and engineers use this skill to let AI agents build editable FreeCAD models (mechanical parts, enclosures, 3D-printable objects), change their dimensions later, check fits and strength, give parts materials, and export verified STEP/STL/3MF files and DXF drawings.

### Deployment Geography for Use:

Global

## Known Risks and Mitigations:

Risk: The skill writes and may overwrite the requested FreeCAD document and export files.

Mitigation: All paths are confined to the workspace directory (no `..`, absolute paths or symlink escapes; the parts cache is never read or written through links); a request that fails writes nothing; saves are atomic. Run it in a dedicated project folder.

Risk: Generated geometry may not match the user's intent.

Mitigation: Every step reports volumes and exact bounding boxes, and agents can assert expected dimensions; results are checked for validity and self-intersection, and exports are read back; review models before manufacturing.

Risk: Stress analysis (`fem_static`) results may be relied on for safety-critical parts.

Mitigation: Every result is checked for equilibrium and, unless turned off, mesh convergence; a check that cannot run is reported as a warning (NO_EQUILIBRIUM_CHECK, NO_CONVERGENCE_CHECK), and every result carries a disclaimer. It is a linear estimate, not a substitute for engineering review.

Risk: Library parts are downloaded from GitHub and are licensed CC-BY 3.0.

Mitigation: Network is used only by the library command and by import steps that name a library part. URLs are allow-listed to the official FreeCAD/FreeCAD-library repository on api.github.com and raw.githubusercontent.com (redirects elsewhere are refused); requests are anonymous GETs that send no user data; files are verified against its git hashes and size-capped; FCSKILL_OFFLINE=1 disables network access. Every imported part carries its attribution, which agents are told to pass on.

## Reference(s):

- https://clawhub.ai/ninja7v/skills/freecad-skill
- FreeCAD: https://www.freecad.org

## Skill Output:

**Output Type(s):** [JSON, Shell commands, Files, Guidance]

**Output Format:** [Structured JSON requests and responses, shell command invocations, and local CAD files (.FCStd, STEP, IGES, BREP, STL, OBJ, 3MF, DXF, SVG) and PNG previews.]

**Output Parameters:** [1D]

**Other Properties Related to Output:** [Runs locally through FreeCAD's headless interpreter (and the Gmsh and CalculiX tools bundled with FreeCAD for `fem_static`); network only for the optional FreeCAD parts library (github.com/FreeCAD/FreeCAD-library, verified downloads; FCSKILL_OFFLINE=1 disables it); writes only inside the workspace.]

## Skill Version(s):

3.0.1

## Ethical Considerations:

Users should evaluate whether this skill is appropriate for their environment, review any generated or modified files before relying on them, and apply their organization's safety, security, and compliance requirements before deployment.
