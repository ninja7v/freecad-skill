"""Tests that need no FreeCAD: catalog, validation, selectors, profiles, library, paths, docs."""

import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fcengine import (  # noqa: E402
    catalog,
    compat,
    doclock,
    docs,
    errors,
    guidata,
    library,
    matdata,
    profiles,
    selectors,
    validate,
    workspace,
)


def problems(req):
    try:
        validate.validate_request(req)
    except errors.SkillError as e:
        return e.details.get("problems", [{"message": e.message}])
    return []


class CatalogTests(unittest.TestCase):
    def test_names_unique_and_params_sane(self):
        self.assertEqual(len(catalog.OPS), len(catalog.OPS_BY_NAME))
        for op in catalog.OPS:
            self.assertIn(op.category, catalog.CATEGORIES)
            names = [p.name for p in op.params]
            self.assertEqual(len(names), len(set(names)), op.name)
            for group in op.one_of:
                for g in group:
                    self.assertIsNotNone(op.param(g), f"{op.name}: one_of refers to unknown {g}")

    def test_examples_in_catalog_validate(self):
        for op in catalog.OPS:
            if op.example:
                if op.name in ("cut", "fillet", "linear_array", "set", "shell"):
                    continue  # reference other objects; validation is static so they still pass
                self.assertEqual(problems({"steps": [op.example]}), [], op.name)

    def test_describe_is_json_serialisable(self):
        import json

        json.dumps(catalog.describe())


