"""Tests for dashboard frame selection and audit filtering."""

import pytest

from src.mission_view import banner_for, filter_audit_rows, select_record
from src.models import AnomalyType
from src.orchestrator import IncidentOrchestrator
from src.audit_db import AuditDatabase
from src.simulator import ScenarioSimulator


def test_banner_distinguishes_attack_multipath_and_nominal():
    assert banner_for(True, AnomalyType.TELEPORTATION_JUMP) == "ATTACK"
    assert banner_for(False, AnomalyType.MULTIPATH_INTERFERENCE) == "MULTIPATH"
    assert banner_for(False, AnomalyType.NONE) == "NOMINAL"


def test_select_record_returns_the_requested_frame(tmp_path):
    db = AuditDatabase(db_path=tmp_path / "frames.db")
    orchestrator = IncidentOrchestrator(audit_db=db)
    stream = ScenarioSimulator().generate_scenario_stream(
        AnomalyType.TELEPORTATION_JUMP, total_steps=4, attack_start_step=2, seed=8
    )
    records = [orchestrator.process_frame(frame) for frame in stream]
    chosen = select_record(records, 2)
    assert chosen.telemetry.sequence_id == 2
    assert chosen.integrity.primary_anomaly == records[2].integrity.primary_anomaly
    assert chosen.incident_id == records[2].incident_id
    with pytest.raises(IndexError):
        select_record(records, 9)
    with pytest.raises(IndexError):
        select_record([], 0)


def test_filter_audit_rows_by_anomaly_type():
    rows = [
        {"incident_id": "a", "anomaly_type": "NONE"},
        {"incident_id": "b", "anomaly_type": "RF_POWER_SURGE"},
        {"incident_id": "c", "anomaly_type": "RF_POWER_SURGE"},
    ]
    assert [row["incident_id"] for row in filter_audit_rows(rows, "ALL")] == ["a", "b", "c"]
    assert [row["incident_id"] for row in filter_audit_rows(rows, None)] == ["a", "b", "c"]
    surged = filter_audit_rows(rows, "RF_POWER_SURGE")
    assert [row["incident_id"] for row in surged] == ["b", "c"]
