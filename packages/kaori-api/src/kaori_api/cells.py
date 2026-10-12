"""
H3 cells of TruthKeys: where a report may stand, and which truths light which hexagons.

Each ClaimType keeps the H3 resolution that suits it (sky cover res 8, the ground claims res 10). The
Liminal map draws islands as res 10 hexagons, and a truth lights every res 10 child of its cell. These
helpers are read-only: they never change a TruthKey or a signed artifact.

- `cell_info(truth_key)`: the key's cell and resolution, added to progress and PENDING compile responses.
- `check_report_position(config, truth_key, observations)`: for a ClaimType with `truthkey.position`, the
  key must be a valid H3 cell at the ClaimType's resolution (and its domain and topic), and every report's
  GPS fix must fall in that hexagon or its ring of neighbours, or reach it within its accuracy.
- `truths_for_cells(...)`: GET /v1/truths, the truths whose cell is a requested cell, an ancestor of one
  (cell_to_parent at the truth's resolution) or a descendant of one.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from kaori_truth.primitives.truthkey import parse_truthkey

try:  # h3 is a dependency of kaori-api and kaori-truth; keep imports cheap where it is missing
    import h3
except ImportError:  # pragma: no cover
    h3 = None  # type: ignore[assignment]

MAX_CELLS = 5000                 # one island's res 10 hexagons, with room to spare
DEFAULT_RING = 1
DEFAULT_MAX_ACCURACY_M = 100.0


class PositionError(ValueError):
    """A report or key that does not fit the ClaimType's hexagon."""


def is_cell(value: Any) -> bool:
    if h3 is None or not isinstance(value, str):
        return False
    try:
        return bool(h3.is_valid_cell(value))
    except Exception:
        return False


def key_cell(truth_key: str) -> Optional[str]:
    """The H3 cell of a TruthKey, or None for a non-H3 or unparseable key."""
    try:
        parts = parse_truthkey(truth_key)
    except Exception:
        return None
    if parts.spatial_system != "h3" or not is_cell(parts.spatial_id):
        return None
    return parts.spatial_id


def cell_info(truth_key: str) -> Dict[str, Any]:
    """{cell, resolution} of a TruthKey; both None when the key is not an H3 cell."""
    cell = key_cell(truth_key)
    return {"cell": cell, "resolution": h3.get_resolution(cell) if cell else None}


# ------------------------------------------------------------------------------------------ report position

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(min(1.0, math.sqrt(h)))


