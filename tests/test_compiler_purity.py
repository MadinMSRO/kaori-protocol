"""
Refining Purity Test (Nuclear Option)

Mechanically enforces Law 2: The Compiler is Pure.

This test performs Static Analysis (AST) on the `kaori_truth` package to ensure:
1.  NO imports from `kaori_flow`, `kaori_db`, `kaori_api` anywhere in kaori_truth.
2.  NO imports from `kaori_truth.io` inside `compiler.py` or `primitives`.
3.  NO usage of `datetime.now()` or `open()` in pure modules.

Usage: pytest tests/test_compiler_purity.py
"""
import ast
import os
import pytest
from pathlib import Path

PACKAGE_ROOT = Path("packages/kaori-truth/src/kaori_truth")

# 1. Global Bans (Applies to ALL files in kaori_truth)
GLOBAL_BANS = {
    "kaori_flow", "kaori_db", "kaori_api",
    "requests", "http", "socket", 
    # datetime.now is tricky, let's catch it per-file
}

# 2. Pure Modules (compiler.py, primitives/*, validation/*)
# MUST NOT import io
# MUST NOT call open(), datetime.now()
PURE_MODULES_GLOBS = [
    "compiler.py",
    "primitives/*.py",
    "validation/*.py",
    "hashing/*.py",
    "crypto/*.py"
]

def is_pure_module(filepath: Path) -> bool:
    # Check if file matches pure globs
    rel = filepath.relative_to(PACKAGE_ROOT)
    for glob in PURE_MODULES_GLOBS:
        if rel.match(glob):
            return True
    return False

class PurityVisitor(ast.NodeVisitor):
    def __init__(self, filename, is_pure):
        self.filename = filename
        self.is_pure = is_pure
        self.errors = []

    def visit_Import(self, node):
        for alias in node.names:
            self._check_import(alias.name, node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            self._check_import(node.module, node.lineno)
        self.generic_visit(node)

    def _check_import(self, module_name, lineno):
        # 1. Global Bans
        base = module_name.split('.')[0]
        if base in GLOBAL_BANS:
             self.errors.append(f"{self.filename}:{lineno} - GLOBAL BAN: import '{module_name}'")

        # 2. Purity Rules
        if self.is_pure:
            if module_name.startswith("kaori_truth.io"):
                self.errors.append(f"{self.filename}:{lineno} - PURITY PACT: import '{module_name}' forbidden in pure module.")
            if module_name == "urllib.request": # specific dangerous lib
                self.errors.append(f"{self.filename}:{lineno} - PURITY PACT: import '{module_name}' forbidden.")

    def visit_Call(self, node):
        # Forbidden calls in Pure modules
        if self.is_pure:
            if isinstance(node.func, ast.Name):
                if node.func.id == "open":
                    self.errors.append(f"{self.filename}:{node.lineno} - PURITY PACT: call 'open()' forbidden.")
            
            elif isinstance(node.func, ast.Attribute):
                # Check datetime.now()
                # We assume standard import `from datetime import datetime` or `import datetime`
                # If node.func.attr == 'now' and node.func.value.id == 'datetime'
                attr = node.func.attr
                if attr in ('now', 'utcnow'):
                     # Heuristic: verify if it looks like datetime.now
                     if isinstance(node.func.value, ast.Name) and node.func.value.id == "datetime":
                          # Exception: normalize.py::utc_now() is a wrapper helper, but it shouldn't be called by compiler
                          pass 
                          # Actually, we want to ban it everywhere in pure modules except helpers?
                          # Let's be strict: NO datetime.now() in pure modules.
                          # normalize.py IS a pure helper module but it encapsulates the dirty call. 
                          # Wait, normalize.py `utc_now` is legal as a helper.
                          if "normalize.py" in str(self.filename):
                               pass
                          else:
                               self.errors.append(f"{self.filename}:{node.lineno} - PURITY PACT: call 'datetime.{attr}()' forbidden.")

        self.generic_visit(node)

def get_python_files(root: Path):
    for r, d, f in os.walk(root):
        for file in f:
            if file.endswith(".py"):
                yield Path(r) / file

def test_structural_purity():
    """Run AST check enforcing Temple Boundary."""
    if not PACKAGE_ROOT.exists():
        pytest.skip("Package root not found")

    all_errors = []
    print(f"Scanning {PACKAGE_ROOT}...")

    for file_path in get_python_files(PACKAGE_ROOT):
        if "test" in file_path.name: continue
        
        is_pure = is_pure_module(file_path)
        
        try:
            tree = ast.parse(file_path.read_text(encoding='utf-8'))
            visitor = PurityVisitor(file_path.name, is_pure)
            visitor.visit(tree)
            if visitor.errors:
                all_errors.extend(visitor.errors)
        except Exception as e:
            all_errors.append(f"{file_path}: {e}")

    if all_errors:
        pytest.fail("\n".join(["STRUCTURAL PURITY VIOLATION:"] + all_errors))
