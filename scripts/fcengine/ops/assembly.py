"""Assemblies (native Assembly workbench, FreeCAD 1.0+): parts as links, joints, solve, verify.

Probed on FreeCAD 1.1 headless:
- Assembly::AssemblyObject + App::Link parts + JointObject joints solve headless.
- Joint references are topological ('Edge10'): after an upstream edit they break
  ("Broken link in: Reference1") and solve() still returns 0. So joints store
  selectors, re-resolved after every edit (like fillets), and every joint is
  verified geometrically after solving instead of trusting the solver.
- Global joint frame = part placement * joint Placement1/2 (offsets are already
  included in Placement1). FreeCAD may flip a frame so the two face each other,
  so "aligned" means collinear axes (|dot| = 1), and Offset1 acts along the
  possibly flipped frame: the skill's 'offset' is converted to "away from side a".
"""

from __future__ import annotations

import json
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple

import FreeCAD as App

from .. import errors, geometry
from ..document import Context
from ..errors import SkillError

JOINT_TYPES = ("fixed", "revolute", "cylindrical", "slider", "ball", "parallel", "perpendicular")
JOINT_PROP = "FCSkillJoint"
TOL_POS, TOL_DOT = 1e-3, 1e-4


def _is_assembly(obj: Any) -> bool:
    return obj is not None and obj.TypeId == "Assembly::AssemblyObject"


def get_assembly(ctx: Context, ref: str) -> Any:
    obj = ctx.get(ref, need_shape=False)
    if not _is_assembly(obj):
        raise SkillError(
            errors.INVALID_PARAM,
            f"'{ref}' is not an assembly ({obj.TypeId})",
            hint='Create one with {"op": "assembly", "name": ..., "parts": [...]}.',
        )
    return obj


def _joint_group(asm: Any) -> Any:
    for o in asm.Group:
        if o.TypeId == "Assembly::JointGroup":
            return o
    return asm.newObject("Assembly::JointGroup", f"{asm.Name}_Joints")


def parts_of(asm: Any) -> List[Any]:
    return [o for o in asm.Group if o.TypeId == "App::Link"]


def _part(ctx: Context, asm: Any, ref: str) -> Any:
    """A part of the assembly, by link name or by the name of the linked object."""
    for link in parts_of(asm):
        if link.Name == ref or link.Label == ref or (link.LinkedObject is not None and link.LinkedObject.Name == ref):
            return link
    raise SkillError(
        errors.OBJECT_NOT_FOUND,
        f"'{ref}' is not a part of assembly '{asm.Name}'",
        details={"parts": [link.Name for link in parts_of(asm)]},
    )


# ------------------------------------------------------------------ assembly op


def assembly(ctx: Context, p: Dict[str, Any]) -> Any:
    import JointObject

    asm = ctx.add("Assembly::AssemblyObject", p.get("name"), "Assembly")
    jg = asm.newObject("Assembly::JointGroup", f"{asm.Name}_Joints")
    links = []
    for spec in p["parts"]:
        src = ctx.get(spec["object"])
        if _is_assembly(src):
            raise SkillError(errors.UNSUPPORTED, "Nested assemblies are not supported", hint="Add the parts directly.")
        name = spec.get("name") or f"{src.Name}_Part"
        if ctx.doc.getObject(name) is not None:
            raise SkillError(
                errors.NAME_CONFLICT, f"An object named '{name}' already exists", hint="Give the part a 'name'."
            )
        link = asm.newObject("App::Link", name)
        link.Label = link.Name
        link.LinkedObject = src
        if spec.get("position") or spec.get("rotation"):
            rot = spec.get("rotation")
            link.Placement = App.Placement(
                App.Vector(*(spec.get("position") or [0, 0, 0])),
                App.Rotation(App.Vector(*rot["axis"]), rot["angle"]) if rot else App.Rotation(),
            )
        links.append(link)
    grounded = [link for link, spec in zip(links, p["parts"]) if spec.get("ground")] or links[:1]
    for link in grounded:
        g = jg.newObject("App::FeaturePython", f"{link.Name}_Ground")
        JointObject.GroundedJoint(g, link)
    ctx.recompute()
    return {
        "object": asm,
        "data": {
            "parts": [link.Name for link in links],
            "grounded": [link.Name for link in grounded],
            "interferences": interferences(asm),
        },
    }


# ------------------------------------------------------------------ joints


def _element(ctx: Context, asm: Any, side: Dict[str, Any], label: str) -> Tuple[Any, str]:
    link = _part(ctx, asm, side["part"])
    shape = link.LinkedObject.Shape  # topological indices are those of the linked object
    kinds = [k for k in ("face", "edge") if k in side]
    kind = kinds[0]
    if kind == "face":
        idx = geometry.select_faces(shape, side["face"])
        prefix = "Face"
    else:
        idx = geometry.select_edges(shape, side["edge"])
        prefix = "Edge"
    if len(idx) != 1:
        raise SkillError(
            errors.INVALID_SELECTOR,
            f"{label}: {kind} selector {side[kind]!r} on '{link.Name}' matches {len(idx)} {kind}s; a joint needs exactly one",
            hint=f"Refine the selector (e.g. add 'and >Z'); inspect '{link.LinkedObject.Name}' with topology=true.",
            details={"matches": idx[:20]},
        )
    return link, f"{prefix}{idx[0]}"


