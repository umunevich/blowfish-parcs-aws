#!/usr/bin/env python3
"""Build a self-contained PARCS solution file: build/solver.py.

PARCS-Python uploads exactly one .py file to the master and the workers, so
the modules the solver depends on are inlined into the template
src/parcs_solver.py at the "# @@INLINE-MODULES@@" marker. Lines marked with
"# @@INLINE-IMPORT" (imports of the inlined modules) and `from __future__`
lines of the inlined modules are dropped.

Usage:
    python3 scripts/build_solver.py            # -> build/solver.py
"""
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SRC = os.path.join(ROOT, "src")
INLINE_MODULES = ["blowfish_constants.py", "blowfish.py", "jobfile.py"]
MARKER = "# @@INLINE-MODULES@@"


def module_body(name):
    with open(os.path.join(SRC, name)) as f:
        lines = f.read().splitlines()
    kept = [line for line in lines
            if "@@INLINE-IMPORT" not in line
            and not line.startswith("from __future__")
            and not line.startswith("# -*- coding")]
    bar = "# " + "=" * 74
    return "\n".join([bar, "# Inlined from src/%s" % name, bar] + kept)


def build(out_path):
    with open(os.path.join(SRC, "parcs_solver.py")) as f:
        template = f.read()
    if template.count(MARKER) != 1:
        sys.exit("marker %s not found exactly once" % MARKER)
    template = "\n".join(line for line in template.splitlines()
                         if "@@INLINE-IMPORT" not in line) + "\n"
    inlined = "\n\n".join(module_body(name) for name in INLINE_MODULES)
    result = template.replace(MARKER, inlined)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(result)
    compile(result, out_path, "exec")  # fail early on syntax errors
    return out_path


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "solver.py")
    print("Wrote %s" % build(out))
