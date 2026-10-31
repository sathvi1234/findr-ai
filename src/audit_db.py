"""
FINDR AI — SQLite Audit History Engine
======================================
Append-only incident history with a SHA-256 hash chain.

Each event stores the hash of its canonical payload plus the previous event
hash. Verification recomputes that chain and compares incident and operator
rows with the hashed payload.

This is tamper-evident, not tamper-proof. A person who can rewrite the
database can also recompute every hash and the endpoint anchor. Deleting the
newest rows without updating the anchor is detected. Rewriting the chain and
the anchor together is not.
"""

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.models import ApprovalStatus, IncidentRecord

def default_audit_path() -> Path:
    """Persistent audit file. Set FINDR_AUDIT_DB to a durable disk path in production."""
    configured = os.environ.get("FINDR_AUDIT_DB", "").strip()
    return Path(configured) if configured else Path("findr_audit.db")


DEFAULT_DB_PATH = default_audit_path()
GENESIS_HASH = "0" * 64
TERMINAL_APPROVALS = {
    ApprovalStatus.APPROVED,
    ApprovalStatus.REJECTED,
    ApprovalStatus.OVERRIDDEN,
}
OPERATOR_DECISIONS = TERMINAL_APPROVALS


class ApprovalTransitionError(ValueError):
    """Raised when an operator decision repeats or skips the pending state."""


