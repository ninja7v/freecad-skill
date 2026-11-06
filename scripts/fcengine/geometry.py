"""Geometry measurement, topology descriptors and expectation checks."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import FreeCAD as App

from . import selectors

DIGITS = 4


def num(x: float, digits: int = DIGITS) -> float:
    v = round(float(x), digits)
    return 0.0 if v == 0 else v  # avoid -0.0


def vec(v: Any, digits: int = DIGITS) -> List[float]:
    return [num(v.x, digits), num(v.y, digits), num(v.z, digits)]


def tight_bbox(shape: Any) -> Any:
    """Exact bounding box. Shape.BoundBox can be loose on curved surfaces
    (a 92 mm torus reports ~99.6 mm), which would mislead dimension checks."""
    try:
        return shape.optimalBoundingBox(False, False)
    except Exception:
        return shape.BoundBox


def bbox(shape: Any) -> Optional[Dict[str, List[float]]]:
    if shape is None or shape.isNull():
        return None
    bb = tight_bbox(shape)
    if not bb.isValid():
        return None
    return {
        "min": [num(bb.XMin), num(bb.YMin), num(bb.ZMin)],
        "max": [num(bb.XMax), num(bb.YMax), num(bb.ZMax)],
        "size": [num(bb.XLength), num(bb.YLength), num(bb.ZLength)],
    }


def summary(shape: Any, detailed: bool = False) -> Dict[str, Any]:
    """Compact geometric summary of a shape."""
    if shape is None or shape.isNull():
        return {"empty": True}
    out: Dict[str, Any] = {
        "volume": num(shape.Volume, 3),
        "bbox": bbox(shape),
        "solids": len(shape.Solids),
        "valid": bool(shape.isValid()),
    }
    if detailed:
        out["area"] = num(shape.Area, 3)
        out["faces"] = len(shape.Faces)
        out["edges"] = len(shape.Edges)
        if shape.Solids:
            try:
                out["center_of_mass"] = vec(
                    shape.Solids[0].CenterOfMass if len(shape.Solids) == 1 else _compound_com(shape)
                )
            except Exception:
                pass
    return out


def _compound_com(shape: Any) -> Any:
    total = App.Vector(0, 0, 0)
    vol = 0.0
    for s in shape.Solids:
        total = total + s.CenterOfMass * s.Volume
        vol += s.Volume
    return total * (1.0 / vol) if vol else total


# ------------------------------------------------------------------ descriptors

_SURFACES = {
    "Plane": "plane",
    "Cylinder": "cylinder",
    "Cone": "cone",
    "Sphere": "sphere",
    "Toroid": "torus",
    "BSplineSurface": "bspline",
    "BezierSurface": "bezier",
}
_CURVES = {
    "Line": "line",
    "LineSegment": "line",
    "Circle": "circle",
    "Ellipse": "ellipse",
    "BSplineCurve": "bspline",
    "BezierCurve": "bezier",
}


def _face_desc(i: int, f: Any) -> Dict[str, Any]:
    try:
        s = f.Surface
    except Exception:
        s = None
    t = _SURFACES.get(type(s).__name__, "other") if s is not None else "other"
    d: Dict[str, Any] = {"kind": "face", "index": i, "type": t, "area": num(f.Area, 3), "center": _center(f)}
    try:
        if t == "plane":
            u0, u1, v0, v1 = f.ParameterRange
            d["normal"] = vec(f.normalAt((u0 + u1) / 2, (v0 + v1) / 2), 6)
        elif t in ("cylinder", "cone"):
            d["axis"] = vec(s.Axis, 6)
            if t == "cylinder":
                d["radius"] = num(s.Radius)
        elif t == "sphere":
            d["radius"] = num(s.Radius)
    except Exception:
        pass
    return d


def _center(s: Any) -> List[float]:
    try:
        return vec(s.CenterOfMass)
    except Exception:  # degenerated edges have no mass properties
        pts = [v.Point for v in s.Vertexes]
        if not pts:
            return [0.0, 0.0, 0.0]
        acc = App.Vector(0, 0, 0)
        for p in pts:
            acc = acc + p
        return vec(acc * (1.0 / len(pts)))


def _edge_desc(i: int, e: Any) -> Dict[str, Any]:
    try:
        c = e.Curve
    except Exception:
        # Edges at a sphere's poles are degenerated: FreeCAD raises
        # TypeError ("undefined curve type") instead of returning a curve.
        c = None
    t = _CURVES.get(type(c).__name__, "other") if c is not None else "other"
    d: Dict[str, Any] = {"kind": "edge", "index": i, "type": t, "length": num(e.Length), "center": _center(e)}
    if c is None:
        d["degenerated"] = True
    try:
        if t == "line":
            p0, p1 = e.Vertexes[0].Point, e.Vertexes[-1].Point
            dv = p1 - p0
            if dv.Length > 0:
                d["direction"] = vec(dv.normalize(), 6)
        elif t == "circle":
            d["radius"] = num(c.Radius)
            d["axis"] = vec(c.Axis, 6)
            d["closed"] = bool(e.isClosed())
    except Exception:
        pass
    try:
        if getattr(e, "Degenerated", False):
            d["degenerated"] = True
    except Exception:
        pass
    return d


def describe_faces(shape: Any) -> List[Dict[str, Any]]:
    return [_face_desc(i + 1, f) for i, f in enumerate(shape.Faces)]


def describe_edges(shape: Any) -> List[Dict[str, Any]]:
    return [_edge_desc(i + 1, e) for i, e in enumerate(shape.Edges)]


def edge_face_map(shape: Any) -> Dict[int, List[int]]:
    """1-based edge index -> 1-based indices of faces that contain it."""
    faces = shape.Faces
    out: Dict[int, List[int]] = {}
    for ei, e in enumerate(shape.Edges, start=1):
        out[ei] = [fi for fi, f in enumerate(faces, start=1) if any(e.isSame(fe) for fe in f.Edges)]
    return out


def select_edges(shape: Any, value: Any, filletable: bool = False) -> List[int]:
    """Resolve an edge selector on ``shape``.

    With ``filletable`` the result skips seam and degenerated edges
    (e.g. the seam line of a cylinder), which fillets cannot round.
    """
    edges = describe_edges(shape)
    cache: Dict[str, Dict[int, List[int]]] = {}

    def lazy_map() -> Dict[int, List[int]]:
        if "m" not in cache:
            cache["m"] = edge_face_map(shape)
        return cache["m"]

    picked = selectors.select(value, edges, describe_faces(shape), lazy_map)
    if filletable and not isinstance(value, list) and not isinstance(value, int):
        mapping = lazy_map()
        picked = [i for i in picked if len(mapping.get(i, [])) == 2 and not edges[i - 1].get("degenerated")]
    return picked


def select_faces(shape: Any, value: Any) -> List[int]:
    return selectors.select(value, describe_faces(shape))


# ------------------------------------------------------------------ expectations


def check_expectations(shape: Any, exp: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return a list of failed expectations (empty if all hold)."""
    tol = float(exp.get("tolerance", 0.01))
    vtol = float(exp.get("volume_tolerance", 0.001))
    failures: List[Dict[str, Any]] = []
    if shape is None or shape.isNull():
        return [{"check": "shape", "expected": "non-empty", "actual": "empty"}]
    if "volume" in exp:
        want = float(exp["volume"])
        got = shape.Volume
        if abs(got - want) > vtol * max(abs(want), 1e-9) + 1e-6:
            failures.append({"check": "volume", "expected": want, "actual": num(got, 3)})
    bb = tight_bbox(shape)
    for key, actual in (
        ("bbox_size", [bb.XLength, bb.YLength, bb.ZLength]),
        ("bbox_min", [bb.XMin, bb.YMin, bb.ZMin]),
        ("bbox_max", [bb.XMax, bb.YMax, bb.ZMax]),
    ):
        if key in exp:
            want_v: Sequence[float] = exp[key]
            if any(abs(a - w) > tol for a, w in zip(actual, want_v)):
                failures.append({"check": key, "expected": list(want_v), "actual": [num(a) for a in actual]})
    if "solids" in exp and len(shape.Solids) != exp["solids"]:
        failures.append({"check": "solids", "expected": exp["solids"], "actual": len(shape.Solids)})
    if "valid" in exp and bool(shape.isValid()) != exp["valid"]:
        failures.append({"check": "valid", "expected": exp["valid"], "actual": bool(shape.isValid())})
    return failures


def rotation_to(direction: Sequence[float]) -> Any:
    """Rotation taking +Z onto ``direction``."""
    return App.Rotation(App.Vector(0, 0, 1), App.Vector(*direction))


def newell_normal(points: Sequence[Any]) -> Any:
    n = App.Vector(0, 0, 0)
    for i, p in enumerate(points):
        q = points[(i + 1) % len(points)]
        n.x += (p.y - q.y) * (p.z + q.z)
        n.y += (p.z - q.z) * (p.x + q.x)
        n.z += (p.x - q.x) * (p.y + q.y)
    return n


def is_part_shape(obj: Any) -> bool:
    if obj.TypeId == "Assembly::AssemblyObject":
        return True  # its Shape is the compound of its placed parts
    return obj.isDerivedFrom("Part::Feature") and hasattr(obj, "Shape")