class ValidationTests(unittest.TestCase):
    def test_valid_request_gets_defaults(self):
        req = validate.validate_request({"steps": [{"op": "box", "length": 1, "width": 2, "height": 3}]})
        self.assertEqual(req["doc"], "model.FCStd")
        self.assertEqual(req["steps"][0]["params"]["position"], [0, 0, 0])

    def test_reports_all_problems_with_suggestions(self):
        probs = problems(
            {
                "steps": [
                    {"op": "boxx"},
                    {"op": "box", "lenght": 3, "width": 1, "height": 1},
                    {"op": "cylinder", "radius": -1, "height": 2},
                ]
            }
        )
        msgs = " | ".join(p["message"] for p in probs)
        self.assertIn("Did you mean 'box'", msgs)
        self.assertIn("Did you mean 'length'", msgs)
        self.assertIn("missing required parameter 'length'", msgs)
        self.assertIn("must be > 0", msgs)
        self.assertEqual({p.get("step") for p in probs}, {0, 1, 2})

    def test_types(self):
        bad = [
            {"op": "box", "length": True, "width": 1, "height": 1},
            {"op": "box", "length": "10", "width": 1, "height": 1},
            {"op": "box", "length": 1, "width": 1, "height": 1, "position": [0, 0]},
            {"op": "box", "length": 1, "width": 1, "height": 1, "name": "has space"},
            {"op": "cylinder", "radius": 1, "height": 1, "direction": [0, 0, 0]},
            {"op": "fuse", "objects": ["A"]},
            {"op": "fillet", "target": "A", "radius": 1, "edges": [0]},
            {"op": "extrude", "points": [[0, 0], [1, 0], [0, 0]], "height": 1},
            {"op": "extrude", "points": [[0, 0], [1, 0], [0, 1]]},
            {"op": "extrude", "points": [[0, 0], [1, 0], [0, 1]], "height": 1, "direction": [0, 0, 1]},
            {"op": "torus", "radius1": 2, "radius2": 3},
            {"op": "cone", "radius1": 2, "radius2": 2, "height": 1},
            {"op": "delete"},
        ]
        for step in bad:
            self.assertTrue(problems({"steps": [step]}), step)

    def test_sub_precision_sizes_rejected(self):
        msgs = " | ".join(
            p["message"] for p in problems({"steps": [{"op": "box", "length": 1e-7, "width": 1, "height": 1}]})
        )
        self.assertIn("modelling precision", msgs)
        self.assertEqual(problems({"steps": [{"op": "box", "length": 1e-5, "width": 1, "height": 1}]}), [])

    def test_labels_are_free_text(self):
        self.assertEqual(problems({"steps": [{"op": "rename", "target": "B", "label": "Plaque de base é"}]}), [])
        for bad in (" lead", "tab\there", "x" * 101, ""):
            self.assertTrue(problems({"steps": [{"op": "rename", "target": "B", "label": bad}]}), bad)

    def test_expressions_accepted_only_where_declared(self):
        self.assertEqual(problems({"steps": [{"op": "box", "length": "=Params.w", "width": 1, "height": 1}]}), [])
        self.assertTrue(problems({"steps": [{"op": "box", "length": "Params.w", "width": 1, "height": 1}]}))
        self.assertTrue(problems({"steps": [{"op": "fillet", "target": "A", "radius": "=Params.r"}]}))

    def test_enum_normalised(self):
        req = validate.validate_request({"steps": [{"op": "mirror", "target": "A", "plane": "yz"}]})
        self.assertEqual(req["steps"][0]["params"]["plane"], "YZ")

    def test_single_step_shorthand(self):
        req = validate.validate_request({"doc": "a.FCStd", "op": "inspect"})
        self.assertEqual(req["steps"][0]["op"], "inspect")

    def test_envelope(self):
        self.assertTrue(problems({"steps": []}))
        self.assertTrue(problems({"doc": "x.step", "steps": [{"op": "inspect"}]}))
        self.assertTrue(problems({"stepz": [{"op": "inspect"}]}))

    def test_set_params_values(self):
        """OpenClaw report H3: NaN/Infinity and empty strings were stored."""
        for v in (float("nan"), float("inf"), True, None, [1], "", "="):
            self.assertTrue(problems({"steps": [{"op": "set_params", "values": {"wall": v}}]}), v)
        self.assertEqual(problems({"steps": [{"op": "set_params", "values": {"wall": 2, "ang": "15 deg"}}]}), [])

    def test_degenerate_arrays_and_reserved_names(self):
        """OpenClaw report M1, M7, L1."""
        self.assertTrue(problems({"steps": [{"op": "linear_array", "target": "C", "count": 4, "step": [0, 0, 0]}]}))
        self.assertTrue(
            problems(
                {"steps": [{"op": "grid_array", "target": "C", "count_x": 3, "count_y": 3, "step_x": 0, "step_y": 5}]}
            )
        )
        self.assertEqual(
            problems(
                {"steps": [{"op": "grid_array", "target": "C", "count_x": 1, "count_y": 3, "step_x": 0, "step_y": 5}]}
            ),
            [],
        )
        self.assertTrue(problems({"steps": [{"op": "render", "filename": "a.png", "size": 5000}]}))
        self.assertTrue(problems({"steps": [{"op": "box", "name": "Params", "length": 1, "width": 1, "height": 1}]}))

    def test_check_expectations_are_validated(self):
        """OpenClaw report H2: 'check' accepted typos, wrong lengths and bad types."""
        for exp in (
            {"mass": 1},
            {"solids": True},
            {"bbox_size": [10, 10]},
            {"bbox_size": [10, 10, 10, 10]},
            {"volume": "abc"},
            {"bbox_min": "x"},
            {"volume": -1},
            {"tolerance": 0.1},
            {},
        ):
            self.assertTrue(problems({"steps": [{"op": "check", "target": "B", "expect": exp}]}), exp)
            self.assertTrue(
                problems({"steps": [{"op": "box", "length": 1, "width": 1, "height": 1, "expect": exp}]}), exp
            )
        self.assertEqual(
            problems({"steps": [{"op": "check", "target": "B", "expect": {"solids": 1, "bbox_size": [1, 2, 3]}}]}), []
        )

    def test_reserved_parameter_names_reported_together(self):
        probs = problems(
            {"steps": [{"op": "set_params", "values": {"L": 100, "W": 70, "H": 35, "mm": 1, "A1": 2, "wall": 2}}]}
        )
        msgs = " | ".join(p["message"] for p in probs)
        for bad in ("'W'", "'H'", "'mm'", "'A1'"):
            self.assertIn(bad, msgs)
        self.assertNotIn("'L'", msgs)  # accepted by FreeCAD
        self.assertNotIn("'wall'", msgs)
        self.assertIn("'width'", msgs)  # suggestion

    def test_expect_validation(self):
        self.assertEqual(
            problems({"steps": [{"op": "box", "length": 1, "width": 1, "height": 1, "expect": {"volume": 1}}]}), []
        )
        self.assertTrue(
            problems({"steps": [{"op": "box", "length": 1, "width": 1, "height": 1, "expect": {"vol": 1}}]})
        )
        # 'check' owns its 'expect' parameter
        req = validate.validate_request({"steps": [{"op": "check", "target": "A", "expect": {"solids": 1}}]})
        self.assertEqual(req["steps"][0]["params"]["expect"], {"solids": 1})


def _box_descriptors():
    """Faces/edges of a 10 mm cube at the origin, in OCC order."""
    faces = [
        {"kind": "face", "index": 1, "type": "plane", "center": [0, 5, 5], "normal": [-1, 0, 0]},
        {"kind": "face", "index": 2, "type": "plane", "center": [10, 5, 5], "normal": [1, 0, 0]},
        {"kind": "face", "index": 3, "type": "plane", "center": [5, 0, 5], "normal": [0, -1, 0]},
        {"kind": "face", "index": 4, "type": "plane", "center": [5, 10, 5], "normal": [0, 1, 0]},
        {"kind": "face", "index": 5, "type": "plane", "center": [5, 5, 0], "normal": [0, 0, -1]},
        {"kind": "face", "index": 6, "type": "plane", "center": [5, 5, 10], "normal": [0, 0, 1]},
    ]
    edges = [
        {"kind": "edge", "index": 1, "type": "line", "center": [0, 0, 5], "direction": [0, 0, 1]},
        {"kind": "edge", "index": 2, "type": "line", "center": [0, 5, 10], "direction": [0, 1, 0]},
        {"kind": "edge", "index": 3, "type": "line", "center": [0, 10, 5], "direction": [0, 0, 1]},
        {"kind": "edge", "index": 4, "type": "line", "center": [0, 5, 0], "direction": [0, 1, 0]},
        {"kind": "edge", "index": 5, "type": "circle", "center": [5, 5, 10], "radius": 2.0},
    ]
    return faces, edges


