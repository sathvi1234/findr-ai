"""Unit tests for RescueWorkflowManager."""

import pytest
from src.rescue_workflow import RescueWorkflowManager
from src.audit_db import ApprovalTransitionError, AuditDatabase
from src.integrity_engine import DeterministicIntegrityEngine
from src.simulator import ScenarioSimulator, haversine_distance
from src.models import (
    IncidentRecord,
    RescuePlan,
    RescueActionType,
    ApprovalStatus,
    AnomalyType,
)


def _store_frame(db: AuditDatabase, incident_id: str):
    frame = ScenarioSimulator().generate_scenario_stream(
        AnomalyType.NONE, total_steps=1, seed=11
    )[0]
    integ = DeterministicIntegrityEngine().assess_frame(frame)
    db.record_incident(IncidentRecord(
        incident_id=incident_id,
        drone_id=frame.drone_id,
        mission_id=frame.mission_id,
        timestamp=frame.timestamp,
        telemetry=frame,
        integrity=integ,
    ))
    return frame


def _pending_plan(incident_id: str) -> RescuePlan:
    return RescuePlan(
        incident_id=incident_id,
        recommended_action=RescueActionType.REROUTE_SAFE_HAVEN,
        target_coordinates=(30.2850, -97.7320),
        flight_mode_switch="INS_ONLY",
        rescue_rationale="Simulated test plan",
        urgency_level="URGENT",
        requires_human_approval=True,
        approval_status=ApprovalStatus.PENDING,
        execution_status="AWAITING_APPROVAL",
    )


def test_rescue_workflow_human_gate(tmp_path):
    test_db = tmp_path / "test_rescue.db"
    db = AuditDatabase(db_path=test_db)
    manager = RescueWorkflowManager(audit_db=db)

    _store_frame(db, "INC-TEST-99")
    plan = _pending_plan("INC-TEST-99")

    # Human Approves
    updated_plan = manager.process_human_approval(
        incident_id="INC-TEST-99",
        rescue_plan=plan,
        decision=ApprovalStatus.APPROVED,
        operator_name="Flight Lead Chen",
        operator_notes="Confirmed diversion coordinates cleared",
    )

    assert updated_plan.approval_status == ApprovalStatus.APPROVED
    assert updated_plan.execution_status == "EXECUTED"
    assert updated_plan.approved_by == "Flight Lead Chen"


def test_simulated_recovery_step(tmp_path):
    manager = RescueWorkflowManager(audit_db=AuditDatabase(db_path=tmp_path / "recovery.db"))
    sim = ScenarioSimulator()
    frame = sim.generate_scenario_stream(AnomalyType.NONE, total_steps=1, seed=5)[0]

    plan = RescuePlan(
        incident_id="INC-TEST-100",
        recommended_action=RescueActionType.REROUTE_SAFE_HAVEN,
        target_coordinates=(30.2850, -97.7320),
        flight_mode_switch="INS_ONLY",
        rescue_rationale="Diverting",
        urgency_level="URGENT",
        requires_human_approval=True,
        approval_status=ApprovalStatus.APPROVED,
        execution_status="EXECUTED",
    )

    before = haversine_distance(
        frame.inertial_truth.latitude, frame.inertial_truth.longitude, 30.2850, -97.7320
    )
    next_state = manager.simulate_recovery_step(frame, plan, step_dt_seconds=1.0)
    after = haversine_distance(
        next_state.inertial_truth.latitude, next_state.inertial_truth.longitude, 30.2850, -97.7320
    )
    assert next_state.sequence_id == frame.sequence_id + 1
    assert next_state.battery_pct < frame.battery_pct
    assert after < before


def test_pending_and_rejected_plans_do_not_move_the_drone(tmp_path):
    db = AuditDatabase(db_path=tmp_path / "reject.db")
    manager = RescueWorkflowManager(audit_db=db)
    frame = _store_frame(db, "INC-REJECT")
    pending = _pending_plan("INC-REJECT")
    assert manager.simulate_recovery_step(frame, pending) is frame

    rejected = manager.process_human_approval(
        incident_id="INC-REJECT",
        rescue_plan=pending,
        decision=ApprovalStatus.REJECTED,
        operator_name="Flight Lead Chen",
        operator_notes="Continue on inertial corridor",
    )
    held = manager.simulate_recovery_step(frame, rejected)
    assert rejected.execution_status == "CANCELLED_BY_OPERATOR"
    assert held.sequence_id == frame.sequence_id
    assert held.inertial_truth.latitude == frame.inertial_truth.latitude
    rows = db.list_recent_incidents(limit=5)
    assert rows[0]["approval_status"] == "REJECTED"
    assert rows[0]["operator_name"] == "Flight Lead Chen"


def test_override_holds_position_instead_of_diverting(tmp_path):
    db = AuditDatabase(db_path=tmp_path / "override.db")
    manager = RescueWorkflowManager(audit_db=db)
    frame = _store_frame(db, "INC-HOLD")
    plan = _pending_plan("INC-HOLD")
    overridden = manager.process_human_approval(
        incident_id="INC-HOLD",
        rescue_plan=plan,
        decision=ApprovalStatus.OVERRIDDEN,
        operator_name="Flight Lead Chen",
        operator_notes="Hold and watch the corridor",
    )
    hovered = manager.simulate_recovery_step(frame, overridden)
    assert overridden.execution_status == "OVERRIDDEN_MANUAL_HOLD"
    assert overridden.recommended_action == RescueActionType.HOVER_HOLD_VERIFY
    assert hovered.inertial_truth.latitude == frame.inertial_truth.latitude
    assert hovered.inertial_truth.longitude == frame.inertial_truth.longitude
    assert hovered.inertial_truth.speed_mps == 0.0
    target_before = haversine_distance(
        frame.inertial_truth.latitude, frame.inertial_truth.longitude, 30.2850, -97.7320
    )
    target_after = haversine_distance(
        hovered.inertial_truth.latitude, hovered.inertial_truth.longitude, 30.2850, -97.7320
    )
    assert target_after == pytest.approx(target_before)


def test_second_decision_and_blank_operator_are_rejected(tmp_path):
    db = AuditDatabase(db_path=tmp_path / "twice.db")
    manager = RescueWorkflowManager(audit_db=db)
    _store_frame(db, "INC-TWICE")
    plan = _pending_plan("INC-TWICE")
    with pytest.raises(ValueError):
        manager.process_human_approval(
            incident_id="INC-TWICE",
            rescue_plan=plan,
            decision=ApprovalStatus.APPROVED,
            operator_name="   ",
            operator_notes="missing callsign",
        )
    assert plan.approval_status == ApprovalStatus.PENDING
    manager.process_human_approval(
        incident_id="INC-TWICE",
        rescue_plan=plan,
        decision=ApprovalStatus.APPROVED,
        operator_name="Flight Lead Chen",
        operator_notes="cleared",
    )
    with pytest.raises(ApprovalTransitionError):
        manager.process_human_approval(
            incident_id="INC-TWICE",
            rescue_plan=plan,
            decision=ApprovalStatus.REJECTED,
            operator_name="Flight Lead Chen",
            operator_notes="changed mind",
        )
    assert plan.approval_status == ApprovalStatus.APPROVED
    assert plan.execution_status == "EXECUTED"