def position_rule(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The ClaimType's `truthkey.position` block, or None when it has none (v1 types: no check)."""
    rule = ((config or {}).get("truthkey") or {}).get("position")
    return rule if isinstance(rule, dict) else None


def _accuracy(geo: Dict[str, Any]) -> Optional[float]:
    for name in ("accuracy_m", "accuracy"):
        value = geo.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
            return float(value)
    return None


def position_fits(cell: str, lat: float, lon: float, accuracy_m: Optional[float], rule: Dict[str, Any]) -> bool:
    """
    True when a fix at (lat, lon) may stand for `cell`: its own hexagon at the cell's resolution is the cell
    or within `ring` steps of it (default 1: the 6 neighbours), or its accuracy circle, counted up to
    `max_accuracy_m`, reaches the cell (measured to the cell's circumscribed circle).
    """
    resolution = h3.get_resolution(cell)
    ring = int(rule.get("ring", DEFAULT_RING))
    if h3.latlng_to_cell(lat, lon, resolution) in set(h3.grid_disk(cell, max(0, ring))):
        return True
    if accuracy_m is None:
        return False
    reach = min(accuracy_m, float(rule.get("max_accuracy_m", DEFAULT_MAX_ACCURACY_M)))
    clat, clon = h3.cell_to_latlng(cell)
    radius = max(_haversine_m(clat, clon, vlat, vlon) for vlat, vlon in h3.cell_to_boundary(cell))
    return _haversine_m(lat, lon, clat, clon) <= radius + reach


def check_report_position(config: Dict[str, Any], truth_key: str, observations: Sequence[Any]) -> None:
    """Raise PositionError when a ClaimType with `truthkey.position` gets a key or a fix that does not fit."""
    rule = position_rule(config)
    if rule is None or h3 is None:
        return
    truthkey_cfg = config.get("truthkey") or {}
    try:
        parts = parse_truthkey(truth_key)
    except Exception as exc:
        raise PositionError("truth_key is not a TruthKey") from exc
    claim_id = str(config.get("id") or "")
    domain, topic = (claim_id.split(".") + ["", ""])[:2]
    if (parts.domain, parts.topic) != (domain, topic):
        raise PositionError(f"truth_key is not a {claim_id} key")
    if parts.spatial_system != "h3" or not is_cell(parts.spatial_id):
        raise PositionError("truth_key must name an H3 cell")
    want = int(truthkey_cfg.get("resolution", 8))
    if h3.get_resolution(parts.spatial_id) != want:
        raise PositionError(f"{claim_id} is filed on H3 resolution {want} hexagons; "
                            f"this key's cell is resolution {h3.get_resolution(parts.spatial_id)}")
    for observation in observations:
        geo = getattr(observation, "geo", None) or {}
        lat, lon = geo.get("lat"), geo.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            raise PositionError("This report needs its position (geo.lat and geo.lon)")
        if not position_fits(parts.spatial_id, float(lat), float(lon), _accuracy(geo), rule):
            raise PositionError("This report's position is outside its hexagon")


# ------------------------------------------------------------------------------------------ truths by cell

def parse_cells(values: Iterable[str]) -> List[str]:
    """Cells from `cells=a,b` and repeated `cell=` parameters, lowercased, de-duplicated, in order."""
    out: List[str] = []
    seen = set()
    for value in values:
        for item in str(value or "").split(","):
            item = item.strip().lower()
            if item and item not in seen:
                seen.add(item)
                out.append(item)
    return out


def _bucket_time(text: str) -> Optional[datetime]:
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _matches(truth_cell: str, by_ancestor: Dict[str, List[str]], by_res: Dict[int, set]) -> List[str]:
    """Requested cells this truth lights: those under the truth's cell (or equal to it), or, when the truth
    is finer than a requested cell, that requested cell."""
    lit = list(by_ancestor.get(truth_cell, []))
    res = h3.get_resolution(truth_cell)
    for q, requested in by_res.items():
        if q < res:
            parent = h3.cell_to_parent(truth_cell, q)
            if parent in requested and parent not in lit:
                lit.append(parent)
    return lit


def truths_for_cells(truth_keys: Iterable[str], truth_store: Any, cells: Sequence[str],
                     claim_type_ids: Optional[Sequence[str]] = None,
                     since: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """
    The latest TruthState of every key whose cell is a requested cell, an ancestor of one or a descendant of
    one, as {truthkey, claim_type_id, cell, resolution, time_bucket, status, claim, confidence, lights}.
    `lights` is the requested cells the truth covers. Keys come from the ledger (TRUTHSTATE_EMITTED).
    """
    by_ancestor: Dict[str, List[str]] = {}
    by_res: Dict[int, set] = {}
    for cell in cells:
        by_res.setdefault(h3.get_resolution(cell), set()).add(cell)
        for res in range(h3.get_resolution(cell), -1, -1):
            by_ancestor.setdefault(h3.cell_to_parent(cell, res), []).append(cell)
    wanted_claims = set(claim_type_ids or [])
    out: List[Dict[str, Any]] = []
    seen = set()
    for key in truth_keys:
        if key in seen:
            continue
        seen.add(key)
        cell = key_cell(key)
        if cell is None:
            continue
        lights = _matches(cell, by_ancestor, by_res)
        if not lights:
            continue
        bucket = parse_truthkey(key).time_bucket
        if since is not None:
            when = _bucket_time(bucket)
            if when is None or when < since:
                continue
        artifact = truth_store.get(key)
        if not isinstance(artifact, dict):
            continue
        claim_type_id = artifact.get("claim_type")
        if wanted_claims and claim_type_id not in wanted_claims:
            continue
        out.append({
            "truthkey": key,
            "claim_type_id": claim_type_id,
            "cell": cell,
            "resolution": h3.get_resolution(cell),
            "time_bucket": bucket,
            "status": artifact.get("status"),
            "claim": artifact.get("claim") or {},
            "confidence": artifact.get("confidence"),
            "lights": lights,
        })
    out.sort(key=lambda t: (t["time_bucket"], t["truthkey"]), reverse=True)
    return out