class SelectorTests(unittest.TestCase):
    def setUp(self):
        self.faces, self.edges = _box_descriptors()

    def test_faces(self):
        sel = lambda s: selectors.select(s, self.faces)  # noqa: E731
        self.assertEqual(sel(">Z"), [6])
        self.assertEqual(sel("<X"), [1])
        self.assertEqual(sel("|Z"), [5, 6])
        self.assertEqual(sel("#Z"), [1, 2, 3, 4])
        self.assertEqual(sel("+Y"), [4])
        self.assertEqual(sel("-Z"), [5])
        self.assertEqual(sel("not (>Z or <Z)"), [1, 2, 3, 4])
        self.assertEqual(sel("all"), [1, 2, 3, 4, 5, 6])

    def test_edges(self):
        mapping = {1: [1, 3], 2: [1, 6], 3: [1, 4], 4: [1, 5], 5: [6]}
        sel = lambda s: selectors.select(s, self.edges, self.faces, lambda: mapping)  # noqa: E731
        self.assertEqual(sel("|Z"), [1, 3])
        self.assertEqual(sel("%CIRCLE"), [5])
        self.assertEqual(sel("r<3"), [5])
        self.assertEqual(sel("r=2"), [5])
        self.assertEqual(sel("r>3"), [])
        self.assertEqual(sel("face(>Z)"), [2, 5])
        self.assertEqual(sel("|Z and <Y"), [1])
        self.assertEqual(sel([3, 1, 3]), [1, 3])
        with self.assertRaises(selectors.SelectorError):
            sel([9])

    def test_face_selector_only_for_edges(self):
        with self.assertRaises(selectors.SelectorError):
            selectors.select("face(>Z)", self.faces)

    def test_syntax_errors(self):
        for bad in (">W", "%FOO", "(>Z", ">Z and", "", "face(>Z"):
            with self.assertRaises(selectors.SelectorError, msg=bad):
                selectors.parse(bad)