def placed_shape(link: Any) -> Any:
    """Shape of an assembly part in assembly coordinates. (link.Shape can be stale or
    unplaced right after solving; Part.getShape applies the link placement.)"""
    import Part

    return Part.getShape(link)


def _outward(link: Any, element: str) -> Any:
    """Direction pointing away from the material of ``link`` at ``element`` (global).

    Faces: the outward normal. Circular edges: the outward normal of a planar face bounded by
    the edge (a hole rim -> the top face; a pin's end -> its end face). Probing around the
    circle's centre would fail for holes, whose centre lies in empty space.
    """
    shape = placed_shape(link)
    sub = shape.getElement(element)
    if element.startswith("Face"):
        u0, u1, v0, v1 = sub.ParameterRange
        return sub.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
    for f in shape.Faces:
        if type(f.Surface).__name__ == "Plane" and any(sub.isSame(e) for e in f.Edges):
            u0, u1, v0, v1 = f.ParameterRange
            return f.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
    c = sub.Curve
    axis = App.Vector(c.Axis)
    point = sub.valueAt(sub.FirstParameter)
    probe = max(1e-3, 1e-3 * shape.BoundBox.DiagonalLength)
    return axis * -1 if shape.isInside(point + axis * probe, 1e-7, True) else axis


def _connect(ctx: Context, joint: Any, asm: Any, spec: Dict[str, Any]) -> None:
    la, ea = _element(ctx, asm, spec["a"], "a")
    lb, eb = _element(ctx, asm, spec["b"], "b")
    if la is lb:
        raise SkillError(errors.INVALID_PARAM, "A joint connects two different parts")
    joint.Offset1 = App.Placement()
    joint.Proxy.setJointConnectors(joint, [[la, [ea, ea]], [lb, [eb, eb]]])
    off = float(spec.get("offset") or 0)
    if off:
        # The sign is checked (and flipped if needed) after solving: see _fix_offsets.
        joint.Offset1 = App.Placement(App.Vector(0, 0, off), App.Rotation())


def _gap(joint: Any) -> Optional[float]:
    """Signed distance of side b's element from side a's, along a's outward direction."""
    try:
        la, ea = joint.Reference1[0], joint.Reference1[1][0]
        lb, eb = joint.Reference2[0], joint.Reference2[1][0]
        n = _outward(la, ea)
        return (placed_shape(lb).getElement(eb).CenterOfMass - placed_shape(la).getElement(ea).CenterOfMass).dot(n)
    except Exception:
        return None


def _spec(joint: Any) -> Dict[str, Any]:
    return json.loads(getattr(joint, JOINT_PROP)) if JOINT_PROP in joint.PropertiesList else {}


def _fix_offsets(asm: Any) -> bool:
    """FreeCAD applies Offset1 along a frame it may flip while solving: correct the sign once."""
    changed = False
    for j in _joint_group(asm).Group:
        off = float(_spec(j).get("offset") or 0)
        if not off or j.FCSkillJointType not in (0, 1, 2, 3):
            continue
        gap = _gap(j)
        if gap is not None and abs(gap - off) > TOL_POS and abs(gap + off) <= max(TOL_POS, 1e-6 * abs(off)) + TOL_POS:
            j.Offset1 = App.Placement(App.Vector(0, 0, -j.Offset1.Base.z), App.Rotation())
            changed = True
    return changed


def _frames(joint: Any) -> Tuple[Any, Any]:
    a, b = joint.Reference1[0], joint.Reference2[0]
    return a.Placement.multiply(joint.Placement1), b.Placement.multiply(joint.Placement2)


def joint_errors(joint: Any) -> List[str]:
    """Geometric check that a solved joint is actually satisfied."""
    if "Invalid" in joint.State:
        return ["the joint is invalid (a reference is broken)"]
    kind = JOINT_TYPES[int(getattr(joint, "FCSkillJointType", 0))] if hasattr(joint, "FCSkillJointType") else "fixed"
    g1, g2 = _frames(joint)
    z1, z2 = g1.Rotation.multVec(App.Vector(0, 0, 1)), g2.Rotation.multVec(App.Vector(0, 0, 1))
    x1, x2 = g1.Rotation.multVec(App.Vector(1, 0, 0)), g2.Rotation.multVec(App.Vector(1, 0, 0))
    d = g2.Base - g1.Base
    off_axis = (d - z1 * d.dot(z1)).Length
    out = []
    if kind in ("fixed", "revolute", "ball") and d.Length > TOL_POS:
        out.append(f"frames are {d.Length:.4f} mm apart")
    if kind in ("cylindrical", "slider") and off_axis > TOL_POS:
        out.append(f"part is {off_axis:.4f} mm off the joint axis")
    if kind in ("fixed", "revolute", "slider", "cylindrical", "parallel") and abs(z1.dot(z2)) < 1 - TOL_DOT:
        out.append("axes are not aligned")
    if kind in ("fixed", "slider") and abs(x1.dot(x2)) < 1 - TOL_DOT:
        out.append("orientation about the axis differs")
    if kind == "perpendicular" and abs(z1.dot(z2)) > TOL_DOT:
        out.append("axes are not perpendicular")
    off = float(_spec(joint).get("offset") or 0)
    if kind in ("fixed", "revolute", "ball"):
        gap = _gap(joint)
        if gap is not None and abs(gap - off) > max(TOL_POS, 1e-6 * abs(off)) + TOL_POS:
            out.append(f"distance between the two elements is {gap:.4f} mm, expected {off:.4f} mm")
    return out


