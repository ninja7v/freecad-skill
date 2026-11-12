# Architecture and design decisions

## Flow

```text
agent ──JSON──► scripts/fcskill.py (Python ≥ 3.12, stdlib only)
                 │  finds FreeCAD, stages files if snap-confined
                 ▼
                FreeCADCmd -c bootstrap ──► fcengine.runner.execute()
                 │  validate (catalog) → open doc
                 │  for each step: handler → recompute → verify → expect
                 │  all ok → atomic save + move verified exports into place
                 ▼
agent ◄──JSON── response file → stdout
```

| Module | Role | Needs FreeCAD |
|---|---|---|
| `catalog.py` | Every op and parameter, with types, constraints, docs and examples. Single source of truth. | no |
| `validate.py` | Static validation; reports all problems at once, with suggestions | no |
| `selectors.py` | Edge/face selector language, evaluated on descriptor dicts | no |
| `workspace.py` | Path confinement | no |
| `docs.py` | Markdown generated from the catalog | no |
| `document.py` | Execution context: lookup, naming, expressions, recompute diagnostics, roles, save | yes |
| `geometry.py` | Summaries, exact bounding boxes, topology descriptors, expectations | yes |
| `ops/*.py` | One handler per op | yes |
| `runner.py` | Request lifecycle, response format, final quality gate | yes |
| `matdata.py` | The one material table (appearance, density, strength data) | no |

## Decisions

**JSON operations, not generated Python.** LLMs write plausible FreeCAD Python that fails in subtle ways:
API differences between versions, topological naming, wrong placement semantics. A small, validated
vocabulary allows typo detection before execution, uniform verification after each step, and errors written
for the agent. The cost is expressiveness. The catalog grows where real use shows gaps.

**No scripting escape hatch.** Versions 2.0.0 and 2.0.1 had an opt-in `python` op for the long tail that no op
covers. It was removed in 2.0.2: general code execution is the main thing security reviews flag in a CAD
skill, and "the skill runs only validated operations" is a stronger guarantee than "off by default". Gaps are
filled with new ops instead.

**One CLI tool, not many tools or an MCP server.** OpenClaw skills drive tools through the shell, so a single
command with a `describe` subcommand is the simplest thing that works everywhere. It needs no daemon and no
FreeCAD addon. Starting FreeCADCmd costs about 0.4 s per request, which batching amortises.

**Native parametric features.** v1 baked every result into a `Part::Feature`, so nothing could be edited.
v2 uses `Part::Box`, `Part::Cut`, `Part::Fillet`, Draft arrays and clones, and spreadsheet parameters. The
saved `.FCStd` is a real feature tree that a human can open and keep editing in FreeCAD.

**Profiles from shapes, not constraints.** LLMs are unreliable at constraint-based sketching: they produce
under- or over-constrained sketches and get the solver into odd states. Agents describe profiles as
rectangles, circles, slots, rounded polygons and arc paths. `profiles.py` turns these into exact line and arc
segments (pure Python, unit-tested), which become a native `Sketcher::SketchObject`. Nested loops become holes through FreeCAD's Bullseye face maker.

Since 3.0 the agent still never writes constraints, but the engine does: a `rect`, `circle` or `slot` has
exactly one number per degree of freedom, so the engine adds one named dimension per number (plus
horizontal/vertical, tangent and equal-radius constraints) and the sketch is fully constrained (verified
with `DoF == 0` in the tests). A number given as `"=expression"` becomes an expression on its dimension,
which makes outlines follow `Params`. Polygons, splines and paths keep coincident constraints only: their
corner points have no one-to-one dimensions an agent could name. If a dimensioned literal sketch does not
solve, the engine falls back to the plain outline; with expressions it fails instead.

**PartDesign through the same vocabulary.** There is no parallel set of PartDesign ops. `body` and `hole`
are new; `extrude`, `revolve`, `fillet`, `chamfer`, `shell` and the arrays gain a body mode. Two findings
from probing FreeCAD 1.1 shaped this:

- Sketches attached to a face use that face's own axes, and in testing an agent-style request put the
  pocket outside the part.
