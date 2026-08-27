"""Validate frozen evidence bundles without consulting model outputs or Gold scores."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUNDLES = ROOT / "meta_eval/frozen_evidence_scoring_v1"
BANNED = ("expected_score", "expected_status", "gold", "partially_supported", "substantial recovery")

def main() -> None:
    files = sorted(BUNDLES.glob("att_*.json"))
    if len(files) != 5:
        raise SystemExit(f"expected 5 bundles, got {len(files)}")
    manifest = []
    for path in files:
        raw = path.read_text()
        data = json.loads(raw)
        if data.get("schema_version") != "agenteval.frozen_evidence_bundle.v1":
            raise SystemExit(f"{path}: wrong schema")
        if data.get("question_id") != "observed_failure_handling":
            raise SystemExit(f"{path}: wrong question")
        fact_ids = [str(x.get("fact_id")) for x in data.get("facts") or []]
        if not fact_ids or len(set(fact_ids)) != len(fact_ids):
            raise SystemExit(f"{path}: missing or duplicate fact ids")
        if not data.get("claim_set"):
            raise SystemExit(f"{path}: missing claim set")
        lowered = raw.lower()
        found = [term for term in BANNED if term in lowered]
        if found:
            raise SystemExit(f"{path}: scoring leakage terms {found}")
        manifest.append({
            "case_id": data["case_id"],
            "bundle_digest": hashlib.sha256(raw.encode()).hexdigest(),
            "fact_count": len(fact_ids),
            "claim_count": len(data["claim_set"]),
        })
    print(json.dumps({"bundles": manifest}, ensure_ascii=False, indent=2))

if __name__ == "__main__": main()
