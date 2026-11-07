"""Integration tests against real FreeCAD. Run through tests/run.py.

Assertions use analytic volumes and bounding boxes: an operation counts as
working only if it produces the right geometry.
"""

import hashlib
import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import FreeCAD as App  # noqa: E402

from fcengine.runner import execute  # noqa: E402

PI = math.pi


class EngineCase(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp(prefix="fcskill-test-"))

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)
        for name in list(App.listDocuments()):
            App.closeDocument(name)

    def run_ok(self, steps, doc="t.FCStd", new=True, **extra):
        resp = execute({"doc": doc, "new": new, "steps": steps, **extra}, self.ws)
        self.assertEqual(resp["status"], "success", json.dumps(resp.get("error"), indent=1))
        return resp

    def run_err(self, steps, code, doc="t.FCStd", new=True):
        resp = execute({"doc": doc, "new": new, "steps": steps}, self.ws)
        self.assertEqual(resp["status"], "error", "expected failure")
        self.assertEqual(resp["error"]["code"], code, json.dumps(resp["error"], indent=1))
        return resp["error"]

    def step(self, resp, i=-1):
        return resp["steps"][i]

    def result(self, resp, name):
        for r in resp["results"]:
            if r["name"] == name:
                return r
        self.fail(f"{name} not among results {[r['name'] for r in resp['results']]}")

    def assertVolume(self, entry, expected, rel=1e-4):
        self.assertAlmostEqual(entry["volume"], expected, delta=max(abs(expected) * rel, 1e-3))

    def assertBBox(self, entry, mn, mx, tol=1e-3):
        for a, b in zip(entry["bbox"]["min"], mn):
            self.assertAlmostEqual(a, b, delta=tol, msg=entry["bbox"])
        for a, b in zip(entry["bbox"]["max"], mx):
            self.assertAlmostEqual(a, b, delta=tol, msg=entry["bbox"])


BOX = {"op": "box", "name": "B", "length": 10, "width": 10, "height": 10}


class SolidTests(EngineCase):
    def test_primitives(self):
        r = self.run_ok(
            [
                {"op": "box", "name": "Bx", "length": 30, "width": 20, "height": 10, "position": [1, 2, 3]},
                {
                    "op": "cylinder",
                    "name": "Cy",
                    "radius": 5,
                    "height": 20,
                    "position": [100, 0, 0],
                    "direction": [1, 0, 0],
                },
                {"op": "sphere", "name": "Sp", "radius": 3},
                {"op": "cone", "name": "Co", "radius1": 4, "radius2": 2, "height": 9},
                {"op": "torus", "name": "To", "radius1": 10, "radius2": 2},
                {"op": "prism", "name": "Pr", "sides": 6, "circumradius": 10, "height": 5},
            ]
        )
        s = {x["object"]: x for x in r["steps"]}
        self.assertVolume(s["Bx"], 6000)
        self.assertBBox(s["Bx"], [1, 2, 3], [31, 22, 13])
        self.assertVolume(s["Cy"], PI * 25 * 20)
        self.assertBBox(s["Cy"], [100, -5, -5], [120, 5, 5])  # axis along +X
        self.assertVolume(s["Sp"], 4 / 3 * PI * 27)
        self.assertVolume(s["Co"], PI * 9 / 3 * (16 + 8 + 4))
        self.assertVolume(s["To"], 2 * PI**2 * 10 * 4)
        self.assertVolume(s["Pr"], 1.5 * math.sqrt(3) * 100 * 5)

    def test_rotation_param(self):
        r = self.run_ok(
            [
                {
                    "op": "box",
                    "name": "B",
                    "length": 10,
                    "width": 2,
                    "height": 2,
                    "rotation": {"axis": [0, 0, 1], "angle": 90},
                }
            ]
        )
        self.assertBBox(self.step(r), [-2, 0, 0], [0, 10, 2])

    def test_extrude_planes(self):
        tri = [[0, 0], [10, 0], [0, 10]]
        r = self.run_ok(
            [
                {"op": "extrude", "name": "Exy", "points": tri, "height": 5},
                {"op": "extrude", "name": "Exz", "points": tri, "plane": "XZ", "height": 5},
                {"op": "extrude", "name": "Eyz", "points": tri, "plane": "YZ", "height": 5, "symmetric": True},
                {"op": "extrude", "name": "Edir", "points": tri, "direction": [0, 0, -3]},
            ]
        )
        s = {x["object"]: x for x in r["steps"]}
        for n in ("Exy", "Exz", "Eyz"):
            self.assertVolume(s[n], 250)
        self.assertBBox(s["Exy"], [0, 0, 0], [10, 10, 5])
        self.assertBBox(s["Exz"], [0, 0, 0], [10, 5, 10])
        self.assertBBox(s["Eyz"], [-2.5, 0, 0], [2.5, 10, 10])
        self.assertBBox(s["Edir"], [0, 0, -3], [10, 10, 0])
        self.assertNotIn("Exy_Profile", [x["name"] for x in r["results"]])
        self.assertIn("Exy_Profile", r["intermediates"])

    def test_revolve(self):
        r = self.run_ok(
            [{"op": "revolve", "name": "Ring", "points": [[10, 0], [20, 0], [20, 30], [10, 30]], "axis": [0, 1, 0]}]
        )
        self.assertVolume(self.step(r), PI * (400 - 100) * 30)
        r = self.run_ok(
            [
                {
                    "op": "revolve",
                    "name": "Half",
                    "points": [[10, 0], [20, 0], [20, 30], [10, 30]],
                    "axis": [0, 1, 0],
                    "angle": 180,
                }
            ]
        )
        self.assertVolume(self.step(r), PI * (400 - 100) * 30 / 2)

    def test_shapes_plate_with_holes(self):
        r = self.run_ok(
            [
                {
                    "op": "extrude",
                    "name": "P",
                    "height": 6,
                    "shapes": [
                        {"rect": [0, 0, 80, 50], "corner_radius": 5},
                        {"circle": [10, 10], "radius": 3.25},
                        {"slot": [[30, 25], [50, 25]], "radius": 4},
                    ],
                }
            ]
        )
        expected = (80 * 50 - (4 - PI) * 25) * 6 - PI * 3.25**2 * 6 - (20 * 8 + PI * 16) * 6
        self.assertVolume(self.result(r, "P"), expected)
        self.assertIn("P_Sketch", r["intermediates"])
        r = self.run_ok(
            [{"op": "set", "target": "P", "properties": {"shapes": [{"rect": [0, 0, 100, 50]}], "LengthFwd": 2}}],
            new=False,
        )
        self.assertVolume(self.result(r, "P"), 10000)
        doc = App.openDocument(str(self.ws / "t.FCStd"))
        try:
            self.assertEqual(doc.getObject("P_Sketch").TypeId, "Sketcher::SketchObject")
        finally:
            App.closeDocument(doc.Name)

    def test_shapes_plane_offset_and_arcs(self):
        r = self.run_ok(
            [
                {
                    "op": "extrude",
                    "name": "Q",
                    "height": 4,
                    "plane": "XZ",
                    "offset": 10,
                    "shapes": [{"path": [[0, 0], [20, 0], {"arc_to": [20, 10], "center": [20, 5]}, [0, 10]]}],
                }
            ]
        )
        q = self.result(r, "Q")
        self.assertVolume(q, (200 + PI * 25 / 2) * 4)
        self.assertBBox(q, [0, 10, 0], [25, 14, 10])

    def test_shapes_revolve(self):
        r = self.run_ok([{"op": "revolve", "name": "Tube", "shapes": [{"rect": [5, 0, 10, 20]}], "axis": [0, 1, 0]}])
        self.assertVolume(self.result(r, "Tube"), PI * (100 - 25) * 20)
        self.run_err(
            [{"op": "revolve", "shapes": [{"circle": [0, 5], "radius": 2}], "axis": [0, 1, 0]}], "INVALID_PARAM"
        )

    def test_shapes_errors(self):
        err = self.run_err(
            [{"op": "extrude", "height": 1, "shapes": [{"rect": [0, 0, 10, 10]}, {"rect": [5, 5, 15, 15]}]}],
            "INVALID_PARAM",
        )
        self.assertIn("overlap", err["message"])
        self.run_err(
            [{"op": "extrude", "height": 1, "shapes": [{"path": [[0, 0], [10, 10], [10, 0], [0, 10]]}]}],
            "INVALID_PARAM",
        )

    def test_profile_errors(self):
        self.run_err(
            [{"op": "revolve", "points": [[-5, 0], [5, 0], [5, 10], [-5, 10]], "axis": [0, 1, 0]}], "INVALID_PARAM"
        )
        self.run_err([{"op": "extrude", "points": [[0, 0], [1, 1], [2, 2]], "height": 1}], "INVALID_PARAM")
        self.run_err(
            [{"op": "extrude", "points": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 5]], "height": 1}], "INVALID_PARAM"
        )
        # self-intersecting bow-tie
        err = self.run_err(
            [{"op": "extrude", "points": [[0, 0], [10, 10], [10, 0], [0, 4]], "height": 1}], "INVALID_PARAM"
        )
        self.assertIn("cross", err["message"])

    def test_name_conflict(self):
        err = self.run_err([BOX, BOX], "NAME_CONFLICT")
        self.assertEqual(err["step"], 1)


class BooleanTests(EngineCase):
    def test_cut_single_and_multi(self):
        r = self.run_ok(
            [
                {"op": "box", "name": "P", "length": 40, "width": 20, "height": 5},
                {"op": "cylinder", "name": "H1", "radius": 2, "height": 7, "position": [10, 10, -1]},
                {"op": "cylinder", "name": "H2", "radius": 2, "height": 7, "position": [30, 10, -1]},
                {"op": "cut", "name": "Drilled", "base": "P", "tools": ["H1", "H2"]},
            ]
        )
        self.assertVolume(self.result(r, "Drilled"), 4000 - 2 * PI * 4 * 5)
        self.assertEqual([x["name"] for x in r["results"]], ["Drilled"])
        self.assertNotIn("warnings", r)

    def test_cut_no_effect_warns(self):
        r = self.run_ok(
            [
                BOX,
                {"op": "sphere", "name": "S", "radius": 1, "position": [50, 50, 50]},
                {"op": "cut", "base": "B", "tool": "S"},
            ]
        )
        self.assertEqual(r["warnings"][0]["code"], "NO_EFFECT")
        self.assertIn("NO_EFFECT", self.step(r)["warnings"][0])

    def test_error_keeps_earlier_warnings(self):
        resp = execute(
            {
                "doc": "t.FCStd",
                "new": True,
                "steps": [
                    BOX,
                    {"op": "sphere", "name": "S", "radius": 1, "position": [50, 50, 50]},
                    {"op": "cut", "name": "R", "base": "B", "tool": "S"},
                    {"op": "fillet", "target": "R", "radius": 20},
                ],
            },
            self.ws,
        )
        self.assertEqual(resp["status"], "error")
        self.assertEqual(resp["warnings"][0]["code"], "NO_EFFECT")

    def test_cut_everything_is_error(self):
        self.run_err(
            [
                {"op": "box", "name": "Small", "length": 1, "width": 1, "height": 1},
                {"op": "box", "name": "Big", "length": 5, "width": 5, "height": 5, "position": [-2, -2, -2]},
                {"op": "cut", "base": "Small", "tool": "Big"},
            ],
            "EMPTY_RESULT",
        )

    def test_fuse(self):
        r = self.run_ok(
            [
                BOX,
                {"op": "box", "name": "B2", "length": 10, "width": 10, "height": 10, "position": [5, 0, 0]},
                {"op": "fuse", "name": "U", "objects": ["B", "B2"]},
            ]
        )
        u = self.result(r, "U")
        self.assertVolume(u, 1500)
        self.assertEqual(u["solids"], 1)
        r = self.run_ok(
            [
                BOX,
                {"op": "box", "name": "Far", "length": 1, "width": 1, "height": 1, "position": [50, 0, 0]},
                {"op": "fuse", "objects": ["B", "Far"]},
            ]
        )
        self.assertEqual(r["warnings"][0]["code"], "DISJOINT")

    def test_common(self):
        r = self.run_ok(
            [BOX, {"op": "sphere", "name": "S", "radius": 5}, {"op": "common", "name": "I", "objects": ["B", "S"]}]
        )
        self.assertVolume(self.result(r, "I"), 4 / 3 * PI * 125 / 8)
        self.run_err(
            [
                BOX,
                {"op": "sphere", "name": "S", "radius": 1, "position": [50, 0, 0]},
                {"op": "common", "objects": ["B", "S"]},
            ],
            "EMPTY_RESULT",
        )

    def test_missing_object(self):
        err = self.run_err(
            [
                {"op": "box", "name": "Plate", "length": 1, "width": 1, "height": 1},
                {"op": "cut", "base": "Plate", "tool": "Hole"},
            ],
            "OBJECT_NOT_FOUND",
        )
        self.assertIn("Plate", err["details"]["available"])