class ProfileTests(unittest.TestCase):
    def test_rounded_rect_tangent_points(self):
        segs = profiles.shape_segments({"rect": [0, 0, 40, 20], "corner_radius": 5}, 0)
        self.assertEqual([s[0] for s in segs], ["arc", "line"] * 4)
        arc = segs[0]  # corner (0, 0)
        self.assertAlmostEqual(arc[1][1], 5)  # starts 5 mm up the left edge
        self.assertAlmostEqual(arc[3][0], 5)  # ends 5 mm along the bottom edge
        mid = arc[2]
        self.assertAlmostEqual(math.hypot(mid[0] - 5, mid[1] - 5), 5)

    def test_shapes(self):
        self.assertEqual(len(profiles.shape_segments({"slot": [[0, 0], [10, 0]], "radius": 2}, 0)), 4)
        self.assertEqual(profiles.shape_segments({"circle": [1, 1], "radius": 2}, 0)[0][0], "circle")
        segs = profiles.shape_segments({"path": [[0, 0], [10, 0], {"arc_to": [10, 10], "center": [10, 5]}, [0, 10]]}, 0)
        self.assertEqual([s[0] for s in segs], ["line", "arc", "line", "line"])
        self.assertAlmostEqual(segs[1][2][0], 15)  # counter-clockwise arc bulges to +X
        segs = profiles.shape_segments(
            {"path": [[0, 0], [10, 0], {"arc_to": [10, 10], "center": [10, 5], "clockwise": True}, [0, 10]]}, 0
        )
        self.assertAlmostEqual(segs[1][2][0], 5)

    def test_errors(self):
        bad = [
            {"rect": [0, 0, 10, 10], "corner_radius": 6},
            {"rect": [0, 0, 10, 10], "circle": [0, 0]},
            {"circle": [0, 0]},
            {"slot": [[0, 0], [0, 0]], "radius": 1},
            {"polygon": [[0, 0], [10, 0], [10, 1]], "corner_radius": 5},
            {"polygon": [[0, 0], [1, 0], [2, 0]]},
            {"path": [[0, 0], {"arc_to": [5, 0], "center": [1, 1]}]},
            {"path": [[0, 0], [5, 0]]},
            {"rect": [0, 0, 1, 1], "radius": 1},
        ]
        for s in bad:
            with self.assertRaises(profiles.ProfileError, msg=s):
                profiles.shape_segments(s, 0)

    def test_validation_uses_profiles(self):
        self.assertEqual(problems({"steps": [{"op": "extrude", "height": 1, "shapes": [{"rect": [0, 0, 5, 5]}]}]}), [])
        self.assertTrue(
            problems(
                {"steps": [{"op": "extrude", "height": 1, "shapes": [{"rect": [0, 0, 5, 5], "corner_radius": 3}]}]}
            )
        )
        self.assertTrue(
            problems(
                {
                    "steps": [
                        {
                            "op": "extrude",
                            "height": 1,
                            "points": [[0, 0], [1, 0], [0, 1]],
                            "shapes": [{"rect": [0, 0, 5, 5]}],
                        }
                    ]
                }
            )
        )
        self.assertTrue(
            problems({"steps": [{"op": "extrude", "height": 1, "points": [[0, 0], [1, 0], [0, 1]], "offset": 2}]})
        )

    def test_splines(self):
        segs = profiles.shape_segments({"spline": [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]}, 0)
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0][0], "spline")
        self.assertEqual(len(segs[0][1]), 4)  # repeated closing point dropped
        self.assertTrue(segs[0][2])  # periodic
        segs = profiles.shape_segments(
            {"path": [[-30, 0], [30, 0], {"spline_to": [-30, 0], "through": [[0, 30]], "start_tangent": [0, 1]}]}, 0
        )
        self.assertEqual([s[0] for s in segs], ["line", "spline"])
        self.assertEqual(segs[1][1], ((30.0, 0.0), (0.0, 30.0), (-30.0, 0.0)))
        self.assertEqual((segs[1][3], segs[1][4]), ((0.0, 1.0), None))
        for bad in (
            {"spline": [[0, 0], [1, 1]]},
            {"spline": [[0, 0], [1, 1], [2, 2]]},
            {"spline": [[0, 0], [5, 0], [5, 0], [0, 5]]},
            {"path": [[0, 0], [10, 0], {"spline_to": [0, 0]}]},
            {"path": [[0, 0], [10, 0], {"spline_to": [0, 0], "through": [[5, 5]], "start_tangent": [0, 0]}]},
            {"path": [[0, 0], [10, 0], {"spline_to": [0, 0], "via": [[5, 5]]}]},
        ):
            with self.assertRaises(profiles.ProfileError, msg=bad):
                profiles.shape_segments(bad, 0)

    def test_loft_and_sweep_validation(self):
        sec = {"shape": {"circle": [0, 0], "radius": 5}}
        self.assertEqual(problems({"steps": [{"op": "loft", "sections": [sec, dict(sec, offset="=Params.h")]}]}), [])
        self.assertTrue(problems({"steps": [{"op": "loft", "sections": [sec]}]}))
        self.assertTrue(problems({"steps": [{"op": "loft", "sections": [sec, dict(sec, plane="AB")]}]}))
        self.assertTrue(problems({"steps": [{"op": "loft", "sections": [sec, dict(sec, offset="h")]}]}))
        prof = [{"circle": [0, 0], "radius": 1}]
        self.assertEqual(problems({"steps": [{"op": "sweep", "shapes": prof, "path": [[0, 0, 0], [0, 0, 10]]}]}), [])
        self.assertEqual(
            problems({"steps": [{"op": "sweep", "shapes": prof, "helix": {"radius": 5, "pitch": 2, "height": 10}}]}), []
        )
        self.assertTrue(problems({"steps": [{"op": "sweep", "shapes": prof}]}))  # no path
        self.assertTrue(problems({"steps": [{"op": "sweep", "shapes": prof, "path": [[0, 0, 0]]}]}))
        self.assertTrue(
            problems({"steps": [{"op": "sweep", "shapes": prof, "helix": {"radius": 5, "pitch": 0, "height": 10}}]})
        )
        self.assertTrue(
            problems({"steps": [{"op": "sweep", "shapes": prof, "helix": {"radius": 5, "pitch": 0.01, "height": 100}}]})
        )  # > 500 turns


