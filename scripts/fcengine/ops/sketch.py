"""Build real Sketcher sketches from profile shapes (see ``profiles``)."""

from __future__ import annotations

from typing import Any, Dict, List

import FreeCAD as App

from .. import errors, profiles
from ..document import Context
from ..errors import SkillError

# Plane -> (local X image, local Y image, our extrusion normal)
PLANES = {
    "XY": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "XZ": ((1, 0, 0), (0, 0, 1), (0, 1, 0)),
    "YZ": ((0, 1, 0), (0, 0, 1), (1, 0, 0)),
}
SHAPES_PROP = "FCSkillShapes"


def plane_placement(plane: str, offset: float) -> Any:
    a, b, n = PLANES[plane]
    c = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])  # a x b
    m = App.Matrix(
        a[0], b[0], c[0], n[0] * offset, a[1], b[1], c[1], n[1] * offset, a[2], b[2], c[2], n[2] * offset, 0, 0, 0, 1
    )
    return App.Placement(m)


def normal_of(plane: str) -> Any:
    return App.Vector(*PLANES[plane][2])


def _dist(a: Any, b: Any) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _geom(seg: Any) -> Any:
    import Part

    V = App.Vector
    if seg[0] == "line":
        return Part.LineSegment(V(*seg[1], 0), V(*seg[2], 0))
    if seg[0] == "arc":
        return Part.Arc(V(*seg[1], 0), V(*seg[2], 0), V(*seg[3], 0))
    if seg[0] == "spline":
        _, pts, periodic, t0, t1 = seg
        curve = Part.BSplineCurve()
        if t0 or t1:
            # OCC needs both tangents; a missing one follows the chord at that end. Unit tangents with
            # Scale=False match the chord-length parameterisation; the default Scale=True bends a
            # symmetric input into an asymmetric curve (probed on FreeCAD 1.1).
            a = V(*t0, 0) if t0 else V(*pts[1], 0) - V(*pts[0], 0)
            b = V(*t1, 0) if t1 else V(*pts[-1], 0) - V(*pts[-2], 0)
            curve.interpolate(
                Points=[V(*q, 0) for q in pts], InitialTangent=a.normalize(), FinalTangent=b.normalize(), Scale=False
            )
        elif periodic:
            params, ders = profiles.closed_spline_derivatives(pts)
            curve.interpolate(
                Points=[V(*q, 0) for q in pts],
                PeriodicFlag=True,
                Parameters=params + [params[-1] + _dist(pts[-1], pts[0])],
                Tangents=[V(*t, 0) for t in ders],
                TangentFlags=[True] * len(pts),
                Scale=False,
            )
        else:
            curve.interpolate(Points=[V(*q, 0) for q in pts])
        return curve
    return Part.Circle(V(*seg[1], 0), V(0, 0, 1), seg[2])


def _loop_face(loop: List[Any]) -> Any:
    import Part

    edges = [_geom(s).toShape() for s in loop]
    return Part.Face(Part.Wire(edges))


def _check_overlaps(loops: List[List[Any]]) -> None:
    faces = []
    for i, loop in enumerate(loops):
        try:
            f = _loop_face(loop)
        except Exception:
            raise SkillError(errors.INVALID_PARAM, f"shapes[{i}] does not form a closed loop") from None
        if not f.isValid() or f.Area < 1e-9:
            raise SkillError(
                errors.INVALID_PARAM,
                f"shapes[{i}] is self-intersecting or has zero area",
                hint="List path points in order around the outline so that no edges cross.",
            )
        faces.append(f)
    for i in range(len(faces)):
        for j in range(i + 1, len(faces)):
            inter = faces[i].common(faces[j]).Area
            smaller = min(faces[i].Area, faces[j].Area)
            if inter > 1e-6 * smaller and abs(inter - smaller) > 1e-6 * smaller:
                raise SkillError(
                    errors.INVALID_PARAM,
                    f"shapes[{i}] and shapes[{j}] partially overlap",
                    hint="Shapes must be disjoint (separate regions) or fully nested (holes). Merge overlapping outlines into one 'path'.",
                )


def fill_sketch(sk: Any, shapes: Any) -> None:
    """(Re)build the geometry of ``sk`` from profile shapes."""
    import Sketcher

    try:
        loops = profiles.all_segments(shapes)
    except profiles.ProfileError as e:
        raise SkillError(errors.INVALID_PARAM, str(e)) from None
    _check_overlaps(loops)
    if sk.GeometryCount:
        sk.deleteAllGeometry()
    for loop in loops:
        ids = [sk.addGeometry(_geom(s), False) for s in loop]
        if loop[0][0] == "circle" or (loop[0][0] == "spline" and loop[0][2]):
            continue  # a single closed curve
        # Coincident constraints keep the outline connected when edited in the GUI.
        for k, seg in enumerate(loop):
            nxt = (k + 1) % len(loop)
            joint = App.Vector(*(seg[1][-1] if seg[0] == "spline" else seg[-1]), 0)
            pk = _pos_at(sk, ids[k], joint)
            pn = _pos_at(sk, ids[nxt], joint)
            if pk and pn:
                sk.addConstraint(Sketcher.Constraint("Coincident", ids[k], pk, ids[nxt], pn))
    setattr_json(sk, shapes)


def _pos_at(sk: Any, gid: int, p: Any) -> int:
    for pos in (1, 2):
        if (sk.getPoint(gid, pos) - p).Length < 1e-6:
            return pos
    return 0


def setattr_json(sk: Any, shapes: Any) -> None:
    import json

    if SHAPES_PROP not in sk.PropertiesList:
        sk.addProperty("App::PropertyString", SHAPES_PROP, "FCSkill", "Profile shapes this sketch was built from")
        sk.setEditorMode(SHAPES_PROP, 2)
    setattr(sk, SHAPES_PROP, json.dumps(shapes))


def make_sketch(ctx: Context, owner_name: str, p: Dict[str, Any]) -> Any:
    sk = ctx.doc.addObject("Sketcher::SketchObject", f"{owner_name}_Sketch")
    sk.Label = sk.Name
    sk.Placement = plane_placement(p.get("plane", "XY"), float(p.get("offset", 0)))
    fill_sketch(sk, p["shapes"])
    sk.recompute()
    if sk.solve() != 0:
        raise SkillError(errors.INTERNAL, f"Sketch {sk.Name} did not solve")
    return sk


def sketch_points(sk: Any) -> List[Any]:
    """Points along the sketch outline, in global coordinates."""
    pts: List[Any] = []
    for e in sk.Shape.Edges:
        pts.extend(e.discretize(24))
    return pts
