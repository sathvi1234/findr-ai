"""Unit tests for IncidentOrchestrator."""

import pytest
from src.orchestrator import IncidentOrchestrator
from src.audit_db import AuditDatabase
from src.simulator import ScenarioSimulator
from src.models import AnomalyType, RescueActionType, ApprovalStatus


def test_orchestrator_nominal_flow(tmp_path):
    test_db = tmp_path / "test_orch_nominal.db"
    db = AuditDatabase(db_path=test_db)
    orch = IncidentOrchestrator(audit_db=db)
    sim = ScenarioSimulator()

    stream = sim.generate_scenario_stream(AnomalyType.NONE, total_steps=3)
    for frame in stream:
        record = orch.process_frame(frame)
        assert record.integrity.is_anomalous is False
        assert record.risk.overall_risk_level == "LOW"
        assert record.rescue.recommended_action == RescueActionType.MAINTAIN_COURSE
        assert record.rescue.requires_human_approval is False


def test_orchestrator_spoofing_flow(tmp_path):
    test_db = tmp_path / "test_orch_spoof.db"
    db = AuditDatabase(db_path=test_db)
    orch = IncidentOrchestrator(audit_db=db)
    sim = ScenarioSimulator()

    stream = sim.generate_scenario_stream(
        AnomalyType.TELEPORTATION_JUMP, total_steps=10, attack_start_step=5
    )

    records = [orch.process_frame(f) for f in stream]
    attack_record = records[5]

    assert attack_record.integrity.is_anomalous is True
    assert attack_record.investigation is not None
    assert "CONFIRMED_SPOOFING" in attack_record.investigation.investigation_verdict
    assert attack_record.risk.overall_risk_level in ("HIGH", "CRITICAL")
    assert attack_record.rescue.recommended_action == RescueActionType.REROUTE_SAFE_HAVEN
    assert attack_record.rescue.requires_human_approval is True
    assert attack_record.rescue.approval_status == ApprovalStatus.PENDING

    # Verify persistent storage
    stats = db.get_audit_summary_stats()
    assert stats["total_frames_processed"] == 10
    assert stats["total_anomalies_flagged"] >= 5


def test_process_frame_accepts_reloaded_telemetry_class(tmp_path):
    """A same-shaped object from a reloaded module must still become an incident."""

    class ReloadedState:
        def __init__(self, state):
            self._state = state

        def __getattr__(self, name):
            return getattr(self._state, name)

        def model_dump(self, mode="python"):
            return self._state.model_dump(mode=mode)

    test_db = tmp_path / "test_orch_reload.db"
    orch = IncidentOrchestrator(audit_db=AuditDatabase(db_path=test_db))
    frame = ScenarioSimulator().generate_scenario_stream(AnomalyType.NONE, total_steps=1)[0]
    record = orch.process_frame(ReloadedState(frame))
    assert record.telemetry.drone_id == frame.drone_id
    assert record.telemetry.sequence_id == frame.sequence_id
