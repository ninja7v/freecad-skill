# Changelog

## 2.0.2

A security release: the skill now runs only validated JSON operations.

### Removed (breaking)
- The `python` escape-hatch op and its `FCSKILL_ALLOW_PYTHON` switch. It was off by default, but it was
  general code execution with the user's permissions, which a CAD skill does not need. A request with
  `"op": "python"` now fails validation (`INVALID_REQUEST`), and the `SCRIPT_ERROR` code is gone.
- The environment filter added in 2.0.1. It only existed to keep credentials away from `python` op code;
  without that op, FreeCAD, Gmsh and CalculiX run only the skill's own code and get the normal environment
  again, as in 2.0.0.

### Fixed
- `fem_static`: `checks.convergence` is now `failed` when refining the mesh changes the result too much
  (with a `NOT_CONVERGED` or `STRESS_CONCENTRATION` warning). It used to say `passed` whenever the second
  solve ran.

## 2.0.1

A security patch addressing the ClawHub security audit findings.

### Security
- FreeCAD (and Gmsh, CalculiX and the `python` op under it) now runs without credential-like environment
  variables (tokens, keys, passwords, credentials in URLs, SSH/GPG agent sockets).
- Library downloads are allow-listed to the FreeCAD library on api.github.com and raw.githubusercontent.com;
  redirects to other hosts are refused. Parts copied from a local clone (`FCSKILL_LIBRARY`) must stay inside it.
- Files copied back from the snap staging folder are confined to it as well as to the workspace.
- The documentation now states plainly that the `python` op is not a sandbox and that only its document
  changes are rolled back. The skill description discloses DXF drawings, stress analysis and the optional
  library downloads.

### Changed
- `fem_static` warns `NO_CONVERGENCE_CHECK` when `convergence` is off and `NO_EQUILIBRIUM_CHECK` when the
  solver reports no reactions, instead of skipping those checks silently, and its result has a `checks` field
  (`passed`, `skipped` or `unavailable` for each check).
- `measure` takes the same material names as `material` (every preset, including `rubber`, aliases and
  FreeCAD library materials), with the same densities: `steel` is now FreeCAD's 7.90 g/cm3 instead of 7.85.
  `wood_oak` is an alias of `wood`.
- The `rename` conflict error names the object that already uses the label.

### Fixed
- Closed-loop assemblies (four-bar, crank-slider) now solve. Joint pre-solving left the chain straight, a
  start from which the closing joint fails, so a failed solve is retried from the parts' `position`/`rotation`
  given in `assembly`, then from slightly turned starts. A solve that moves a grounded part counts as failed.
- `joint` no longer warns `INTERFERENCE` for parts that are not joined yet; they are listed in `not_joined`.

## 2.0.0

A rewrite of the engine around native, parametric FreeCAD features. **Breaking changes:** v2 is not
compatible with v1 (see below).

### Added
- Editable feature tree in the saved `.FCStd`: `set`, `set_params` (spreadsheet parameters), `=expressions`
  on dimensions, and edge/face selectors (`>Z`, `%CIRCLE`, `r<5`, ...) that are re-evaluated after edits.
- PartDesign bodies (`body`, `hole` with ISO metric clearance, tap, counterbore and countersink sizes),
  and native Sketcher profiles (rounded rectangles, slots, polygons, arcs, holes).
- Assemblies: parts as links, with fixed, revolute, cylindrical, slider, ball, parallel and perpendicular
  joints. Joints are checked geometrically after solving and follow edits to the parts. `measure` compares
  the parts as assembled.
- `fem_static`: linear static stress analysis (Gmsh + CalculiX) with displacement, von Mises stress,
  safety factor, an equilibrium check and a mesh-convergence check. Verified against beam theory (+0.26%).
- Dimensioned DXF technical drawings (`drawing`), and flat DXF/SVG outlines for laser and CNC cutting.
- Splines in profiles (`spline` shapes and `spline_to` path segments), `loft` through cross-sections and
  `sweep` along paths or helices (tubes, handles, springs, threads), as plain solids or in PartDesign bodies.