class GuiDataTests(unittest.TestCase):
    """GuiDocument.xml written for headless saves (the GUI shows everything hidden without a valid one)."""

    def vp(self, xml, name):
        import xml.etree.ElementTree as ET

        root = ET.fromstring(xml)
        for v in root.find("ViewProviderData").findall("ViewProvider"):
            if v.get("name") == name:
                return {
                    p.get("name"): (list(p)[0].attrib if list(p) else {})
                    for p in v.find("Properties").findall("Property")
                }
        return None

    def test_fresh_document(self):
        xml = guidata.build(
            None, {"A", "B", "C"}, {"A": True, "B": False}, {"A": {"color": [1, 0, 0], "transparency": 20}}, set()
        )
        self.assertIn("<Expand />", xml)  # HasExpansion="1" without it makes the GUI hide everything
        self.assertIn("<Camera", xml)
        self.assertEqual(self.vp(xml, "A")["Visibility"]["value"], "true")
        self.assertEqual(self.vp(xml, "B")["Visibility"]["value"], "false")
        self.assertEqual(self.vp(xml, "A")["ShapeColor"]["value"], str(0xFF0000FF))
        self.assertEqual(self.vp(xml, "A")["Transparency"]["value"], "20")
        self.assertIsNone(self.vp(xml, "C"))  # unmanaged objects keep FreeCAD's defaults
        self.assertIn('ViewProviderData Count="2"', xml)

    def test_existing_gui_data_is_kept(self):
        old = (
            '<Document SchemaVersion="1" HasExpansion="1"><Expand /><ViewProviderData Count="3">'
            '<ViewProvider name="A" expanded="1"><Properties Count="2" TransientCount="0">'
            '<Property name="ShapeAppearance" type="App::PropertyMaterialList" status="1"><MaterialList file="ShapeAppearance2" /></Property>'
            '<Property name="Visibility" type="App::PropertyBool" status="1"><Bool value="false"/></Property></Properties></ViewProvider>'
            '<ViewProvider name="B" expanded="0"><Properties Count="1" TransientCount="0">'
            '<Property name="ShapeAppearance" type="App::PropertyMaterialList" status="1"><MaterialList file="ShapeAppearance10" /></Property>'
            "</Properties></ViewProvider>"
            '<ViewProvider name="Gone" expanded="0"><Properties Count="0" TransientCount="0"></Properties></ViewProvider>'
            '</ViewProviderData><Camera settings="cam" /></Document>'
        )
        captured = {"xml": old, "files": {"ShapeAppearance2": b"a", "ShapeAppearance10": b"b"}}
        xml = guidata.build(
            captured,
            {"A", "B", "New"},
            {"A": True, "B": True, "New": True},
            {"B": {"color": [0, 0, 1], "transparency": 0}},
            {"B"},
        )
        a = self.vp(xml, "A")
        self.assertEqual(a["Visibility"]["value"], "true")
        self.assertIn("ShapeAppearance", a)  # a user's GUI colour survives
        b = self.vp(xml, "B")
        self.assertNotIn("ShapeAppearance", b)  # replaced by the colour this request set
        self.assertIn("ShapeColor", b)
        self.assertIsNone(self.vp(xml, "Gone"))
        self.assertIn('settings="cam"', xml)
        self.assertEqual(guidata.referenced_files(xml), ["ShapeAppearance2"])  # in reference order, not sorted
        with tempfile.TemporaryDirectory() as d:
            import zipfile

            path = Path(d) / "x.FCStd"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("Document.xml", "<Document/>")
            guidata.write(path, xml, captured)
            names = zipfile.ZipFile(path).namelist()
            self.assertEqual(names, ["Document.xml", "GuiDocument.xml", "ShapeAppearance2"])
            self.assertEqual(guidata.capture(path)["files"], {"ShapeAppearance2": b"a"})

    def test_reference_order(self):
        xml = 'file="S2" file="S10" file="S2" file="L1"'
        self.assertEqual(guidata.referenced_files(xml), ["S2", "S10", "L1"])