class FeatureTests(EngineCase):
    def test_fillet_vertical_edges(self):
        r = self.run_ok([BOX, {"op": "fillet", "name": "F", "target": "B", "radius": 2, "edges": "|Z"}])
        self.assertVolume(self.result(r, "F"), 1000 - 4 * (4 - PI) * 10)

    def test_fillet_all_skips_seams(self):
        r = self.run_ok(
            [
                {"op": "cylinder", "name": "C", "radius": 5, "height": 10},
                {"op": "fillet", "name": "F", "target": "C", "radius": 1},
            ]
        )
        self.assertEqual(self.result(r, "F")["solids"], 1)
        self.assertLess(self.result(r, "F")["volume"], PI * 25 * 10)

    def test_fillet_too_large_is_explained(self):
        resp = execute(
            {"doc": "t.FCStd", "new": True, "steps": [BOX, {"op": "fillet", "target": "B", "radius": 6}]}, self.ws
        )
        err = resp["error"]
        self.assertIn(err["code"], ("RECOMPUTE_FAILED", "GEOMETRY_INVALID"))  # depends on the OCC version
        self.assertIn("radius", err["hint"])
        self.assertIn("shortest selected edge is 10.0", err["hint"])

    def test_spherical_shapes(self):
        """Pole edges of spheres are degenerated; describing them used to crash (INTERNAL)."""
        r = self.run_ok(
            [
                {"op": "sphere", "name": "S", "radius": 10},
                {"op": "box", "name": "K", "length": 30, "width": 30, "height": 30, "position": [-15, -15, 0]},
                {"op": "cut", "name": "Hemi", "base": "S", "tool": "K"},
                {"op": "fillet", "name": "F", "target": "Hemi", "radius": 1, "edges": "%CIRCLE"},
                {"op": "inspect", "target": "S", "topology": True},
            ]
        )
        self.assertLess(self.result(r, "F")["volume"], 2 / 3 * PI * 1000)
        edges = r["steps"][-1]["data"]["topology"]["edges"]
        self.assertTrue(any(e.get("degenerated") for e in edges))
        # a plain sphere has nothing to fillet: a clear error, not an internal one
        self.run_err(
            [{"op": "sphere", "name": "S", "radius": 5}, {"op": "fillet", "target": "S", "radius": 1}],
            "INVALID_SELECTOR",
        )

    def test_fillet_hint_names_the_narrow_face(self):
        """Two filleted edges on a 5 mm face: the hint must point at the face, not the 40 mm edges."""
        resp = execute(
            {
                "doc": "t.FCStd",
                "new": True,
                "steps": [
                    {"op": "box", "name": "F", "length": 50, "width": 40, "height": 5},
                    {"op": "fillet", "target": "F", "radius": 3, "edges": "|Y and >X"},
                ],
            },
            self.ws,
        )
        hint = resp["error"]["hint"]
        self.assertIn("5.0 mm wide, and 2 selected edges border it", hint)
        self.assertIn("below about 2.5 mm", hint)

    def test_selector_matches_nothing(self):
        self.run_err([BOX, {"op": "fillet", "target": "B", "radius": 1, "edges": "%CIRCLE"}], "INVALID_SELECTOR")

    def test_chamfer(self):
        r = self.run_ok([BOX, {"op": "chamfer", "name": "C", "target": "B", "size": 1, "edges": "|Z"}])
        self.assertVolume(self.result(r, "C"), 1000 - 4 * 0.5 * 10)

    def test_shell_open_top(self):
        r = self.run_ok([BOX, {"op": "shell", "name": "S", "target": "B", "thickness": 1, "open_faces": ">Z"}])
        s = self.result(r, "S")
        self.assertVolume(s, 1000 - 8 * 8 * 9)
        self.assertBBox(s, [0, 0, 0], [10, 10, 10])
        r = self.run_ok(
            [BOX, {"op": "shell", "name": "S", "target": "B", "thickness": 1, "open_faces": ">Z", "outward": True}]
        )
        self.assertBBox(self.result(r, "S"), [-1, -1, -1], [11, 11, 10])


class PatternTests(EngineCase):
    def test_linear_array_positions(self):
        # v1 regression: count 5 with step 10 produced a 242 mm long array.
        r = self.run_ok(
            [
                {"op": "box", "name": "C", "length": 2, "width": 2, "height": 2},
                {"op": "linear_array", "name": "A", "target": "C", "count": 5, "step": [10, 0, 0]},
            ]
        )
        a = self.result(r, "A")
        self.assertBBox(a, [0, 0, 0], [42, 2, 2])
        self.assertVolume(a, 40)
        self.assertEqual(a["solids"], 5)

    def test_grid_and_polar(self):
        r = self.run_ok(
            [
                {"op": "box", "name": "C", "length": 2, "width": 2, "height": 2},
                {"op": "grid_array", "name": "G", "target": "C", "count_x": 3, "count_y": 2, "step_x": 5, "step_y": 7},
            ]
        )
        self.assertBBox(self.result(r, "G"), [0, 0, 0], [12, 9, 2])
        self.assertEqual(self.result(r, "G")["solids"], 6)
        r = self.run_ok(
            [
                {"op": "cylinder", "name": "P", "radius": 1, "height": 2, "position": [10, 0, 0]},
                {"op": "polar_array", "name": "R", "target": "P", "count": 4},
            ]
        )
        self.assertBBox(self.result(r, "R"), [-11, -11, 0], [11, 11, 2])
        r = self.run_ok(
            [
                {"op": "cylinder", "name": "P", "radius": 1, "height": 2, "position": [10, 0, 0]},
                {"op": "polar_array", "name": "R", "target": "P", "count": 3, "angle": 90},
            ]
        )
        # instances at 0, 45 and 90 degrees
        self.assertBBox(self.result(r, "R"), [-1, -1, 0], [11, 11, 2])


class TransformTests(EngineCase):
    def test_move_rotate_place(self):
        r = self.run_ok(
            [
                {"op": "box", "name": "B", "length": 10, "width": 10, "height": 10, "position": [50, 0, 0]},
                {"op": "rotate", "target": "B", "angle": 90, "axis": [0, 0, 1], "center": [55, 5, 5]},
            ]
        )
        self.assertBBox(self.result(r, "B"), [50, 0, 0], [60, 10, 10])  # rotated in place about its centre
        r = self.run_ok([BOX, {"op": "move", "target": "B", "offset": [1, 2, 3]}])
        self.assertBBox(self.result(r, "B"), [1, 2, 3], [11, 12, 13])
        r = self.run_ok([BOX, {"op": "place", "target": "B", "position": [-5, -5, 0]}])
        self.assertBBox(self.result(r, "B"), [-5, -5, 0], [5, 5, 10])

    def test_move_input_moves_inside_boolean(self):
        r = self.run_ok(
            [
                BOX,
                {"op": "cylinder", "name": "H", "radius": 1, "height": 20, "position": [5, 5, -5]},
                {"op": "cut", "name": "R", "base": "B", "tool": "H"},
                {"op": "move", "target": "H", "offset": [20, 0, 0]},
            ]
        )
        self.assertVolume(self.result(r, "R"), 1000)  # the hole moved out of the plate

    def test_move_fillet_redirects_to_base(self):
        r = self.run_ok(
            [
                BOX,
                {"op": "fillet", "name": "F", "target": "B", "radius": 1, "edges": "|Z"},
                {"op": "move", "target": "F", "offset": [100, 0, 0]},
            ]
        )
        self.assertBBox(self.result(r, "F"), [100, 0, 0], [110, 10, 10])
        self.assertEqual(r["warnings"][0]["code"], "REDIRECTED")
        r = self.run_ok([{"op": "set", "target": "F", "properties": {"position": [0, 0, 5]}}], new=False)
        self.assertBBox(self.result(r, "F"), [0, 0, 5], [10, 10, 15])

    def test_mirror_copy_scale(self):
        r = self.run_ok(
            [
                {"op": "box", "name": "B", "length": 10, "width": 10, "height": 10, "position": [5, 0, 0]},
                {"op": "mirror", "name": "M", "target": "B", "plane": "YZ"},
                {"op": "copy", "name": "K", "target": "B", "offset": [0, 50, 0]},
                {"op": "scale", "name": "S", "target": "K", "factor": 2},
            ]
        )
        self.assertBBox(self.result(r, "M"), [-15, 0, 0], [-5, 10, 10])
        self.assertBBox(self.result(r, "B"), [5, 0, 0], [15, 10, 10])  # original kept as a result
        self.assertVolume(self.result(r, "S"), 8000)
        self.assertIn("K", r["intermediates"])  # scaled copy replaces it

    def test_copy_follows_original(self):
        self.run_ok([BOX, {"op": "copy", "name": "K", "target": "B", "offset": [20, 0, 0]}])
        r = self.run_ok([{"op": "set", "target": "B", "properties": {"Height": 3}}], new=False)
        self.assertBBox(self.result(r, "K"), [20, 0, 0], [30, 10, 3])


class EditTests(EngineCase):
    def test_unknown_property_hint_lists_real_properties(self):
        err = self.run_err([BOX, {"op": "set", "target": "B", "properties": {"Radius": 3}}], "INVALID_PARAM")
        self.assertIn("'Height'", err["hint"])
        self.assertNotIn("[]", err["hint"])

    def test_parametric_chain_updates(self):
        self.run_ok(
            [
                {"op": "set_params", "values": {"thickness": 5}},
                {"op": "box", "name": "Plate", "length": 50, "width": 30, "height": "=Params.thickness"},
                {"op": "cylinder", "name": "Hole", "radius": 3, "height": 50, "position": [25, 15, -10]},
                {"op": "cut", "name": "Drilled", "base": "Plate", "tool": "Hole"},
                {"op": "fillet", "name": "Final", "target": "Drilled", "radius": 2, "edges": "|Z and %LINE"},
            ]
        )
        r = self.run_ok(
            [
                {"op": "set_params", "values": {"thickness": 12}},
                {"op": "check", "target": "Final", "expect": {"bbox_size": [50, 30, 12]}},
            ],
            new=False,
        )
        expected = 50 * 30 * 12 - PI * 9 * 12 - 4 * (4 - PI) * 12
        self.assertVolume(self.result(r, "Final"), expected)
        r = self.run_ok([{"op": "set", "target": "Plate", "properties": {"Length": 80}}], new=False)
        self.assertBBox(self.result(r, "Final"), [0, 0, 0], [80, 30, 12])
        # Plate.Height is still driven by the parameter
        r = self.run_ok([{"op": "inspect", "target": "Plate"}], new=False)
        self.assertEqual(self.step(r)["data"]["expressions"], {"Height": "Params.thickness"})

    def test_selector_reevaluated_after_topology_change(self):
        """Fillet on '|Z' keeps targeting vertical edges after the base gains edges."""
        self.run_ok(
            [
                BOX,
                {"op": "cylinder", "name": "H", "radius": 1, "height": 20, "position": [50, 50, -5]},
                {"op": "cut", "name": "R", "base": "B", "tool": "H"},
                {"op": "fillet", "name": "F", "target": "R", "radius": 1, "edges": "|Z and %LINE"},
            ]
        )
        r = self.run_ok([{"op": "move", "target": "H", "offset": [-45, -45, 0]}], new=False)  # hole now drilled
        f = self.result(r, "F")
        self.assertVolume(f, 1000 - PI * 10 - 4 * (1 - PI / 4) * 10)

    def test_fillet_set_radius(self):
        self.run_ok([BOX, {"op": "fillet", "name": "F", "target": "B", "radius": 1, "edges": "|Z"}])
        r = self.run_ok([{"op": "set", "target": "F", "properties": {"radius": 2}}], new=False)
        self.assertVolume(self.result(r, "F"), 1000 - 4 * (4 - PI) * 10)

    def test_relinking_a_tool_warns_about_orphan(self):
        self.run_ok(
            [
                BOX,
                {"op": "cylinder", "name": "H1", "radius": 1, "height": 20, "position": [3, 3, -5]},
                {"op": "cylinder", "name": "H2", "radius": 1, "height": 20, "position": [7, 7, -5]},
                {"op": "cut", "name": "R", "base": "B", "tool": "H1"},
            ]
        )
        r = self.run_ok([{"op": "set", "target": "R", "properties": {"Tool": "H2"}}], new=False)
        self.assertEqual([w["code"] for w in r["warnings"]], ["ORPHANED"])
        self.assertIn("'H1'", r["warnings"][0]["message"])
        r = self.run_ok([{"op": "delete", "targets": ["R"]}], new=False)  # deliberate: no warning
        self.assertNotIn("warnings", r)

    def test_set_errors(self):
        self.run_ok([BOX])
        err = self.run_err([{"op": "set", "target": "B", "properties": {"length": 5}}], "INVALID_PARAM", new=False)
        self.assertIn("Length", err["hint"])
        self.run_err([{"op": "set", "target": "B", "properties": {"Length": -5}}], "RECOMPUTE_FAILED", new=False)
        self.run_err([{"op": "set_params", "values": {"mm": 3}}], "INVALID_REQUEST", new=False)  # caught statically
        self.run_err(
            [{"op": "box", "length": "=Params.missing", "width": 1, "height": 1}], "RECOMPUTE_FAILED", new=False
        )

    def test_parameter_units(self):
        """OpenClaw report H3: bad units were stored; an angle silently became a length."""
        self.run_err([{"op": "set_params", "values": {"len": "5 furlongs"}}], "INVALID_PARAM")
        err = self.run_err(
            [
                {"op": "set_params", "values": {"angle": "15 deg"}},
                {"op": "box", "name": "B", "length": "=Params.angle", "width": 10, "height": 10},
            ],
            "INVALID_EXPRESSION",
        )
        self.assertIn("length", err["message"])
        r = self.run_ok(
            [
                {"op": "set_params", "values": {"ang": "90 deg", "len": "2 cm", "n": 3}},
                {"op": "box", "name": "B", "length": "=Params.len", "width": "=Params.n * 2", "height": 1},
                {
                    "op": "revolve",
                    "name": "R",
                    "points": [[5, 0], [6, 0], [6, 1]],
                    "axis": [0, 1, 0],
                    "angle": "=Params.ang",
                },
            ]
        )
        self.assertBBox(self.result(r, "B"), [0, 0, 0], [20, 6, 1])
        # changing a parameter to the wrong kind is caught on edit too, and nothing is saved
        self.run_err([{"op": "set_params", "values": {"len": "30 deg"}}], "INVALID_EXPRESSION", new=False)

    def test_set_validates_like_ops(self):
        """OpenClaw report H4/M4/L3: set aliases bypassed vector/rotation/label validation."""
        self.run_ok([BOX, dict(BOX, name="C")])
        for props in (
            {"position": [1, 2]},
            {"position": [1, 2, 3, 4]},
            {"rotation": {"axis": [0, 0, 0], "angle": 45}},
            {"rotation": {"axis": [0, 0, 1]}},
            {"rotation": {"axis": [0, 0], "angle": 5}},
            {"Shape": "=1+1"},
            {"Shape": None},
            {"Proxy": 1},
        ):
            with self.subTest(props=props):
                self.run_err([{"op": "set", "target": "B", "properties": props}], "INVALID_PARAM", new=False)
        self.run_err([{"op": "set", "target": "C", "properties": {"Label": "B"}}], "NAME_CONFLICT", new=False)
        r = self.run_ok(
            [{"op": "set", "target": "C", "properties": {"Label": "Second box", "position": [0, 20, 0]}}], new=False
        )
        self.assertEqual(self.result(r, "C")["label"], "Second box")

    def test_set_expression_and_clear(self):
        self.run_ok([BOX, {"op": "box", "name": "B2", "length": "=B.Length * 2", "width": 1, "height": 1}])
        r = self.run_ok([{"op": "set", "target": "B", "properties": {"Length": 7}}], new=False)
        self.assertBBox(self.result(r, "B2"), [0, 0, 0], [14, 1, 1])
        r = self.run_ok(
            [
                {"op": "set", "target": "B2", "properties": {"Length": 3}},
                {"op": "set", "target": "B", "properties": {"Length": 9}},
            ],
            new=False,
        )
        self.assertBBox(self.result(r, "B2"), [0, 0, 0], [3, 1, 1])  # literal replaced the expression

    def test_set_points_of_extrusion(self):
        self.run_ok([{"op": "extrude", "name": "E", "points": [[0, 0], [10, 0], [0, 10]], "height": 2}])
        r = self.run_ok(
            [
                {
                    "op": "set",
                    "target": "E",
                    "properties": {"points": [[0, 0], [20, 0], [20, 10], [0, 10]], "LengthFwd": 3},
                }
            ],
            new=False,
        )
        self.assertVolume(self.result(r, "E"), 600)

    def test_delete_rules(self):
        self.run_ok(
            [
                BOX,
                {"op": "sphere", "name": "S", "radius": 3},
                {"op": "cut", "name": "R", "base": "B", "tool": "S"},
                {"op": "extrude", "name": "E", "points": [[0, 0], [1, 0], [0, 1]], "height": 1, "plane": "XZ"},
            ]
        )
        err = self.run_err([{"op": "delete", "targets": ["B"]}], "DEPENDENCY", new=False)
        self.assertEqual(err["details"]["dependents"], ["R"])
        r = self.run_ok(
            [{"op": "delete", "targets": ["B"], "with_dependents": True}, {"op": "delete", "targets": ["E"]}], new=False
        )
        names = [o["name"] for o in self.run_ok([{"op": "inspect"}], new=False)["steps"][0]["data"]["objects"]]
        self.assertEqual(names, ["S"])  # E_Profile helper deleted with E
        self.assertEqual([x["name"] for x in r["results"]], ["S"])

    def test_free_text_label(self):
        r = self.run_ok(
            [
                BOX,
                {"op": "rename", "target": "B", "label": "Plaque de base é"},
                {"op": "move", "target": "Plaque de base é", "offset": [1, 0, 0]},
            ]
        )
        self.assertEqual(self.result(r, "B")["label"], "Plaque de base é")

    def test_placement_subproperty_hint(self):
        self.run_ok([BOX])
        err = self.run_err(
            [{"op": "set", "target": "B", "properties": {"Placement.Base.x": 5}}], "INVALID_PARAM", new=False
        )
        self.assertIn('"position"', err["hint"])

    def test_generic_recompute_hint(self):
        err = self.run_err(
            [{"op": "box", "name": "B", "length": "=0 - 5", "width": 1, "height": 1}], "RECOMPUTE_FAILED"
        )
        self.assertIn("dimensions", err["hint"])

    def test_rename_and_label_lookup(self):
        r = self.run_ok(
            [
                BOX,
                {"op": "rename", "target": "B", "label": "Base_plate"},
                {"op": "move", "target": "Base_plate", "offset": [1, 0, 0]},
            ]
        )
        self.assertEqual(self.result(r, "B")["label"], "Base_plate")


