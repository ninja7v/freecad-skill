---
name: freecad-skill
description: "Create, edit, verify and export parametric FreeCAD models (STEP, STL, 3MF) and DXF drawings from JSON; STL import; stress checks; optional parts from GitHub."
version: 2.0.2
homepage: https://clawhub.ai/ninja7v/skills/freecad-skill
metadata: {"openclaw":{"emoji":"📐","homepage":"https://clawhub.ai/ninja7v/skills/freecad-skill","requires":{"anyBins":["python3","python"]},"envVars":[{"name":"FCSKILL_FREECAD","required":false,"description":"Path or command of FreeCAD's command-line executable (freecadcmd) if auto-detection fails, e.g. '/path/FreeCAD.AppImage freecadcmd'."},{"name":"FCSKILL_WORKSPACE","required":false,"description":"Root folder for documents and exports. Default: the current directory. Paths outside it are refused."},{"name":"FCSKILL_LIBRARY","required":false,"description":"Path to a local clone of the FreeCAD parts library; library parts are then copied from it instead of downloaded."},{"name":"FCSKILL_OFFLINE","required":false,"description":"Set to 1 to forbid all network access. Otherwise the only network use is the optional parts library: anonymous GET requests to api.github.com and raw.githubusercontent.com for FreeCAD/FreeCAD-library, made only by the library command and by import steps that name a library part."}]}}
---

# FreeCAD skill

Build parametric CAD models with FreeCAD by sending a JSON request to one command. Every operation creates a
native FreeCAD feature (`Part::Box`, `Part::Cut`, `Part::Fillet`, ...), so the model stays editable: change a
dimension later and everything downstream updates. After every step the response reports volumes and bounding
boxes, and failures name the step, the cause and a fix.

`{baseDir}` below means the directory that contains this SKILL.md.

## Run

Write the request to a file and run:

```bash
python3 {baseDir}/scripts/fcskill.py run request.json
```

On Windows, use `python` instead of `python3`. The launcher needs Python 3.12 or newer; if it reports
`PYTHON_VERSION`, run it with a newer interpreter (e.g. `python3.12`).

The request can also be inline JSON or come from stdin (`run -`). Use a file for anything non-trivial, because
it avoids shell-quoting problems. The working directory is the workspace. Documents and exports are relative
to it and cannot leave it.

Other commands:
- `python3 {baseDir}/scripts/fcskill.py library <keywords>`: search ready-made parts (see below).
- `python3 {baseDir}/scripts/fcskill.py describe`: list every op with its parameters (`*` = required).
- `python3 {baseDir}/scripts/fcskill.py describe fillet shell`: full parameter details for those ops.
- `python3 {baseDir}/scripts/fcskill.py doctor`: check the FreeCAD installation.

If `doctor` says FreeCAD is missing, ask the user to install FreeCAD 1.1+ or to set `FCSKILL_FREECAD` to its
`freecadcmd` executable. Do not try to model without it.

## Request

```json
{
  "doc": "bracket.FCStd",
  "steps": [
    {"op": "box", "name": "Plate", "length": 80, "width": 50, "height": 6},
    {"op": "cylinder", "name": "Hole", "radius": 3.25, "height": 8, "position": [10, 10, -1]},
    {"op": "cut", "name": "Drilled", "base": "Plate", "tool": "Hole"},
    {"op": "fillet", "name": "Bracket", "target": "Drilled", "radius": 5, "edges": "|Z and %LINE",
     "expect": {"bbox_size": [80, 50, 6], "solids": 1}},
    {"op": "export", "filename": "bracket.step"}
  ]
}
```

- `doc`: the `.FCStd` file (default `model.FCStd`). It is created if missing and re-opened on later requests.
- `new: true`: start from an empty document, replacing the file's content.
- `dry_run: true`: run and report without saving or exporting.
- **All or nothing:** if any step fails, nothing is saved or exported and the file on disk is unchanged.
  Fix the reported step and resend the whole request.
- Before anything runs, the whole request is validated. Unknown ops or parameters, typos and missing
  values are all reported at once.

## Response

Actual output for the request above (abridged):

