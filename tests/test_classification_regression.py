"""Regression checks for the teleport-versus-drift discrepancy."""

import os
import tempfile

from src.audit_db import AuditDatabase
from src.integrity_engine import DeterministicIntegrityEngine
from src.models import AnomalyType
from src.orchestrator import IncidentOrchestrator
from src.simulator import ScenarioSimulator

DASHBOARD_STEPS = 22
DASHBOARD_ATTACK = 10
LEGACY_STEPS = 18
LEGACY_ATTACK = 8
SEED = 409


def _assess(scenario, steps, attack_start):
    stream = ScenarioSimulator().generate_scenario_stream(
        scenario,
        total_steps=steps,
        attack_start_step=attack_start,
        seed=SEED,
    )
    engine = DeterministicIntegrityEngine()
    return stream, [engine.assess_frame(frame) for frame in stream]


def test_persisted_teleport_stays_a_teleport_on_both_stream_lengths():
    """The old 18-frame script and the dashboard's 22-frame run must agree."""
    for steps, attack_start in (
        (LEGACY_STEPS, LEGACY_ATTACK),
        (DASHBOARD_STEPS, DASHBOARD_ATTACK),
    ):
        _, assessments = _assess(AnomalyType.TELEPORTATION_JUMP, steps, attack_start)
        leap = assessments[attack_start]
        assert leap.primary_anomaly == AnomalyType.TELEPORTATION_JUMP
        assert any("KINEMATIC_JUMP_EXCEEDED" in rule for rule in leap.violated_rules)
        persisted = assessments[attack_start + 1 :]
        assert persisted
        for frame in persisted:
            assert frame.primary_anomaly == AnomalyType.TELEPORTATION_JUMP
            assert frame.is_anomalous is True
            assert frame.anomaly_score > 50
            assert any("GROSS_POSITION_OFFSET" in rule for rule in frame.violated_rules)
            assert frame.dr_residual_m >= 400


def test_creeping_drift_is_not_relabeled_as_a_teleport():
    _, assessments = _assess(AnomalyType.INSIDIOUS_DRIFT, DASHBOARD_STEPS, DASHBOARD_ATTACK)
    assert assessments[-1].primary_anomaly == AnomalyType.INSIDIOUS_DRIFT
    assert assessments[-1].dr_residual_m < 400
    assert all(item.primary_anomaly != AnomalyType.TELEPORTATION_JUMP for item in assessments)


def test_clean_flight_is_not_flagged():
    _, assessments = _assess(AnomalyType.NONE, DASHBOARD_STEPS, DASHBOARD_ATTACK)
    assert all(item.primary_anomaly == AnomalyType.NONE for item in assessments)
    assert all(item.is_anomalous is False for item in assessments)


def test_pipeline_timeline_matches_the_integrity_engine_for_every_scenario():
    for scenario in AnomalyType:
        stream, expected = _assess(scenario, DASHBOARD_STEPS, DASHBOARD_ATTACK)
        database = AuditDatabase(db_path=os.path.join(tempfile.mkdtemp(), "timeline.db"))
        orchestrator = IncidentOrchestrator(audit_db=database)
        records = [orchestrator.process_frame(frame) for frame in stream]
        assert [record.integrity.primary_anomaly for record in records] == [
            item.primary_anomaly for item in expected
        ]
        assert [record.integrity.anomaly_score for record in records] == [
            item.anomaly_score for item in expected
        ]


def test_later_runs_do_not_rewrite_stored_labels(tmp_path):
    database = AuditDatabase(db_path=tmp_path / "history.db")
    orchestrator = IncidentOrchestrator(audit_db=database)
    drift_stream = ScenarioSimulator().generate_scenario_stream(
        AnomalyType.INSIDIOUS_DRIFT,
        total_steps=DASHBOARD_STEPS,
        attack_start_step=DASHBOARD_ATTACK,
        seed=SEED,
    )
    drift_records = [orchestrator.process_frame(frame) for frame in drift_stream]
    drift_ids = [
        record.incident_id
        for record in drift_records
        if record.integrity.primary_anomaly == AnomalyType.INSIDIOUS_DRIFT
    ]
    assert drift_ids

    orchestrator.integrity_engine.reset()
    teleport_stream = ScenarioSimulator().generate_scenario_stream(
        AnomalyType.TELEPORTATION_JUMP,
        total_steps=DASHBOARD_STEPS,
        attack_start_step=DASHBOARD_ATTACK,
        seed=SEED,
    )
    for frame in teleport_stream:
        orchestrator.process_frame(frame)

    stored = {
        row["incident_id"]: row["anomaly_type"]
        for row in database.list_recent_incidents(limit=200)
    }
    for incident_id in drift_ids:
        assert stored[incident_id] == AnomalyType.INSIDIOUS_DRIFT.value
    intact, problems = database.verify_integrity()
    assert intact is True
    assert problems == []
