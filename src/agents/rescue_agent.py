"""
FINDR AI — Delivery Rescue Agent (Layer 2)
==========================================
Computes optimal recovery strategies and safe-haven diversions when GPS spoofing
is detected, enforcing human-in-the-loop authorization for all consequential actions.
"""

from typing import List, Optional, Tuple
from src.models import (
    DroneMissionState,
    IntegrityAssessment,
    InvestigationReport,
    RiskAssessment,
    RescuePlan,
    RescueActionType,
    ApprovalStatus,
    SafeHavenZone,
    AnomalyType,
)
from src.simulator import haversine_distance


class RescueAgent:
    """
    Formulates recovery plans and safe-haven diversions based on risk assessments.
    """

    def plan_rescue(
        self,
        incident_id: str,
        state: DroneMissionState,
        integrity: IntegrityAssessment,
        investigation: InvestigationReport,
        risk: RiskAssessment,
    ) -> RescuePlan:
        # Default nominal plan
        if not risk.requires_immediate_rescue and integrity.primary_anomaly == AnomalyType.NONE:
            return RescuePlan(
                incident_id=incident_id,
                recommended_action=RescueActionType.MAINTAIN_COURSE,
                target_zone=None,
                target_coordinates=state.destination_coords,
                flight_mode_switch="CONTINUE_ON_ROUTE",
                rescue_rationale="GPS and the reference track agree. Continue to the customer door. No recovery action is required.",
                urgency_level="ROUTINE",
                requires_human_approval=False,
                approval_status=ApprovalStatus.NOT_REQUIRED,
                execution_status="EXECUTED",
            )

        # Low battery is consequential even when the GNSS fault is only multipath.
        if state.battery_pct < 18.0:
            nearest_haven, _distance_m = self._select_haven(state)
            return RescuePlan(
                incident_id=incident_id,
                recommended_action=RescueActionType.EMERGENCY_CONTROLLED_LAND,
                target_zone=nearest_haven,
                target_coordinates=(state.inertial_truth.latitude, state.inertial_truth.longitude),
                flight_mode_switch="SECURE_STOP",
                rescue_rationale=(
                    f"CRITICAL BATTERY MARGIN ({state.battery_pct:.1f}%): The vehicle cannot reach a handoff point. "
                    "Recommend a secure stop at the current reference position. This does not mark the parcel recovered."
                ),
                urgency_level="IMMEDIATE",
                requires_human_approval=True,
                approval_status=ApprovalStatus.PENDING,
                execution_status="AWAITING_APPROVAL",
            )

        # Benign multipath changes the flight mode, so an operator still has to authorize the hold.
        if integrity.primary_anomaly == AnomalyType.MULTIPATH_INTERFERENCE:
            return RescuePlan(
                incident_id=incident_id,
                recommended_action=RescueActionType.HOVER_HOLD_VERIFY,
                target_zone=None,
                target_coordinates=(state.inertial_truth.latitude, state.inertial_truth.longitude),
                flight_mode_switch="HOLD_REFERENCE_POSITION",
                rescue_rationale=(
                    "Street-canyon multipath. Hold at the reference position and recheck the fix. "
                    "This is not a spoofing handoff."
                ),
                urgency_level="ADVISORY",
                requires_human_approval=True,
                approval_status=ApprovalStatus.PENDING,
                execution_status="AWAITING_APPROVAL",
            )

        nearest_haven, min_dist_m = self._select_haven(state)

        current_lat = state.inertial_truth.latitude
        current_lon = state.inertial_truth.longitude
        haven_name = nearest_haven.name if nearest_haven else "Nearest staffed handoff point"
        haven_coords = (
            (nearest_haven.latitude, nearest_haven.longitude)
            if nearest_haven
            else (current_lat, current_lon)
        )

        return RescuePlan(
            incident_id=incident_id,
            recommended_action=RescueActionType.REROUTE_SAFE_HAVEN,
            target_zone=nearest_haven,
            target_coordinates=haven_coords,
            flight_mode_switch="REFERENCE_TRACK_TO_HANDOFF",
            rescue_rationale=(
                f"Rule label {integrity.primary_anomaly.value}. "
                f"Investigation: {investigation.investigation_verdict} Risk band: {risk.overall_risk_level}. "
                f"Do not close the delivery on the reported GPS fix. "
                f"Recommended handoff is {min_dist_m:.0f}m away at '{haven_name}', measured from the reference track. "
                f"The parcel is not recovered until an operator authorizes this step."
            ),
            urgency_level="URGENT",
            requires_human_approval=True,
            approval_status=ApprovalStatus.PENDING,
            execution_status="AWAITING_APPROVAL",
        )

    def _select_haven(self, state: DroneMissionState) -> Tuple[Optional[SafeHavenZone], float]:
        """Nearest secured pad that still has landing capacity, measured from INS."""
        current_lat = state.inertial_truth.latitude
        current_lon = state.inertial_truth.longitude

        def nearest(pool: List[SafeHavenZone]) -> Tuple[Optional[SafeHavenZone], float]:
            chosen: Optional[SafeHavenZone] = None
            best = float("inf")
            for haven in pool:
                dist = haversine_distance(current_lat, current_lon, haven.latitude, haven.longitude)
                if dist < best:
                    best = dist
                    chosen = haven
            return chosen, best

        open_secured = [
            haven for haven in state.safe_havens
            if haven.landing_capacity > 0 and haven.is_secured_perimeter
        ]
        if open_secured:
            return nearest(open_secured)
        open_any = [haven for haven in state.safe_havens if haven.landing_capacity > 0]
        if open_any:
            return nearest(open_any)
        return nearest(list(state.safe_havens))
