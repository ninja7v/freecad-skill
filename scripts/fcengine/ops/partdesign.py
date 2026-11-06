"""PartDesign: bodies and sketch-based features (pad, pocket, revolution, groove, hole).

Design choices (probed on FreeCAD 1.1):

- Sketches are always attached to the body's XY origin plane, with an
  AttachmentOffset that maps the requested plane. Profile coordinates are
  therefore body coordinates. Sketches attached to faces use the face's own
  axes (agents place features in the wrong spot) and break when the face's
  topology changes.
- 'offset' can be an expression ('=Base.Length') so a feature stays on the face
  it was placed on when dimensions change.
- Arbitrary axes (revolve, patterns) use deactivated PartDesign::Line datums.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import FreeCAD as App

from .. import errors, fasteners, geometry
from ..document import Context
from ..errors import SkillError
from .sketch import fill_sketch, normal_of, plane_placement, sketch_points

OFFSET_AXIS = {"XY": "z", "XZ": "y", "YZ": "x"}
# Pads follow the sketch normal; for XZ the sketch normal is -Y while the skill's
# convention is +Y, so XZ features are reversed (probed).
FLIP = {"XY": False, "XZ": True, "YZ": False}


def get_body(ctx: Context, ref: str) -> Any:
    obj = ctx.get(ref, need_shape=False)
    if obj.TypeId != "PartDesign::Body":
        body = obj.getParentGeoFeatureGroup() if hasattr(obj, "getParentGeoFeatureGroup") else None
        hint = (
            f"'{ref}' is a feature of body '{body.Name}'; give the body."
            if body is not None and body.TypeId == "PartDesign::Body"
            else 'Create one with {"op": "body", "name": ...}.'
        )
        raise SkillError(errors.INVALID_PARAM, f"'{ref}' is not a PartDesign body ({obj.TypeId})", hint=hint)
    return obj


def body_of(obj: Any) -> Optional[Any]:
    parent = obj.getParentGeoFeatureGroup() if hasattr(obj, "getParentGeoFeatureGroup") else None
    return parent if parent is not None and parent.TypeId == "PartDesign::Body" else None


def _volume(body: Any) -> float:
    s = body.Shape
    return 0.0 if s.isNull() else s.Volume


def _origin(body: Any, role: str) -> Any:
    for f in body.Origin.OriginFeatures:
        if getattr(f, "Role", "") == role:
            return f
    raise SkillError(errors.INTERNAL, f"Body {body.Name} has no {role}")


def make_sketch(ctx: Context, body: Any, owner: str, p: Dict[str, Any], shapes: Any, suffix: str = "Sketch") -> Any:
    """Sketch on the body's XY plane, offset/rotated onto the requested plane."""
    plane = p.get("plane", "XY")
    off = p.get("offset", 0)
    sk = ctx.doc.addObject("Sketcher::SketchObject", f"{owner}_{suffix}")
    sk.Label = sk.Name
    body.addObject(sk)
    sk.AttachmentSupport = [(_origin(body, "XY_Plane"), "")]
    sk.MapMode = "FlatFace"
    sk.AttachmentOffset = plane_placement(plane, 0 if isinstance(off, str) else float(off))
    if isinstance(off, str):
        ctx.assign(sk, f".AttachmentOffset.Base.{OFFSET_AXIS[plane]}", off)
    fill_sketch(sk, shapes)
    return sk


def make_axis(ctx: Context, body: Any, owner: str, axis: List[float], center: List[float]) -> Any:
    dl = ctx.doc.addObject("PartDesign::Line", f"{owner}_Axis")
    dl.Label = dl.Name
    body.addObject(dl)
    dl.MapMode = "Deactivated"
    dl.Placement = App.Placement(App.Vector(*center), App.Rotation(App.Vector(0, 0, 1), App.Vector(*axis)))
    return dl