def interferences(asm: Any) -> List[Dict[str, Any]]:
    out = []
    for a, b in combinations(parts_of(asm), 2):
        sa, sb = placed_shape(a), placed_shape(b)
        if sa.isNull() or sb.isNull() or not sa.BoundBox.intersect(sb.BoundBox):
            continue
        try:
            v = sa.common(sb).Volume
        except Exception:
            continue
        if v > 1e-6:
            out.append({"a": a.Name, "b": b.Name, "overlap_volume": geometry.num(v, 3)})
    return out


def solve(ctx: Context, asm: Any) -> Dict[str, Any]:
    rc = asm.solve()
    ctx.doc.recompute()
    if rc == 0 and _fix_offsets(asm):
        rc = asm.solve()
        ctx.doc.recompute()
    problems = {}
    for j in _joint_group(asm).Group:
        if hasattr(j, "Reference1") and j.Reference1 is not None:
            errs = joint_errors(j)
            if errs:
                problems[j.Name] = errs
    if rc != 0 or problems:
        raise SkillError(
            errors.RECOMPUTE_FAILED,
            f"Assembly '{asm.Name}' could not be solved"
            + (f" (solver code {rc})" if rc != 0 else "")
            + (f": joints not satisfied {problems}" if problems else ""),
            hint="Joints may conflict (over-constrained), or reference geometry that changed. "
            "Check each joint's faces/edges; a part with too many joints cannot satisfy all of them.",
            details={"solver_code": rc, "unsatisfied": problems},
        )
    return {
        "placements": {
            link.Name: {
                "position": geometry.vec(link.Placement.Base, 4),
                "rotation": {
                    "axis": geometry.vec(link.Placement.Rotation.Axis, 6),
                    "angle": geometry.num(link.Placement.Rotation.Angle * 57.29577951308232, 4),
                },
            }
            for link in parts_of(asm)
        }
    }


def joint(ctx: Context, p: Dict[str, Any]) -> Any:
    import JointObject

    asm = get_assembly(ctx, p["assembly"])
    jg = _joint_group(asm)
    j = ctx.add("App::FeaturePython", p.get("name"), "Joint")
    jg.addObject(j)
    kind = p["type"]
    JointObject.Joint(j, JointObject.JointTypes.index(kind.capitalize()))
    j.addProperty("App::PropertyInteger", "FCSkillJointType", "FCSkill", "Joint type index in the skill")
    j.FCSkillJointType = JOINT_TYPES.index(kind)
    spec = {"a": p["a"], "b": p["b"], "offset": p.get("offset", 0)}
    _connect(ctx, j, asm, spec)
    j.addProperty(
        "App::PropertyString", JOINT_PROP, "FCSkill", "Joint references as selectors (re-resolved after edits)"
    )
    setattr(j, JOINT_PROP, json.dumps(spec))
    result = solve(ctx, asm)
    clashes = interferences(asm)
    for c in clashes:
        ctx.warn("INTERFERENCE", f"'{c['a']}' and '{c['b']}' overlap by {c['overlap_volume']} mm3 after solving")
    result["interferences"] = clashes
    return {"object": asm, "data": result}


def reselect_joints(ctx: Context) -> None:
    """Re-resolve joint references after upstream edits, then re-solve (see module doc)."""
    touched = set()
    for o in ctx.doc.Objects:
        if JOINT_PROP in getattr(o, "PropertiesList", []):
            asm = o.getParentGeoFeatureGroup() if hasattr(o, "getParentGeoFeatureGroup") else None
            if asm is None:
                for parent in o.InList:
                    if _is_assembly(parent) or parent.TypeId == "Assembly::JointGroup":
                        asm = parent if _is_assembly(parent) else (parent.InList[0] if parent.InList else None)
            if asm is None or not _is_assembly(asm):
                continue
            _connect(ctx, o, asm, json.loads(getattr(o, JOINT_PROP)))
            touched.add(asm.Name)
    for name in touched:
        solve(ctx, ctx.doc.getObject(name))


HANDLERS = {"assembly": assembly, "joint": joint}