- Ready-made parts from the official FreeCAD library: `fcskill.py library <keywords>` searches it, and `import`
  brings a part in (downloaded once, verified against the repository's git hashes, with its CC-BY attribution).
  `import` also reads STEP/IGES/BREP/FCStd files from the workspace.
- `material`: FreeCAD library materials (presets such as steel, aluminium, brass, PLA, rubber, glass) and
  custom colours, shown in FreeCAD, in renders and used by `measure` for masses.
- `measure` (clearance, interference, mass), `check` and per-step `expect` assertions, `inspect`, and
  headless, smooth-shaded PNG `render` views for visual checks.
- New modelling ops: `place`, `grid_array`, `shell`, `mirror`, `copy`, `scale`, `prism`, `delete`,
  `rename`, and a `python` escape hatch that is off unless `FCSKILL_ALLOW_PYTHON=1`.
- `fcskill.py` launcher: finds FreeCAD on its own (including snap and flatpak) and adds the `describe` and
  `doctor` commands.
- Reliability: validation of the whole request before execution, structured errors with hints, atomic
  requests (nothing saved on error), `dry_run`, per-document locking, workspace path confinement, and
  exports to STEP, IGES, BREP, STL, OBJ and 3MF that are read back and verified.
- Test suite (160 tests, 111 against real FreeCAD), CI with ruff lint and format checks, and a generated operations reference.

### Fixed
- v1 bugs:
  - Linear arrays with more than 3 copies were misplaced.
  - `model.step` contained every intermediate object.
  - Misspelt parameters were silently replaced by defaults.
  - `rotate` ignored `center`.
  - 3D profile points crashed.
  - Errors exited with code 0.
  - Several documented operations did not exist.
- Saved documents opened in the FreeCAD GUI showed every object hidden: headless FreeCAD writes no GUI
  data, and the GUI then ignores the objects' own visibility. The skill now writes it (only finished parts
  shown) and keeps GUI data already in the file (colours, camera) instead of dropping it on every save.
- Edits that break downstream features are rejected or reported instead of saved silently.
- Meshing for `fem_static` could hang indefinitely: in FreeCAD 1.1 Gmsh ran on every core with no timeout,
  because the skill's safeguard was bypassed by FreeCAD's newer meshing path. It now runs single-threaded,
  under a timeout.
- Finished parts that overlap each other are reported (`OVERLAPPING_RESULTS`, and `OVERLAPPING_SOLIDS` on
  export). Typical causes are a leftover helper that hides the part in renders, or mating parts sized wrong.

### Breaking changes
- The request format changed: `{"doc": ..., "steps": [{"op": ...}]}` replaces v1's
  `{"operation": ..., "parameters": ...}`, which is now rejected with an error. The operations were renamed and
  regrouped (see `describe`).
- The v1 entry point `scripts/cad_engine.py` is gone; use `scripts/fcskill.py run`.
- `model.step` is no longer written automatically after each request; use an `export` step.
- FreeCAD 1.1 or newer is required, and Python 3.12 or newer for the launcher.
- `FREECAD_PATH` is no longer read; use `FCSKILL_FREECAD`.
- Documents made by v1 open, but their objects are fixed shapes with no editable dimensions.

## 1.0.1

Fixed the "suspicious patterns" flag raised by OpenClaw's scan of 1.0.0:
- Declared the Python runtime requirement in `metadata.openclaw`.
- Found local FreeCAD installations automatically (Windows, macOS, Linux).
- Export filenames were reduced to their base name, so files could no longer be written outside the working directory.
- Clarified the description.

## 1.0.0

First ClawHub release. Built FreeCAD models headlessly from JSON requests: primitives (box, cylinder,
sphere, cone, torus), extruded and revolved profiles, booleans, move/rotate/scale, fillet and chamfer,
linear and polar arrays, batch requests, inspection, and STEP/STL/BREP export.
