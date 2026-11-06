"""End-to-end tests through scripts/fcskill.py (needs FreeCAD; run by tests/run.py)."""

import concurrent.futures as cf
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SK = ROOT / "scripts" / "fcskill.py"


def _home_tmp() -> Path:
    # Snap FreeCAD cannot see /tmp; use a non-hidden folder under $HOME.
    base = Path.home() / "fcskill-test-tmp"
    base.mkdir(exist_ok=True)
    return Path(tempfile.mkdtemp(dir=base))


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.ws = _home_tmp()

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)
        try:
            self.ws.parent.rmdir()
        except OSError:
            pass

    def run_req(self, req, name="r", *args):
        p = self.ws / f"{name}.json"
        p.write_text(json.dumps(req))
        cp = subprocess.run(
            [sys.executable, str(SK), "run", str(p), *args], cwd=self.ws, capture_output=True, text=True, timeout=600
        )
        return cp.returncode, json.loads(cp.stdout)

    def test_concurrent_requests_do_not_lose_updates(self):
        code, r = self.run_req(
            {"doc": "c.FCStd", "steps": [{"op": "box", "name": "B", "length": 1, "width": 1, "height": 1}]}
        )
        self.assertEqual(code, 0, r)
        steps = [
            {"doc": "c.FCStd", "steps": [{"op": "sphere", "name": f"S{i}", "radius": 1, "position": [5 * i, 0, 0]}]}
            for i in range(4)
        ]
        with cf.ThreadPoolExecutor(4) as ex:
            results = list(ex.map(lambda ir: self.run_req(ir[1], f"p{ir[0]}"), enumerate(steps)))
        self.assertTrue(all(c == 0 for c, _ in results), results)
        _, r = self.run_req({"doc": "c.FCStd", "op": "inspect"}, "i")
        names = sorted(o["name"] for o in r["steps"][0]["data"]["objects"])
        self.assertEqual(names, ["B", "S0", "S1", "S2", "S3"])

    def test_bom_request_file_is_accepted(self):
        p = self.ws / "bom.json"
        p.write_bytes(
            b"\xef\xbb\xbf"
            + json.dumps({"doc": "b.FCStd", "steps": [{"op": "box", "length": 1, "width": 1, "height": 1}]}).encode()
        )
        cp = subprocess.run(
            [sys.executable, str(SK), "run", str(p)], cwd=self.ws, capture_output=True, text=True, timeout=600
        )
        self.assertEqual(json.loads(cp.stdout)["status"], "success", cp.stdout)

    def test_describe_unknown_op_is_usage_error(self):
        cp = subprocess.run([sys.executable, str(SK), "describe", "nope"], capture_output=True, text=True)
        self.assertEqual(cp.returncode, 2)

    def test_exit_codes_and_json_errors(self):
        code, r = self.run_req({"steps": [{"op": "boxx"}]})
        self.assertEqual((code, r["error"]["code"]), (1, "INVALID_REQUEST"))
        code, r = self.run_req({"doc": "../x.FCStd", "op": "inspect"})
        self.assertEqual((code, r["error"]["code"]), (1, "PATH_NOT_ALLOWED"))


if __name__ == "__main__":
    unittest.main()
