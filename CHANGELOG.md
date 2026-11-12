# Changelog

## 3.0.1

Fixes for the two weaknesses the ClawHub security audit of 3.0.0 confirmed, and a clearer scope.

### Fixed
- **The self-intersection check could report a clean result it had not obtained.** FreeCAD runs that test
  only on geometry that passes its validity test, and the skill read every checker error that did not name a
  self-intersection as "none found", then cached it. The check now has three faithful outcomes: found, not
  found (only when every solid was examined), and not established, with the reason. A result that was not
  cleared carries `self_intersection_check: "not checked (reason)"` and a `SELF_INTERSECTION_UNCHECKED`
  warning, STEP/BREP exports list it under `verified.self_intersection_unchecked`, and `inspect` shows the
  reason. Results with more than 3000 faces, which skip the check, are reported the same way (they had
  no warning before).
- **A link planted in the workspace could redirect the parts cache.** The cache writer compared resolved
  paths, so a link at `.fcskill` or `.fcskill/library` itself passed the check, and folders were created
  before it. Cache files are now reached from the workspace folder one component at a time without
  following links (descriptor-relative on Linux and macOS, a per-component check on Windows), for reads as
  well as writes; a link anywhere on the way is refused with `LIBRARY_UNAVAILABLE`. Staging for snap FreeCAD
  copies real files only.

### Added
- `expect: {"self_intersecting": false}` on a step or in `check` fails the request unless the check ran and
  passed, for work that needs the confirmation.

### Changed
- The launcher starts FreeCAD with its own environment instead of a copy of it, and the solver's
  single-thread settings are set by name: same behaviour, no copy of the environment anywhere.
- The parts library code reads no environment variable: the launcher passes the `FCSKILL_LIBRARY` and
  `FCSKILL_OFFLINE` settings in, so a download is built from constants and a library path only.
- SKILL.md has a "Scope" section listing the commands, files, network use and environment variables.

## 3.0.0

A reliability and engineering release.

### Added
- **Parametric profiles.** The numbers of `rect`, `circle` and `slot` shapes (coordinates, `radius`,
  `corner_radius`) can be expressions such as `"=Params.width"`, in `extrude` and `revolve`, in and out of a
  body. These shapes are now fully dimensioned sketches (one named dimension per number, zero degrees of
  freedom), so they are also stable when edited in the FreeCAD GUI. `inspect` of a sketch reports
  `degrees_of_freedom`. Until now only heights, offsets and primitive sizes could follow parameters.
- **Mass properties.** `measure` reports volume, area, centre of mass and the inertia tensor per object
  (`properties`), in g*mm2 with principal moments when a density is known, and the `total` mass and centre of
  mass of several parts. `inspect` of an object includes the geometric inertia.
- **STEP files with names and structure.** Parts are written as named products, and an assembly as a product
  structure in which each part is defined once and placed as often as it is used. `verified.part_names`
  confirms it. Before, every STEP held anonymous shapes and assemblies were flattened.
- **Self-intersection check.** Results a request creates or changes are checked for passing through
  themselves, which FreeCAD's validity check does not see (e.g. a spring with a wire thicker than its pitch
  was reported valid, with a wrong volume). Reported as a `SELF_INTERSECTION` warning, in the result and in
  the export record; mesh exports report `self_intersections`.
- **Drawings:** equal holes get one diameter with a count (`4x ⌀5.5`), and a hole table on the sheet and in
  the result (`holes`) gives each vertical hole's position.
- **Bill of materials** for assemblies (`bom`: part, quantity, material, mass each), from `assembly` and
  `inspect`.
- `fem_static` uses the material assigned to the part when `material` is left out.
- New material grades with strength data: `steel_s235`, `steel_s355`, `stainless_304`, `aluminium_5754`,
  `nylon_pa12`, usable in `material`, `measure` and `fem_static` alike.
- `brief: true` on a request leaves the per-step geometry out of long responses.
- `DEEP_CHAIN` warning when booleans are stacked 12 deep, with advice to batch.

### Changed (breaking)
- `export`: the `format` parameter is removed. It could never differ from the file extension.
- `fem_static`: `material` must be a specific grade; generic `steel` and `aluminium` are refused because their
  yield strength depends on the grade. `aluminium_6061_t6` and `titanium_gr5` remain valid names.
- `assembly`: a part without `position` or `rotation` keeps the placement it was modelled with. It used to move
  to the origin, often into another part, without a warning.
- `inspect` without a target no longer reports `valid` for every object, and the `results` of a request
  that changes nothing carry no `valid` field. `inspect` one object to check it.