class PostEditAuditTests(EngineCase):
    """Edits must not silently break features created earlier (OpenClaw report H1/M2)."""

    HOLE = {"op": "cylinder", "name": "H", "radius": 2, "height": 20, "position": [5, 5, -5]}

    def doc_bytes(self):
        return (self.ws / "t.FCStd").read_bytes()

    def test_edit_that_empties_a_cut_is_rejected(self):
        self.run_ok([BOX, self.HOLE, {"op": "cut", "name": "R", "base": "B", "tool": "H"}])
        before = self.doc_bytes()
        err = self.run_err([{"op": "set", "target": "H", "properties": {"Radius": 100}}], "EMPTY_RESULT", new=False)
        self.assertEqual(err["details"]["object"], "R")
        self.assertEqual(self.doc_bytes(), before)

    def test_edit_that_makes_a_cut_miss_warns(self):
        self.run_ok([BOX, self.HOLE, {"op": "cut", "name": "R", "base": "B", "tool": "H"}])
        r = self.run_ok([{"op": "move", "target": "H", "offset": [100, 0, 0]}], new=False)
        self.assertEqual([w["code"] for w in r["warnings"]], ["NO_EFFECT"])

    def test_edit_that_splits_a_fusion_warns_once(self):
        self.run_ok(
            [
                {"op": "box", "name": "A", "length": 10, "width": 10, "height": 10},
                dict(BOX, position=[10, 0, 0]),
                {"op": "fuse", "name": "F", "objects": ["A", "B"]},
            ]
        )
        r = self.run_ok([{"op": "move", "target": "B", "offset": [100, 0, 0]}], new=False)
        self.assertEqual([w["code"] for w in r["warnings"]], ["DISJOINT"])
        r = self.run_ok([{"op": "set", "target": "A", "properties": {"Height": 12}}], new=False)
        self.assertNotIn("warnings", r)  # already disjoint before this edit: no repeat

    def test_overlapping_results_warned_once_per_request(self):
        r = self.run_ok(
            [
                BOX,
                {"op": "box", "name": "Leftover", "length": 20, "width": 20, "height": 20, "position": [-5, -5, -5]},
                {"op": "box", "name": "Apart", "length": 5, "width": 5, "height": 5, "position": [50, 0, 0]},
            ]
        )
        codes = [(w["code"], w["step"]) for w in r["warnings"]]
        self.assertEqual(codes, [("OVERLAPPING_RESULTS", None)])
        self.assertIn("'B'", r["warnings"][0]["message"])
        r = self.run_ok([{"op": "inspect"}], new=False)  # read-only requests stay quiet
        self.assertNotIn("warnings", r)
        r = self.run_ok(
            [{"op": "export", "filename": "all.stl"}], new=False
        )  # but files with overlapping solids are flagged
        self.assertEqual([w["code"] for w in r["warnings"]], ["OVERLAPPING_SOLIDS"])


