"""
FINDR AI — Delivery Rescue Execution & Human-in-the-Loop Workflow
=================================================================
Coordinates the human operator approval gate and executes simulated recovery
maneuvers without modifying real devices or production delivery systems.
"""

import time
from typing import Optional, Tuple
from src.models import (
    DroneMissionState,
    RescuePlan,
    ApprovalStatus,
    RescueActionType,
    DeadReckoningFix,
)
from src.simulator import compute_destination_point, haversine_distance, initial_bearing_deg
from src.audit_db import ApprovalTransitionError, AuditDatabase


class RescueWorkflowManager:
    """
    Safely executes and tracks recovery actions subject to human operator consent.
    """

    def __init__(self, audit_db: Optional[AuditDatabase] = None, document_store=None):
        self.audit_db = audit_db or AuditDatabase()
        self.document_store = document_store

    def process_human_approval(
        self,
        incident_id: str,
        rescue_plan: RescuePlan,
        decision: ApprovalStatus,
        operator_name: str,
        operator_notes: str = "",
    ) -> RescuePlan:
        """
        Handle human operator approval, rejection, or override for a rescue plan.
        """
        if decision == ApprovalStatus.APPROVED:
            execution_status = "EXECUTED"
        elif decision == ApprovalStatus.REJECTED:
            execution_status = "CANCELLED_BY_OPERATOR"
        elif decision == ApprovalStatus.OVERRIDDEN:
            execution_status = "OVERRIDDEN_MANUAL_HOLD"
        else:
            raise ApprovalTransitionError(
                "Operator decisions are approve, reject, or override. Pending plans do not execute."
            )

        # Persist first so a rejected transition leaves the in-memory plan unchanged.
        self.audit_db.update_operator_decision(
            incident_id=incident_id,
            status=decision,
            operator_name=operator_name,
            notes=operator_notes,
            execution_status=execution_status,
        )
        if self.document_store is not None:
            linked = self.document_store.find_one("anomaly_events", "incident_id", incident_id) or {}
            try:
                self.document_store.save_decision(
                    incident_id=incident_id,
                    order_id=linked.get("order_id", ""),
                    agent_id=linked.get("agent_id", ""),
                    approval_status=decision.value,
                    operator_name=operator_name.strip(),
                    execution_status=execution_status,
                    decided_at=time.time(),
                )
            except Exception:
                pass

        rescue_plan.approval_status = decision
        rescue_plan.approved_by = operator_name.strip()
        rescue_plan.approval_timestamp = time.time()
        rescue_plan.operator_notes = operator_notes
        rescue_plan.execution_status = execution_status
        if decision == ApprovalStatus.OVERRIDDEN:
            rescue_plan.recommended_action = RescueActionType.HOVER_HOLD_VERIFY
            rescue_plan.flight_mode_switch = "MANUAL_HOLD"

        return rescue_plan

    def simulate_recovery_step(
        self,
        state: DroneMissionState,
        plan: RescuePlan,
        step_dt_seconds: float = 1.0,
    ) -> DroneMissionState:
        """
        Simulate vehicle state update under approved recovery action.
        Only advances physical Dead-Reckoning truth; rejects corrupted GNSS.
        """
        if plan.execution_status in ("AWAITING_APPROVAL", "CANCELLED_BY_OPERATOR"):
            return state
        if plan.execution_status == "OVERRIDDEN_MANUAL_HOLD":
            return self._hover_state(state, step_dt_seconds)
        if plan.execution_status != "EXECUTED":
            return state

        curr_truth = state.inertial_truth
        action = plan.recommended_action

        if action == RescueActionType.HOVER_HOLD_VERIFY:
            return self._hover_state(state, step_dt_seconds)

        if action == RescueActionType.REROUTE_SAFE_HAVEN and plan.target_coordinates:
            target_lat, target_lon = plan.target_coordinates
            dist_to_target = haversine_distance(
                curr_truth.latitude, curr_truth.longitude, target_lat, target_lon
            )

            if dist_to_target > 5.0:
                bearing = initial_bearing_deg(
                    curr_truth.latitude, curr_truth.longitude, target_lat, target_lon
                )
                step_dist = min(dist_to_target, 14.0 * step_dt_seconds)
                new_lat, new_lon = compute_destination_point(
                    curr_truth.latitude, curr_truth.longitude, step_dist, bearing
                )
                new_speed = 14.0
                new_alt = curr_truth.altitude_m
            else:
                new_lat, new_lon = target_lat, target_lon
                new_speed = 0.0
                new_alt = max(0.0, curr_truth.altitude_m - 5.0)  # Gentle touchdown

        elif action == RescueActionType.EMERGENCY_CONTROLLED_LAND:
            new_lat, new_lon = curr_truth.latitude, curr_truth.longitude
            new_speed = 0.0
            new_alt = max(0.0, curr_truth.altitude_m - 8.0)  # Descend to ground

        else:
            return state

        # Updated truth state
        updated_truth = DeadReckoningFix(
            timestamp=state.timestamp + step_dt_seconds,
            latitude=new_lat,
            longitude=new_lon,
            altitude_m=new_alt,
            speed_mps=new_speed,
            heading_deg=curr_truth.heading_deg,
            accel_x=0.0,
            accel_y=0.0,
            accel_z=9.81,
            gyro_z=0.0,
        )

        return state.model_copy(update={
            "sequence_id": state.sequence_id + 1,
            "timestamp": state.timestamp + step_dt_seconds,
            "reported_gps": state.reported_gps,
            "inertial_truth": updated_truth,
            "battery_pct": max(0.0, state.battery_pct - 0.2),
            "destination_name": plan.target_zone.name if plan.target_zone else state.destination_name,
            "destination_coords": plan.target_coordinates or state.destination_coords,
        })

    def _hover_state(self, state: DroneMissionState, step_dt_seconds: float) -> DroneMissionState:
        """Hold the inertial position. Does not follow a safe-haven divert."""
        truth = state.inertial_truth
        held = DeadReckoningFix(
            timestamp=state.timestamp + step_dt_seconds,
            latitude=truth.latitude,
            longitude=truth.longitude,
            altitude_m=truth.altitude_m,
            speed_mps=0.0,
            heading_deg=truth.heading_deg,
            accel_x=0.0,
            accel_y=0.0,
            accel_z=9.81,
            gyro_z=0.0,
        )
        return state.model_copy(update={
            "sequence_id": state.sequence_id + 1,
            "timestamp": state.timestamp + step_dt_seconds,
            "inertial_truth": held,
            "battery_pct": max(0.0, state.battery_pct - 0.05),
            "delivery_status": state.delivery_status,
        })