- One material table (`matdata.py`) replaces the separate tables of `material` and `fem_static`. Densities now
  come from it (e.g. `steel` 7.85 g/cm3 instead of the FreeCAD library's 7.9; `abs` 1.04).

### Fixed
- **Speed of read-only requests.** Listing a document checked the validity of every object: 7.9 s for a plate
  built from 50 chained cuts, 84 s with 100. It now takes 1.1 s and 6.2 s (4 s of the latter is FreeCAD opening
  the file). Requests that only read (`inspect`, `measure`, `export`, `render`) no longer re-check shapes that
  were checked when they were made, so their `results` carry no `valid` field. Building such a plate one cut
  at a time stays slow in FreeCAD itself (21 s for 50 holes); SKILL.md now tells agents to batch, which takes
  1.3 s for the same part.
- **Imported files and fonts were not found when FreeCAD is a snap and the workspace is a hidden folder or
  outside the home directory** (the usual place of agent workspaces). The launcher now stages every file a
  request reads, not only the document.
- When Python could import FreeCAD directly (conda), requests ran inside the launcher with no timeout and no
  protection from a crash. Every backend now runs as a separate process.
- `set` with `open_faces` given as indices on a shell made with a selector was silently ignored.
- A fillet whose edges disappeared after an upstream change was explained as "radius too large". The hint now
  says the edge references are gone and how to set them again.
- STEP export of one moved part through the new writer keeps its position (checked by the read-back).
- `set` can no longer overwrite the skill's own bookkeeping properties (`FCSkill...`).
- Arrays are limited to 1000 instances per direction and 5000 per grid.
- The documented default mesh size of `fem_static` ("half the thinnest dimension") was wrong; it is about the
  wall thickness. The documentation is corrected, the behaviour is unchanged.
- ARCHITECTURE.md listed limitations that no longer applied (splines, materials).

### Documentation
- SKILL.md is shorter (491 to about 400 lines) although it gained the new features. Guidance for `loft`/`sweep`/`text`, imports and library parts, assemblies and
  stress analysis moved to `docs/SHAPES.md`, `docs/PARTS.md`, `docs/ASSEMBLIES.md` and `docs/ANALYSIS.md`,
  which the agent reads when it needs them.

## 2.0.3

### Fixed
- FEM mesh convergence could be reported as `passed` when the finer mesh was barely finer than the
  first one (Gmsh can ignore a size limit the geometry already meets), so two near-identical meshes
  agreed. If three refinement attempts don't give 30% more nodes, convergence is now `unavailable`, with
  a `NO_CONVERGENCE_CHECK` warning and `convergence.refined: false`.
- Library cache writes no longer follow links. A link planted in `.fcskill/library` could redirect a
  copy or download to a file outside the workspace. Files are now written to a new temporary file and
  renamed into place, and a cache folder that resolves outside the cache is refused.

## 2.0.2

A security release: the skill now runs only validated JSON operations. It also adds modelling tools.

### Removed (breaking)
- The `python` escape-hatch op and its `FCSKILL_ALLOW_PYTHON` switch. It was off by default, but it was
  general code execution with the user's permissions, which a CAD skill does not need. A request with
  `"op": "python"` now fails validation (`INVALID_REQUEST`), and the `SCRIPT_ERROR` code is gone.
- The environment filter added in 2.0.1. It only existed to keep credentials away from `python` op code;
  without that op, FreeCAD, Gmsh and CalculiX run only the skill's own code and get the normal environment
  again, as in 2.0.0.

### Added
- `text`: lettering as a solid (Draft ShapeString, extruded), to engrave (cut) or emboss (fuse). It uses
  FreeCAD's bundled osifont by default or a `.ttf`/`.otf` file in the workspace, and can be edited with
  `set` (`text`, `size`, `font`, `align`, `height`).
- `hole` with `threaded: true`: a modelled ISO metric coarse thread (class 6H) over the hole depth.
- `import` of meshes (STL, OBJ, 3MF, PLY, OFF) as solids, so that an STL can be cut, fused, measured
  and exported. Open, non-manifold or self-intersecting meshes are refused, and so are meshes above 20,000
  triangles (booleans on faceted solids are slow in FreeCAD). `refine` merges coplanar triangles, and
  `CHECK_UNITS` warns when the size looks like inches or metres.
- `mirror` of a PartDesign feature mirrors it inside its body (`PartDesign::Mirrored`).
- `grid_array` of a PartDesign feature: one `MultiTransform` inside the body. It used to be refused.

### Changed
- Patterning or mirroring a pattern or mirror of a body fails up front, with a hint to name the original
  feature. FreeCAD can't repeat a repeated feature.
- SKILL.md tells agents to report unsupported requests instead of writing their own FreeCAD scripts.
- Shape validity is checked once per shape and request instead of several times, which makes large
  models (and imported meshes) faster.

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
