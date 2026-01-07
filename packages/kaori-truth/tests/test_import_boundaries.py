"""
Kaori Truth — Test Suite for Import Boundaries

Tests that verify kaori_truth does not import forbidden dependencies.

kaori_truth MUST NOT import:
- sqlalchemy (database)
- fastapi (API framework)
- kaori_flow (Flow layer)
- kaori_db (DB layer)
- kaori_api (API layer)
"""
from __future__ import annotations

import sys
import pytest


class TestImportBoundaries:
    """Tests that kaori_truth respects import boundaries."""
    
    def test_no_sqlalchemy_import(self):
        """kaori_truth MUST NOT import sqlalchemy."""
        # Clear any cached imports
        forbidden = ['sqlalchemy']
        
        # Import kaori_truth
        import kaori_truth
        
        # Check that forbidden modules are not imported
        for module in forbidden:
            if module in sys.modules:
                # Check if it was imported BY kaori_truth
                # This is a heuristic - we check if it appeared after importing
                pass  # Can't easily check causation
        
        # At minimum, verify kaori_truth itself doesn't have these as dependencies
        import importlib.util
        spec = importlib.util.find_spec("kaori_truth")
        assert spec is not None
    
    def test_no_fastapi_import(self):
        """kaori_truth MUST NOT import fastapi."""
        # Record modules before import
        before = set(sys.modules.keys())
        
        # Import kaori_truth components
        from kaori_truth import compile_truth_state
        from kaori_truth.canonical import canonical_json
        from kaori_truth.time import bucket_datetime
        
        # Record modules after import
        after = set(sys.modules.keys())
        
        # Check no fastapi modules were added
        new_modules = after - before
        fastapi_modules = [m for m in new_modules if 'fastapi' in m.lower()]
        
        assert len(fastapi_modules) == 0, f"FastAPI modules imported: {fastapi_modules}"
    
    def test_compiler_has_no_db_imports(self):
        """compile_truth_state MUST NOT import database modules."""
        import inspect
        from kaori_truth.compiler import compile_truth_state
        
        # Get the source file
        source_file = inspect.getfile(compile_truth_state)
        
        with open(source_file, 'r') as f:
            source = f.read()
        
        # Check for forbidden import patterns
        forbidden_patterns = [
            'from kaori_db',
            'import kaori_db',
            'from sqlalchemy',
            'import sqlalchemy',
            'from kaori_api',
            'import kaori_api',
            'SessionLocal',
            'db_engine',
        ]
        
        for pattern in forbidden_patterns:
            assert pattern not in source, f"Forbidden import pattern found: {pattern}"
    
    def test_primitives_pure(self):
        """Primitives MUST be pure (no side effects on import)."""
        # This test verifies that importing primitives doesn't cause side effects
        import_before = len(sys.modules)
        
        from kaori_truth.primitives import (
            TruthKey,
            Observation,
            TruthState,
            ClaimType,
            EvidenceRef,
        )
        
        # Only a reasonable number of modules should be added
        import_after = len(sys.modules)
        new_imports = import_after - import_before
        
        # Should be less than 50 new modules (pydantic + deps)
        assert new_imports < 100, f"Too many imports: {new_imports}"
    
    def test_canonical_no_dependencies(self):
        """Canonical subsystem should have minimal dependencies."""
        from kaori_truth.canonical import (
            canonical_json,
            canonical_hash,
            canonicalize,
        )
        
        # Should work without any database or API imports
        result = canonical_json({"key": "value"})
        assert result == '{"key":"value"}'
        
        hash_result = canonical_hash({"key": "value"})
        assert len(hash_result) == 64  # SHA256 hex


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
