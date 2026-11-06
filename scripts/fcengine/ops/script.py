"""Opt-in escape hatch: run FreeCAD Python inside the verified pipeline.

Disabled unless the user sets FCSKILL_ALLOW_PYTHON=1. The code runs inside
the request like any other step: the result is recomputed and verified, and
on failure nothing is saved.
"""

from __future__ import annotations

import io
import json
import os
import traceback
from contextlib import redirect_stdout
from typing import Any, Dict

import FreeCAD as App

from .. import errors, geometry
from ..document import Context
from ..errors import SkillError

ENV = "FCSKILL_ALLOW_PYTHON"
MAX_OUTPUT = 4000


def python(ctx: Context, p: Dict[str, Any]) -> Dict[str, Any]:
    if os.environ.get(ENV) != "1":
        raise SkillError(
            errors.UNSUPPORTED,
            "The 'python' op is disabled",
            hint=f"It is off by default. Only the user can enable it, by setting {ENV}=1; "
            "do not set it yourself. Otherwise, express the change with the regular operations.",
        )
    import Part

    doc = ctx.doc
    before = {o.Name for o in doc.Objects}
    ns: Dict[str, Any] = {
        "App": App,
        "FreeCAD": App,
        "Part": Part,
        "Vector": App.Vector,
        "doc": doc,
        "get": lambda name: ctx.get(name, need_shape=False),
        "result": None,
    }
    out = io.StringIO()
    try:
        code = compile(p["code"], "<python step>", "exec")
        with redirect_stdout(out):
            exec(code, ns)  # noqa: S102 - explicit, user-enabled escape hatch
    except SkillError:
        raise
    except SyntaxError as e:
        raise SkillError(errors.SCRIPT_ERROR, f"Syntax error in python step, line {e.lineno}: {e.msg}") from None
    except Exception as e:
        tb = [f for f in traceback.extract_tb(e.__traceback__) if f.filename == "<python step>"]
        line = f" (line {tb[-1].lineno})" if tb else ""
        raise SkillError(
            errors.SCRIPT_ERROR, f"{type(e).__name__}{line}: {e}", details={"output": out.getvalue()[-MAX_OUTPUT:]}
        ) from None
    ctx.mutated = True
    ctx.reselect()
    ctx.recompute()
    created = [o for o in doc.Objects if o.Name not in before]
    for o in created:
        if geometry.is_part_shape(o) and not o.Shape.isNull() and not o.Shape.isValid():
            raise SkillError(errors.GEOMETRY_INVALID, f"python step created '{o.Name}' with invalid geometry")
    data: Dict[str, Any] = {"created": [o.Name for o in created]}
    res = ns.get("result")
    if res is not None:
        try:
            json.dumps(res)
            data["result"] = res
        except (TypeError, ValueError):
            data["result"] = repr(res)[:MAX_OUTPUT]
    if out.getvalue():
        data["output"] = out.getvalue()[-MAX_OUTPUT:]
    obj = created[-1] if created else None
    return {"object": obj, "data": data} if obj is not None else {"data": data}


HANDLERS = {"python": python}