- Topological naming still breaks PartDesign fillets when an upstream pad changes ("Invalid edge link").

So sketches are always attached to the body's XY origin plane, with an AttachmentOffset onto the
requested plane, and `offset` can be an expression that follows a face. Dress-ups use stored selectors
re-evaluated after each edit, the same mechanism as Part fillets. Arbitrary axes for revolutions and
patterns are deactivated datum lines. `body.addObject` doesn't always advance the Tip (patterns), so the
Tip is set explicitly.

**Part workbench and PartDesign side by side.** Part features are robust headless and map one-to-one onto the
operations; PartDesign bodies use the same vocabulary for sketch-based parts.

**Every backend is a separate process.** Until 2.x a Python that could import FreeCAD ran the engine
in-process, with no timeout and no protection from a crash in the CAD kernel. Since 3.0 the launcher always
starts a child process (FreeCADCmd, or the same Python), so `--timeout` and `FREECAD_CRASHED` apply everywhere.

**Cost of validity checks.** `isValid()` took 6.6 of the 7.9 s that listing a 50-hole plate needed, so a
document listing no longer checks it; each new shape is checked once when made, and the results of a
request that changes something once at the end. Read-only requests skip both the check and the shape
fingerprints.
Booleans stacked on booleans are slow in FreeCAD itself (50 chained cuts: 21 s; the same holes in one cut:
1.3 s), which the engine cannot fix: it warns (`DEEP_CHAIN`) and SKILL.md tells agents to batch.

**A quality gate beyond isValid.** OCC calls a solid that passes through itself valid (a spring with a 6 mm
wire on a 4 mm pitch). Results a request created or changed are therefore run through OCC's boolean-argument
checker, solid by solid (separate solids of a compound may overlap on purpose), up to 3000 faces. A hit is
a `SELF_INTERSECTION` warning, repeated in the export record; mesh exports test triangle intersections.

**STEP through the structured writer.** `Part.export` writes anonymous shapes. `Import.export(objs, path,
False, True)` writes named products and an assembly's product structure headless (the fourth argument keeps
a single part's placement). The read-back comparison decides: if the structured file does not match the
model, the plain writer is used and the response says so (`STEP_NAMES`). Colours are not written: FreeCAD
keeps them in the GUI document.

**Verification is part of every op.** "No exception" is not success:

- Each step recomputes and checks shape validity and non-empty solids.
- Booleans check that they actually changed the volume, or stayed connected.
- `expect` and `check` turn the agent's intent into assertions.
- Bounding boxes use `optimalBoundingBox`, because `Shape.BoundBox` is loose on curved surfaces.
- Exports are read back and compared with the model.

**A built-in renderer.** Numbers miss mistakes like a hole on the wrong face, which a picture shows at
once. FreeCAD's own rendering needs the GUI and OpenGL, so `render` uses a small numpy rasteriser:
tessellate, z-buffer, Lambert shading, BRep edges drawn on top, PNG written with zlib. It needs no extra
dependencies and takes about 0.1–2 s per sheet.

**Drawings through TechDraw, headless.** Pages compute nothing without a template, and views compute on a
background thread, so the engine pumps the Qt event loop until they're done. `writeDXFPage` is the only
page export available without the GUI.

TechDraw also picks its own in-plane orientation unless `XDirection` is set. The DXF writer keeps only the
first line of each annotation, and the template's title block isn't exported. So every view gets an explicit
X direction, and title lines are separate annotations.

Dimensions reference the views' extreme vertices and closed circles, and every value is compared with the
model before writing. Flat cutting outlines rotate the shape so the requested view becomes a top view, then
project it. The PNG preview is rendered from the DXF that was actually written.

