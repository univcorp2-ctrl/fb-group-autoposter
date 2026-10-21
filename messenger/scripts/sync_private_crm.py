"""One-shot private Messenger CRM sync; safe for unattended read-only input.

Stores only anonymized metrics and pseudonymous draft observation events
on private Google Drive. No sending, API, browser, or public deployment.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
# Allow Task Scheduler's pythonw.exe to execute this file from any CWD.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.export_real_crm_aggregate import build_live_metrics
from scripts.record_crm_operational_snapshot import safe_record, append_private_history
from scripts.ingest_live_draft_crm import ingest

def sync(data_dir: Path, private_dir: Path) -> dict:
    metrics = build_live_metrics(data_dir)
    checked = safe_record(metrics)
    private_dir.mkdir(parents=True, exist_ok=True)
    history_path=private_dir / "messenger_crm_operational_history_VERIFIED_20261021.sqlite"
    observations_path=private_dir / "messenger_crm_observations_20261021.sqlite"
    history=append_private_history(history_path,checked)
    observations=ingest(data_dir/"drafts.json",observations_path)
    snapshot_path=private_dir / "verified_messenger_snapshot_latest.json"
    safe_data={
        "schema_version":metrics["schema_version"],
        "source":metrics["source"],
        "scope":metrics["scope"],
        "contains_personal_data":False,
        "generated_at_utc":metrics["generated_at_utc"],
        **{key:metrics[key] for key in checked if key!="stamp"},
        "estateboard_publication_confirmed":False
    }
    pending=snapshot_path.with_suffix(".tmp")
    pending.write_text(json.dumps(safe_data,indent=2,ensure_ascii=False),encoding="utf-8")
    pending.replace(snapshot_path)
    return {"history_rows":history,
            "observed_draft_events":observations["stored_event_count"],
            "unresolved_sends":metrics["uncertain_send_count"],
            "customer_data_published":False,
            "outbound_actions":0}

def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--data-dir",type=Path,required=True)
    parser.add_argument("--private-dir",type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(sync(args.data_dir,args.private_dir),ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
