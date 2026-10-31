"""Map an incident into MongoDB documents. Detection scores are copied, not recomputed."""

from datetime import datetime, timezone
from typing import Any, Optional

from src.meeting.geo import geojson_point
from src.models import IncidentRecord

PROTECTED_ORDER_STATUSES = {
    "MEETING_REQUESTED",
    "CONFIRMED",
    "HANDED_OVER",
    "HANDED_OVER_AT_MEETING_POINT",
    "REJECTED",
}


def utc_datetime(timestamp: float) -> datetime:
    return datetime.fromtimestamp(float(timestamp), tz=timezone.utc)


def incident_documents(record: IncidentRecord) -> dict[str, Any]:
    """One document per collection for a frame the existing pipeline already scored."""
    state = record.telemetry
    recorded_at = utc_datetime(record.timestamp)
    reported = geojson_point(state.reported_gps.latitude, state.reported_gps.longitude)
    reference = geojson_point(state.inertial_truth.latitude, state.inertial_truth.longitude)
    destination = geojson_point(state.destination_coords[0], state.destination_coords[1])
    rescue = record.rescue
    risk = record.risk
    return {
        "agent": {
            "agent_id": record.agent_id,
            "vehicle_type": state.vehicle_type.value,
            "last_location": reported,
            "position_source": "synthetic",
            "updated_at": recorded_at,
        },
        "order": {
            "order_id": record.order_id,
            "agent_id": record.agent_id,
            "destination_name": state.destination_name,
            "destination": destination,
            "vehicle_type": state.vehicle_type.value,
            "status": state.delivery_status.value,
            "updated_at": recorded_at,
        },
        "telemetry": {
            "incident_id": record.incident_id,
            "order_id": record.order_id,
            "agent_id": record.agent_id,
            "sequence_id": state.sequence_id,
            "recorded_at": recorded_at,
            "created_at": recorded_at,
            "location": reported,
            "reference_location": reference,
            "position_source": "synthetic",
        },
        "anomaly": {
            "incident_id": record.incident_id,
            "order_id": record.order_id,
            "agent_id": record.agent_id,
            "anomaly_type": record.integrity.primary_anomaly.value,
            "anomaly_score": record.integrity.anomaly_score,
            "is_anomalous": record.integrity.is_anomalous,
            "rule_explanation": record.integrity.rule_explanation,
            "created_at": recorded_at,
        },
        "rescue": None if rescue is None else {
            "incident_id": record.incident_id,
            "order_id": record.order_id,
            "agent_id": record.agent_id,
            "recommended_action": rescue.recommended_action.value,
            "approval_status": rescue.approval_status.value,
            "execution_status": rescue.execution_status,
            "risk_level": None if risk is None else risk.overall_risk_level,
            "risk_score": None if risk is None else risk.risk_score,
            "operator_name": rescue.approved_by,
            "created_at": recorded_at,
        },
        "audit": {
            "source": "pipeline",
            "event_type": "incident",
            "incident_id": record.incident_id,
            "order_id": record.order_id,
            "agent_id": record.agent_id,
            "anomaly_type": record.integrity.primary_anomaly.value,
            "anomaly_score": record.integrity.anomaly_score,
            "created_at": recorded_at,
            "note": "SHA-256 chain for this frame stays in the SQLite audit log.",
        },
    }


def merge_order_status(existing: Optional[str], incoming: str) -> str:
    """Keep a meeting-point status if the GPS pipeline writes the same order later."""
    if existing in PROTECTED_ORDER_STATUSES:
        return existing
    return incoming
