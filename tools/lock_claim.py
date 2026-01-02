#!/usr/bin/env python3
import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
LOCKFILE_PATH = ROOT / "meta" / "claimtype.lock.json"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_file_hash(path: Path) -> str:
    return sha256_text(path.read_text(encoding="utf-8"))


def load_lockfile() -> dict:
    if not LOCKFILE_PATH.exists():
        return {"locked": {}}
    return json.loads(LOCKFILE_PATH.read_text(encoding="utf-8"))


def save_lockfile(lock_data: dict):
    LOCKFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCKFILE_PATH.write_text(json.dumps(lock_data, indent=2, sort_keys=True), encoding="utf-8")


def lock_claim_file(path: Path, lock_data: dict, force: bool = False):
    rel = str(path.relative_to(ROOT))
    locked = lock_data.setdefault("locked", {})

    current_hash = compute_file_hash(path)
    timestamp = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    if rel in locked and not force:
        # already locked
        prev_hash = locked[rel]["sha256"]
        if prev_hash == current_hash:
            print(f"✅ Already locked (no change): {rel}")
            return
        else:
            print(f"❌ {rel} is already locked but content hash differs.")
            print(f" - locked_sha256:  {prev_hash}")
            print(f" - current_sha256: {current_hash}")
            print("Use --force to overwrite the lock entry (NOT recommended unless you are intentionally bumping version).")
            sys.exit(1)

    locked[rel] = {
        "sha256": current_hash,
        "locked_at": timestamp
    }

    print(f"🔒 Locked: {rel}")
    print(f" - sha256: {current_hash}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/lock_claim.py <path_to_claim_yaml> [<path_to_claim_yaml> ...] [--force]")
        sys.exit(2)

    args = sys.argv[1:]
    force = False

    if "--force" in args:
        force = True
        args.remove("--force")

    lock_data = load_lockfile()

    for arg in args:
        path = (ROOT / arg).resolve() if not Path(arg).is_absolute() else Path(arg).resolve()

        if not path.exists():
            print(f"❌ File not found: {arg}")
            sys.exit(2)

        # Ensure file is within repo root
        try:
            path.relative_to(ROOT)
        except Exception:
            print(f"❌ File must be inside repository root: {path}")
            sys.exit(2)

        lock_claim_file(path, lock_data, force=force)

    save_lockfile(lock_data)
    print(f"\n✅ Updated lockfile: {LOCKFILE_PATH}")


if __name__ == "__main__":
    main()