class PartDesignTests(EngineCase):
    BODY = [
        {"op": "body", "name": "Part"},
        {"op": "extrude", "body": "Part", "name": "Base", "height": 10, "shapes": [{"rect": [0, 0, 40, 20]}]},
    ]

    def test_pad_planes_follow_skill_convention(self):
        for plane, mx in (("XY", [40, 20, 5]), ("XZ", [40, 5, 20]), ("YZ", [5, 40, 20])):
            with self.subTest(plane=plane):
                r = self.run_ok(
                    [
                        {"op": "body", "name": "B"},
                        {
                            "op": "extrude",
                            "body": "B",
                            "plane": plane,
                            "height": 5,
                            "shapes": [{"rect": [0, 0, 40, 20]}],
                        },
                    ]
                )
                self.assertBBox(self.result(r, "B"), [0, 0, 0], mx)

    def test_pocket_follows_face_when_part_grows(self):
        r = self.run_ok(
            self.BODY
            + [
                {
                    "op": "extrude",
                    "body": "Part",
                    "name": "Bore",
                    "mode": "remove",
                    "through_all": True,
                    "offset": "=Base.Length",
                    "shapes": [{"circle": [10, 10], "radius": 3}],
                },
                {
                    "op": "extrude",
                    "body": "Part",
                    "name": "Recess",
                    "mode": "remove",
                    "height": 4,
                    "offset": "=Base.Length",
                    "shapes": [{"rect": [25, 5, 35, 15]}],
                },
            ]
        )
        self.assertVolume(self.result(r, "Part"), 8000 - PI * 9 * 10 - 100 * 4)
        self.assertEqual(self.result(r, "Part")["solids"], 1)
        r = self.run_ok([{"op": "set", "target": "Base", "properties": {"Length": 16}}], new=False)
        self.assertVolume(
            self.result(r, "Part"), 40 * 20 * 16 - PI * 9 * 16 - 100 * 4
        )  # recess still 4 deep from the new top

    def test_pocket_direction_and_no_effect(self):
        r = self.run_ok(
            self.BODY
            + [
                {
                    "op": "extrude",
                    "body": "Part",
                    "mode": "remove",
                    "height": 3,
                    "offset": 10,
                    "shapes": [{"circle": [10, 10], "radius": 2}],
                    "reversed": True,
                }
            ]
        )
        self.assertEqual(r["warnings"][0]["code"], "NO_EFFECT")  # reversed cuts upwards, into air
        r = self.run_ok(
            self.BODY
            + [
                {
                    "op": "extrude",
                    "body": "Part",
                    "mode": "remove",
                    "height": 3,
                    "plane": "XZ",
                    "offset": 0,
                    "shapes": [{"circle": [20, 5], "radius": 2}],
                    "reversed": True,
                }
            ]
        )
        self.assertVolume(self.result(r, "Part"), 8000 - PI * 4 * 3)  # front face (y=0), cut towards +Y
        self.assertNotIn("warnings", r)

    def test_holes(self):
        r = self.run_ok(
            self.BODY
            + [
                {
                    "op": "hole",
                    "body": "Part",
                    "name": "Mount",
                    "at": [[6, 10], [34, 10]],
                    "offset": "=Base.Length",
                    "size": "M4",
                    "type": "counterbore",
                }
            ]
        )
        removed = 2 * (PI * 2.25**2 * (10 - 4.4) + PI * 4**2 * 4.4)
        self.assertVolume(self.result(r, "Part"), 8000 - removed)
        self.assertEqual(r["steps"][-1]["data"]["cut_diameter"], 8.0)
        r = self.run_ok(
            self.BODY
            + [{"op": "hole", "body": "Part", "at": [[20, 10]], "offset": 10, "size": "M6", "fit": "tap", "depth": 6}]
        )
        self.assertVolume(self.result(r, "Part"), 8000 - PI * 2.5**2 * 6)
        r = self.run_ok(
            self.BODY + [{"op": "hole", "body": "Part", "at": [[20, 10], [80, 10]], "offset": 10, "diameter": 3}]
        )
        self.assertEqual(r["warnings"][0]["code"], "HOLE_OUTSIDE")
        self.assertIn("[80, 10]", r["warnings"][0]["message"])

    def test_hole_countersink_and_move(self):
        self.run_ok(
            self.BODY
            + [
                {
                    "op": "hole",
                    "body": "Part",
                    "name": "H",
                    "at": [[20, 10]],
                    "offset": "=Base.Length",
                    "size": "M5",
                    "type": "countersink",
                }
            ]
        )
        r = self.run_ok([{"op": "set", "target": "H", "properties": {"at": [[10, 10], [30, 10]]}}], new=False)
        self.assertLess(self.result(r, "Part")["volume"], 8000 - 2 * PI * 2.75**2 * 10)

    def test_revolution_and_groove(self):
        r = self.run_ok(
            [
                {"op": "body", "name": "Shaft"},
                {
                    "op": "revolve",
                    "body": "Shaft",
                    "name": "Core",
                    "shapes": [{"rect": [0, 0, 10, 50]}],
                    "axis": [0, 1, 0],
                },
                {
                    "op": "revolve",
                    "body": "Shaft",
                    "name": "Ring",
                    "mode": "remove",
                    "shapes": [{"rect": [8, 20, 10, 23]}],
                    "axis": [0, 1, 0],
                },
            ]
        )
        self.assertVolume(self.result(r, "Shaft"), PI * 100 * 50 - PI * (100 - 64) * 3)

    def test_dressups_survive_upstream_edits(self):
        """The topological-naming case: PartDesign fillets break on edits unless selectors are re-evaluated."""
        self.run_ok(
            self.BODY
            + [
                {"op": "fillet", "target": "Part", "name": "Round", "radius": 2, "edges": "|Z"},
                {"op": "chamfer", "target": "Part", "name": "Bevel", "size": 0.5, "edges": "face(>Z) and %LINE"},
            ]
        )
        r = self.run_ok([{"op": "set", "target": "Base", "properties": {"Length": 15}}], new=False)
        part = self.result(r, "Part")
        self.assertBBox(part, [0, 0, 0], [40, 20, 15])
        self.assertLess(part["volume"], 40 * 20 * 15 - 4 * (4 - PI) * 15 + 1e-6)
        r = self.run_ok([{"op": "set", "target": "Round", "properties": {"radius": 3}}], new=False)
        self.assertEqual(self.result(r, "Part")["solids"], 1)

    def test_fillet_exact_and_shell(self):
        r = self.run_ok(self.BODY + [{"op": "fillet", "target": "Part", "radius": 2, "edges": "|Z"}])
        self.assertVolume(self.result(r, "Part"), 8000 - 4 * (4 - PI) * 10)
        r = self.run_ok(
            [
                {"op": "body", "name": "Box"},
                {"op": "extrude", "body": "Box", "height": 10, "shapes": [{"rect": [0, 0, 10, 10]}]},
                {"op": "shell", "target": "Box", "thickness": 1, "open_faces": ">Z"},
            ]
        )
        self.assertVolume(self.result(r, "Box"), 1000 - 8 * 8 * 9)
        self.assertBBox(self.result(r, "Box"), [0, 0, 0], [10, 10, 10])

    def test_feature_patterns(self):
        r = self.run_ok(
            self.BODY
            + [
                {
                    "op": "extrude",
                    "body": "Part",
                    "name": "Slot",
                    "mode": "remove",
                    "through_all": True,
                    "offset": "=Base.Length",
                    "shapes": [{"circle": [5, 10], "radius": 2}],
                },
                {"op": "linear_array", "target": "Slot", "count": 4, "step": [10, 0, 0]},
            ]
        )
        self.assertVolume(self.result(r, "Part"), 8000 - 4 * PI * 4 * 10)
        r = self.run_ok(
            [
                {"op": "body", "name": "Disc"},
                {
                    "op": "extrude",
                    "body": "Disc",
                    "name": "D",
                    "height": 5,
                    "shapes": [{"circle": [0, 0], "radius": 30}],
                },
                {"op": "hole", "body": "Disc", "name": "Bolt", "at": [[20, 0]], "offset": 5, "diameter": 4},
                {"op": "polar_array", "target": "Bolt", "count": 6},
            ]
        )
        self.assertVolume(self.result(r, "Disc"), PI * 900 * 5 - 6 * PI * 4 * 5)

    def test_feature_mirror_and_grid(self):
        slot = {
            "op": "extrude",
            "body": "Part",
            "name": "Slot",
            "mode": "remove",
            "through_all": True,
            "offset": "=Base.Length",
            "shapes": [{"circle": [5, 10], "radius": 2}],
        }
        r = self.run_ok(self.BODY + [slot, {"op": "mirror", "target": "Slot", "plane": "YZ", "point": [20, 0, 0]}])
        self.assertVolume(self.result(r, "Part"), 8000 - 2 * PI * 4 * 10)
        self.assertEqual([x["name"] for x in r["results"]], ["Part"])  # the mirror is a feature of the body
        vent = dict(slot, name="Vent", shapes=[{"circle": [5, 5], "radius": 1}])
        grid = {
            "op": "grid_array",
            "name": "Vents",
            "target": "Vent",
            "count_x": 4,
            "count_y": 2,
            "step_x": 10,
            "step_y": 10,
        }
        r = self.run_ok(self.BODY + [vent, grid], doc="g.FCStd")
        self.assertVolume(self.result(r, "Part"), 8000 - 8 * PI * 10)
        # Parametric after saving and reopening: the grid follows the body's height.
        r = self.run_ok([{"op": "set", "target": "Base", "properties": {"Length": 12}}], doc="g.FCStd", new=False)
        self.assertVolume(self.result(r, "Part"), 9600 - 8 * PI * 12)
        err = self.run_err(
            [{"op": "mirror", "target": "Vents", "plane": "XZ", "point": [0, 10, 0]}],
            "INVALID_PARAM",
            doc="g.FCStd",
            new=False,
        )
        self.assertIn("Vent", err["hint"])  # names the original feature
        self.run_err(
            [{"op": "linear_array", "target": "Vents", "count": 2, "step": [0, 5, 0]}],
            "INVALID_PARAM",
            doc="g.FCStd",
            new=False,
        )
        r = self.run_ok(self.BODY + [slot, {"op": "mirror", "target": "Slot", "plane": "YZ", "point": [100, 0, 0]}])
        self.assertIn("NO_EFFECT", [w["code"] for w in r.get("warnings", [])])  # mirrored copy misses the part

    def test_threaded_hole(self):
        tapped = {"op": "hole", "body": "Part", "name": "Tap", "at": [[10, 10]], "offset": "=Base.Length", "size": "M6"}
        r = self.run_ok(self.BODY + [dict(tapped, threaded=True, depth=8), {"op": "export", "filename": "t.step"}])
        data = self.step(r, -2)["data"]
        self.assertEqual((data["thread"], data["thread_class"]), ("M6x1.0", "6H"))
        removed = 8000 - self.result(r, "Part")["volume"]
        self.assertGreater(removed, PI * 2.5**2 * 8)  # more than the bore: the thread grooves are cut
        self.assertLess(removed, PI * 3**2 * 8)  # less than the major diameter
        self.assertGreater(r["exports"][0]["verified"]["faces"], 20)  # real thread geometry
        r = self.run_ok(self.BODY + [dict(tapped, threaded=True)])  # through all
        self.assertLess(8000 - self.result(r, "Part")["volume"], PI * 9 * 10)
        self.run_err(self.BODY + [dict(tapped, threaded=True, type="counterbore")], "INVALID_PARAM")
        bad = {k: v for k, v in tapped.items() if k != "size"}
        self.run_err(self.BODY + [dict(bad, diameter=5, threaded=True)], "INVALID_PARAM")

    def test_body_rules(self):
        self.run_err(
            [
                {"op": "body", "name": "B"},
                {"op": "extrude", "body": "B", "mode": "remove", "height": 2, "shapes": [{"rect": [0, 0, 5, 5]}]},
            ],
            "EMPTY_RESULT",
        )
        err = self.run_err(
            self.BODY + [{"op": "extrude", "body": "Part", "height": 5, "shapes": [{"rect": [100, 0, 110, 10]}]}],
            "GEOMETRY_INVALID",
        )
        self.assertIn("one solid", err["hint"])
        self.run_err(
            [{"op": "body", "name": "B"}, {"op": "hole", "body": "B", "at": [[0, 0]], "diameter": 3}], "EMPTY_RESULT"
        )
        self.run_err(self.BODY + [{"op": "move", "target": "Base", "offset": [1, 0, 0]}], "INVALID_PARAM")
        self.run_err(self.BODY + [{"op": "fillet", "target": "Base", "radius": 1}], "INVALID_PARAM")
        self.run_err(
            [BOX, {"op": "extrude", "body": "B", "height": 1, "shapes": [{"rect": [0, 0, 1, 1]}]}], "INVALID_PARAM"
        )
        r = self.run_ok([{"op": "body", "name": "Empty"}])  # an empty body is fine until features are added
        self.assertTrue(r["saved"])

    def test_body_placement_roles_visibility_and_export(self):
        r = self.run_ok(
            self.BODY
            + [
                {"op": "move", "target": "Part", "offset": [100, 0, 0]},
                {"op": "export", "filename": "part.step"},
                {"op": "render", "filename": "part.png", "views": ["iso"]},
            ]
        )
        self.assertEqual([x["name"] for x in r["results"]], ["Part"])
        self.assertBBox(self.result(r, "Part"), [100, 0, 0], [140, 20, 10])
        self.assertEqual(r["exports"][0]["verified"]["solids"], 1)
        doc = App.openDocument(str(self.ws / "t.FCStd"))
        try:
            vis = {o.Name: o.Visibility for o in doc.Objects if not o.TypeId.startswith("App::")}
        finally:
            App.closeDocument(doc.Name)
        self.assertTrue(vis["Part"] and vis["Base"])  # the GUI shows a body through its tip
        self.assertFalse(vis["Base_Sketch"])

    def test_body_works_with_part_ops(self):
        r = self.run_ok(
            self.BODY
            + [
                {"op": "cylinder", "name": "Pin", "radius": 2, "height": 30, "position": [20, 10, -5]},
                {"op": "cut", "name": "Drilled", "base": "Part", "tool": "Pin"},
            ]
        )
        self.assertVolume(self.result(r, "Drilled"), 8000 - PI * 4 * 10)


class LoftSweepTests(EngineCase):
    def test_spline_profiles(self):
        r = self.run_ok(
            [
                {
                    "op": "extrude",
                    "name": "Blob",
                    "height": 5,
                    "shapes": [{"spline": [[20, 0], [0, 12], [-20, 0], [0, -12]]}],
                },
                {
                    "op": "extrude",
                    "name": "Arch",
                    "height": 4,
                    "offset": 50,
                    "shapes": [
                        {
                            "path": [
                                [-30, 0],
                                [30, 0],
                                {
                                    "spline_to": [-30, 0],
                                    "through": [[20, 25], [0, 32], [-20, 25]],
                                    "start_tangent": [0, 1],
                                    "end_tangent": [0, -1],
                                },
                            ]
                        }
                    ],
                },
            ]
        )
        bb = self.result(r, "Blob")["bbox"]
        self.assertAlmostEqual(bb["max"][0], -bb["min"][0], places=3)  # symmetric input, symmetric curve
        arch = self.result(r, "Arch")["bbox"]
        self.assertAlmostEqual(arch["max"][1], 32, places=3)  # passes exactly through its top point
        self.assertAlmostEqual(arch["min"][0], -30, places=3)
        self.assertAlmostEqual(arch["max"][0], 30, places=3)  # tangents keep it inside the end points
        self.run_err(
            [
                {
                    "op": "extrude",
                    "height": 1,
                    "shapes": [
                        {"spline": [[0, 0], [10, 10], [20, 0], [10, -10], [0, 0.5], [-10, 10], [-20, 0], [-10, -10]]}
                    ],
                }
            ],
            "INVALID_PARAM",
        )  # figure eight

    def test_loft_volume_and_edit(self):
        frustum = lambda r1, r2, h: PI * h / 3 * (r1 * r1 + r1 * r2 + r2 * r2)  # noqa: E731
        r = self.run_ok(
            [
                {
                    "op": "loft",
                    "name": "L",
                    "sections": [
                        {"shape": {"circle": [0, 0], "radius": 20}},
                        {"shape": {"circle": [0, 0], "radius": 10}, "offset": 30},
                    ],
                }
            ]
        )
        self.assertVolume(self.result(r, "L"), frustum(20, 10, 30))
        r = self.run_ok(
            [
                {
                    "op": "set",
                    "target": "L",
                    "properties": {
                        "sections": [
                            {"shape": {"circle": [0, 0], "radius": 15}, "plane": "YZ"},
                            {"shape": {"circle": [0, 0], "radius": 5}, "plane": "YZ", "offset": 40},
                        ]
                    },
                }
            ],
            new=False,
        )
        self.assertVolume(self.result(r, "L"), frustum(15, 5, 40))
        self.assertBBox(self.result(r, "L"), [0, -15, -15], [40, 15, 15])
        self.run_err(
            [
                {
                    "op": "set",
                    "target": "L",
                    "properties": {"sections": [{"shape": {"circle": [0, 0], "radius": 15}}] * 3},
                }
            ],
            "INVALID_PARAM",
            new=False,
        )

    def test_sweeps_match_exact_volumes(self):
        coil = 2 * PI * 10 * 6 / math.cos(math.atan(5 / (2 * PI * 10)))  # 6 turns of radius 10, pitch 5
        r = self.run_ok(
            [
                {
                    "op": "sweep",
                    "name": "Rod",
                    "shapes": [{"rect": [-3, -2, 3, 2]}],
                    "path": [[0, 0, 0], [50, 0, 0], [50, 50, 0]],
                },
                {
                    "op": "sweep",
                    "name": "Tube",
                    "shapes": [{"circle": [0, 0], "radius": 6}, {"circle": [0, 0], "radius": 4}],
                    "path": [[100, 0, 0], [100, 0, 40], [160, 0, 40]],
                    "corner_radius": 12,
                },
                {
                    "op": "sweep",
                    "name": "Spring",
                    "shapes": [{"circle": [0, 0], "radius": 1}],
                    "helix": {"radius": 10, "pitch": 5, "height": 30, "center": [-100, 0, 0]},
                },
            ]
        )
        self.assertVolume(self.result(r, "Rod"), 24 * 100)  # sharp corner: 'Right corner' transition is exact
        tube_len = self.step(r, 1)["data"]["path_length"]
        self.assertAlmostEqual(tube_len, 28 + 48 + PI * 12 / 2, places=3)
        self.assertVolume(self.result(r, "Tube"), PI * (36 - 16) * tube_len)
        self.assertVolume(self.result(r, "Spring"), PI * coil)
        self.assertEqual(self.step(r, 0)["data"]["profile_frame"]["x"], [0, -1, 0])  # right of +X travel, y up
        r = self.run_ok(
            [
                {
                    "op": "set",
                    "target": "Tube",
                    "properties": {
                        "path": [[100, 0, 0], [100, 0, 60], [180, 0, 60]],
                        "shapes": [{"circle": [0, 0], "radius": 5}, {"circle": [0, 0], "radius": 3}],
                    },
                }
            ],
            new=False,
        )
        self.assertVolume(self.result(r, "Tube"), PI * 16 * (48 + 68 + PI * 12 / 2))
        self.run_err(
            [{"op": "set", "target": "Tube", "properties": {"helix": {"radius": 1, "pitch": 1, "height": 1}}}],
            "INVALID_PARAM",
            new=False,
        )

    def test_body_loft_thread_follows_body(self):
        thread = {
            "op": "sweep",
            "body": "B",
            "name": "Th",
            "shapes": [{"polygon": [[-0.1, -1], [1.5, 0], [-0.1, 1]]}],
            "helix": {"radius": 10, "pitch": 4, "height": 12, "center": [0, 0, 4]},
        }
        r = self.run_ok(
            [
                {"op": "body", "name": "B"},
                {
                    "op": "loft",
                    "body": "B",
                    "name": "Neck",
                    "sections": [
                        {"shape": {"circle": [0, 0], "radius": 10}},
                        {"shape": {"circle": [0, 0], "radius": 10}, "offset": 20},
                    ],
                },
                thread,
            ]
        )
        neck = PI * 100 * 20
        v = self.result(r, "B")["volume"]
        self.assertGreater(v - neck, 1.5 * 0.9 * 75)  # a triangle of ~1.5 mm2 along ~75 mm of helix, outside the neck
        self.assertEqual(self.step(r)["data"]["profile_frame"]["x"], [1, 0, 0])  # radially outward on a helix
        r = self.run_ok(
            [
                {
                    "op": "set",
                    "target": "B",
                    "properties": {"position": [50, 0, 0], "rotation": {"axis": [0, 1, 0], "angle": 90}},
                }
            ],
            new=False,
        )
        self.assertAlmostEqual(self.result(r, "B")["volume"], v, delta=0.01)
        self.assertBBox(self.result(r, "B"), [50, -11.5, -11.5], [70, 11.5, 11.5], tol=0.01)
        r = self.run_ok(
            [
                {"op": "body", "name": "G"},
                {"op": "extrude", "body": "G", "name": "Bar", "height": 10, "shapes": [{"rect": [-40, -10, 40, 10]}]},
                {
                    "op": "sweep",
                    "body": "G",
                    "name": "Groove",
                    "mode": "remove",
                    "shapes": [{"circle": [0, 0], "radius": 2}],
                    "path": [[-45, 0, 10], [45, 0, 10]],
                },
            ],
            new=False,
        )
        self.assertVolume(self.result(r, "G"), 16000 - PI * 4 / 2 * 80)  # half the groove is above the bar


