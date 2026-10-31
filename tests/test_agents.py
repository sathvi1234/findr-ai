"""Tests for investigation, risk, and rescue agents."""

from src.agents.investigation_agent import InvestigationAgent
from src.agents.rescue_agent import RescueAgent
from src.agents.risk_agent import RiskAssessmentAgent
from src.integrity_engine import DeterministicIntegrityEngine
from src.models import (
    AnomalyType,
    ApprovalStatus,
    IntegrityAssessment,
    InvestigationReport,
    PayloadPriority,
    RescueActionType,
    RiskAssessment,
    SafeHavenZone,
)
from src.simulator import ScenarioSimulator, haversine_distance


def _pipeline(scenario: AnomalyType, attack_start: int, total_steps: int, seed: int):
    sim = ScenarioSimulator(payload_type=PayloadPriority.ORGAN_TRANSPORT)
    engine = DeterministicIntegrityEngine()
    stream = sim.generate_scenario_stream(
        scenario, total_steps=total_steps, attack_start_step=attack_start, seed=seed
    )
    for frame in stream[:attack_start]:
        engine.assess_frame(frame)
    assessment = engine.assess_frame(stream[attack_start])
    investigator = InvestigationAgent()
    risk_agent = RiskAssessmentAgent()
    rescue = RescueAgent()
    report = investigator.investigate("INC-AGENT", stream[attack_start], assessment)
    risk = risk_agent.evaluate_risk("INC-AGENT", stream[attack_start], assessment, report)
    plan = rescue.plan_rescue("INC-AGENT", stream[attack_start], assessment, report, risk)
    return stream[attack_start], assessment, report, risk, plan


def test_teleport_agents_agree_with_integrity_engine():
    _frame, assessment, report, risk, plan = _pipeline(
        AnomalyType.TELEPORTATION_JUMP, attack_start=2, total_steps=4, seed=3
    )
    assert assessment.is_anomalous is True
    assert assessment.primary_anomaly == AnomalyType.TELEPORTATION_JUMP
    assert "CONFIRMED_SPOOFING" in report.investigation_verdict
    assert report.confidence_pct >= 85.0
    assert report.evidence_points
    assert risk.overall_risk_level in ("HIGH", "CRITICAL")
    assert risk.requires_immediate_rescue is True
    assert "ORGAN_TRANSPORT" in risk.payload_criticality
    assert risk.battery_margin_min > 0.0
    assert plan.recommended_action == RescueActionType.REROUTE_SAFE_HAVEN
    assert plan.requires_human_approval is True
    assert plan.approval_status == ApprovalStatus.PENDING
    assert plan.execution_status == "AWAITING_APPROVAL"
    assert plan.target_zone is not None
    assert plan.target_zone.landing_capacity > 0


def test_multipath_stays_a_hold_not_a_spoofing_divert():
    _frame, assessment, report, risk, plan = _pipeline(
        AnomalyType.MULTIPATH_INTERFERENCE, attack_start=3, total_steps=6, seed=29
    )
    assert assessment.primary_anomaly == AnomalyType.MULTIPATH_INTERFERENCE
    assert assessment.is_anomalous is False
    assert "BENIGN_DEGRADATION" in report.investigation_verdict
    assert risk.overall_risk_level == "MEDIUM"
    assert risk.requires_immediate_rescue is False
    assert plan.recommended_action == RescueActionType.HOVER_HOLD_VERIFY
    assert plan.requires_human_approval is True
    assert plan.execution_status == "AWAITING_APPROVAL"