**Assemblies verified geometrically.** Joints use the native Assembly workbench (links plus JointObject),
which solves headless. Its references are topological: after an upstream edit they break ("Broken link in:
Reference1") while `solve()` still returns 0. So joints store selectors, are re-resolved after every edit,
and each joint is checked after solving. The check compares the two global joint frames (part placement
times joint placement) by position and axis collinearity, and the distance between the referenced elements
against the requested `offset`.

FreeCAD may flip a frame so the two face each other, which makes the sign of `Offset1` unpredictable. The
skill therefore defines `offset` as "away from side a's material" (the outward normal of the bounded planar
face), measures it after solving, and corrects the sign once. Measurements use `Part.getShape(link)`,
because `link.Shape` can be stale or unplaced right after solving.

**FEM with mandatory self-checks.** `fem_static` wraps Gmsh and CalculiX, because plausible-looking wrong
numbers are the main risk. The checks below come from measurements on FreeCAD 1.1:

- **Element order.** First-order tetrahedra were 39% too stiff in bending, while second order matched
  beam theory within 0.3%. So second order is always used, and verified after meshing.
- **Units.** A bare force number is read in mN, so loads must carry units.
- **Gmsh reliability.** Gmsh occasionally returned an empty mesh without an error, and its multithreaded
  mesher once spun for more than 10 minutes. In FreeCAD 1.1, `GmshTools.create_mesh()` runs Gmsh through
  a QProcess that it waits on forever, with every core, and reads the mesh back in a Qt signal handler
  that headless runs don't always reach. That path also bypasses `run_gmsh_with_geo`, so a first fix that
  patched only that method never took effect; a later suite run caught a Gmsh process spinning for
  10 minutes. `create_mesh` is now replaced: FreeCAD prepares the input, the skill runs Gmsh
  single-threaded under a timeout and reads the mesh file directly, then checks it (10-node elements) and
  retries if needed.
- **CalculiX threading.** With its default preference, FreeCAD runs CalculiX with `OMP_NUM_THREADS` set to
  every core. In about 1 run in 15 that returned wrong results on identical input: deflection 5–60% off, and
  stresses of 10⁴–10⁵ MPa, while equilibrium still held, so no output check could catch it. CalculiX is
  therefore always run single-threaded, under a timeout. In 60 repeated runs afterwards, every result was
  identical.
- **Load direction.** A force direction assigned from a helper line that hadn't been recomputed yet came out
  random. The line is now recomputed first, and the constraint's direction is verified.
- **Equilibrium.** Every result reports reactions against applied loads, read from CalculiX's `.dat` file.
  The tolerance is 8% instead of 2% when loaded faces touch fixed faces, since load on shared nodes is
  counted as reaction.
- **Convergence.** A second solve on a mesh that really is finer (node count checked) exposes unconverged
  meshes and sharp-corner stress singularities.

**Selectors instead of indices.** Edge indices are meaningless to an LLM and change when the model changes.
Selectors are stored on the feature (`FCSkillSelector`) and re-resolved after every edit made through the
skill. Edits made in the FreeCAD GUI don't re-resolve them; this is a known limitation (topological naming).

**Atomic requests.** The document is saved (to a temporary copy, then renamed) only if every step succeeds.
Exports go to temporary files and are moved into place last. An agent can retry without cleaning up.

**Roles.** An object is an *intermediate* if a consuming feature (boolean, fillet, array, extrusion, scale
clone) uses it, and a *result* otherwise. Responses list results in full and intermediates by name, which
keeps feedback short and makes "export the model" mean the finished parts.

**Snap staging.** Snap-confined FreeCAD can't read hidden directories under `$HOME` (where OpenClaw lives)
or the host `/tmp`. The launcher copies the engine and, when needed, the document to
`~/snap/freecad/common/fcskill`, runs there, and copies written files back.

## Known limitations

- Profiles: only rect, circle and slot are dimensioned; planes are XY/XZ/YZ with an offset.
- Drawings: no section views, tolerances or PDF; hole positions are a table, not dimension lines.
- STEP: no colours on export; an imported STEP becomes one fixed shape.
- FEM: fixed supports, forces and planar pressures only; peak stress includes the clamped edges.
- Placement values are literal; expressions apply to dimensions.
- Selector re-evaluation happens only through the skill.
- FreeCAD 1.1 or newer is required, and checked at the start of every request. In 1.0.x, Draft (used for
  arrays, copy and scale) imports `FreeCADGui` at load time (`draftutils/params.py` →
  `init_draft_statusbar`), which fails headless where the GUI library can't load, e.g. conda on macOS and
  Windows. 1.1 guards that import.