def finish(ctx: Context, body: Any, obj: Any, before: float, remove: Optional[bool]) -> Any:
    """Recompute and verify a body after a feature. remove=None: any change counts (fillets can add material)."""
    if body.Tip != obj:
        body.Tip = obj  # addObject does not always advance the tip (e.g. for patterns)
    ctx.recompute()
    shape = body.Shape
    if shape.isNull() or not shape.Solids:
        raise SkillError(
            errors.EMPTY_RESULT,
            f"'{obj.Name}' left body '{body.Name}' without a solid",
            hint="A first feature must add material (a pad or revolution).",
        )
    if len(shape.Solids) > 1:
        raise SkillError(
            errors.GEOMETRY_INVALID,
            f"'{obj.Name}' split body '{body.Name}' into {len(shape.Solids)} solids",
            hint="A body is one solid: added material must touch the existing part. Use a separate body for separate parts.",
        )
    if not shape.isValid():
        raise SkillError(errors.GEOMETRY_INVALID, f"'{obj.Name}' produced invalid geometry in body '{body.Name}'")
    after = shape.Volume
    eps = 1e-6 * max(before, 1.0)
    if remove is None:
        if abs(after - before) <= eps:
            ctx.warn("NO_EFFECT", f"'{obj.Name}' did not change the part")
    elif remove and before - after <= eps:
        ctx.warn(
            "NO_EFFECT",
            f"'{obj.Name}' removed no material: the profile is outside the part, or the depth/direction "
            "misses it (remove goes against the plane normal; use 'reversed' or check 'offset')",
        )
    elif not remove and after - before <= eps:
        ctx.warn("NO_EFFECT", f"'{obj.Name}' added no material: it lies entirely inside the existing part")
    return obj


# ------------------------------------------------------------------ ops


def body(ctx: Context, p: Dict[str, Any]) -> Any:
    obj = ctx.add("PartDesign::Body", p.get("name"), "Body")
    pos = App.Vector(*p.get("position", [0, 0, 0]))
    rot = (
        App.Rotation(App.Vector(*p["rotation"]["axis"]), p["rotation"]["angle"])
        if p.get("rotation")
        else App.Rotation()
    )
    obj.Placement = App.Placement(pos, rot)
    ctx.recompute()
    return {"object": obj, "data": {"body": obj.Name, "note": "empty until a feature adds material"}}


def _require_material(body: Any, what: str) -> None:
    if body.Tip is None or body.Shape.isNull() or not body.Shape.Solids:
        raise SkillError(
            errors.EMPTY_RESULT,
            f"Body '{body.Name}' has no material to {what} yet",
            hint="A body's first feature must add material: an extrude or revolve with mode 'add'.",
        )


def _shapes(p: Dict[str, Any]) -> Any:
    return p["shapes"] if "shapes" in p else [{"polygon": p["points"]}]


def extrude(ctx: Context, p: Dict[str, Any]) -> Any:
    bd = get_body(ctx, p["body"])
    remove = p.get("mode", "add") == "remove"
    if remove:
        _require_material(bd, "cut")
    before = _volume(bd)
    obj = ctx.add("PartDesign::Pocket" if remove else "PartDesign::Pad", p.get("name"), "Pocket" if remove else "Pad")
    sk = make_sketch(ctx, bd, obj.Name, p, _shapes(p))
    bd.addObject(obj)
    ctx.own_helper(obj, sk)
    obj.Profile = sk
    if remove and p.get("through_all"):
        obj.Type = "ThroughAll"
    else:
        ctx.assign(obj, "Length", p["height"])
    obj.Midplane = bool(p.get("symmetric", False))
    obj.Reversed = FLIP[p.get("plane", "XY")] != bool(p.get("reversed", False))
    return finish(ctx, bd, obj, before, remove)


def revolve(ctx: Context, p: Dict[str, Any]) -> Any:
    from .solids import _check_axis_side

    bd = get_body(ctx, p["body"])
    remove = p.get("mode", "add") == "remove"
    if remove:
        _require_material(bd, "cut")
    before = _volume(bd)
    obj = ctx.add(
        "PartDesign::Groove" if remove else "PartDesign::Revolution",
        p.get("name"),
        "Groove" if remove else "Revolution",
    )
    sk = make_sketch(ctx, bd, obj.Name, p, _shapes(p))
    sk.recompute()
    _check_axis_side(
        sketch_points(sk), App.Vector(*p["axis"]), App.Vector(*p["center"]), normal_of(p.get("plane", "XY"))
    )
    axis = make_axis(ctx, bd, obj.Name, p["axis"], p["center"])
    bd.addObject(obj)
    ctx.own_helper(obj, sk)
    ctx.own_helper(obj, axis)
    obj.Profile = sk
    obj.ReferenceAxis = (axis, [""])
    ctx.assign(obj, "Angle", p["angle"])
    return finish(ctx, bd, obj, before, remove)


HOLE_CUT = {"simple": "None", "counterbore": "Counterbore", "countersink": "Countersink"}


