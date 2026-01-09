"""
Kaori Truth — IO Loaders (The "Dirty" Layer)

This module handles all File IO and YAML parsing.
It is part of the `kaori_truth.io` package.

STRICT BOUNDARY:
- ALLOWED: File IO, YAML parsing, Path operations.
- FORBIDDEN: This module MUST NOT be imported by `compiler.py` or `primitives`.
- CONSUMER: Only `kaori_truth.factory` should import this.
"""
import json
import yaml
from pathlib import Path
from typing import Any, Dict

def load_yaml_file(path: str | Path) -> Dict[str, Any]:
    """Load raw YAML file."""
    p = Path(path)
    with open(p, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def load_json_file(path: str | Path) -> Dict[str, Any]:
    """Load raw JSON file."""
    p = Path(path)
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)

def resolve_schema_ref(ref: str, base_path: str = "") -> Dict[str, Any]:
    """Resolve and load a JSON schema reference."""
    if base_path:
        path = Path(base_path) / ref
    else:
        path = Path(ref)
    
    return load_json_file(path)
