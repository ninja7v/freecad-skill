# FreeCAD skill for OpenClaw

[![Tests](https://github.com/ninja7v/freecad-skill/actions/workflows/tests.yml/badge.svg)](https://github.com/ninja7v/freecad-skill/actions/workflows/tests.yml)
[![License: MIT-0](https://img.shields.io/badge/License-MIT--0-green.svg)](LICENSE)

This skill lets an AI agent create, edit, inspect and export real, **parametric** FreeCAD models. It sends
structured JSON and gets verified geometry back. You can open the result in FreeCAD and keep working on it:
each step is a native feature (`Part::Box`, `Part::Cut`, `Part::Fillet`, Draft arrays, spreadsheet
parameters), so you don't get a dead lump of geometry.

```text
"80×50 mounting plate, 6 mm thick, four M6 holes 10 mm from the corners, rounded corners"
        │  agent writes JSON
        ▼
fcskill.py ──► FreeCADCmd (headless) ──► mounting_plate.FCStd + .step
        │
        ▼  structured feedback: per-step volume and bbox, warnings, verified exports
agent checks the numbers, fixes mistakes, edits "make it 8 mm thick" in place
```

## What makes it reliable

- **Parametric documents.** Change `Params.plate_t` or `Plate.Length` later and the cuts, arrays and
  fillets downstream recompute.
- **Verified every step.** Shape validity, empty results, cuts that remove nothing and fusions that fall
  apart are all detected. Steps can declare `expect` (volume, bounding box, solid count) and fail if the
  geometry doesn't match.
- **Errors an LLM can act on.** Each error has a code, the failing step, a hint and measured values. For
  example: *"Requested size 6 mm; the shortest selected edge is 10 mm."* The whole request is validated
  first, with typo suggestions.
- **Semantic edge/face selection.** `"edges": "|Z and %LINE"` or `"open_faces": ">Z"` instead of fragile
  indices. Selectors are re-evaluated when dimensions change.
- **All-or-nothing requests.** If a step fails, nothing is saved or exported.
- **Visual checks without a GUI.** `render` writes shaded PNG views (iso/front/top/right) that a
  vision-capable agent can look at.
- **Verified exports.** STEP, IGES, BREP, STL, OBJ and 3MF files are read back and compared with the model.
  Meshes are checked for being watertight.
- **No daemon, no GUI, no addon.** One stdlib-only Python launcher runs FreeCAD's own headless interpreter.

## Install

Requirements: **Python 3.12 or newer** for the launcher (`python3 --version`), and FreeCAD 1.1 or newer. FreeCAD
keeps its own Python, whatever its version.

### 1. FreeCAD 1.1 or newer

| OS | Command |
|---|---|
| Ubuntu / Debian | `sudo apt install freecad`, or `sudo snap install freecad` |
| Fedora | `sudo dnf install freecad` |
| Arch | `sudo pacman -S freecad` |
| macOS | `brew install --cask freecad` |
| Windows | `winget install FreeCAD.FreeCAD` or the installer from [freecad.org](https://www.freecad.org/downloads.php) |
| Any (conda) | `conda install -c conda-forge freecad` |

The skill finds FreeCAD automatically: on `PATH`, in standard install locations, as a snap or a flatpak, or
as a Python-importable module. If yours lives somewhere else, point `FCSKILL_FREECAD` at its command-line
executable:

```bash
export FCSKILL_FREECAD=/opt/freecad/bin/freecadcmd
export FCSKILL_FREECAD="$HOME/Apps/FreeCAD.AppImage freecadcmd"                       # AppImage
set FCSKILL_FREECAD=C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe                   # Windows
export FCSKILL_FREECAD=/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd    # macOS
```

### 2. The skill

```bash
clawhub install freecad-skill
# or
git clone https://github.com/ninja7v/freecad-skill.git ~/.openclaw/skills/freecad-skill
```

### 3. Check

```bash
python3 ~/.openclaw/skills/freecad-skill/scripts/fcskill.py doctor
```

`doctor` models, verifies and exports a test part and reports the FreeCAD version it used.

> **Snap users:** snap-confined FreeCAD can't see `/tmp` or hidden folders such as `~/.openclaw`. The
> launcher detects this and stages files through `~/snap/freecad/common` automatically.
>
> **Windows:** use `python` (or `py`) instead of `python3` in the commands below.
>
> **Sandboxed agents (Docker):** FreeCAD must be installed *inside* the sandbox image, because OpenClaw
> checks and runs binaries in the container. Snap packages don't work in containers; use the distribution
> package, conda (`conda install -c conda-forge freecad`) or an extracted AppImage with `FCSKILL_FREECAD`.

## Use

The agent normally does this for you (see [SKILL.md](SKILL.md)), but you can run it directly:

```bash
python3 scripts/fcskill.py run examples/mounting_plate.json     # file
python3 scripts/fcskill.py run - < request.json                 # stdin
python3 scripts/fcskill.py describe                             # list operations
python3 scripts/fcskill.py describe fillet                      # one operation in detail
```

A request is a document plus ordered steps:

```json
{
  "doc": "mounting_plate.FCStd",
  "steps": [
    {"op": "set_params", "values": {"plate_t": 6, "hole_r": 3.25}},
    {"op": "box", "name": "Plate", "length": 80, "width": 50, "height": "=Params.plate_t"},
    {"op": "cylinder", "name": "Hole", "radius": "=Params.hole_r", "height": "=Params.plate_t + 2", "position": [10, 10, -1]},
    {"op": "grid_array", "name": "Holes", "target": "Hole", "count_x": 2, "count_y": 2, "step_x": 60, "step_y": 30, "fuse": false},
    {"op": "cut", "name": "Drilled", "base": "Plate", "tool": "Holes"},
    {"op": "fillet", "name": "MountingPlate", "target": "Drilled", "radius": 5, "edges": "|Z and %LINE",
     "expect": {"bbox_size": [80, 50, 6], "solids": 1}},
    {"op": "export", "filename": "mounting_plate.step"}
  ]
}
```

Later, to make the plate 8 mm thick:

```json
{"doc": "mounting_plate.FCStd", "steps": [{"op": "set_params", "values": {"plate_t": 8}}, {"op": "export", "filename": "mounting_plate.step"}]}
```

The output is a single JSON object on stdout. The exit code is `0` on success, `1` if the request failed
(see `error`), and `2` for environment problems.

### Operations

- **Solids:** `box`, `cylinder`, `sphere`, `cone`, `torus`, `prism`
- **Profiles:** `extrude`, `revolve`, from rounded rectangles, circles, slots, polygons and arc paths,
  built as editable FreeCAD sketches
- **PartDesign:** `body`, `hole` (ISO clearance and tap sizes, counterbore, countersink). `extrude` and
  `revolve` with `body` make pads, pockets, revolutions and grooves. Fillets, chamfers, shells and patterns
  work on bodies too.
- **Booleans:** `cut`, `fuse`, `common`
- **Features:** `fillet`, `chamfer`, `shell`
- **Patterns:** `linear_array`, `grid_array`, `polar_array`
- **Transforms:** `move`, `rotate`, `place`, `mirror`, `copy`, `scale`
- **Assemblies:** `assembly`, `joint` (fixed, revolute, cylindrical, slider, ball, parallel, perpendicular).
  Every joint is verified after solving, interferences are reported, and joints follow upstream edits.
- **Editing:** `set`, `set_params`, `delete`, `rename`, `python` (opt-in)
- **Queries:** `inspect`, `check`, `measure` (clearance, interference, mass), `fem_static` (linear stress
  analysis with equilibrium and mesh-convergence checks, safety factor, stress map)
- **Output:** `export` (including flat DXF/SVG outlines for laser cutting), `drawing` (dimensioned DXF
  technical drawings), `render`

The full reference is in [docs/OPERATIONS.md](docs/OPERATIONS.md), generated from the code. The design and
its trade-offs are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

### Examples

[`examples/`](examples/) has ready-to-run requests: a PartDesign bracket (pads, pocket, counterbored holes, fillet), a mounting plate, a gasket (sketch profile),
an enclosure, a flanged bushing, a wheel, an L-bracket and a table. Each one asserts its own geometry and is part of the test suite.

## Files and safety

- All paths are relative to the **workspace** (the current directory, or `--workspace` / `FCSKILL_WORKSPACE`).
  Paths outside it, including through symlinks or `..`, are refused.
- Only the requested document and explicit exports are written. Saves are atomic, and FreeCAD backup files
  are not created.
- Requests on the same document run one at a time: a lock file (`.<name>.FCStd.lock`) next to the
  document serialises them, so parallel tool calls can't overwrite each other's changes.
- Network access is used only for the FreeCAD parts library (`fcskill.py library`, and `import` with `library`),
  only to `api.github.com` and `raw.githubusercontent.com` for the `FreeCAD/FreeCAD-library` repository, and
  never for arbitrary URLs. Downloads are checked against the repository's git hashes, capped at 60 MB and
  cached in the workspace (`.fcskill/library`). `FCSKILL_OFFLINE=1` forbids all network access;
  `FCSKILL_LIBRARY` uses a local clone instead. FreeCAD itself runs offline.
- The skill runs no agent-written Python unless you opt in with
  `FCSKILL_ALLOW_PYTHON=1`, which enables the `python` escape-hatch op for cases the operations don't cover.
  **With it enabled, the workspace confinement above no longer holds:** that code can read and write
  anywhere your user account can. Enable it only for agents and inputs you trust.

## Limitations

- Profiles support lines, arcs, circles and slots, but not splines or dimensional constraints.
- Not yet supported: nested assemblies, motion joints (gears, belts, screws), non-linear/modal/thermal FEM, PartDesign loft, sweep and mirror, and PDF/SVG drawing pages
  without the GUI (drawings are written as DXF).
- Requires FreeCAD 1.1 or newer. FreeCAD 1.0's Draft module needs the GUI libraries even when headless,
  which breaks arrays and copies on conda's macOS and Windows builds, so older versions are refused with
  `FREECAD_VERSION`. Verified by hand on Linux with FreeCAD 1.1 (snap); CI runs the suite on Linux, macOS
  and Windows with conda-forge FreeCAD 1.1. Report problems with other setups, including the output of `doctor`.

## Breaking changes in v2

v2 is not compatible with v1:

- The request format changed: `{"doc": ..., "steps": [{"op": ...}]}` replaces v1's
  `{"operation": ..., "parameters": ...}`, which is now rejected with an error. The operations were renamed and
  regrouped (see `describe`).
- The v1 entry point `scripts/cad_engine.py` is gone; use `scripts/fcskill.py run`.
- `model.step` is no longer written automatically after each request; use an `export` step.
- FreeCAD 1.1 or newer is required.
- `FREECAD_PATH` is no longer read; use `FCSKILL_FREECAD`.
- Documents made by v1 open, but their objects are fixed shapes with no editable dimensions.

See [CHANGELOG.md](CHANGELOG.md).

## Development

```bash
python3 tests/run.py          # pure tests here, engine tests inside FreeCAD (auto-detected)
python3 tests/run.py --pure   # no FreeCAD needed
python3 scripts/fcskill.py describe --markdown > docs/OPERATIONS.md   # after changing the catalog
ruff check . && ruff format .   # lint and format (CI runs both; config in pyproject.toml)
```

To add an operation:

1. Declare it in `scripts/fcengine/catalog.py`.
2. Implement the handler in `scripts/fcengine/ops/`.
3. Add an engine test that checks the resulting geometry.
4. Regenerate `docs/OPERATIONS.md`.

## Publishing (maintainers)

```bash
python3 tests/run.py                                   # everything green first
clawhub skill publish . --version 2.0.0 --dry-run      # check what will be uploaded
clawhub skill publish . --version 2.0.0 \
  --categories development,creative --topics cad,freecad,3d-printing,step,parametric
clawhub scan --slug freecad-skill                      # read the security report
```

- Always pass `--version`. Without it, ClawHub publishes the next *patch* version.
- Publish to the existing slug so that installed copies receive the update. Check it with
  `clawhub inspect @ninja7v/freecad-skill`.
- The ClawHub GitHub importer skips private repositories, so publish with the CLI.
- `.clawhubignore` keeps `tests/` out of the published bundle.

## License

[MIT-0](LICENSE)