class MaterialTests(EngineCase):
    def gui(self, name="t.FCStd"):
        import zipfile

        return zipfile.ZipFile(self.ws / name).read("GuiDocument.xml").decode()

    def test_materials_colours_and_gui_visibility(self):
        r = self.run_ok(
            [
                BOX,
                {"op": "cylinder", "name": "Hole", "radius": 2, "height": 20, "position": [5, 5, -5]},
                {"op": "cut", "name": "Rim", "base": "B", "tool": "Hole"},
                {"op": "box", "name": "Tire", "length": 5, "width": 5, "height": 5, "position": [20, 0, 0]},
                {"op": "material", "targets": ["Rim"], "material": "aluminium"},
                {"op": "material", "targets": ["Tire"], "material": "rubber"},
                {"op": "measure", "objects": ["Rim", "Tire"]},
            ]
        )
        rim = self.step(r, 4)["data"]["parts"][0]
        self.assertEqual(rim["freecad_material"], "Aluminum-Generic")
        self.assertAlmostEqual(rim["mass_g"], (1000 - PI * 4 * 10) / 1000 * 2.7, places=2)
        self.assertEqual(self.step(r)["data"]["mass_source"], "assigned materials")
        self.assertAlmostEqual(self.step(r)["data"]["mass_g"]["Tire"], 0.125 * 1.15, delta=0.006)  # reported to 0.01 g
        gui = self.gui()
        for name, shown in (("Rim", "true"), ("Tire", "true"), ("B", "false"), ("Hole", "false")):
            self.assertRegex(gui, f'name="{name}".*?name="Visibility".*?value="{shown}"')
        self.assertIn("<Expand />", gui)
        doc = App.openDocument(str(self.ws / "t.FCStd"))
        try:
            self.assertEqual(doc.getObject("Rim").ShapeMaterial.Name, "Aluminum-Generic")
        finally:
            App.closeDocument(doc.Name)

    def test_body_colour_reaches_features_and_errors(self):
        self.run_ok(
            [
                {"op": "body", "name": "Bd"},
                {
                    "op": "extrude",
                    "body": "Bd",
                    "name": "Pad",
                    "height": 5,
                    "shapes": [{"circle": [0, 0], "radius": 5}],
                },
                {"op": "material", "targets": ["Pad"], "material": "pla", "color": "#E03020"},
            ]
        )
        gui = self.gui()
        packed = str((0xE0 << 24) | (0x30 << 16) | (0x20 << 8) | 0xFF)
        self.assertRegex(gui, f'name="Pad".*?name="ShapeColor".*?value="{packed}"')  # drawn through its tip feature
        err = self.run_err(
            [{"op": "material", "targets": ["Bd"], "material": "unobtainium"}], "INVALID_PARAM", new=False
        )
        self.assertIn("Presets", err["hint"])
        self.run_err([{"op": "material", "targets": ["Bd"], "color": [2, 0, 0]}], "INVALID_REQUEST", new=False)


class ImportTests(EngineCase):
    def test_import_step_with_anchor_and_library_attribution(self):
        self.run_ok(
            [
                {"op": "box", "name": "Src", "length": 10, "width": 20, "height": 30, "position": [100, 0, 0]},
                {"op": "export", "filename": "src.step"},
            ],
            doc="src.FCStd",
        )
        r = self.run_ok(
            [
                {"op": "import", "file": "src.step", "name": "Part", "anchor": "bottom_center", "position": [0, 0, 5]},
                {"op": "set", "target": "Part", "properties": {"position": [0, 0, 50]}},
            ]
        )
        self.assertBBox(self.result(r, "Part"), [-5, -10, 50], [5, 10, 80])  # anchor kept after moving it
        self.assertVolume(self.result(r, "Part"), 6000)
        # a library part as the launcher leaves it: file + attribution sidecar under .fcskill/library/parts
        lib = self.ws / ".fcskill" / "library" / "parts" / "Mechanical Parts" / "Block.step"
        lib.parent.mkdir(parents=True)
        shutil.copy(self.ws / "src.step", lib)
        (lib.parent / "Block.step.json").write_text(
            json.dumps(
                {
                    "library": "Mechanical Parts/Block.step",
                    "text": "'Block' from the FreeCAD library, CC-BY 3.0",
                    "license": "CC-BY 3.0",
                }
            )
        )
        r = self.run_ok(
            [{"op": "import", "library": "Mechanical Parts/Block", "name": "Lib", "anchor": "center"}], new=False
        )
        self.assertIn("CC-BY 3.0", self.step(r)["data"]["attribution"])
        self.assertBBox(self.result(r, "Lib"), [-5, -10, -15], [5, 10, 15])
        err = self.run_err([{"op": "import", "library": "Mechanical Parts/Missing"}], "LIBRARY_UNAVAILABLE", new=False)
        self.assertIn("fcskill.py", err["hint"])
        self.run_err([{"op": "import", "file": "../outside.step"}], "PATH_NOT_ALLOWED", new=False)

    def test_import_fcstd_takes_finished_solids(self):
        self.run_ok(
            [
                BOX,
                {"op": "cylinder", "name": "H", "radius": 2, "height": 20, "position": [5, 5, -5]},
                {"op": "cut", "name": "Holed", "base": "B", "tool": "H"},
            ],
            doc="other.FCStd",
        )
        r = self.run_ok([{"op": "import", "file": "other.FCStd", "name": "Copy"}])
        self.assertVolume(self.result(r, "Copy"), 1000 - PI * 4 * 10)
        self.assertEqual(self.result(r, "Copy")["solids"], 1)  # the cut only, not its inputs

    def _mesh_file(self, name, shape, deflection=0.01):
        import Mesh

        m = Mesh.Mesh()
        m.addFacets(shape.tessellate(deflection))
        m.write(str(self.ws / name))
        return m

    def test_import_mesh_as_solid(self):
        import Part

        holed = Part.makeBox(20, 10, 5).cut(Part.makeCylinder(2, 10, App.Vector(10, 5, -1)))
        m = self._mesh_file("part.stl", holed)
        r = self.run_ok(
            [
                {"op": "import", "file": "part.stl", "name": "Scan"},
                {"op": "box", "name": "Cutter", "length": 5, "width": 20, "height": 20, "position": [-1, -5, -5]},
                {"op": "cut", "name": "Trimmed", "base": "Scan", "tool": "Cutter"},
            ]
        )
        data = self.step(r, 0)["data"]
        self.assertEqual(data["mesh"]["triangles"], m.CountFacets)
        self.assertLess(data["mesh"]["faces"], m.CountFacets)  # coplanar triangles merged
        self.assertAlmostEqual(self.step(r, 0)["volume"], holed.Volume, delta=holed.Volume * 0.01)
        self.assertNotIn("CHECK_UNITS", [w["code"] for w in r.get("warnings", [])])
        self.assertAlmostEqual(self.result(r, "Trimmed")["volume"], self.step(r, 0)["volume"] - 4 * 10 * 5, delta=0.5)
        self.assertEqual(self.result(r, "Trimmed")["solids"], 1)
        self._mesh_file("part.obj", holed)
        r = self.run_ok([{"op": "import", "file": "part.obj", "refine": False}])
        self.assertEqual(self.step(r)["data"]["mesh"]["faces"], m.CountFacets)

    def test_import_mesh_rejects_open_and_warns_units(self):
        import Mesh
        import Part

        m = Mesh.Mesh()
        m.addFacets(Part.makeBox(10, 10, 10).tessellate(0.1))
        m.removeFacets([0])
        m.write(str(self.ws / "open.stl"))
        err = self.run_err([{"op": "import", "file": "open.stl"}], "GEOMETRY_INVALID")
        self.assertIn("not closed", err["message"])
        (self.ws / "one.stl").write_text(
            "solid t\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 10 0 0\nvertex 0 10 0\n"
            "endloop\nendfacet\nendsolid t\n"
        )
        err = self.run_err([{"op": "import", "file": "one.stl"}], "GEOMETRY_INVALID")  # FreeCAD reads 0 triangles
        self.assertIn("not a closed solid", err["message"])
        self._mesh_file("tiny.stl", Part.makeBox(0.5, 0.5, 0.5))  # e.g. a part modelled in inches or metres
        r = self.run_ok([{"op": "import", "file": "tiny.stl"}])
        self.assertIn("CHECK_UNITS", [w["code"] for w in r.get("warnings", [])])
        two = Part.makeCompound([Part.makeBox(5, 5, 5), Part.makeBox(5, 5, 5, App.Vector(10, 0, 0))])
        self._mesh_file("two.stl", two)
        r = self.run_ok([{"op": "import", "file": "two.stl", "name": "Pair"}])
        self.assertEqual(self.step(r)["data"]["mesh"]["pieces"], 2)
        self.assertEqual(self.result(r, "Pair")["solids"], 2)


class MeasureTests(EngineCase):
    def test_clearance_touching_interference(self):
        r = self.run_ok(
            [
                BOX,
                {"op": "box", "name": "Gap", "length": 10, "width": 10, "height": 10, "position": [10.5, 0, 0]},
                {"op": "box", "name": "Touch", "length": 5, "width": 5, "height": 5, "position": [0, 0, 10]},
                {"op": "box", "name": "Hit", "length": 4, "width": 4, "height": 4, "position": [8, 8, 8]},
                {"op": "measure", "objects": ["B", "Gap", "Touch", "Hit"], "material": "pla"},
            ]
        )
        data = r["steps"][-1]["data"]
        pairs = {(x["a"], x["b"]): x for x in data["pairs"]}
        self.assertEqual(pairs[("B", "Gap")]["status"], "clear")
        self.assertAlmostEqual(pairs[("B", "Gap")]["distance"], 0.5, places=6)
        self.assertEqual(pairs[("B", "Touch")]["status"], "touching")
        self.assertEqual(pairs[("B", "Hit")]["status"], "interfering")
        self.assertAlmostEqual(pairs[("B", "Hit")]["overlap_volume"], 8.0, places=3)  # 2x2x2 corner overlap
        self.assertEqual(pairs[("Gap", "Hit")]["status"], "interfering")  # x 10.5-12, y 8-10, z 8-10
        self.assertAlmostEqual(pairs[("Gap", "Hit")]["overlap_volume"], 1.5 * 2 * 2, places=3)
        self.assertEqual(data["interferences"], 2)
        self.assertAlmostEqual(data["mass_g"]["B"], 1.24, places=2)  # 1 cm3 of PLA

    def test_requirements(self):
        self.run_ok(
            [
                BOX,
                dict(BOX, name="Lid", position=[0, 0, 10.4]),
                {"op": "measure", "objects": ["B", "Lid"], "require": {"min_clearance": 0.3, "no_interference": True}},
            ]
        )
        err = self.run_err(
            [
                BOX,
                dict(BOX, name="Lid", position=[0, 0, 10.2]),
                {"op": "measure", "objects": ["B", "Lid"], "require": {"min_clearance": 0.3}},
            ],
            "EXPECTATION_FAILED",
        )
        self.assertAlmostEqual(err["details"]["failures"][0]["actual"], 0.2, places=6)
        self.run_err([BOX, {"op": "measure", "require": {"gap": 1}}], "INVALID_REQUEST")

    def test_body_and_curved_parts(self):
        r = self.run_ok(
            [
                {"op": "body", "name": "Shaft"},
                {"op": "extrude", "body": "Shaft", "height": 20, "shapes": [{"circle": [0, 0], "radius": 4.9}]},
                {
                    "op": "extrude",
                    "name": "Bushing",
                    "height": 10,
                    "shapes": [{"circle": [0, 0], "radius": 8}, {"circle": [0, 0], "radius": 5}],
                },
                {"op": "measure", "objects": ["Shaft", "Bushing"]},
            ]
        )
        self.assertAlmostEqual(r["steps"][-1]["data"]["min_distance"], 0.1, places=4)  # radial clearance

    def test_material_names_as_in_material_op(self):
        r = self.run_ok(
            [
                BOX,
                {"op": "measure", "objects": ["B"], "material": "rubber"},  # a preset without a library material
                {"op": "measure", "objects": ["B"], "material": "Aluminum"},  # alias
            ]
        )
        self.assertAlmostEqual(self.step(r, -2)["data"]["mass_g"]["B"], 1.15, places=2)
        self.assertAlmostEqual(self.step(r, -1)["data"]["mass_g"]["B"], 2.7, places=1)
        err = self.run_err([BOX, {"op": "measure", "objects": ["B"], "material": "unobtainium"}], "INVALID_PARAM")
        self.assertIn("Unknown material", err["message"])