def hole(ctx: Context, p: Dict[str, Any]) -> Any:
    bd = get_body(ctx, p["body"])
    _require_material(bd, "drill")
    kind = p.get("type", "simple")
    dims: Dict[str, float] = {}
    if "size" in p:
        dims = fasteners.hole_dimensions(p["size"], p.get("fit", "clearance"), kind)
    diameter = p.get("diameter", dims.get("diameter"))
    cut_d = p.get("cut_diameter", dims.get("cut_diameter"))
    cut_h = p.get("cut_depth", dims.get("cut_depth"))
    before = _volume(bd)
    base_shape = bd.Shape.copy()
    obj = ctx.add("PartDesign::Hole", p.get("name"), "Hole")
    r = float(diameter) / 2 if not isinstance(diameter, str) else 1.0
    sk = make_sketch(ctx, bd, obj.Name, p, [{"circle": pt, "radius": r} for pt in p["at"]])
    bd.addObject(obj)
    ctx.own_helper(obj, sk)
    obj.Profile = sk
    obj.Threaded = False
    ctx.assign(obj, "Diameter", diameter)
    if "depth" in p:
        obj.DepthType = "Dimension"
        ctx.assign(obj, "Depth", p["depth"])
    else:
        obj.DepthType = "ThroughAll"
    obj.DrillPoint = "Flat"
    obj.HoleCutType = HOLE_CUT[kind]
    if kind != "simple":
        obj.HoleCutDiameter = float(cut_d)
        if kind == "counterbore":
            obj.HoleCutDepth = float(cut_h)
        else:
            obj.HoleCutCountersinkAngle = 90
    plane = p.get("plane", "XY")
    obj.Reversed = FLIP[plane] != bool(p.get("reversed", False))
    ctx.recompute()
    # Each hole must start on material: probe just past the start plane, in the drilling direction.
    n = normal_of(plane)
    drill = n * (1.0 if p.get("reversed") else -1.0)
    place = sk.getGlobalPlacement()
    outside = []
    for pt in p["at"]:
        start = place.multVec(App.Vector(pt[0], pt[1], 0))
        if not base_shape.isInside(start + drill * 0.05, 1e-6, True):
            outside.append(pt)
    if outside:
        ctx.warn(
            "HOLE_OUTSIDE",
            f"{len(outside)} hole(s) start in empty space: {outside}. Check 'at', 'offset' (the face the "
            "hole starts on) and the drilling direction (against the plane normal unless 'reversed')",
        )
    obj = finish(ctx, bd, obj, before, True)
    return {
        "object": obj,
        "data": {
            "holes": len(p["at"]),
            "diameter": geometry.num(obj.Diameter.Value),
            "type": kind,
            **({"cut_diameter": cut_d} if kind != "simple" else {}),
            **({"cut_depth": cut_h} if kind == "counterbore" else {}),
        },
    }


# ------------------------------------------------------------------ patterns of features


def pattern(ctx: Context, p: Dict[str, Any], kind: str, target: Any) -> Any:
    bd = body_of(target)
    if bd is None:
        raise SkillError(errors.INTERNAL, "pattern target is not in a body")
    if kind == "grid":
        raise SkillError(
            errors.UNSUPPORTED,
            "grid_array of a PartDesign feature is not supported",
            hint="For holes, give several points in one 'hole' op ('at'); otherwise use two linear_array steps on separate features.",
        )
    before = _volume(bd)
    if kind == "linear":
        obj = ctx.add("PartDesign::LinearPattern", p.get("name"), "LinearPattern")
        step = App.Vector(*p["step"])
        axis = make_axis(ctx, bd, obj.Name, list(step), [0, 0, 0])
        bd.addObject(obj)
        obj.Originals = [target]
        obj.Direction = (axis, [""])
        obj.Length = step.Length * (p["count"] - 1)
        obj.Occurrences = p["count"]
    else:
        obj = ctx.add("PartDesign::PolarPattern", p.get("name"), "PolarPattern")
        axis = make_axis(ctx, bd, obj.Name, p["axis"], p["center"])
        bd.addObject(obj)
        obj.Originals = [target]
        obj.Axis = (axis, [""])
        obj.Angle = p["angle"]
        obj.Occurrences = p["count"]
    ctx.own_helper(obj, axis)
    remove = target.TypeId in ("PartDesign::Pocket", "PartDesign::Hole", "PartDesign::Groove")
    return finish(ctx, bd, obj, before, remove)


HANDLERS = {"body": body, "hole": hole}
