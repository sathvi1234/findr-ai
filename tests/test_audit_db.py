"""Unit tests for AuditDatabase."""

import sqlite3

import pytest
from src.audit_db import AuditDatabase, ApprovalTransitionError
from src.simulator import ScenarioSimulator
from src.integrity_engine import DeterministicIntegrityEngine
from src.models import (
    IncidentRecord,
    ApprovalStatus,
    AnomalyType,
)


def test_audit_db_lifecycle(tmp_path):
    test_db = tmp_path / "test_audit.db"
    db = AuditDatabase(db_path=test_db)

    # Process frame
    sim = ScenarioSimulator()
    frame = sim.generate_scenario_stream(AnomalyType.NONE, total_steps=1)[0]
    engine = DeterministicIntegrityEngine()
    integ = engine.assess_frame(frame)

    incident = IncidentRecord(
        incident_id="TEST-INC-001",
        drone_id=frame.drone_id,
        mission_id=frame.mission_id,
        timestamp=frame.timestamp,
        telemetry=frame,
        integrity=integ,
    )

    db.record_incident(incident)

    # Check stats
    stats = db.get_audit_summary_stats()
    assert stats["total_frames_processed"] == 1

    # Update decision
    db.update_operator_decision(
        incident_id="TEST-INC-001",
        status=ApprovalStatus.APPROVED,
        operator_name="Operator Sarah",
        notes="Safe test authorization",
        execution_status="EXECUTED",
    )

    stats2 = db.get_audit_summary_stats()
    assert stats2["total_rescues_approved"] == 1

    # Retrieve rows
    rows = db.list_recent_incidents(limit=5)
    assert len(rows) == 1
    assert rows[0]["incident_id"] == "TEST-INC-001"
    assert rows[0]["approval_status"] == "APPROVED"
    assert rows[0]["operator_name"] == "Operator Sarah"

    intact, problems = db.verify_integrity()
    assert intact is True
    assert problems == []


def test_hash_chain_detects_a_rewritten_anomaly_score(tmp_path):
    db = AuditDatabase(db_path=tmp_path / "tamper.db")
    sim = ScenarioSimulator()
    frame = sim.generate_scenario_stream(AnomalyType.NONE, total_steps=1, seed=1)[0]
    engine = DeterministicIntegrityEngine()
    integ = engine.assess_frame(frame)
    db.record_incident(IncidentRecord(
        incident_id="TEST-INC-TAMPER",
        drone_id=frame.drone_id,
        mission_id=frame.mission_id,
        timestamp=frame.timestamp,
        telemetry=frame,
        integrity=integ,
    ))
    ok, problems = db.verify_integrity()
    assert ok is True
    assert problems == []

    with sqlite3.connect(db.db_path) as conn:
        conn.execute(
            "UPDATE incidents SET anomaly_score = 99 WHERE incident_id = 'TEST-INC-TAMPER'"
        )

    ok, problems = db.verify_integrity()
    assert ok is False
    assert any("tampered anomaly score" in item for item in problems)


def test_deleting_the_chain_tip_without_the_anchor_fails(tmp_path):
    db = AuditDatabase(db_path=tmp_path / "truncate.db")
    sim = ScenarioSimulator()
    engine = DeterministicIntegrityEngine()
    stream = sim.generate_scenario_stream(AnomalyType.NONE, total_steps=2, seed=2)
    for index, frame in enumerate(stream):
        integ = engine.assess_frame(frame)
        db.record_incident(IncidentRecord(
            incident_id=f"TEST-INC-{index}",
            drone_id=frame.drone_id,
            mission_id=frame.mission_id,
            timestamp=frame.timestamp,
            telemetry=frame,
            integrity=integ,
        ))
    ok, _problems = db.verify_integrity()
    assert ok is True

    with sqlite3.connect(db.db_path) as conn:
        conn.execute("DELETE FROM audit_chain WHERE seq = (SELECT MAX(seq) FROM audit_chain)")

    ok, problems = db.verify_integrity()
    assert ok is False
    assert any("endpoint unproven" in item or "broken link" in item for item in problems)


def test_duplicate_operator_decision_is_rejected(tmp_path):
    db = AuditDatabase(db_path=tmp_path / "once.db")
    sim = ScenarioSimulator()
    frame = sim.generate_scenario_stream(AnomalyType.NONE, total_steps=1, seed=3)[0]
    engine = DeterministicIntegrityEngine()
    integ = engine.assess_frame(frame)
    db.record_incident(IncidentRecord(
        incident_id="TEST-INC-ONCE",
        drone_id=frame.drone_id,
        mission_id=frame.mission_id,
        timestamp=frame.timestamp,
        telemetry=frame,
        integrity=integ,
    ))
    db.update_operator_decision(
        incident_id="TEST-INC-ONCE",
        status=ApprovalStatus.APPROVED,
        operator_name="Operator Sarah",
        notes="first",
        execution_status="EXECUTED",
    )
    with pytest.raises(ApprovalTransitionError):
        db.update_operator_decision(
            incident_id="TEST-INC-ONCE",
            status=ApprovalStatus.REJECTED,
            operator_name="Operator Sarah",
            notes="second",
            execution_status="CANCELLED_BY_OPERATOR",
        )
    stats = db.get_audit_summary_stats()
    assert stats["total_rescues_approved"] == 1
    assert stats["total_rescues_rejected"] == 0