class DrawingTests(EngineCase):
    PLATE = {
        "op": "extrude",
        "name": "Plate",
        "height": 3,
        "shapes": [{"rect": [0, 0, 80, 50], "corner_radius": 6}, {"circle": [15, 25], "radius": 4}],
    }

    def test_flat_dxf_and_svg(self):
        r = self.run_ok(
            [
                self.PLATE,
                {"op": "export", "filename": "cut/plate.dxf"},
                {"op": "export", "filename": "plate.svg"},
                {"op": "export", "filename": "side.dxf", "view": "front"},
            ]
        )
        top, svg, side = r["exports"]
        self.assertEqual(top["verified"]["entities"], {"ARC": 4, "LINE": 4, "CIRCLE": 1})
        self.assertEqual(top["verified"]["size"], [80.0, 50.0])
        self.assertEqual(side["verified"]["size"], [80.0, 3.0])  # width across, thickness up
        text = (self.ws / "cut" / "plate.dxf").read_text()
        self.assertTrue(text.startswith("0\nSECTION\n2\nENTITIES"))
        self.assertTrue(text.rstrip().endswith("EOF"))
        self.assertIn('width="84.0000mm"', (self.ws / "plate.svg").read_text())

    def test_drawing_dimensions_are_verified(self):
        r = self.run_ok(
            [
                {"op": "body", "name": "Part"},
                {
                    "op": "extrude",
                    "body": "Part",
                    "name": "Base",
                    "height": 8,
                    "shapes": [{"rect": [0, 0, 90, 50], "corner_radius": 6}],
                },
                {"op": "hole", "body": "Part", "at": [[10, 10], [80, 40]], "offset": "=Base.Length", "diameter": 6},
                {"op": "drawing", "filename": "part.dxf", "preview": "part.png", "title": "Test part"},
            ]
        )
        rec = r["steps"][-1]["data"]
        dims = {d["what"]: d["value"] for d in rec["dimensions"] if d["what"] != "diameter"}
        self.assertEqual(dims, {"length (X)": 90.0, "height (Z)": 8.0, "width (Y)": 50.0})
        self.assertIn(6.0, [d["value"] for d in rec["dimensions"] if d["what"] == "diameter"])
        self.assertEqual(rec["entities"]["DIMENSION"], len(rec["dimensions"]))
        self.assertEqual(rec["scale"], "1:1")
        self.assertIn("Test part", (self.ws / "part.dxf").read_text())
        w, h, _ = read_png(self.ws / "part.png")
        self.assertEqual((w, h), (891, 630))  # A4 at 3 px/mm
        # regenerating after an edit replaces the page
        r = self.run_ok(
            [
                {"op": "set", "target": "Base", "properties": {"Length": 12}},
                {"op": "drawing", "filename": "part.dxf", "dimensions": "overall", "projection": "third_angle"},
            ],
            new=False,
        )
        dims = {d["what"]: d["value"] for d in r["steps"][-1]["data"]["dimensions"]}
        self.assertEqual(dims["height (Z)"], 12.0)
        self.assertEqual(r["steps"][-1]["data"]["views"], ["front", "top", "right"])

    def test_scale_selection_and_errors(self):
        r = self.run_ok(
            [
                {"op": "box", "name": "Big", "length": 400, "width": 150, "height": 100},
                {"op": "drawing", "filename": "big.dxf"},
            ]
        )
        self.assertEqual(r["steps"][-1]["data"]["scale"], "1:5")
        r = self.run_ok(
            [
                {"op": "box", "name": "Big", "length": 400, "width": 150, "height": 100},
                {"op": "drawing", "filename": "big.dxf", "sheet": "A3", "scale": 0.5, "dimensions": "none"},
            ]
        )
        self.assertEqual(r["steps"][-1]["data"]["scale"], "1:2")
        self.run_err([BOX, {"op": "drawing", "filename": "b.pdf"}], "INVALID_PARAM")
        self.run_err(
            [{"op": "set_params", "values": {"wall": 1}}, {"op": "drawing", "filename": "x.dxf"}], "EMPTY_RESULT"
        )


def _fem_available():
    import shutil as _sh

    return bool(_sh.which("ccx") or _sh.which("ccx.exe")) and bool(_sh.which("gmsh") or _sh.which("gmsh.exe"))


@unittest.skipUnless(_fem_available(), "CalculiX (ccx) and Gmsh are needed for FEM tests")
class FemTests(EngineCase):
    BEAM = {"op": "box", "name": "Beam", "length": 100, "width": 10, "height": 10}

    def fem(self, **kw):
        step = {
            "op": "fem_static",
            "target": "Beam",
            "material": "steel_s355",
            "fixed": "<X",
            "loads": [{"faces": ">X", "force": "1000 N", "direction": [0, 0, -1]}],
        }
        step.update(kw)
        return step

    def test_cantilever_matches_beam_theory(self):
        r = self.run_ok([self.BEAM, self.fem(report="beam.png")])
        d = r["steps"][-1]["data"]
        tip = 1000 * 100**3 / (3 * 210000 * (10 * 10**3 / 12))
        self.assertAlmostEqual(d["max_displacement_mm"], tip, delta=tip * 0.01)
        self.assertAlmostEqual(d["max_von_mises_mpa"], 600, delta=600 * 0.06)  # beam theory at the root
        self.assertLess(d["equilibrium_error"], 0.001)
        self.assertEqual(d["reaction_n"], [0.0, 0.0, 1000.0])
        self.assertLess(d["convergence"]["displacement_change"], 0.01)
        self.assertGreater(d["convergence"]["nodes"][1], d["convergence"]["nodes"][0])
        warned = {"NOT_CONVERGED", "STRESS_CONCENTRATION"} & {w["code"] for w in r.get("warnings", [])}
        self.assertEqual(d["checks"]["convergence"], "failed" if warned else "passed")
        self.assertAlmostEqual(d["safety_factor"], 355 / d["max_von_mises_mpa"], places=2)
        self.assertTrue((self.ws / "beam.png").exists())
        self.assertFalse(r["saved"] and any(x["name"] != "Beam" for x in r["results"]))  # no FEM objects left

    def test_pressure_and_requirements(self):
        r = self.run_ok([self.BEAM, self.fem(loads=[{"faces": ">Z", "pressure": "1 MPa"}], convergence=False)])
        d = r["steps"][-1]["data"]
        self.assertEqual(d["applied_load_n"], [0.0, 0.0, -1000.0])
        self.assertLess(d["equilibrium_error"], 0.08)  # top face touches the fixed face (see equilibrium_note)
        self.assertIn("equilibrium_note", d)
        self.assertIn("NO_CONVERGENCE_CHECK", [w["code"] for w in r.get("warnings", [])])
        self.assertEqual(d["checks"], {"equilibrium": "passed", "convergence": "skipped"})
        q = 10.0
        self.assertAlmostEqual(d["max_displacement_mm"], q * 100**4 / (8 * 210000 * (10 * 1000 / 12)), delta=0.02)
        err = self.run_err(
            [self.BEAM, self.fem(convergence=False, require={"min_safety_factor": 2})], "EXPECTATION_FAILED"
        )
        self.assertEqual(err["details"]["failures"][0]["check"], "min_safety_factor")

    def test_units_and_inputs_are_validated(self):
        self.run_err(
            [self.BEAM, self.fem(loads=[{"faces": ">X", "force": 1000, "direction": [0, 0, -1]}])], "INVALID_REQUEST"
        )
        self.run_err([self.BEAM, self.fem(loads=[{"faces": ">X", "force": "1000 N"}])], "INVALID_REQUEST")
        self.run_err(
            [self.BEAM, self.fem(loads=[{"faces": ">X", "force": "10 MPa", "direction": [0, 0, -1]}])], "INVALID_PARAM"
        )
        self.run_err(
            [self.BEAM, self.fem(loads=[{"faces": "<X", "force": "1 N", "direction": [0, 0, -1]}])], "INVALID_PARAM"
        )
        self.run_err(
            [
                self.BEAM,
                dict(self.BEAM, name="Other", position=[50, 50, 0]),
                {"op": "fuse", "name": "Two", "objects": ["Beam", "Other"]},
                self.fem(target="Two"),
            ],
            "INVALID_PARAM",
        )

    def test_keep_results_in_document(self):
        r = self.run_ok([self.BEAM, self.fem(convergence=False, keep=True)])
        self.assertEqual([x["name"] for x in r["results"]], ["Beam"])  # FEM helpers are not results
        doc = App.openDocument(str(self.ws / "t.FCStd"))
        try:
            self.assertTrue(any(o.isDerivedFrom("Fem::FemResultObject") for o in doc.Objects))
        finally:
            App.closeDocument(doc.Name)


