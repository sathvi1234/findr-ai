"""Copy the SQLite audit log into MongoDB. The SQLite file is not deleted or rewritten."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.meeting.geo import geojson_point
from src.persistence.documents import merge_order_status
from src.persistence.env import load_env_file
from src.audit_db import default_audit_path
from src.persistence.store import open_document_store


def _utc(timestamp: float) -> datetime:
    return datetime.fromtimestamp(float(timestamp), tz=timezone.utc)


def _rows(connection: sqlite3.Connection, sql: str) -> list[sqlite3.Row]:
    return list(connection.execute(sql))


def migrate_sqlite(store, db_path: Path) -> dict[str, int]:
    """Insert existing incidents, decisions, and hash-chain events. Repeat runs do not duplicate them."""
    path = Path(db_path)
    counts = {"incidents": 0, "decisions": 0, "chain_events": 0, "skipped": 0}
    if not path.is_file():
        return counts
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        incidents = _rows(connection, "SELECT * FROM incidents")
        evaluations = {
            row["incident_id"]: row
            for row in _rows(connection, "SELECT * FROM agent_evaluations")
        }
        actions = _rows(connection, "SELECT * FROM operator_actions ORDER BY action_id")
        chain = _rows(connection, "SELECT * FROM audit_chain ORDER BY seq")
    except sqlite3.OperationalError:
        connection.close()
        return counts

    for row in incidents:
        key = f"sqlite:incident:{row['incident_id']}"
        if store.find_one("audit_logs", "migration_key", key):
            counts["skipped"] += 1
            continue
        recorded_at = _utc(row["timestamp"])
        agent_id = row["agent_id"] or row["drone_id"]
        order_id = row["order_id"] or row["mission_id"]
        reported = geojson_point(row["reported_lat"], row["reported_lon"])
        reference = geojson_point(row["truth_lat"], row["truth_lon"])
        store.upsert("delivery_agents", "agent_id", agent_id, {
            **(store.find_one("delivery_agents", "agent_id", agent_id) or {}),
            "agent_id": agent_id,
            "vehicle_type": row["vehicle_type"],
            "last_location": reported,
            "position_source": "synthetic",
            "updated_at": recorded_at,
        })
        previous = store.find_one("delivery_orders", "order_id", order_id) or {}
        store.upsert("delivery_orders", "order_id", order_id, {
            **previous,
            "order_id": order_id,
            "agent_id": agent_id,
            "vehicle_type": row["vehicle_type"] or previous.get("vehicle_type"),
            "status": merge_order_status(previous.get("status"), row["delivery_status"] or "IN_TRANSIT"),
            "updated_at": recorded_at,
        })
        store.insert_new("telemetry_frames", "incident_id", row["incident_id"], {
            "incident_id": row["incident_id"],
            "order_id": order_id,
            "agent_id": agent_id,
            "recorded_at": recorded_at,
            "created_at": recorded_at,
            "location": reported,
            "reference_location": reference,
            "position_source": "sqlite_migration",
            "migration_key": f"sqlite:telemetry:{row['incident_id']}",
        })
        evaluation = evaluations.get(row["incident_id"])
        store.insert_new("anomaly_events", "incident_id", row["incident_id"], {
            "incident_id": row["incident_id"],
            "order_id": order_id,
            "agent_id": agent_id,
            "anomaly_type": row["anomaly_type"],
            "anomaly_score": row["anomaly_score"],
            "is_anomalous": bool(row["is_anomalous"]),
            "rule_explanation": row["rule_explanation"],
            "created_at": recorded_at,
            "source": "sqlite_migration",
        })
        if evaluation is not None:
            store.insert_new("rescue_actions", "migration_key", f"sqlite:rescue:{row['incident_id']}", {
                "migration_key": f"sqlite:rescue:{row['incident_id']}",
                "incident_id": row["incident_id"],
                "order_id": order_id,
                "agent_id": agent_id,
                "recommended_action": evaluation["recommended_action"],
                "risk_level": evaluation["risk_level"],
                "risk_score": evaluation["risk_score"],
                "created_at": recorded_at,
                "source": "sqlite_migration",
            })
        store.insert_new("audit_logs", "migration_key", key, {
            "migration_key": key,
            "source": "sqlite_migration",
            "event_type": "incident",
            "incident_id": row["incident_id"],
            "order_id": order_id,
            "agent_id": agent_id,
            "anomaly_type": row["anomaly_type"],
            "anomaly_score": row["anomaly_score"],
            "created_at": recorded_at,
            "note": "Copied from SQLite. The original row and its hash were not rewritten.",
        })
        counts["incidents"] += 1

    for row in actions:
        key = f"sqlite:decision:{row['action_id']}"
        if store.find_one("audit_logs", "migration_key", key):
            counts["skipped"] += 1
            continue
        decided_at = _utc(row["decided_at"])
        store.insert_new("rescue_actions", "migration_key", key, {
            "migration_key": key,
            "incident_id": row["incident_id"],
            "approval_status": row["approval_status"],
            "operator_name": row["operator_name"],
            "execution_status": row["execution_status"],
            "event_type": "operator_decision",
            "created_at": decided_at,
            "source": "sqlite_migration",
        })
        store.insert_new("audit_logs", "migration_key", key, {
            "migration_key": key,
            "source": "sqlite_migration",
            "event_type": "decision",
            "incident_id": row["incident_id"],
            "approval_status": row["approval_status"],
            "operator_name": row["operator_name"],
            "execution_status": row["execution_status"],
            "created_at": decided_at,
            "note": "Copied from SQLite operator_actions.",
        })
        counts["decisions"] += 1

    for row in chain:
        key = f"sqlite:chain:{row['seq']}"
        if store.find_one("audit_logs", "migration_key", key):
            counts["skipped"] += 1
            continue
        try:
            payload: Any = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            payload = {"raw": row["payload_json"]}
        store.insert_new("audit_logs", "migration_key", key, {
            "migration_key": key,
            "source": "sqlite_migration",
            "event_type": row["event_type"],
            "incident_id": row["incident_id"],
            "payload": payload,
            "payload_json": row["payload_json"],
            "previous_hash": row["previous_hash"],
            "event_hash": row["event_hash"],
            "chain_seq": row["seq"],
            "created_at": datetime.now(timezone.utc),
            "note": "Original SQLite hash-chain event. Hashes were copied, not recomputed.",
        })
        counts["chain_events"] += 1
    connection.close()
    return counts


def main() -> None:
    load_env_file()
    store, kind = open_document_store()
    if store is None:
        raise SystemExit(
            "MongoDB is not connected. Set MONGODB_URI to the Atlas connection string and run this again. "
            f"Status: {kind}."
        )
    counts = migrate_sqlite(store, default_audit_path())
    print(
        "SQLite copy finished. The original findr_audit.db was left in place. "
        f"incidents={counts['incidents']} decisions={counts['decisions']} "
        f"chain_events={counts['chain_events']} skipped={counts['skipped']}"
    )


if __name__ == "__main__":
    main()