```json
{"status": "success", "doc": "bracket.FCStd", "saved": true,
 "steps": [{"index": 0, "op": "box", "object": "Plate", "volume": 24000.0,
            "bbox": {"min": [0,0,0], "max": [80,50,6], "size": [80,50,6]}, "solids": 1},
           {"index": 2, "op": "cut", "object": "Drilled", "volume": 23800.902, "...": "..."},
           {"index": 3, "op": "fillet", "object": "Bracket", "volume": 23672.14, "...": "..."},
           {"index": 4, "op": "export", "data": {"file": "bracket.step"}}],
 "results": [{"name": "Bracket", "type": "Part::Fillet", "role": "result", "inputs": ["Drilled"],
              "volume": 23672.14, "bbox": {"min": [0,0,0], "max": [80,50,6], "size": [80,50,6]}, "solids": 1, "valid": true}],
 "intermediates": ["Plate", "Hole", "Drilled"],
 "exports": [{"file": "bracket.step", "format": "step", "objects": ["Bracket"], "bytes": 13775,
              "verified": {"faces": 11, "bbox_size": [80,50,6], "solids": 1, "volume": 23672.14}}],
 "files_written": ["bracket.FCStd", "bracket.step"]}
```

When something is wrong, `warnings` appears, e.g.
`{"step": 2, "code": "NO_EFFECT", "message": "cut removed no material from 'Plate'; ['Hole'] do not overlap it. ..."}`.

- `results` are the finished parts: objects that no other feature consumes. Exports default to these.
- **Read `warnings`.** For example, `NO_EFFECT` means a cut missed the part, and `DISJOINT` means a fusion
  produced separate pieces. These are geometry mistakes even though the status is success.
- `OVERLAPPING_RESULTS` means two finished parts occupy the same space. Usually one is a leftover helper (a
  cutter you never used, which then hides the part in renders), or two parts that should touch are sized wrong.
  Every result is rendered and exported, so delete leftovers before trusting a render.
- On failure, `error` has `code`, `message`, `hint`, `step`, `op` and often `details` (available names,
  measured values). Exit code is 0 on success, 1 when the request failed, 2 when FreeCAD is missing or crashed.

## Conventions

- Units are **mm** and **degrees**, and the axes are right-handed X/Y/Z with +Z up.
- `box`: `position` is the **minimum corner**; the box extends along +X/+Y/+Z. To centre a 40×20 box on
  (0, 0), use `position: [-20, -10, z]`.
- `cylinder`, `cone`, `prism`: `position` is the **centre of the bottom face**; the axis is +Z unless you
  give `direction` (e.g. `[1, 0, 0]`). `sphere`, `torus`: `position` is the centre.