class AuditDatabase:
    """Manages SQLite tables and the hash-chained audit log."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path is not None else default_audit_path()
        if self.db_path.parent not in (Path("."), Path("")):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db(self):
        """Create tables and indexes if they do not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                incident_id TEXT PRIMARY KEY,
                drone_id TEXT NOT NULL,
                mission_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                anomaly_type TEXT NOT NULL,
                anomaly_score REAL NOT NULL,
                is_anomalous INTEGER NOT NULL,
                reported_lat REAL NOT NULL,
                reported_lon REAL NOT NULL,
                reported_alt REAL NOT NULL,
                truth_lat REAL NOT NULL,
                truth_lon REAL NOT NULL,
                truth_alt REAL NOT NULL,
                kinematic_jump_m REAL,
                dr_residual_m REAL,
                snr_mean REAL,
                snr_std REAL,
                rule_explanation TEXT
            );
            """)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_evaluations (
                incident_id TEXT PRIMARY KEY,
                investigation_verdict TEXT,
                evidence_points TEXT,
                rf_summary TEXT,
                risk_level TEXT,
                risk_score REAL,
                risk_summary TEXT,
                recommended_action TEXT,
                target_zone_name TEXT,
                flight_mode TEXT,
                rescue_rationale TEXT,
                urgency TEXT,
                requires_human_approval INTEGER,
                FOREIGN KEY (incident_id) REFERENCES incidents (incident_id)
            );
            """)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS operator_actions (
                action_id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id TEXT NOT NULL,
                approval_status TEXT NOT NULL,
                operator_name TEXT,
                operator_notes TEXT,
                decided_at REAL NOT NULL,
                execution_status TEXT NOT NULL,
                FOREIGN KEY (incident_id) REFERENCES incidents (incident_id)
            );
            """)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_chain (
                seq INTEGER PRIMARY KEY,
                event_type TEXT NOT NULL,
                incident_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL
            );
            """)
            self._migrate(cursor)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_anchor (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                event_count INTEGER NOT NULL,
                tip_hash TEXT NOT NULL
            );
            """)
            conn.commit()

    @staticmethod
    def _migrate(cursor: sqlite3.Cursor) -> None:
        """Add delivery columns. Existing rows and the hash chain are left in place."""
        columns = {row[1] for row in cursor.execute("PRAGMA table_info(incidents)")}
        for name, column_type in (
            ("agent_id", "TEXT"),
            ("order_id", "TEXT"),
            ("vehicle_type", "TEXT"),
            ("delivery_status", "TEXT"),
        ):
            if name not in columns:
                cursor.execute(f"ALTER TABLE incidents ADD COLUMN {name} {column_type}")
        cursor.execute(
            "UPDATE incidents SET agent_id = drone_id WHERE agent_id IS NULL OR agent_id = ''"
        )
        cursor.execute(
            "UPDATE incidents SET order_id = mission_id WHERE order_id IS NULL OR order_id = ''"
        )

    def record_incident(self, incident: IncidentRecord):
        """Persist a complete incident frame and append it to the hash chain."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            state = incident.telemetry
            gps = state.reported_gps
            truth = state.inertial_truth
            integ = incident.integrity
            inv = incident.investigation
            risk = incident.risk
            rescue = incident.rescue

            cursor.execute("""
            INSERT OR REPLACE INTO incidents (
                incident_id, drone_id, mission_id, timestamp, anomaly_type,
                anomaly_score, is_anomalous, reported_lat, reported_lon, reported_alt,
                truth_lat, truth_lon, truth_alt, kinematic_jump_m, dr_residual_m,
                snr_mean, snr_std, rule_explanation,
                agent_id, order_id, vehicle_type, delivery_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                incident.incident_id,
                incident.agent_id,
                incident.order_id,
                incident.timestamp,
                integ.primary_anomaly.value,
                integ.anomaly_score,
                1 if integ.is_anomalous else 0,
                gps.latitude, gps.longitude, gps.altitude_m,
                truth.latitude, truth.longitude, truth.altitude_m,
                integ.kinematic_jump_m,
                integ.dr_residual_m,
                integ.snr_mean_db,
                integ.snr_std_db,
                integ.rule_explanation,
                incident.agent_id,
                incident.order_id,
                state.vehicle_type.value,
                state.delivery_status.value,
            ))

            if inv and risk and rescue:
                target_zone = rescue.target_zone.name if rescue.target_zone else None
                cursor.execute("""
                INSERT OR REPLACE INTO agent_evaluations (
                    incident_id, investigation_verdict, evidence_points, rf_summary,
                    risk_level, risk_score, risk_summary, recommended_action,
                    target_zone_name, flight_mode, rescue_rationale, urgency,
                    requires_human_approval
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    incident.incident_id,
                    inv.investigation_verdict,
                    json.dumps(inv.evidence_points),
                    inv.rf_fingerprint_summary,
                    risk.overall_risk_level,
                    risk.risk_score,
                    risk.risk_summary,
                    rescue.recommended_action.value,
                    target_zone,
                    rescue.flight_mode_switch,
                    rescue.rescue_rationale,
                    rescue.urgency_level,
                    1 if rescue.requires_human_approval else 0,
                ))
                cursor.execute("""
                INSERT INTO operator_actions (
                    incident_id, approval_status, operator_name, operator_notes,
                    decided_at, execution_status
                ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    incident.incident_id,
                    rescue.approval_status.value,
                    rescue.approved_by,
                    rescue.operator_notes,
                    time.time(),
                    rescue.execution_status,
                ))

            self._append_chain(cursor, "incident", incident.incident_id, self._incident_payload(incident))
            conn.commit()

    def update_operator_decision(
        self,
        incident_id: str,
        status: ApprovalStatus,
        operator_name: str,
        notes: str,
        execution_status: str,
    ):
        """Record one approve, reject, or override. A second decision is rejected."""
        cleaned_name = (operator_name or "").strip()
        if not cleaned_name:
            raise ValueError("operator name is required")
        if status not in OPERATOR_DECISIONS:
            raise ApprovalTransitionError(
                "Operator decisions are approve, reject, or override."
            )

        decided_at = time.time()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            parent = cursor.execute(
                "SELECT incident_id FROM incidents WHERE incident_id = ?",
                (incident_id,),
            ).fetchone()
            if parent is None:
                raise ApprovalTransitionError(
                    f"No incident {incident_id} exists to authorize."
                )
            latest = self._latest_status(cursor, incident_id)
            if latest in TERMINAL_APPROVALS or latest == ApprovalStatus.NOT_REQUIRED:
                current = latest.value if latest else "none"
                raise ApprovalTransitionError(
                    f"Cannot apply {status.value} after {current}."
                )

            cursor.execute("""
            INSERT INTO operator_actions (
                incident_id, approval_status, operator_name, operator_notes,
                decided_at, execution_status
            ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                incident_id,
                status.value,
                cleaned_name,
                notes,
                decided_at,
                execution_status,
            ))
            self._append_chain(cursor, "decision", incident_id, {
                "incident_id": incident_id,
                "approval_status": status.value,
                "operator_name": cleaned_name,
                "operator_notes": notes,
                "execution_status": execution_status,
                "decided_at": decided_at,
            })
            conn.commit()

    def list_recent_incidents(
        self,
        limit: int = 20,
        anomaly_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve recent incidents joined to the latest operator action."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT
                i.incident_id, i.drone_id, i.mission_id, i.agent_id, i.order_id,
                i.vehicle_type, i.delivery_status, i.timestamp,
                i.anomaly_type, i.anomaly_score, i.is_anomalous, i.rule_explanation,
                a.risk_level, a.risk_score, a.recommended_action, a.target_zone_name,
                o.approval_status, o.operator_name, o.operator_notes,
                o.execution_status, o.decided_at
            FROM incidents i
            LEFT JOIN agent_evaluations a ON i.incident_id = a.incident_id
            LEFT JOIN operator_actions o ON o.action_id = (
                SELECT MAX(action_id) FROM operator_actions
                WHERE incident_id = i.incident_id
            )
            WHERE (? IS NULL OR i.anomaly_type = ?)
            ORDER BY i.timestamp DESC
            LIMIT ?
            """, (anomaly_type, anomaly_type, limit))
            return [dict(row) for row in cursor.fetchall()]

    def get_audit_summary_stats(self) -> Dict[str, Any]:
        """Compute aggregated statistics across audit history."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM incidents")
            total_incidents = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM incidents WHERE is_anomalous = 1")
            total_anomalies = cursor.fetchone()[0]
            cursor.execute(
                "SELECT COUNT(*) FROM operator_actions WHERE approval_status = 'APPROVED'"
            )
            total_approved = cursor.fetchone()[0]
            cursor.execute(
                "SELECT COUNT(*) FROM operator_actions WHERE approval_status = 'REJECTED'"
            )
            total_rejected = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT drone_id) FROM incidents")
            agents = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT mission_id) FROM incidents")
            orders = cursor.fetchone()[0]
            cursor.execute(
                "SELECT COUNT(DISTINCT mission_id) FROM incidents WHERE is_anomalous = 1"
            )
            suspicious_orders = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT COUNT(*) FROM operator_actions AS action
                WHERE action.action_id = (
                    SELECT MAX(latest.action_id) FROM operator_actions AS latest
                    WHERE latest.incident_id = action.incident_id
                )
                AND action.approval_status = 'PENDING'
                """
            )
            pending = cursor.fetchone()[0]
            return {
                "total_frames_processed": total_incidents,
                "total_anomalies_flagged": total_anomalies,
                "total_rescues_approved": total_approved,
                "total_rescues_rejected": total_rejected,
                "active_agents": agents,
                "orders_monitored": orders,
                "suspicious_orders": suspicious_orders,
                "pending_authorizations": pending,
            }

    def verify_integrity(self) -> Tuple[bool, List[str]]:
        """Recompute the hash chain and compare it with stored incident rows.

        Returns ``(ok, problems)``. An empty database is intact. A chain whose
        newest rows were deleted without updating the anchor is not.
        """
        problems: List[str] = []
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT seq, event_type, incident_id, payload_json, previous_hash, event_hash "
                "FROM audit_chain ORDER BY seq ASC"
            ).fetchall()
            anchor = conn.execute(
                "SELECT event_count, tip_hash FROM audit_anchor WHERE id = 1"
            ).fetchone()

            if not rows and anchor is None:
                return True, []
            if not rows and anchor is not None:
                problems.append("endpoint unproven: anchor exists but the chain is empty")
            if rows and anchor is None:
                problems.append("endpoint unproven: chain has events but the anchor is missing")

            previous = GENESIS_HASH
            for index, row in enumerate(rows, start=1):
                if int(row["seq"]) != index:
                    problems.append(
                        f"broken link at seq {row['seq']}: expected sequence {index}"
                    )
                if row["previous_hash"] != previous:
                    problems.append(
                        f"broken link at seq {row['seq']}: previous hash does not match"
                    )
                recomputed = self._event_hash(row["previous_hash"], row["payload_json"])
                if recomputed != row["event_hash"]:
                    problems.append(f"tampered payload at seq {row['seq']}")
                self._check_payload_against_tables(conn, row, problems)
                previous = row["event_hash"]

            if anchor is not None and rows:
                if int(anchor["event_count"]) != len(rows):
                    problems.append(
                        "endpoint unproven: anchor count does not match chain length"
                    )
                if anchor["tip_hash"] != rows[-1]["event_hash"]:
                    problems.append(
                        "endpoint unproven: anchor tip does not match the last event"
                    )
        return len(problems) == 0, problems

    def _incident_payload(self, incident: IncidentRecord) -> Dict[str, Any]:
        integ = incident.integrity
        inv = incident.investigation
        risk = incident.risk
        rescue = incident.rescue
        return {
            "incident_id": incident.incident_id,
            "drone_id": incident.agent_id,
            "mission_id": incident.order_id,
            "agent_id": incident.agent_id,
            "order_id": incident.order_id,
            "vehicle_type": incident.telemetry.vehicle_type.value,
            "timestamp": incident.timestamp,
            "anomaly_type": integ.primary_anomaly.value,
            "anomaly_score": integ.anomaly_score,
            "is_anomalous": bool(integ.is_anomalous),
            "rule_explanation": integ.rule_explanation,
            "reported_lat": incident.telemetry.reported_gps.latitude,
            "reported_lon": incident.telemetry.reported_gps.longitude,
            "verdict": inv.investigation_verdict if inv else None,
            "risk_level": risk.overall_risk_level if risk else None,
            "recommended_action": rescue.recommended_action.value if rescue else None,
            "approval_status": rescue.approval_status.value if rescue else None,
        }

    def _append_chain(self, cursor: sqlite3.Cursor, event_type: str, incident_id: str, payload: Dict[str, Any]):
        tip = cursor.execute(
            "SELECT seq, event_hash FROM audit_chain ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        if tip is None:
            seq = 1
            previous = GENESIS_HASH
        else:
            seq = int(tip["seq"]) + 1
            previous = tip["event_hash"]
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        event_hash = self._event_hash(previous, payload_json)
        cursor.execute("""
        INSERT INTO audit_chain (
            seq, event_type, incident_id, payload_json, previous_hash, event_hash
        ) VALUES (?, ?, ?, ?, ?, ?)
        """, (seq, event_type, incident_id, payload_json, previous, event_hash))
        cursor.execute("""
        INSERT INTO audit_anchor (id, event_count, tip_hash) VALUES (1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            event_count = excluded.event_count,
            tip_hash = excluded.tip_hash
        """, (seq, event_hash))

    @staticmethod
    def _event_hash(previous_hash: str, payload_json: str) -> str:
        material = f"{previous_hash}|{payload_json}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    @staticmethod
    def _latest_status(cursor: sqlite3.Cursor, incident_id: str) -> Optional[ApprovalStatus]:
        row = cursor.execute(
            "SELECT approval_status FROM operator_actions WHERE incident_id = ? "
            "ORDER BY action_id DESC LIMIT 1",
            (incident_id,),
        ).fetchone()
        if row is None:
            return None
        return ApprovalStatus(row["approval_status"])

    def _check_payload_against_tables(self, conn: sqlite3.Connection, row: sqlite3.Row, problems: List[str]):
        payload = json.loads(row["payload_json"])
        if row["event_type"] == "incident":
            stored = conn.execute(
                "SELECT anomaly_type, anomaly_score FROM incidents WHERE incident_id = ?",
                (row["incident_id"],),
            ).fetchone()
            if stored is None:
                problems.append(f"tampered or missing incident row {row['incident_id']}")
                return
            if stored["anomaly_type"] != payload["anomaly_type"]:
                problems.append(f"tampered anomaly type for {row['incident_id']}")
            if abs(float(stored["anomaly_score"]) - float(payload["anomaly_score"])) > 1e-6:
                problems.append(f"tampered anomaly score for {row['incident_id']}")
            return

        if row["event_type"] == "decision":
            actions = conn.execute(
                "SELECT approval_status, operator_name, execution_status, decided_at, operator_notes "
                "FROM operator_actions WHERE incident_id = ?",
                (payload["incident_id"],),
            ).fetchall()
            found = any(
                action["approval_status"] == payload["approval_status"]
                and action["operator_name"] == payload["operator_name"]
                and action["execution_status"] == payload["execution_status"]
                and (action["operator_notes"] or "") == (payload["operator_notes"] or "")
                and abs(float(action["decided_at"]) - float(payload["decided_at"])) < 1e-4
                for action in actions
            )
            if not found:
                problems.append(f"tampered operator decision for {payload['incident_id']}")
