#!/usr/bin/env python3
import os
import sys
import json
import hashlib
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "meta" / "claimtype.schema.json"
SCHEMAS_DIR = ROOT / "schemas"
LOCKFILE_PATH = ROOT / "meta" / "claimtype.lock.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def gather_claim_files():
    if not SCHEMAS_DIR.exists():
        print(f"[ERROR] schemas dir not found: {SCHEMAS_DIR}")
        sys.exit(2)
    return sorted([p for p in SCHEMAS_DIR.rglob("*.yaml")])


def load_yaml(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"Failed to parse YAML {path}: {e}")


def validate_against_schema(obj: dict, validator: Draft202012Validator, file_path: Path):
    errors = sorted(validator.iter_errors(obj), key=lambda e: e.path)
    if errors:
        print(f"\n[SCHEMA ERROR] {file_path}")
        for e in errors[:25]:
            loc = ".".join([str(x) for x in e.path]) if e.path else "<root>"
            print(f" - {loc}: {e.message}")
        if len(errors) > 25:
            print(f" ... and {len(errors)-25} more errors")
        return False
    return True


def validate_semantics(obj: dict, file_path: Path):
    ok = True

    auto = obj.get("autovalidation", {})
    t_true = auto.get("ai_verified_true_threshold")
    t_false = auto.get("ai_verified_false_threshold")
    band = auto.get("uncertainty_band", {})
    low = band.get("low")
    high = band.get("high")

    if isinstance(t_true, (int, float)) and isinstance(t_false, (int, float)):
        if t_true <= t_false:
            print(f"[SEMANTIC ERROR] {file_path}: ai_verified_true_threshold must be > ai_verified_false_threshold")
            ok = False

    if isinstance(low, (int, float)) and isinstance(high, (int, float)):
        if low >= high:
            print(f"[SEMANTIC ERROR] {file_path}: uncertainty_band.low must be < uncertainty_band.high")
            ok = False

    # Risk profile and policy alignment checks
    risk = obj.get("risk_profile")
    policy = obj.get("state_verification_policy", {})
    monitor_lane = policy.get("monitor_lane", {})
    critical_lane = policy.get("critical_lane", {})

    if risk == "critical":
        if critical_lane.get("require_human_consensus_for_verified_true") is not True:
            print(f"[SEMANTIC ERROR] {file_path}: critical risk_profile requires human consensus for VERIFIED_TRUE")
            ok = False

    # Embedding compute mode normalization
    emb = obj.get("evidence_similarity", {}).get("embedding", {})
    mode = emb.get("compute_mode")
    if mode and mode not in ("ALWAYS", "ON_DEMAND", "OFF", "on_demand"):
        print(f"[SEMANTIC ERROR] {file_path}: embedding.compute_mode must be ALWAYS|ON_DEMAND|OFF")
        ok = False

    return ok


def load_lockfile():
    if not LOCKFILE_PATH.exists():
        return {"locked": {}}
    return load_json(LOCKFILE_PATH)


def compute_file_hash(path: Path):
    return sha256_text(path.read_text(encoding="utf-8"))


def enforce_immutability(claim_path: Path, lock_data: dict):
    """
    If a claim file is present in lockfile under "locked",
    its content hash MUST NOT change.
    """
    locked = lock_data.get("locked", {})
    rel = str(claim_path.relative_to(ROOT))

    if rel not in locked:
        return True  # Not locked yet

    prev_hash = locked[rel]["sha256"]
    current_hash = compute_file_hash(claim_path)

    if prev_hash != current_hash:
        print(f"[IMMUTABILITY ERROR] {rel} is locked but was modified.")
        print(f" - locked_sha256:  {prev_hash}")
        print(f" - current_sha256: {current_hash}")
        return False

    return True


def main():
    schema = load_json(SCHEMA_PATH)
    validator = Draft202012Validator(schema)

    claim_files = gather_claim_files()
    if not claim_files:
        print("[ERROR] No claim YAML files found under schemas/")
        sys.exit(2)

    lock_data = load_lockfile()

    all_ok = True

    for p in claim_files:
        obj = load_yaml(p)

        # Basic schema validation
        if not validate_against_schema(obj, validator, p):
            all_ok = False
            continue

        # Semantic validation
        if not validate_semantics(obj, p):
            all_ok = False

        # Immutability validation
        if not enforce_immutability(p, lock_data):
            all_ok = False

    if not all_ok:
        print("\n❌ Claim validation failed.")
        sys.exit(1)

    print("✅ All claim schemas validated successfully.")
    sys.exit(0)


if __name__ == "__main__":
    main()