def test_safe_haven_uses_ins_position_and_skips_a_full_pad():
    frame, assessment, report, risk, _plan = _pipeline(
        AnomalyType.RF_POWER_SURGE, attack_start=1, total_steps=3, seed=17
    )
    assert assessment.primary_anomaly == AnomalyType.RF_POWER_SURGE
    ins_lat = frame.inertial_truth.latitude
    ins_lon = frame.inertial_truth.longitude
    frame.reported_gps.latitude = ins_lat + 0.08
    frame.reported_gps.longitude = ins_lon + 0.08
    spoofed = SafeHavenZone(
        zone_id="SPOOF-NEAR",
        name="Pad Beside the Spoofed Fix",
        latitude=frame.reported_gps.latitude,
        longitude=frame.reported_gps.longitude,
        altitude_m=160.0,
        landing_capacity=3,
        is_secured_perimeter=True,
    )
    full_pad = SafeHavenZone(
        zone_id="FULL",
        name="Full Pad on the Inertial Position",
        latitude=ins_lat,
        longitude=ins_lon,
        altitude_m=160.0,
        landing_capacity=0,
        is_secured_perimeter=True,
    )
    open_pad = SafeHavenZone(
        zone_id="OPEN",
        name="Open Secured Pad",
        latitude=ins_lat + 0.01,
        longitude=ins_lon,
        altitude_m=160.0,
        landing_capacity=2,
        is_secured_perimeter=True,
    )
    frame.safe_havens = [spoofed, full_pad, open_pad]
    plan = RescueAgent().plan_rescue("INC-HAVEN", frame, assessment, report, risk)
    assert plan.target_zone is not None
    assert plan.target_zone.zone_id == "OPEN"
    assert haversine_distance(ins_lat, ins_lon, open_pad.latitude, open_pad.longitude) < haversine_distance(
        ins_lat, ins_lon, spoofed.latitude, spoofed.longitude
    )


def test_risk_fields_cover_payload_battery_and_collateral():
    frame, assessment, report, risk, _plan = _pipeline(
        AnomalyType.NONE, attack_start=0, total_steps=1, seed=2
    )
    # attack_start 0 on a clean scenario never injects an attack
    assert assessment.primary_anomaly == AnomalyType.NONE
    assert isinstance(risk, RiskAssessment)
    assert isinstance(report, InvestigationReport)
    assert risk.overall_risk_level == "LOW"
    assert risk.can_continue_autonomous is True
    assert "battery" in risk.collateral_ground_risk.lower() or "Battery" in risk.collateral_ground_risk or "LOW" in risk.collateral_ground_risk
    assert frame.battery_pct > 80.0


def test_manual_integrity_still_selects_an_open_haven():
    frame, _assessment, report, _risk, _plan = _pipeline(
        AnomalyType.TELEPORTATION_JUMP, attack_start=1, total_steps=2, seed=4
    )
    forced = IntegrityAssessment(
        timestamp=frame.timestamp,
        is_anomalous=True,
        anomaly_score=80.0,
        primary_anomaly=AnomalyType.INSIDIOUS_DRIFT,
        rule_explanation="synthetic divergence",
        dr_residual_m=80.0,
    )
    risk = RiskAssessment(
        incident_id="INC-FORCED",
        overall_risk_level="CRITICAL",
        risk_score=90.0,
        payload_criticality="ORGAN_TRANSPORT",
        flight_safety_hazard="CRITICAL_NAV_LOSS",
        collateral_ground_risk="LOW",
        battery_margin_min=8.0,
        can_continue_autonomous=False,
        requires_immediate_rescue=True,
        risk_summary="forced",
    )
    frame.safe_havens = [
        SafeHavenZone(
            zone_id="NEAR-FULL",
            name="Nearest Full",
            latitude=frame.inertial_truth.latitude + 0.0001,
            longitude=frame.inertial_truth.longitude,
            altitude_m=120.0,
            landing_capacity=0,
        ),
        SafeHavenZone(
            zone_id="FAR-OPEN",
            name="Farther Open",
            latitude=frame.inertial_truth.latitude + 0.02,
            longitude=frame.inertial_truth.longitude,
            altitude_m=120.0,
            landing_capacity=1,
        ),
    ]
    plan = RescueAgent().plan_rescue("INC-FORCED", frame, forced, report, risk)
    assert plan.target_zone is not None
    assert plan.target_zone.zone_id == "FAR-OPEN"