class LibraryTests(unittest.TestCase):
    INDEX = {
        "source": "test",
        "files": {
            "Mechanical Parts/Bearings/608ZZ_Ball_Bearing.step": {"size": 4000, "sha": "a"},
            "Mechanical Parts/Bearings/608ZZ_Ball_Bearing.FCStd": {"size": 9000, "sha": "b"},
            "Mechanical Parts/Bearings/608ZZ_Ball_Bearing.stl": {"size": 9000, "sha": "c"},
            "Mechanical Parts/Bearings/6082_Big_Bearing.FCStd": {"size": 9000, "sha": "d"},
            "Mechanical Parts/Pulleys/GT2_Pulley_608_bore.stl": {"size": 100, "sha": "e"},
            "Electrical Parts/Motors/NEMA_17.step": {"size": 100, "sha": "f"},
        },
    }

    def test_search_ranks_and_flags_meshes(self):
        m = library.search(self.INDEX, "608 bearing")
        self.assertEqual(m[0]["part"], "Mechanical Parts/Bearings/608ZZ_Ball_Bearing")
        self.assertEqual(m[0]["formats"], ["fcstd", "step", "stl"])
        self.assertTrue(m[0]["importable"])
        self.assertIn("608ZZ_Ball_Bearing.step", m[0]["url"].replace("%20", " "))
        m = library.search(self.INDEX, "608")
        self.assertEqual(
            m[-1]["part"], "Mechanical Parts/Pulleys/GT2_Pulley_608_bore"
        )  # STL only: last, not importable
        self.assertFalse(m[-1]["importable"])
        self.assertEqual(library.search(self.INDEX, "unicorn"), [])
        with self.assertRaises(errors.SkillError):
            library.search(self.INDEX, "  ")

    def test_resolve_prefers_step_and_rejects_meshes_and_escapes(self):
        self.assertEqual(
            library.resolve(self.INDEX, "Mechanical Parts/Bearings/608ZZ_Ball_Bearing"),
            "Mechanical Parts/Bearings/608ZZ_Ball_Bearing.step",
        )
        self.assertEqual(
            library.resolve(self.INDEX, "Mechanical Parts/Bearings/608ZZ_Ball_Bearing.FCStd"),
            "Mechanical Parts/Bearings/608ZZ_Ball_Bearing.FCStd",
        )
        for bad, code in (
            ("Mechanical Parts/Pulleys/GT2_Pulley_608_bore", errors.UNSUPPORTED),
            ("Mechanical Parts/Bearings/608ZZ_Ball_Bearing.stl", errors.UNSUPPORTED),
            ("Nothing/Here", errors.OBJECT_NOT_FOUND),
            ("../../etc/passwd", errors.INVALID_PARAM),
            ("/etc/passwd", errors.OBJECT_NOT_FOUND),
        ):
            with self.assertRaises(errors.SkillError, msg=bad) as cm:
                library.resolve(self.INDEX, bad)
            self.assertEqual(cm.exception.code, code, bad)

    def test_attribution_and_refs(self):
        a = library.attribution("Mechanical Parts/Bearings/608ZZ_Ball_Bearing.step")
        self.assertIn("CC-BY 3.0", a["text"])
        self.assertIn("commits/master/Mechanical%20Parts", a["authors"])
        req = {"steps": [{"op": "import", "library": "A/B"}, {"op": "box"}, {"op": "import", "file": "x.step"}]}
        self.assertEqual(library.library_refs(req), ["A/B"])

    def test_local_clone_and_offline(self):
        with tempfile.TemporaryDirectory() as clone, tempfile.TemporaryDirectory() as ws:
            part = Path(clone) / "Mechanical Parts" / "Nut_M3.step"
            part.parent.mkdir(parents=True)
            part.write_text("ISO-10303-21;")
            (Path(clone) / "readme.md").write_text("x")
            old = {k: os.environ.get(k) for k in (library.ENV_LOCAL, library.ENV_OFFLINE)}
            try:
                os.environ[library.ENV_LOCAL] = clone
                index = library.load_index(Path(ws))
                self.assertEqual(list(index["files"]), ["Mechanical Parts/Nut_M3.step"])
                dest, meta = library.fetch(Path(ws), "Mechanical Parts/Nut_M3", index)
                self.assertEqual(dest.read_text(), "ISO-10303-21;")
                self.assertTrue(str(dest).startswith(ws))
                self.assertTrue(dest.with_name(dest.name + ".json").is_file())
                del os.environ[library.ENV_LOCAL]
                os.environ[library.ENV_OFFLINE] = "1"
                with self.assertRaises(errors.SkillError) as cm:
                    library.load_index(Path(ws) / "empty")
                self.assertEqual(cm.exception.code, errors.LIBRARY_UNAVAILABLE)
            finally:
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

    def test_planted_links_cannot_redirect_cache_writes(self):
        with (
            tempfile.TemporaryDirectory() as clone,
            tempfile.TemporaryDirectory() as ws,
            tempfile.TemporaryDirectory() as out,
        ):
            part = Path(clone) / "Mechanical Parts" / "Nut_M3.step"
            part.parent.mkdir(parents=True)
            part.write_text("ISO-10303-21;")
            victim = Path(out) / "victim.txt"
            victim.write_text("keep")
            old = os.environ.get(library.ENV_LOCAL)
            try:
                os.environ[library.ENV_LOCAL] = clone
                index = library.load_index(Path(ws))
                dest = library.local_path(Path(ws), "Mechanical Parts/Nut_M3.step")
                dest.parent.mkdir(parents=True)
                dest.symlink_to(victim)  # a link to a file outside: replaced by the part, victim untouched
                library.fetch(Path(ws), "Mechanical Parts/Nut_M3", index)
                self.assertFalse(dest.is_symlink())
                self.assertEqual(dest.read_text(), "ISO-10303-21;")
                self.assertEqual(victim.read_text(), "keep")
                for p in dest.parent.iterdir():
                    p.unlink()
                dest.parent.rmdir()
                dest.parent.symlink_to(out, target_is_directory=True)  # a linked folder: refused
                with self.assertRaises(errors.SkillError) as cm:
                    library.fetch(Path(ws), "Mechanical Parts/Nut_M3", index)
                self.assertEqual(cm.exception.code, errors.LIBRARY_UNAVAILABLE)
                self.assertEqual(sorted(p.name for p in Path(out).iterdir()), ["victim.txt"])
            finally:
                if old is None:
                    os.environ.pop(library.ENV_LOCAL, None)
                else:
                    os.environ[library.ENV_LOCAL] = old

    def test_blob_hash_matches_git(self):
        self.assertEqual(library._blob_sha(b"hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a")  # git hash-object

    def test_only_the_freecad_library_is_contacted(self):
        library._check_url(library.API_TREE)
        library._check_url(library.RAW + "Mechanical%20Parts/Nut.step")
        for bad in (
            "https://example.com/x",
            "http://raw.githubusercontent.com/FreeCAD/FreeCAD-library/master/x",
            "https://raw.githubusercontent.com/someone/else/master/x",
            "https://api.github.com/repos/FreeCAD/FreeCAD-library.evil/x",
            "https://raw.githubusercontent.com.evil.com/FreeCAD/FreeCAD-library/master/x",
        ):
            with self.assertRaises(errors.SkillError, msg=bad):
                library._check_url(bad)


class V3PureTests(unittest.TestCase):
    def test_expressions_only_where_a_dimension_can_carry_them(self):
        ok = [
            {"rect": [0, 0, "=Params.w", 30], "corner_radius": "=Params.r"},
            {"circle": [5, "=Params.y"], "radius": 2},
        ]
        profiles.check_expressions(ok)
        self.assertTrue(profiles.has_expressions(ok))
        got = profiles.resolve(ok, lambda e: 7.0)
        self.assertEqual(got[0], {"rect": [0, 0, 7.0, 30], "corner_radius": 7.0})
        self.assertEqual(ok[0]["rect"][2], "=Params.w")  # the request is not modified
        for bad in (
            [{"polygon": [[0, 0], ["=a", 0], [1, 1]]}],
            [{"path": [[0, 0], [5, 0], {"arc_to": [5, 5], "center": ["=a", 2.5]}]}],
            [{"spline": [[0, 0], [5, "=a"], [1, 4]]}],
            [{"rect": [0, 0, "=a", 3], "radius": 2}],
        ):
            with self.assertRaises(profiles.ProfileError):
                profiles.check_expressions(bad)
        # a literal shape next to a parametric one is still checked in full
        with self.assertRaises(profiles.ProfileError):
            profiles.check_expressions([{"circle": [0, 0], "radius": "=a"}, {"rect": [0, 0, -5, 3]}])
        self.assertEqual(problems({"steps": [{"op": "extrude", "height": 1, "shapes": ok}]}), [])
        self.assertTrue(
            problems({"steps": [{"op": "loft", "sections": [{"shape": ok[1]}, {"shape": ok[1], "offset": 5}]}]})
        )

    def test_one_material_table(self):
        names = matdata.structural_names()
        self.assertIn("steel_s235", names)
        self.assertNotIn("steel", names)  # generic: no single yield strength
        self.assertEqual(matdata.canonical("Aluminium 6061-T6"), "aluminium_6061")
        self.assertEqual(matdata.canonical("titanium_gr5"), "titanium")
        self.assertIsNone(matdata.canonical("unobtainium"))
        for target in matdata.ALIASES.values():
            self.assertIn(target, matdata.PRESETS)
        for name in names:
            m = matdata.PRESETS[name]
            self.assertTrue(500 < m.youngs_mpa < 500000 and 0 < m.poisson < 0.5 and 0 < m.yield_mpa < 3000, name)
        # every grade the fem_static documentation names exists and has strength data
        doc = catalog.OPS_BY_NAME["fem_static"].param("material").doc
        for name in ("steel_s355", "stainless_304", "aluminium_7075", "aluminium_5754", "nylon_pa12", "petg"):
            self.assertIn(name, doc)
            self.assertIn(name, names)

    def test_request_inputs_are_found_for_staging(self):
        req = {
            "steps": [
                {"op": "import", "file": "vendor/motor.step"},
                {"op": "import", "library": "Mechanical Parts/x"},
                {"op": "text", "text": "A", "size": 5, "height": 1, "font": "fonts/a.ttf"},
                {"op": "set", "target": "T", "properties": {"font": "fonts/b.ttf", "size": 3}},
                {"op": "set", "target": "T", "properties": {"font": "default"}},
                {"op": "box", "length": 1, "width": 1, "height": 1},
            ]
        }
        self.assertEqual(workspace.request_inputs(req), ["vendor/motor.step", "fonts/a.ttf", "fonts/b.ttf"])
        self.assertEqual(workspace.request_inputs({"op": "import", "file": "a.stl"}), ["a.stl"])
        self.assertEqual(workspace.request_inputs("junk"), [])

    def test_request_options_and_limits(self):
        box = {"op": "box", "length": 1, "width": 1, "height": 1}
        self.assertEqual(problems({"brief": True, "steps": [box]}), [])
        self.assertTrue(problems({"brief": "yes", "steps": [box]}))
        self.assertTrue(problems({"steps": [{"op": "linear_array", "target": "B", "count": 5000, "step": [1, 0, 0]}]}))
        grid = {"op": "grid_array", "target": "B", "count_x": 100, "count_y": 100, "step_x": 1, "step_y": 1}
        self.assertTrue(any("at most" in m["message"] for m in problems({"steps": [grid]})))
        self.assertTrue(problems({"steps": [{"op": "export", "filename": "a.step", "format": "step"}]}))


class V1FormatTests(unittest.TestCase):
    def test_v1_requests_get_a_clear_error(self):
        with self.assertRaises(errors.SkillError) as cm:
            validate.validate_request({"operation": "create_primitive", "parameters": {"type": "box"}})
        self.assertIn("no longer supported", cm.exception.message)
        self.assertIn("steps", cm.exception.hint)


class WorkspaceTests(unittest.TestCase):
    def test_confinement(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(workspace.resolve(root, "a/b.step"), Path(os.path.realpath(root)) / "a" / "b.step")
            for bad in ("../x.step", "/etc/passwd", "a/../../x"):
                with self.assertRaises(errors.SkillError):
                    workspace.resolve(root, bad)

    def test_windows_separators_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(workspace.resolve(root, "out\\a.step"), Path(os.path.realpath(root)) / "out" / "a.step")
            with self.assertRaises(errors.SkillError):
                workspace.resolve(root, "..\\x.step")

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_symlink_escape(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as outside:
            os.symlink(outside, os.path.join(d, "link"))
            with self.assertRaises(errors.SkillError):
                workspace.resolve(Path(d), "link/x.step")


class CompatTests(unittest.TestCase):
    def test_minimum_version(self):
        for ok in (["1", "1", "0"], ["1", "1", "4", "44227 +813 (Git)"], ["1", "2", "0dev"], ["2", "0", ""]):
            compat.check_version(ok)
        for old in (["1", "0", "2"], ["0", "21", "2"], ["1", "0"]):
            with self.assertRaises(errors.SkillError) as ctx:
                compat.check_version(old)
            self.assertEqual(ctx.exception.code, errors.FREECAD_VERSION)
        self.assertEqual(compat.parse_version(["1", "1", "0dev"]), (1, 1, 0))


class LockTests(unittest.TestCase):
    def test_second_holder_waits_then_fails(self):
        with tempfile.TemporaryDirectory() as d:
            doc = Path(d) / "a.FCStd"
            with doclock.DocumentLock(doc, 5):
                with self.assertRaises(errors.SkillError) as ctx:
                    with doclock.DocumentLock(doc, 0.3):
                        pass
                self.assertEqual(ctx.exception.code, errors.DOCUMENT_BUSY)
            with doclock.DocumentLock(doc, 0.3):  # released
                pass

    def test_serialises_threads(self):
        import threading

        with tempfile.TemporaryDirectory() as d:
            doc = Path(d) / "a.FCStd"
            inside, peak = [0], [0]

            def work():
                with doclock.DocumentLock(doc, 10):
                    inside[0] += 1
                    peak[0] = max(peak[0], inside[0])
                    import time

                    time.sleep(0.05)
                    inside[0] -= 1

            ts = [threading.Thread(target=work) for _ in range(5)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            self.assertEqual(peak[0], 1)


class DocsTests(unittest.TestCase):
    def test_generated_reference_is_up_to_date(self):
        current = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
        self.assertEqual(
            current,
            docs.operations_markdown(),
            "docs/OPERATIONS.md is stale: run python3 scripts/fcskill.py describe --markdown > docs/OPERATIONS.md",
        )

    def test_frontmatter_is_valid_and_declares_env_vars(self):
        import json
        import re

        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        fm = text.split("\n---\n", 1)[0][4:]
        try:
            import yaml
        except ImportError:
            yaml = None
        if yaml is not None:
            data = yaml.safe_load(fm)
        else:  # minimal fallback: key: value lines, metadata as JSON
            data = {}
            for line in fm.splitlines():
                k, _, v = line.partition(": ")
                data[k] = json.loads(v) if k == "metadata" else v.strip('"')
        self.assertEqual(data["name"], "freecad-skill")  # must match the ClawHub slug and install folder
        self.assertRegex(data["name"], r"^[a-z0-9-]{1,64}$")
        self.assertLess(len(data["description"]), 160)
        declared = {e["name"] for e in data["metadata"]["openclaw"]["envVars"]}
        used = set()
        for f in (ROOT / "scripts").rglob("*.py"):
            used |= set(re.findall(r"\b(FCSKILL_[A-Z_]+|FREECAD_PATH)\b", f.read_text(encoding="utf-8")))
        self.assertEqual(sorted(used - declared), [], "env vars used in code but not declared in SKILL.md")

    def test_skill_md_lists_every_op(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        missing = [op.name for op in catalog.OPS if f"`{op.name}`" not in skill]
        self.assertEqual(missing, [], "ops missing from SKILL.md")


if __name__ == "__main__":
    unittest.main()
