import ast
import pathlib
import sys

errors = 0
for p in pathlib.Path(".").rglob("*.py"):
    if p.name == "_check_syntax.py":
        continue
    try:
        ast.parse(p.read_text(encoding="utf-8"))
    except SyntaxError as e:
        print(f"SYNTAX ERROR in {p}: {e}")
        errors += 1

print(f"Checked all .py files. Errors: {errors}")
sys.exit(1 if errors else 0)