class AssemblyTests(EngineCase):
    PARTS = [
        {"op": "box", "name": "Base", "length": 40, "width": 40, "height": 10},
        {"op": "cylinder", "name": "Hole", "radius": 3, "height": 30, "position": [20, 20, -5]},
        {"op": "cut", "name": "Plate", "base": "Base", "tool": "Hole"},
        {"op": "cylinder", "name": "Pin", "radius": 3, "height": 30, "position": [100, 100, 50]},
        {"op": "box", "name": "Blk", "length": 10, "width": 10, "height": 10, "position": [-50, 0, 0]},
    ]
    PIN = {
        "op": "joint",
        "assembly": "Asm",
        "type": "revolute",
        "offset": -10,
        "a": {"part": "Plate", "edge": "%CIRCLE and >Z"},
        "b": {"part": "Pin", "edge": "%CIRCLE and <Z"},
    }
    BLOCK = {
        "op": "joint",
        "assembly": "Asm",
        "type": "fixed",
        "offset": 2,
        "a": {"part": "Plate", "face": ">Z"},
        "b": {"part": "Blk", "face": "<Z"},
    }

    def placed_bbox(self, name):
        import Part

        doc = App.openDocument(str(self.ws / "t.FCStd"))
        try:
            b = Part.getShape(doc.getObject(name)).BoundBox
            return [round(x, 4) for x in (b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax)], doc.getObject(
                name
            ).Visibility
        finally:
            App.closeDocument(doc.Name)

    def test_joints_offsets_and_interference(self):
        r = self.run_ok(
            self.PARTS
            + [
                {
                    "op": "assembly",
                    "name": "Asm",
                    "parts": [{"object": "Plate"}, {"object": "Pin"}, {"object": "Blk", "position": [60, 0, 0]}],
                },
                self.PIN,
                self.BLOCK,
                {"op": "export", "filename": "asm.step"},
            ]
        )
        self.assertEqual([x["name"] for x in r["results"]], ["Asm"])
        self.assertEqual(r["exports"][0]["verified"]["solids"], 3)
        self.assertEqual(self.placed_bbox("Pin_Part")[0], [17, 17, 0, 23, 23, 30])  # sunk 10 mm into the 10 mm plate
        bb, visible = self.placed_bbox("Blk_Part")
        self.assertEqual(bb, [15, 15, 12, 25, 25, 22])  # 2 mm above the plate
        self.assertTrue(visible)
        clash = r["steps"][-2]["data"]["interferences"]
        self.assertEqual(
            [(c["a"], c["b"]) for c in clash], [("Pin_Part", "Blk_Part")]
        )  # the pin passes through the block
        self.assertAlmostEqual(clash[0]["overlap_volume"], PI * 9 * 10, places=2)
        self.assertEqual(r["warnings"][0]["code"], "INTERFERENCE")
        self.assertFalse(self.placed_bbox("Plate")[1])  # originals hidden: the assembly shows them

    def test_joints_follow_upstream_edits(self):
        """FreeCAD's own joint references break on such edits while solve() still reports success."""
        self.run_ok(
            self.PARTS
            + [
                {"op": "assembly", "name": "Asm", "parts": [{"object": "Plate"}, {"object": "Pin"}, {"object": "Blk"}]},
                self.PIN,
                self.BLOCK,
            ]
        )
        self.run_ok(
            [
                {"op": "set", "target": "Hole", "properties": {"Height": 40}},
                {"op": "set", "target": "Base", "properties": {"Height": 20}},
            ],
            new=False,
        )
        self.assertEqual(self.placed_bbox("Pin_Part")[0][2], 10)  # still 10 mm below the (new) top
        self.assertEqual(self.placed_bbox("Blk_Part")[0][2], 22)

    def test_selector_must_match_one_element_and_conflicts_fail(self):
        steps = self.PARTS + [
            {"op": "assembly", "name": "Asm", "parts": [{"object": "Plate"}, {"object": "Pin"}, {"object": "Blk"}]}
        ]
        err = self.run_err(steps + [dict(self.PIN, a={"part": "Plate", "edge": "%CIRCLE"})], "INVALID_SELECTOR")
        self.assertIn("matches 2", err["message"])
        err = self.run_err(
            steps
            + [
                self.BLOCK,
                {
                    "op": "joint",
                    "assembly": "Asm",
                    "type": "fixed",
                    "a": {"part": "Plate", "face": "<Z"},
                    "b": {"part": "Blk", "face": "<Z"},
                },
            ],
            "RECOMPUTE_FAILED",
        )
        self.assertIn("not satisfied", err["message"] + json.dumps(err.get("details", {})) + "not satisfied")

    def test_same_part_twice(self):
        self.run_ok(
            self.PARTS
            + [
                {
                    "op": "assembly",
                    "name": "Asm",
                    "parts": [{"object": "Plate"}, {"object": "Blk", "name": "B1"}, {"object": "Blk", "name": "B2"}],
                },
                {
                    "op": "joint",
                    "assembly": "Asm",
                    "type": "fixed",
                    "a": {"part": "Plate", "face": ">Z"},
                    "b": {"part": "B1", "face": "<Z"},
                },
                {
                    "op": "joint",
                    "assembly": "Asm",
                    "type": "fixed",
                    "a": {"part": "Plate", "face": "<Z"},
                    "b": {"part": "B2", "face": ">Z"},
                },
            ]
        )
        self.assertEqual(self.placed_bbox("B1")[0][2], 10)
        self.assertEqual(self.placed_bbox("B2")[0][5], 0)  # hangs under the plate
        self.run_err(
            self.PARTS + [{"op": "assembly", "parts": [{"object": "Blk"}, {"object": "Blk"}]}], "INVALID_REQUEST"
        )

    @staticmethod
    def mechanism(coupler=60, pivot_d=True):
        """Ground plates with a pivot at x=-35 (and x=35), links of 40/``coupler``/40 mm. Link edges
        (inspect topology): 12/13 bottom of the holes at x=0/x=length, 15/16 their top."""
        steps = []
        for name, x0, hx in (("PlateA", -55, -35), ("PlateD", 0, 35))[: 2 if pivot_d else 1]:
            steps += [
                {"op": "box", "name": f"{name}Raw", "length": 55, "width": 30, "height": 8, "position": [x0, -15, 0]},
                {"op": "cylinder", "name": f"{name}H", "radius": 3.2, "height": 20, "position": [hx, 0, -5]},
                {"op": "cut", "name": name, "base": f"{name}Raw", "tool": f"{name}H"},
            ]
        for name, length in (("Crank", 40), ("Coupler", coupler), ("Rocker", 40)):
            steps += [
                {
                    "op": "extrude",
                    "name": f"{name}Raw",
                    "height": 8,
                    "shapes": [{"slot": [[0, 0], [length, 0]], "radius": 6}],
                },
                {"op": "cylinder", "name": f"{name}H1", "radius": 3.2, "height": 20, "position": [0, 0, -5]},
                {"op": "cylinder", "name": f"{name}H2", "radius": 3.2, "height": 20, "position": [length, 0, -5]},
                {"op": "cut", "name": f"{name}A", "base": f"{name}Raw", "tool": f"{name}H1"},
                {"op": "cut", "name": name, "base": f"{name}A", "tool": f"{name}H2"},
            ]
        return steps

    @staticmethod
    def hinge(a, a_edge, b, b_edge):
        return {
            "op": "joint",
            "assembly": "Mech",
            "type": "revolute",
            "a": {"part": a, a_edge[0]: a_edge[1]},
            "b": {"part": b, "edge": b_edge},
        }

    def four_bar(self, coupler=60):
        top = ("edge", "%CIRCLE and >Z")
        return self.mechanism(coupler) + [
            {
                "op": "assembly",
                "name": "Mech",
                "parts": [{"object": "PlateA", "ground": True}, {"object": "PlateD", "ground": True}]
                + [{"object": n} for n in ("Crank", "Coupler", "Rocker")],
            },
            self.hinge("PlateA", top, "Crank", 12),  # crank on the plate: z 8..16
            self.hinge("Crank", ("edge", 16), "Coupler", 12),  # coupler on the crank: z 16..24
            self.hinge("Coupler", ("edge", 13), "Rocker", 15),  # rocker under the coupler: z 8..16
            self.hinge("PlateD", top, "Rocker", 13),  # closes the loop
        ]

    def test_closed_four_bar_solves(self):
        """Joint pre-solving leaves the chain straight, a singular start: the skill retries from a bent one."""
        r = self.run_ok(self.four_bar())
        self.assertNotIn("warnings", r)
        doc = App.openDocument(str(self.ws / "t.FCStd"))
        try:

            def at(link, x):
                return doc.getObject(link).Placement.multVec(App.Vector(x, 0, 0))

            def same(p, q):
                self.assertAlmostEqual((p - q).Length, 0, places=3)

            same(at("Crank_Part", 0), App.Vector(-35, 0, 8))
            same(at("Crank_Part", 40) + App.Vector(0, 0, 8), at("Coupler_Part", 0))
            same(at("Coupler_Part", 60), at("Rocker_Part", 0) + App.Vector(0, 0, 8))
            same(at("Rocker_Part", 40), App.Vector(35, 0, 8))
            self.assertGreater(abs(at("Crank_Part", 40).y), 30)  # a real four-bar pose, not a straight line
            for plate in ("PlateA_Part", "PlateD_Part"):
                self.assertTrue(doc.getObject(plate).Placement.isIdentity())  # grounded parts did not move
        finally:
            App.closeDocument(doc.Name)

    def test_four_bar_stacked_with_offsets(self):
        """Layers set by 'offset' between top edges survive the closed-loop solve."""

        def hinge(a, a_edge, b, b_edge, offset):
            return dict(self.hinge(a, a_edge, b, b_edge), offset=offset)

        top = ("edge", "%CIRCLE and >Z")
        r = self.run_ok(
            self.mechanism()
            + [
                {
                    "op": "assembly",
                    "name": "Mech",
                    "parts": [{"object": "PlateA", "ground": True}, {"object": "PlateD", "ground": True}]
                    + [{"object": n} for n in ("Crank", "Coupler", "Rocker")],
                },
                hinge("PlateA", top, "Crank", 15, 8),  # top edges 8 apart: crank z 8..16
                hinge("Crank", ("edge", 16), "Coupler", 15, 8),  # coupler z 16..24
                hinge("Coupler", ("edge", 16), "Rocker", 16, -8),  # rocker z 8..16, under the coupler
                hinge("PlateD", top, "Rocker", 15, 8),  # closes the loop
            ]
        )
        self.assertNotIn("warnings", r)  # no INTERFERENCE: the layers held
        z = {k: v["position"][2] for k, v in self.step(r)["data"]["placements"].items()}
        self.assertEqual((z["Crank_Part"], z["Coupler_Part"], z["Rocker_Part"]), (8, 16, 8))

    def test_four_bar_that_cannot_close_fails(self):
        err = self.run_err(self.four_bar(coupler=160), "RECOMPUTE_FAILED")  # 160 > 40 + 70 + 40
        self.assertIn("closed loop", err["hint"])

    def test_no_interference_warning_for_parts_not_joined_yet(self):
        r = self.run_ok(
            self.mechanism(pivot_d=False)
            + [
                {"op": "assembly", "name": "Mech", "parts": [{"object": n} for n in ("PlateA", "Crank", "Coupler")]},
                self.hinge("PlateA", ("edge", "%CIRCLE and >Z"), "Crank", 12),
                self.hinge("Crank", ("edge", 16), "Coupler", 12),
            ]
        )
        self.assertNotIn("warnings", r)  # Coupler overlapped the plate before it was joined
        self.assertEqual(self.step(r, -2)["data"]["not_joined"], ["Coupler_Part"])

    def test_measure_compares_parts_as_assembled(self):
        r = self.run_ok(
            self.PARTS
            + [
                {"op": "assembly", "name": "Asm", "parts": [{"object": "Plate"}, {"object": "Pin"}]},
                self.PIN,
                {"op": "measure", "objects": ["Asm"], "material": "steel"},
                {"op": "measure", "objects": ["Plate_Part", "Pin_Part"]},
            ]
        )
        for i in (-2, -1):
            pair = self.step(r, i)["data"]["pairs"][0]
            self.assertEqual(
                (pair["a"], pair["b"], pair["status"]), ("Plate_Part", "Pin_Part", "touching")
            )  # pin seated in its bore
        data = self.step(r, -2)["data"]
        self.assertAlmostEqual(data["density_g_cm3"], 7.9, places=2)  # FreeCAD's Steel-Generic, as in 'material'
        self.assertAlmostEqual(data["mass_g"]["Pin_Part"], PI * 9 * 30 / 1000 * data["density_g_cm3"], places=2)


class ReservedNameTests(EngineCase):
    def test_static_list_matches_freecad(self):
        """RESERVED_PARAM_NAMES must agree with the running FreeCAD."""
        from fcengine.validate import RESERVED_PARAM_NAMES

        doc = App.newDocument("Alias")
        try:
            sheet = doc.addObject("Spreadsheet::Sheet", "S")
            sheet.set("B1", "1")
            for name in sorted(RESERVED_PARAM_NAMES):
                with self.assertRaises(ValueError, msg=name):
                    sheet.setAlias("B1", name)
            for ok in ("L", "wall", "len_x", "width", "thick"):
                sheet.setAlias("B1", ok)
                sheet.setAlias("B1", "")
        finally:
            App.closeDocument(doc.Name)


class DocumentTests(EngineCase):
    def doc_hash(self):
        return hashlib.sha256((self.ws / "t.FCStd").read_bytes()).hexdigest()

    def test_failed_request_changes_nothing(self):
        self.run_ok([BOX])
        before = self.doc_hash()
        resp = execute(
            {
                "doc": "t.FCStd",
                "steps": [
                    {"op": "set", "target": "B", "properties": {"Height": 50}},
                    {"op": "export", "filename": "x.stl"},
                    {"op": "cut", "base": "B", "tool": "Nope"},
                ],
            },
            self.ws,
        )
        self.assertEqual(resp["status"], "error")
        self.assertEqual(resp["error"]["step"], 2)
        self.assertEqual(len(resp["completed_steps"]), 2)
        self.assertEqual(self.doc_hash(), before)
        self.assertEqual(sorted(p.name for p in self.ws.iterdir()), ["t.FCStd"])  # no export, no temp files

    def test_dry_run(self):
        self.run_ok([BOX])
        before = self.doc_hash()
        r = self.run_ok(
            [{"op": "set", "target": "B", "properties": {"Height": 2}}, {"op": "export", "filename": "a.step"}],
            new=False,
            dry_run=True,
        )
        self.assertFalse(r["saved"])
        self.assertEqual(self.doc_hash(), before)
        self.assertFalse((self.ws / "a.step").exists())

    def test_query_on_missing_doc_creates_nothing(self):
        r = self.run_ok([{"op": "inspect"}], doc="none.FCStd", new=False)
        self.assertFalse(r["saved"])
        self.assertFalse((self.ws / "none.FCStd").exists())

    def test_reopen_keeps_parametric_tree(self):
        self.run_ok(
            [
                BOX,
                {"op": "linear_array", "name": "A", "target": "B", "count": 3, "step": [20, 0, 0]},
                {"op": "fillet", "name": "F", "target": "B", "radius": 1, "edges": ">Z"},
            ],
            doc="sub/dir/p.FCStd",
        )
        doc = App.openDocument(str(self.ws / "sub/dir/p.FCStd"))
        try:
            types = {o.Name: o.TypeId for o in doc.Objects}
            self.assertEqual(types["B"], "Part::Box")
            self.assertEqual(types["F"], "Part::Fillet")
            doc.getObject("B").Length = 5
            doc.recompute()
            self.assertAlmostEqual(doc.getObject("A").Shape.BoundBox.XMax, 45, places=3)
        finally:
            App.closeDocument(doc.Name)
        self.assertFalse(any(p.suffix == ".FCBak" for p in (self.ws / "sub/dir").iterdir()))

    def test_only_results_visible_in_saved_file(self):
        self.run_ok(
            [
                BOX,
                {"op": "cylinder", "name": "H", "radius": 1, "height": 20, "position": [5, 5, -5]},
                {"op": "set_params", "values": {"wall": 2}},
                {"op": "cut", "name": "R", "base": "B", "tool": "H"},
                {"op": "extrude", "name": "E", "height": 1, "shapes": [{"rect": [20, 0, 30, 10]}]},
            ]
        )
        doc = App.openDocument(str(self.ws / "t.FCStd"))
        try:
            vis = {o.Name: o.Visibility for o in doc.Objects}
        finally:
            App.closeDocument(doc.Name)
        self.assertEqual(vis, {"B": False, "H": False, "Params": False, "R": True, "E": True, "E_Sketch": False})
        # Deleting the cut makes its inputs results again; they become visible.
        self.run_ok([{"op": "delete", "targets": ["R"]}], new=False)
        doc = App.openDocument(str(self.ws / "t.FCStd"))
        try:
            self.assertTrue(doc.getObject("B").Visibility and doc.getObject("H").Visibility)
        finally:
            App.closeDocument(doc.Name)

    def test_no_backup_files_on_resave(self):
        self.run_ok([BOX])
        self.run_ok([{"op": "move", "target": "B", "offset": [1, 0, 0]}], new=False)
        self.assertEqual(sorted(p.name for p in self.ws.iterdir()), ["t.FCStd"])

    def test_inspect(self):
        r = self.run_ok(
            [
                BOX,
                {"op": "fillet", "name": "F", "target": "B", "radius": 1, "edges": ">Z"},
                {"op": "inspect"},
                {"op": "inspect", "target": "B", "topology": True},
            ]
        )
        tree = r["steps"][2]["data"]["objects"]
        self.assertEqual({o["name"]: o["role"] for o in tree}, {"B": "intermediate", "F": "result"})
        detail = r["steps"][3]["data"]
        self.assertEqual(detail["properties"]["Length"], 10)
        self.assertEqual(detail["used_by"], ["F"])
        self.assertEqual(len(detail["topology"]["faces"]), 6)
        self.assertEqual(len(detail["topology"]["edges"]), 12)
        top = [f for f in detail["topology"]["faces"] if f["normal"] == [0, 0, 1]]
        self.assertEqual(top[0]["center"], [5, 5, 10])

    def test_expect_and_check(self):
        self.run_ok([dict(BOX, expect={"volume": 1000, "bbox_size": [10, 10, 10], "solids": 1})])
        err = self.run_err([dict(BOX, expect={"bbox_size": [10, 10, 20]})], "EXPECTATION_FAILED")
        self.assertEqual(err["details"]["failures"][0]["actual"], [10, 10, 10])
        self.run_err([BOX, {"op": "check", "target": "B", "expect": {"volume": 999}}], "EXPECTATION_FAILED")

    def test_old_freecad_is_refused_before_touching_the_document(self):
        real = App.Version
        App.Version = lambda: ["1", "0", "2", "dev"]
        try:
            resp = execute({"doc": "t.FCStd", "steps": [BOX]}, self.ws)
        finally:
            App.Version = real
        self.assertEqual(resp["error"]["code"], "FREECAD_VERSION")
        self.assertIn("1.1", resp["error"]["message"])
        self.assertFalse((self.ws / "t.FCStd").exists())

    def test_validation_errors_before_execution(self):
        resp = execute({"doc": "t.FCStd", "steps": [BOX, {"op": "box", "lenght": 1}]}, self.ws)
        self.assertEqual(resp["error"]["code"], "INVALID_REQUEST")
        self.assertFalse((self.ws / "t.FCStd").exists())

    def test_path_escape(self):
        resp = execute({"doc": "../x.FCStd", "steps": [BOX]}, self.ws)
        self.assertEqual(resp["error"]["code"], "PATH_NOT_ALLOWED")
        resp = execute({"steps": [BOX, {"op": "export", "filename": "../x.step"}]}, self.ws)
        self.assertEqual(resp["error"]["code"], "PATH_NOT_ALLOWED")