- `extrude`, `revolve`: the profile lies in `plane` (`XY` default, `XZ`, `YZ`), with 2D coordinates.
  Extrusion goes along the plane normal: XY→+Z, XZ→+Y, YZ→+X. See [Profiles](#profiles).
- Names are identifiers (`Base_plate`, not `base plate`) and must be unique. Name every object you will
  refer to later.
- Make cutting tools **pass through** the faces they cut: a hole in a 6 mm plate should run from z = -1
  to z = 7. Exactly coincident faces make booleans fail or leave skins.

## Operations

| Op | Purpose | Key parameters (`*` required) |
|---|---|---|
| `box` | Box | `length*` `width*` `height*` `position` `rotation` |
| `cylinder` | Cylinder | `radius*` `height*` `position` `direction` |
| `sphere` | Sphere | `radius*` `position` |
| `cone` | Cone / frustum | `radius1*` (bottom) `radius2*` (top) `height*` `position` `direction` |
| `torus` | Torus | `radius1*` (ring) `radius2*` (tube) `position` `direction` |
| `prism` | Regular polygon prism | `sides*` `circumradius*` `height*` `position` `direction` |
| `extrude` | Profile → solid (pad/pocket in a body) | `shapes` or `points`, `height` or `direction`, `plane` `offset` `symmetric`; in a body: `body` `mode` `through_all` `reversed` |
| `revolve` | Profile → solid of revolution (revolution/groove in a body) | `shapes` or `points`, `plane` `axis` `center` `angle`; in a body: `body` `mode` |
| `loft` | Smooth solid through cross-sections (organic shells, bottles, square-to-round) | `sections*` `ruled` `closed`; in a body: `body` `mode` |
| `sweep` | Profile along a path or helix (tubes, handles, springs, threads) | `shapes*`, `path` (+`smooth`, `corner_radius`) or `helix`, `up`; in a body: `body` `mode` |
| `text` | Lettering as a solid, to engrave (cut) or emboss (fuse) | `text*` `size*` `height*` `position` `plane` `align` `angle` `reversed` `font` |
| `body` | PartDesign body: one solid built feature by feature | `name` `position` `rotation` |
| `assembly` | Assembly of parts (links to solids/bodies); first part grounded | `parts*` (`object`, `name`, `position`, `ground`) |
| `joint` | Connect two assembly parts and solve: fixed, revolute, cylindrical, slider, ball, parallel, perpendicular | `assembly*` `type*` `a*` `b*` (`{"part", "face"/"edge"}`) `offset` |
| `hole` | Drilled holes in a body: simple, counterbore, countersink, threaded | `body*` `at*` `offset` `size` (`M2`…`M20`) or `diameter`, `fit` `threaded` `type` `depth` |
| `cut` | Subtract | `base*` `tool` or `tools` |
| `fuse` | Union | `objects*` (≥2) |
| `common` | Intersection | `objects*` (≥2) |
| `fillet` | Round edges | `target*` `radius*` `edges` (selector, default all) |
| `chamfer` | Bevel edges | `target*` `size*` `edges` |
| `shell` | Hollow out, open faces | `target*` `thickness*` `open_faces*` (selector) `outward` |
| `linear_array` | Repeat along a vector | `target*` `count*` `step*` (offset between copies) |
| `grid_array` | Repeat on a grid | `target*` `count_x*` `count_y*` `step_x*` `step_y*` |
| `polar_array` | Repeat around an axis | `target*` `count*` `angle` `axis` `center` |
| `move` | Translate | `target*` `offset*` |
| `rotate` | Rotate about an axis through a point | `target*` `angle*` `axis` `center` |
| `place` | Absolute position/rotation | `target*` `position` `rotation` |
| `mirror` | Mirrored copy (of a solid, or of a feature inside its body) | `target*` `plane` (`XY`/`XZ`/`YZ`) or `normal`, `point` |
| `copy` | Linked copy that follows the original | `target*` `offset` |
| `scale` | Scaled version (about origin) | `target*` `factor*` (number or `[sx, sy, sz]`) |
| `set` | Change properties, recompute downstream | `target*` `properties*` |
| `set_params` | Named parameters (`Params` spreadsheet) | `values*` |
| `delete` | Delete objects | `targets` or `all`, `with_dependents` |
| `rename` | Change label | `target*` `label*` |
| `inspect` | Document tree, or one object in detail | `target` `topology` |
| `check` | Assert geometry | `target*` `expect*` |
| `measure` | Clearance, interference, closest points, mass | `objects` `require` (`min_clearance`, `no_interference`) `material` |
| `import` | Solid from a STEP/IGES/BREP/FCStd file or a closed STL/OBJ/3MF mesh, or a ready-made part from the FreeCAD library | `library` or `file`, `anchor` `position` `rotation` `refine` `name` |
| `material` | Material and/or colour of finished parts (FreeCAD material, GUI colour, renders, masses) | `targets*` `material` `color` `transparency` |
| `fem_static` | Stress analysis: displacement, von Mises stress, safety factor | `target*` `material*` `fixed*` `loads*` `require` `report` `mesh_size` |
| `export` | STEP/IGES/BREP/STL/OBJ/3MF, or a flat DXF/SVG outline (laser/CNC), verified | `filename*` `targets` `tolerance` `view` |
| `drawing` | Technical drawing (DXF): views, verified dimensions, title | `filename*` `sheet` `projection` `scale` `dimensions` `title` `author` `preview` |
| `render` | Shaded PNG views for a visual check | `filename*` `views` (default iso, front, top, right) `size` |

`rotation` is `{"axis": [x, y, z], "angle": deg}`. Full details are in `describe <op>` or
[docs/OPERATIONS.md](docs/OPERATIONS.md). Complete, tested requests to start from are in `{baseDir}/examples/`:
`pd_bracket.json` (PartDesign body, counterbored holes, fillet), `mounting_plate.json`, `gasket.json` (sketch
profile with holes), `enclosure.json`, `flanged_bushing.json`, `l_bracket.json`, `wheel.json` and `table.json`.

### Profiles

`shapes` builds a real, editable FreeCAD sketch from closed shapes. Shapes inside another shape become holes:

```json
{"op": "extrude", "name": "Gasket", "height": 2, "shapes": [
  {"rect": [0, 0, 90, 60], "corner_radius": 8},
  {"slot": [[30, 30], [60, 30]], "radius": 9},
  {"circle": [10, 10], "radius": 3.5},
  {"polygon": [[40, 5], [50, 5], [45, 12]], "corner_radius": 1},
  {"path": [[70, 40], [80, 40], {"arc_to": [80, 50], "center": [80, 45]}, [70, 50]]}
]}
```

- `rect`: `[x_min, y_min, x_max, y_max]`, optional `corner_radius`.
- `circle`: centre plus `radius`.
- `slot`: the centres of its two rounded ends plus `radius`.
- `polygon`: corners plus optional `corner_radius`, or `radii` with one radius per corner.
- `spline`: a smooth closed curve through 3 or more points, e.g. `{"spline": [[58, 0], [40, 22], [0, 30], [-45, 24], [-58, 0], [-45, -24], [0, -30], [40, -22]]}`.
- `path`: a start point, then `[x, y]` (a line to that point),
  `{"arc_to": [x, y], "center": [cx, cy], "clockwise": false}`, or
  `{"spline_to": [x, y], "through": [[x, y], ...], "start_tangent": [dx, dy], "end_tangent": [dx, dy]}`
  (a smooth curve; tangents are optional). The path closes back to its start automatically.

Splines pass exactly through their points but can bulge between them. Use more points where the curve must be
controlled, and a `path` with straight segments for flat sides, e.g. a flat-bottomed dome:
`{"path": [[-30, 0], [30, 0], {"spline_to": [-30, 0], "through": [[20, 25], [0, 32], [-20, 25]], "start_tangent": [0, 1], "end_tangent": [0, -1]}]}`.

Shapes must be separate or fully nested; partial overlaps are rejected. `offset` moves the profile plane
along its normal. To change the outline later, use `set` with `{"shapes": [...]}`. `points` is a shortcut for
a plain polygon.

### Loft and sweep

Use these for organic and curved parts instead of approximating them with booleans of primitives.

```json
{"op": "loft", "name": "Shell", "sections": [
  {"shape": {"rect": [-20, -15, 20, 15], "corner_radius": 4}, "plane": "XY", "offset": 0},
  {"shape": {"circle": [0, 0], "radius": 12}, "plane": "XY", "offset": 30},
  {"shape": {"circle": [0, 0], "radius": 6}, "plane": "XY", "offset": 50}]}
```

- **Loft:**
  - Each section is one closed shape (no holes) in a plane at an `offset`, drawn like an extrude profile.
  - A smooth loft bulges between very different sections; add intermediate sections, or set `ruled: true`.
  - Edit with `set` and `{"sections": [...]}`, keeping the same number of sections.

```json
{"op": "sweep", "name": "Handle", "shapes": [{"circle": [0, 0], "radius": 6}, {"circle": [0, 0], "radius": 4}],
 "path": [[0, 0, 0], [0, 0, 40], [60, 0, 40], [60, 0, 0]], "corner_radius": 12}
```

- **Sweep:**
  - The path is `[x, y, z]` points: straight segments by default, `corner_radius` for bent-tube corners, or
    `smooth: true` for a curve through the points. Alternatively, a `helix`
    (`{"radius", "pitch", "height", "left_handed", "center", "axis"}`).
  - The profile is drawn in 2D around the start of the path. (0, 0) sits on the path, y points `up`
    (default +Z), and x points to the right when looking along the path (outward on a helix). The response
    reports this `profile_frame`.
  - A profile may have holes (a tube).
  - Spring: a circle swept along a helix. Thread: a triangle such as
    `{"polygon": [[-0.1, -1], [1.5, 0], [-0.1, 1]]}` swept along a helix at the core radius, in a body with
    `mode` add (external) or remove (internal).
  - Edit with `set`: `path`, `corner_radius`, `helix`, `up` or `shapes`.
- Both work in a PartDesign body (`body`, `mode`); coordinates are then body coordinates.

### Text

```json
{"op": "text", "name": "Label", "text": "V2.1", "size": 8, "height": 2, "position": [40, 25, 9], "align": "center"},
{"op": "cut", "name": "Engraved", "base": "Plate", "tool": "Label"}
```

- `size` is the height of capital letters; `height` is the depth of the letters. `position` is where the
  `align` point goes (`bottom_left` default, `center`, `top_right`, ...; bottom is the baseline).
- The text lies in `plane` and is extruded along its normal, like `extrude`: XY reads from above and goes
  +Z; XZ reads from the front and goes +Y (into a front face); YZ reads from the right and goes +X (out of a
  right face). `angle` turns it in its plane; `reversed` flips the extrusion.
- **Engrave:** start below the face and pass through it, then `cut`. The example engraves 1 mm into a 10 mm
  plate: z from 9 to 11. **Emboss:** start just inside the face (z = 9.9 for a top face at 10) and `fuse`.
- The default font is FreeCAD's bundled osifont; `font` takes a `.ttf`/`.otf` file in the workspace.
- Edit with `set`: `text`, `size`, `font`, `align`, `height`.

### Ready-made parts (FreeCAD library)

Don't model standard parts that already exist: bearings, stepper motors, fasteners, aluminium profiles,
electronics boards and more come from the official FreeCAD library (github.com/FreeCAD/FreeCAD-library).

```bash
python3 {baseDir}/scripts/fcskill.py library 608 bearing
```

The command returns `matches` with a `part` path and its formats. Import one:

```json
{"op": "import", "library": "Mechanical Parts/Bearings/608ZZ_Ball_Bearing", "name": "Bearing",
 "anchor": "center", "position": [20, 20, 7.5]}
```

- **Placement:** library parts keep their author's orientation. Check the reported `bbox`, use `anchor`
  (`center`, `bottom_center`, `min_corner`) and `rotation`, then cut seats or holes to fit.
- **Shape:** the result is a fixed solid. It can be placed, cut, fused, measured, given a material and added
  to an assembly, but its dimensions can't be edited.
- **Licence:** parts are CC-BY 3.0. Tell the user the `attribution` from the response when you hand over the
  model.
- **Network:** search and first use need network access to GitHub (parts are then cached in the workspace).
  Only anonymous downloads from the FreeCAD library repository are made; nothing about the user or the model
  is sent. With `FCSKILL_OFFLINE=1`, or without network, the command returns `LIBRARY_UNAVAILABLE`.
- **Files:** `{"op": "import", "file": "vendor/motor.step"}` imports any STEP/IGES/BREP/FCStd file in the
  workspace, e.g. a manufacturer's model.
- **Meshes (STL, OBJ, 3MF, PLY, OFF):** `{"op": "import", "file": "scan.stl"}` turns a closed mesh into a solid
  you can cut, fuse, measure and export (e.g. "add a hole to this STL").
  - The solid is made of the mesh's flat triangles. Coplanar ones are merged (`refine`), but curved surfaces
    stay faceted, so fillets on its edges and FEM are unreliable.
  - Open, non-manifold or self-intersecting meshes are refused with `GEOMETRY_INVALID`: ask the user to repair
    the mesh (or for a STEP file). The limit is 20,000 triangles, and booleans on meshes are slow (about
    a minute at the limit): prefer a STEP file when the user has one.
  - Mesh files carry no units. Check the reported `bbox`; `CHECK_UNITS` warns when the size looks like inches
    or metres, which you fix with `scale` (25.4 or 1000).

### PartDesign bodies

A body is one solid built feature by feature: the way FreeCAD users model mechanical parts, and the most
editable kind of model. Prefer a body for a single part, and stand-alone solids plus booleans for quick
shapes or multi-part layouts.

```json
{"op": "body", "name": "Bracket"},
{"op": "extrude", "body": "Bracket", "name": "Base", "height": 8, "shapes": [{"rect": [0, 0, 90, 50], "corner_radius": 6}]},
{"op": "extrude", "body": "Bracket", "name": "Boss", "height": 12, "offset": "=Base.Length", "shapes": [{"circle": [45, 25], "radius": 12}]},
{"op": "extrude", "body": "Bracket", "mode": "remove", "through_all": true, "offset": "=Base.Length + Boss.Length", "shapes": [{"circle": [45, 25], "radius": 6}]},
{"op": "hole", "body": "Bracket", "at": [[10, 10], [80, 10]], "offset": "=Base.Length", "size": "M5", "type": "counterbore"},
{"op": "fillet", "target": "Bracket", "radius": 2, "edges": "%CIRCLE and r=12 and not >Z"}
```

- **Placing features:**
  - Profiles always use body coordinates. `offset` places the profile plane, e.g. on top of `Base`.
  - Use an expression (`"=Base.Length"`) so the feature follows when dimensions change.
- **Directions:**
  - `mode: "add"` (pad) goes along the plane normal: XY→+Z, XZ→+Y, YZ→+X.
  - `mode: "remove"` (pocket) and `hole` go against it, so they cut down into a part from a profile on its top face.
  - For the bottom, back or left faces, use `reversed: true`.
  - A feature that misses the part gets a `NO_EFFECT` warning, and a hole that starts in air gets `HOLE_OUTSIDE`.
- **The first feature must add material.** A body stays one solid, so added material must touch the existing part.
- **Dress-ups and patterns:**
  - `fillet`, `chamfer` and `shell` take the **body** as `target` and are added at the end of its feature tree.
  - `linear_array`, `grid_array`, `polar_array` and `mirror` take a **feature** of the body (e.g. a pocket,
    hole or pad) as `target` and repeat it inside the body. A pattern or mirror can't be repeated again:
    name the original feature (one `grid_array` gives a grid).
- **Holes:**
  - `size` uses ISO tables: `fit: "clearance"` (default) for a screw to pass, `"tap"` for a tap drill.
  - `threaded: true` (with `size`, type `simple`) models a real ISO metric thread over the hole depth. Give
    `depth` for a blind hole. Prefer a plain hole for small printed threads (below about M5).
  - Counterbores fit ISO 4762 socket heads; countersinks fit ISO 10642 (90°).
- **Editing:**
  - Use `set` on a feature for native properties (`Length`, `Diameter`, ...), or for `shapes`, `offset` and `at` (holes).
  - Fillet and chamfer selectors are re-evaluated after every edit.
  - Move the whole part by moving the body; features have no placement of their own.
- **Combining with other solids:** a body can be used like any solid in `cut`, `fuse`, `mirror`, `copy` and `export`.

### Assemblies

```json
{"op": "assembly", "name": "Hinge", "parts": [{"object": "Plate"}, {"object": "Pin"}]},
{"op": "joint", "assembly": "Hinge", "type": "revolute", "offset": -10,
 "a": {"part": "Plate", "edge": "%CIRCLE and >Z"}, "b": {"part": "Pin", "edge": "%CIRCLE and <Z"}}
```

- **Parts:**
  - Parts are links to existing solids or bodies. Editing the original updates every instance; add the same
    object twice under different `name`s.
  - The first part is grounded (fixed in place) unless you set `ground`.
  - The assembly is the result: export or render the assembly itself. `measure` on the assembly compares its
    parts as assembled (or name single parts by their link, e.g. `Pin_Part`).
- **Joints:**
  - Each side gives a part and **exactly one** face or edge.
  - A face gives a frame at its centre, along its normal; a circular edge gives its centre and axis.
  - Part `b` moves to meet part `a`.
  - `offset` is the distance of `b` from `a`'s surface: positive moves it away, negative sinks it into the
    material (e.g. a pin into a hole).
  - Typical uses: a block on a plate is `fixed` face to face; a pin in a hole is `revolute` on circular
    edges; a shaft that also slides is `cylindrical`.
  - The two elements are placed on each other, so the choice of edges sets the layers. A hole's top edge on
    another part's top edge sinks it into that part; the top edge of `a`'s hole with the bottom edge of `b`'s
    hole stacks `b` on `a`; `offset` adds a gap (a washer).
  - Linkages: links in one plane overlap at every joint (`INTERFERENCE`), as they would in reality. Stack
    each link on the one it hinges on, e.g. crank on the ground plate, coupler on the crank, and the rocker
    under the coupler and on its own pivot.
  - Closed loops (four-bar, crank-slider) work: set `ground` on every fixed part and add the joints in
    order, the last one closing the loop. To get a particular pose (e.g. which way the crank points), give the
    moving parts an approximate `position`/`rotation` in `assembly`. A loop whose lengths can't close fails.
  - Selector extremes (`<X`, `>X`) are taken over all edges, so on a link with rounded ends they pick the end
    arc, not the hole: there, give hole edges by index (`inspect` with `topology: true`).
- **Checks:**
  - Every joint is verified after solving, so a joint that can't be satisfied, e.g. a conflicting one,
    fails the request.
  - Overlapping parts are reported as `INTERFERENCE` warnings with their overlap volume. Check them with
    `measure` too. Parts not joined yet are listed in `not_joined` and left out of that check.
- **After edits:** joints are re-resolved and the assembly re-solved after every edit, so parts follow
  dimension changes.

### Edge and face selectors

`edges` (fillet/chamfer) and `open_faces` (shell) accept `"all"`, 1-based indices `[1, 3]`, or an expression:

| Selector | Meaning |
|---|---|
| `>Z` / `<Z` | elements whose centre is highest / lowest in Z (same for X, Y) |
| `\|Z` | straight edges parallel to Z; planar faces whose normal is parallel to Z |
| `#Z` | straight edges / face normals perpendicular to Z |
| `+Z` / `-Z` | planar faces facing +Z / -Z |
| `%LINE` `%CIRCLE` `%PLANE` `%CYLINDER` | geometry type |
| `r<5` `r=3` `r>2` | radius of circular edges / cylindrical faces |
| `face(>Z)` | edges bounding the selected faces (e.g. all top edges) |
| `and` `or` `not` `( )` | combine |

Examples: vertical corners of a plate `"|Z and %LINE"`, top outline `"face(>Z)"`, hole edges `"%CIRCLE and r<4"`,
open top of a box `">Z"`. Prefer selectors to indices. They are re-evaluated when upstream dimensions change,
while indices can point at different edges after an edit. Use `inspect` with `"topology": true` to see faces and
edges with their type, centre, normal, direction and radius.

## Workflow

1. **Plan** the part as solids, profiles, booleans, then features: fillets and chamfers last, after the cuts
   they should round.
2. **Parametrise** dimensions the user may change: `{"op": "set_params", "values": {"wall": 2}}`, then use
   `"height": "=Params.wall * 3"`. Expressions can also reference other objects: `"=Plate.Length - 10"`.
   Parameter names must not be unit symbols or constants: `h`, `l`, `t`, `s`, `g`, `e`, `W`, `H`, `mm`, `in`,
   `deg` and similar are rejected (`L` happens to be allowed). Use descriptive names such as `height`,
   `length`, `thickness` or `wall`; the error suggests one.
3. **Send one request per coherent change**, with `expect` on the steps that matter (`volume`, `bbox_size`,
   `bbox_min`, `bbox_max`, `solids`). An expectation that doesn't hold is an error, so mistakes never slip
   through as a success.
4. **Read the response:** per-step `bbox`/`volume`, `results`, `warnings`.
5. **Modify existing models in place** rather than rebuilding them:
   `{"doc": "bracket.FCStd", "steps": [{"op": "set_params", "values": {"wall": 3}}]}` or
   `{"op": "set", "target": "Plate", "properties": {"Length": 120}}`. For an unfamiliar document, start with
   `{"doc": "x.FCStd", "op": "inspect"}`, then `inspect` the objects you need. Their `properties` are exactly
   what `set` accepts.
6. **Check fits between parts** with `measure`, e.g.
   `{"op": "measure", "objects": ["Lid", "Box"], "require": {"min_clearance": 0.3}}`. It fails if any gap is
   smaller, and `closest` gives the points where the gap is smallest. Each pair is reported as `clear`,
   `touching` or `interfering` (with the overlap volume). With a `material`, it also gives each part's mass.
7. **Check strength** with `fem_static` when the user cares whether a part will hold:
   ```json
   {"op": "fem_static", "target": "Bracket", "material": "aluminium_6061_t6", "fixed": "<X",
    "loads": [{"faces": ">X", "force": "200 N", "direction": [0, 0, -1]}],
    "require": {"min_safety_factor": 2}, "report": "stress.png"}
   ```
   - **Inputs:**
     - Loads need units (`"500 N"`, `"2 kN"`, `"0.5 MPa"`).
     - A force is the total over the selected faces; a pressure pushes into the faces.
   - **Results:**
     - Max displacement (mm) and max von Mises stress (MPa), each with its location.
     - Safety factor against yield, and a stress-map PNG.
     - Always check `equilibrium_error`, which should be near 0, and `convergence`.
     - `checks` says whether each check `passed`, `failed` or was `unavailable`/`skipped`. A failed
       equilibrium check is an error. A failed convergence check comes with a `NOT_CONVERGED` or
       `STRESS_CONCENTRATION` warning (below). `NO_EQUILIBRIUM_CHECK` or `NO_CONVERGENCE_CHECK` warnings mean
       the result is unverified. In all these cases, say so to the user.
   - **Warnings:**
     - `STRESS_CONCENTRATION` means the peak sits at a sharp inner corner, where FEM stress is unreliable
       and keeps rising with mesh refinement. Add a fillet there and re-run.
     - `NOT_CONVERGED` means the mesh needs a smaller `mesh_size`.
   - **Limits:**
     - This is a linear estimate (no contact, small deformations).
     - Printed plastics are weaker between layers, so treat their safety factors with extra margin, and tell
       the user it is not a certified calculation.
     - It takes seconds to a minute.
8. **Look at it.** Numbers can't show a hole on the wrong face. Add `{"op": "render", "filename": "preview.png"}`
   and view the PNG if you can read images.
   - It shows a 2×2 grid: iso, front (looking along +Y), top (looking down), right (looking along -X).
   - Each view has an axis triad: X red, Y green, Z blue.
   - `mm_per_pixel` in the result lets you estimate sizes.
9. **Drawings and cutting files:**
   - For laser, waterjet or CNC cutting, use `{"op": "export", "filename": "plate.dxf"}`: a 1:1 outline in mm,
     viewed from `top` by default.
   - For a dimensioned workshop drawing, use `{"op": "drawing", "filename": "part.dxf", "title": "...", "preview": "part.png"}`.
     It places front, plan and side views (ISO first angle by default) at a standard scale. Its overall and hole
     dimensions are checked against the model, and the `dimensions` list in the result gives their values.
   - Re-run `drawing` after editing the model; it regenerates the page.
   - PDF and SVG pages need the FreeCAD GUI: the page is kept in the `.FCStd`.
10. **Give finished parts a material** so they look right when opened in FreeCAD and in renders, and so
    `measure` reports masses: `{"op": "material", "targets": ["Rim"], "material": "aluminium"}`,
    `{"op": "material", "targets": ["Tire"], "material": "rubber"}`, or a colour for prints:
    `{"op": "material", "targets": ["Case"], "material": "pla", "color": "#E03020"}`. Presets: steel,
    stainless_steel, cast_iron, aluminium (+ _6061, _7075), titanium, copper, brass, bronze, gold, silver, chrome,
    pla, abs, petg, nylon, pom, polypropylene, polycarbonate, acrylic, ptfe, pvc, rubber, glass, wood, concrete;
    or any FreeCAD library material name. Materials of assembly parts go to their source objects.
11. **Export** at the end. Each export is read back and verified; mesh exports report `closed` and `non_manifold`.

## Fixing errors

| `error.code` | What to do |
|---|---|
| `INVALID_REQUEST` | Fix every item in `details.problems` (each names its `step` and `param`) and resend. |
| `OBJECT_NOT_FOUND` | Use a name from `details.available`. Names are case-sensitive. |
| `NAME_CONFLICT` | Choose a new name, or edit the existing object with `set`. |
| `RECOMPUTE_FAILED` / `GEOMETRY_INVALID` | Read `hint` and `details.freecad_message`. Typical causes: fillet radius too large (hint gives the shortest edge), coincident boolean faces, self-intersecting profile. |
| `EMPTY_RESULT` | The cut removed everything, or the objects of a `common` don't overlap. Check positions. |
| `EXPECTATION_FAILED` | Compare `details.failures` (expected vs actual) to find the wrong dimension or position. |
| `INVALID_SELECTOR` | The selector matched nothing. `inspect` the base with `topology: true`. |
| `DEPENDENCY` | Delete the dependents first, or pass `with_dependents: true`. |
| `PATH_NOT_ALLOWED` | Use a path inside the workspace. |
| `FREECAD_NOT_FOUND` / `FREECAD_VERSION` / `FREECAD_CRASHED` / `TIMEOUT` | Environment problem (FreeCAD missing, older than 1.1, or crashed): run `doctor` and tell the user. |
| `DOCUMENT_BUSY` | Another request is editing the same document. Wait for it, then retry. |

Don't resend an unchanged request after an error. Change what the error points at.

## Limits

- Profiles have no Sketcher dimensional constraints; edit them by resending `shapes`.
- Assemblies: no nested assemblies, no motion (gear, belt, screw) joints, and no limits. FEM is linear static only (no contact, buckling, thermal or modal analysis). Drawings are DXF only (PDF/SVG from the GUI); automatic dimensions
  are the overall sizes and circle diameters only. PartDesign supports pad, pocket, revolution, groove, hole,
  fillet, chamfer, shell, loft, sweep, mirror and linear/grid/polar patterns. No surface modelling (free-form
  patches, blends between arbitrary faces). Imported meshes stay faceted.
- If a request needs something these operations can't do, tell the user it isn't supported. Don't work around
  the skill with your own FreeCAD scripts: they skip validation and checks.
- Placement (`position`) values are literal numbers; expressions apply to dimensions.

## Compatibility

Version 2 has breaking changes: v1 requests (`{"operation": ..., "parameters": ...}`) and
`scripts/cad_engine.py` are no longer supported. Since 2.0.2 there is no `python` op: requests use only the
operations above. Use only the format described here.
