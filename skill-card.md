## Description:

Create or modify 3D CAD models in FreeCAD using parametric JSON operations.

This skill is ready for commercial/non-commercial use.

## Publisher:

[ninja7v](https://clawhub.ai/user/ninja7v)

### License/Terms of Use:

MIT-0

## Use Case:

Developers and engineers use this skill to create, transform, inspect, and export FreeCAD CAD models through structured parametric operations.

### Deployment Geography for Use:

Global

## Known Risks and Mitigations:

Risk: The skill writes and may overwrite local CAD output files, including model.FCStd, model.step, or requested export filenames.

Mitigation: Run the skill in a dedicated project folder where generated CAD files can be safely created or replaced.

## Reference(s):


## Skill Output:

**Output Type(s):** [JSON, Shell commands, Files, Guidance]

**Output Format:** [Structured JSON operation payloads, shell command invocations, and local CAD output files such as model.FCStd and model.step.]

**Output Parameters:** [1D]

**Other Properties Related to Output:** [Runs through a local Python and FreeCAD engine and may create or overwrite CAD files in the working directory.]

## Skill Version(s):

1.0.1 (source: server release metadata)

## Ethical Considerations:

Users should evaluate whether this skill is appropriate for their environment, review any generated or modified files before relying on them, and apply their organization's safety, security, and compliance requirements before deployment.