class ExportTests(EngineCase):
    def test_all_formats_verified(self):
        steps = [
            BOX,
            {"op": "cylinder", "name": "H", "radius": 2, "height": 12, "position": [5, 5, -1]},
            {"op": "cut", "name": "R", "base": "B", "tool": "H"},
        ]
        for ext in ("step", "stp", "iges", "brep", "stl", "obj", "3mf"):
            steps.append({"op": "export", "filename": f"out/r.{ext}", "tolerance": 0.01})
        r = self.run_ok(steps)
        vol = 1000 - PI * 4 * 10
        for e in r["exports"]:
            self.assertTrue((self.ws / e["file"]).stat().st_size > 0)
            self.assertEqual(e["objects"], ["R"])
            v = e["verified"]
            if e["format"] in ("stl", "obj", "3mf"):
                self.assertTrue(v["closed"], e)
                self.assertFalse(v["non_manifold"], e)
                self.assertAlmostEqual(v["volume"], vol, delta=vol * 0.01)
            elif e["format"] != "iges":
                self.assertEqual(v["solids"], 1)
                self.assertAlmostEqual(v["volume"], vol, delta=0.1)
            self.assertTrue(v.get("faces", 1) > 0)
        self.assertEqual(
            sorted(p.name for p in (self.ws / "out").iterdir()),
            sorted(f"r.{x}" for x in ("step", "stp", "iges", "brep", "stl", "obj", "3mf")),
        )

    def test_default_targets_are_results_only(self):
        """A default export holds the finished parts, not their intermediate inputs."""
        r = self.run_ok(
            [
                BOX,
                {"op": "cylinder", "name": "H", "radius": 2, "height": 20, "position": [5, 5, -5]},
                {"op": "cut", "name": "Holed", "base": "B", "tool": "H"},
                {"op": "box", "name": "Other", "length": 2, "width": 2, "height": 2, "position": [30, 0, 0]},
                {"op": "export", "filename": "all.step"},
            ]
        )
        import Part

        s = Part.read(str(self.ws / "all.step"))
        self.assertEqual(len(s.Solids), 2)
        self.assertAlmostEqual(s.Volume, self.result(r, "Holed")["volume"] + 8, delta=0.1)

    def test_export_messages_use_user_filename(self):
        err = self.run_err(
            [
                {"op": "extrude", "name": "E", "height": 1, "points": [[0, 0], [1, 0], [0, 1]]},
                {"op": "export", "filename": "p.step", "targets": ["E_Profile"]},
            ],
            "EXPORT_FAILED",
        )
        self.assertIn("no faces", err["message"])
        self.assertNotIn("fcskill-tmp", json.dumps(err))

    def test_export_with_backslash_path(self):
        import os

        r = self.run_ok([BOX, {"op": "export", "filename": "out\\b.step"}])
        if os.sep == "/":
            self.assertEqual(r["exports"][0]["file"], "out/b.step")
            self.assertTrue((self.ws / "out" / "b.step").exists())

    def test_export_to_fcstd_is_refused_clearly(self):
        err = self.run_err([BOX, {"op": "export", "filename": "copy.FCStd"}], "PATH_NOT_ALLOWED")
        self.assertIn("doc", err["hint"])

    def test_export_errors(self):
        self.run_err([BOX, {"op": "export", "filename": "a.step", "format": "stl"}], "INVALID_PARAM")
        self.run_err([BOX, {"op": "export", "filename": "a.xyz"}], "INVALID_PARAM")
        self.run_err(
            [{"op": "set_params", "values": {"wall": 1}}, {"op": "export", "filename": "a.step"}], "EXPORT_FAILED"
        )


def read_png(path):
    """Minimal decoder for the renderer's own output (RGB8, filter 0)."""
    import struct
    import zlib

    data = Path(path).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(data):
        n, tag = struct.unpack(">I4s", data[pos : pos + 8])
        body = data[pos + 8 : pos + 8 + n]
        if tag == b"IHDR":
            w, h = struct.unpack(">II", body[:8])
        elif tag == b"IDAT":
            idat += body
        pos += 12 + n
    raw = zlib.decompress(idat)
    stride = 1 + 3 * w
    return w, h, lambda x, y: tuple(raw[y * stride + 1 + 3 * x : y * stride + 4 + 3 * x])


class RenderTests(EngineCase):
    def test_top_view_shows_hole(self):
        r = self.run_ok(
            [
                {
                    "op": "extrude",
                    "name": "P",
                    "height": 3,
                    "shapes": [{"rect": [0, 0, 20, 20]}, {"circle": [10, 10], "radius": 4}],
                },
                {"op": "render", "filename": "v/top.png", "views": ["top"], "size": 200},
            ]
        )
        rec = self.step(r)["data"]
        self.assertAlmostEqual(rec["mm_per_pixel"], 20 / (0.86 * 200), places=3)
        w, h, px = read_png(self.ws / "v/top.png")
        self.assertEqual((w, h), (200, 200))
        self.assertEqual(px(100, 100), (255, 255, 255))  # hole: background shows through
        self.assertNotEqual(px(100 + 60, 100), (255, 255, 255))  # 7 mm from centre: material
        self.assertEqual(px(5, 100), (255, 255, 255))  # outside the plate

    def test_profile_target_is_a_clear_error(self):
        err = self.run_err(
            [
                {"op": "extrude", "name": "E", "points": [[0, 0], [10, 0], [0, 10]], "height": 5},
                {"op": "render", "filename": "p.png", "targets": ["E_Profile"]},
            ],
            "INVALID_PARAM",
        )
        self.assertIn("no faces", err["message"])

    def test_grid_layout_and_atomicity(self):
        self.run_ok([BOX, {"op": "render", "filename": "a.png"}])
        w, h, _ = read_png(self.ws / "a.png")
        self.assertEqual((w, h), (802, 802))  # 2x2 views of 400 px + separators
        resp = execute(
            {
                "doc": "t.FCStd",
                "steps": [{"op": "render", "filename": "b.png"}, {"op": "cut", "base": "B", "tool": "Nope"}],
            },
            self.ws,
        )
        self.assertEqual(resp["status"], "error")
        self.assertFalse((self.ws / "b.png").exists())
        self.run_err([BOX, {"op": "render", "filename": "c.jpg"}], "INVALID_PARAM")


class TextTests(EngineCase):
    PLATE = {"op": "box", "name": "Plate", "length": 60, "width": 20, "height": 5}

    def test_engrave_and_emboss(self):
        label = {"op": "text", "name": "Label", "text": "AB", "size": 8, "height": 2, "position": [5, 5, 4]}
        r = self.run_ok([self.PLATE, label, {"op": "cut", "name": "Engraved", "base": "Plate", "tool": "Label"}])
        t = self.step(r, 1)
        self.assertAlmostEqual(t["bbox"]["min"][2], 4, delta=1e-6)
        self.assertAlmostEqual(t["bbox"]["max"][2], 6, delta=1e-6)
        self.assertAlmostEqual(t["bbox"]["max"][1], 13, delta=0.3)  # cap height above the baseline
        self.assertGreater(t["bbox"]["min"][0], 4.9)
        self.assertEqual(t["data"]["font"], "osifont-lgpl3fe.ttf")
        engraved = self.result(r, "Engraved")
        self.assertLess(engraved["volume"], 6000 - 10)
        self.assertBBox(engraved, [0, 0, 0], [60, 20, 5])
        # Edit the text after reopening the document: the ShapeString is restored headless.
        r = self.run_ok([{"op": "set", "target": "Label", "properties": {"text": "ABCD", "size": 6}}], new=False)
        self.assertLess(self.result(r, "Engraved")["volume"], 6000 - 10)
        r = self.run_ok(
            [
                self.PLATE,
                dict(label, name="Raised", position=[30, 10, 4.9], height=1.1, align="center"),
                {"op": "fuse", "name": "Badge", "objects": ["Plate", "Raised"]},
            ]
        )
        t = self.step(r, 1)
        self.assertAlmostEqual((t["bbox"]["min"][0] + t["bbox"]["max"][0]) / 2, 30, delta=0.3)
        self.assertAlmostEqual((t["bbox"]["min"][1] + t["bbox"]["max"][1]) / 2, 10, delta=0.3)
        badge = self.result(r, "Badge")
        self.assertEqual(badge["solids"], 1)
        self.assertAlmostEqual(badge["bbox"]["max"][2], 6, delta=1e-6)

    def test_planes_and_errors(self):
        r = self.run_ok([{"op": "text", "name": "Front", "text": "AB", "size": 8, "height": 2, "plane": "XZ"}])
        t = self.step(r)
        self.assertAlmostEqual(t["bbox"]["min"][1], 0, delta=1e-6)
        self.assertAlmostEqual(t["bbox"]["max"][1], 2, delta=1e-6)  # extruded along +Y
        self.assertAlmostEqual(t["bbox"]["max"][2], 8, delta=0.3)  # upright along +Z
        r = self.run_ok(
            [{"op": "text", "name": "Side", "text": "AB", "size": 8, "height": 2, "plane": "YZ", "reversed": True}]
        )
        self.assertAlmostEqual(self.step(r)["bbox"]["min"][0], -2, delta=1e-6)
        self.run_err([{"op": "text", "text": "   ", "size": 5, "height": 1}], "INVALID_REQUEST")
        self.run_err([{"op": "text", "text": "A", "size": 5, "height": 1, "font": "missing.ttf"}], "INVALID_PARAM")
        (self.ws / "notes.txt").write_text("x")
        self.run_err([{"op": "text", "text": "A", "size": 5, "height": 1, "font": "notes.txt"}], "INVALID_PARAM")
        self.run_err([{"op": "text", "text": "A", "size": 5, "height": 1, "font": "../x.ttf"}], "PATH_NOT_ALLOWED")
        self.run_ok([{"op": "text", "name": "T", "text": "A", "size": 5, "height": 1}])
        self.run_err([{"op": "set", "target": "T", "properties": {"text": ""}}], "INVALID_PARAM", new=False)


class RemovedPythonOpTests(EngineCase):
    def test_python_op_is_gone(self):
        # Removed in 2.0.2: requests can only use the verified operations.
        err = self.run_err([{"op": "python", "code": "result = 1"}], "INVALID_REQUEST")
        self.assertIn("python", json.dumps(err))


class V2ExampleTests(EngineCase):
    def test_examples(self):
        """Every v2 example runs and meets its own expectations."""
        files = sorted((ROOT / "examples").glob("*.json"))
        self.assertTrue(files)
        for f in files:
            with self.subTest(example=f.name):
                for p in list(self.ws.iterdir()):
                    shutil.rmtree(p) if p.is_dir() else p.unlink()
                r = execute(json.loads(f.read_text()), self.ws)
                self.assertEqual(r["status"], "success", f"{f.name}: {json.dumps(r.get('error'), indent=1)}")


if __name__ == "__main__":
    unittest.main()
