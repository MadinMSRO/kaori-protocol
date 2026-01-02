#!/usr/bin/env python3
import sys
from pathlib import Path
from datetime import datetime

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = ROOT / "schemas"


DEFAULT_TEMPLATE = {
    "id": None,
    "version": 1,
    "domain": None,
    "topic": None,

    "truthkey": {
        "spatial_system": "h3",
        "resolution": 8,
        "z_index": "surface",
        "time_bucket": "PT1H"
    },

    "risk_profile": "monitor",

    "ui_schema": {
        "fields": []
    },

    "evidence": {
        "required": True,
        "types": ["photo"],
        "min_count": 1,
        "storage": {
            "canonical_scheme": "gs://",
            "bucket": "kaori-evidence"
        }
    },

    "evidence_similarity": {
        "enabled": True,
        "hash": {
            "enabled": True,
            "method": "phash",
            "duplicate_threshold": 6,
            "immediate_reject_if_duplicate": True
        },
        "embedding": {
            "enabled": True,
            "compute_mode": "ON_DEMAND",
            "engine": "clip_v1",
            "similarity_threshold": 0.85,
            "trigger_conditions": [
                {"ai_confidence_below": 0.80},
                {"requires_semantic_corroboration": True}
            ]
        }
    },

    "ai_validation_routing": {
        "enabled": True,
        "bouncer": {
            "engine": "bouncer_v1",
            "routes": {
                "fail": "reject",
                "pass": "generalist"
            }
        },
        "generalist": {
            "engine": "generalist_v1",
            "routes": {
                "high_confidence": "accept",
                "low_confidence": "specialist"
            }
        },
        "specialist": {
            "engine": "specialist_v1",
            "routes": {
                "pass": "accept",
                "fail": "human_review"
            }
        }
    },

    "autovalidation": {
        "ai_verified_true_threshold": 0.82,
        "ai_verified_false_threshold": 0.20,
        "uncertainty_band": {
            "low": 0.20,
            "high": 0.82
        }
    },

    "human_gating": {
        "always_require_human": False,
        "required_for_risk_profiles": ["critical"],
        "min_trust_score": 0.35,
        "min_ai_confidence": 0.82
    },

    "validation_flow": {
        "mode": "auto"
    },

    "consensus_model": {
        "type": "weighted_threshold",
        "finalize_threshold": 15,
        "reject_threshold": -10,
        "weighted_roles": {
            "bronze": 1,
            "silver": 3,
            "expert": 7,
            "ministry": 10
        },
        "override_allowed_roles": ["ministry"],
        "vote_types": {
            "RATIFY": +1,
            "REJECT": -1,
            "CHALLENGE": 0,
            "OVERRIDE": "special"
        }
    },

    "confidence_model": {
        "type": "composite",
        "components": {
            "ai_confidence": {
                "weight": 0.55,
                "source": "ai_validation.final_confidence"
            },
            "trust_score": {
                "weight": 0.20,
                "source": "reporter_context.trust_score"
            },
            "corroboration": {
                "weight": 0.15,
                "formula": "min(1.0, corroboration_count / 3)"
            },
            "consensus_strength": {
                "weight": 0.10,
                "formula": "min(1.0, consensus_score / finalize_threshold)"
            }
        },
        "modifiers": {
            "contradiction_penalty": {
                "condition": "contradiction_detected == true",
                "apply": "-0.30"
            }
        },
        "thresholds": {
            "verified_true": 0.82,
            "verified_false": 0.20
        }
    },

    "state_verification_policy": {
        "monitor_lane": {
            "allow_ai_verified_truth": True,
            "transparency_flag_if_composite_below": 0.82,
            "flag_label": "LOW_COMPOSITE_CONFIDENCE"
        },
        "critical_lane": {
            "require_human_consensus_for_verified_true": True
        }
    },

    "dispute_resolution": {
        "quorum": {
            "min_votes": 3
        },
        "timeout": {
            "peer_review": "PT12H",
            "expert_review": "PT24H",
            "ministry_escalation": "PT48H"
        },
        "default_action_on_timeout": "maintain_state"
    },

    "contradiction_rules": {
        "enabled": True,
        "trusted_sources": {
            "min_standing": "expert",
            "min_trust_score": 0.70
        },
        "contradiction_trigger": {
            "min_confidence_gap": 0.40,
            "action": "flag_and_escalate"
        }
    },

    "temporal_decay": {
        "half_life": "PT6H",
        "max_validity": "P3D"
    },

    "incentives": {
        "enabled": False,
        "base_credit": 10,
        "verified_bonus": 20,
        "rejected_penalty": -5
    }
}


def usage():
    print("Usage:")
    print("  python tools/new_claim.py <domain> <topic> <version> [--risk critical|monitor] [--out path.yaml]")
    print("")
    print("Examples:")
    print("  python tools/new_claim.py earth flood 1")
    print("  python tools/new_claim.py ocean coral_bleaching 1 --risk critical")
    sys.exit(2)


def main():
    if len(sys.argv) < 4:
        usage()

    domain = sys.argv[1].strip().lower()
    topic = sys.argv[2].strip().lower()
    version = int(sys.argv[3])

    risk = "monitor"
    out_path = None

    args = sys.argv[4:]
    if "--risk" in args:
        i = args.index("--risk")
        risk = args[i + 1].strip().lower()

    if "--out" in args:
        i = args.index("--out")
        out_path = Path(args[i + 1]).expanduser()

    claim_id = f"{domain}.{topic}.v{version}"

    template = dict(DEFAULT_TEMPLATE)
    template["id"] = claim_id
    template["domain"] = domain
    template["topic"] = topic
    template["version"] = version
    template["risk_profile"] = risk

    # Critical lane defaults
    if risk == "critical":
        template["validation_flow"]["mode"] = "human_expert"
        template["human_gating"]["always_require_human"] = True

    if out_path is None:
        out_dir = SCHEMAS_DIR / domain
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{topic}_v{version}.yaml"
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists():
        print(f"❌ Output already exists: {out_path}")
        sys.exit(1)

    header = [
        f"# Kaori ClaimType YAML",
        f"# Generated: {datetime.utcnow().replace(microsecond=0).isoformat()}Z",
        f"# id: {claim_id}",
        ""
    ]

    with out_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(header))
        yaml.safe_dump(
            template,
            f,
            sort_keys=False,
            default_flow_style=False
        )

    print(f"✅ Created new claim schema: {out_path}")
    print(f"   id: {claim_id}")
    print(f"   risk_profile: {risk}")


if __name__ == "__main__":
    main()
