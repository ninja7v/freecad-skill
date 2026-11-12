#!/usr/bin/env python3
"""Run the test suite.

    python3 tests/run.py            # pure tests here, engine tests inside FreeCAD
    python3 tests/run.py --pure     # only tests that need no FreeCAD

Engine tests run in-process if this Python can import FreeCAD (e.g. a
conda-forge environment); otherwise inside FreeCADCmd, found like the
launcher finds it (FCSKILL_FREECAD, PATH, standard locations).
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(TESTS))

ENGINE_BOOT = """
import os, sys, unittest
sys.path[:0] = [{scripts!r}, {tests!r}]
suite = unittest.defaultTestLoader.loadTestsFromName("test_engine")
res = unittest.TextTestRunner(stream=sys.stderr, verbosity={verbosity}).run(suite)
with open({out!r}, "w") as fh:
    fh.write("ok" if res.wasSuccessful() else "fail")
"""


def run_pure(verbosity: int) -> bool:
    suite = unittest.defaultTestLoader.loadTestsFromName("test_pure")
    return unittest.TextTestRunner(verbosity=verbosity).run(suite).wasSuccessful()


def run_engine(verbosity: int) -> bool:
    import fcskill

    backend = fcskill.find_freecad(os.environ.get("FCSKILL_FREECAD"))
    if backend is None:
        print("FreeCAD not found: engine tests skipped (set FCSKILL_FREECAD).", file=sys.stderr)
        return False
    if backend.kind == "python":
        suite = unittest.defaultTestLoader.loadTestsFromName("test_engine")
        return unittest.TextTestRunner(verbosity=verbosity).run(suite).wasSuccessful()
    out = TESTS / ".engine-result"
    if out.exists():
        out.unlink()
    code = ENGINE_BOOT.format(scripts=str(ROOT / "scripts"), tests=str(TESTS), verbosity=verbosity, out=str(out))
    print(f"Running engine tests in {' '.join(backend.cmd)}", file=sys.stderr)
    proc = subprocess.run(backend.cmd + ["-c", code], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    noise = (
        "Warning: Schema",
        "snap-specific",
        "Recompute",
        "Postprocessing",
        "*****",
        "\x1b[",
        "saving",
        "Step File",
        "(100 %)",
    )
    for line in proc.stdout.splitlines():
        if line.strip() and not any(n in line for n in noise):
            print(line)
    ok = out.exists() and out.read_text() == "ok"
    if out.exists():
        out.unlink()
    return ok


def main() -> int:
    verbosity = 2 if "-v" in sys.argv else 1
    ok = run_pure(verbosity)
    if "--pure" not in sys.argv:
        ok = run_engine(verbosity) and ok
        suite = unittest.defaultTestLoader.loadTestsFromName("test_launcher")
        ok = unittest.TextTestRunner(verbosity=verbosity).run(suite).wasSuccessful() and ok
    print("\nALL TESTS PASSED" if ok else "\nTESTS FAILED", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
