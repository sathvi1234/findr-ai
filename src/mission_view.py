"""Pure helpers shared by the mission-control dashboard and its tests."""

from typing import Any, Dict, List, Sequence

from src.models import AnomalyType, IncidentRecord


def banner_for(is_anomalous: bool, primary_anomaly: AnomalyType) -> str:
    """Map a Layer 1 label to the operations banner."""
    if primary_anomaly == AnomalyType.MULTIPATH_INTERFERENCE and not is_anomalous:
        return "MULTIPATH"
    if primary_anomaly == AnomalyType.ROUTE_DEVIATION:
        return "DEVIATION"
    if primary_anomaly == AnomalyType.SUSPICIOUS_MOVEMENT:
        return "REVIEW"
    if primary_anomaly == AnomalyType.FALSE_DELIVERY_ARRIVAL:
        return "ARRIVAL"
    if is_anomalous:
        return "ATTACK"
    return "NOMINAL"


ACTION_LABELS = {
    "MAINTAIN_COURSE": "Continue delivery",
    "SWITCH_TO_INERTIAL_NAV": "Trust the reference track",
    "HOVER_HOLD_VERIFY": "Hold and verify",
    "REROUTE_SAFE_HAVEN": "Reroute to a handoff point",
    "RETURN_TO_BASE": "Return to the depot",
    "EMERGENCY_CONTROLLED_LAND": "Secure stop",
}


def select_record(records: Sequence[IncidentRecord], index: int) -> IncidentRecord:
    """Return the timeline frame that the operator selected."""
    if not records:
        raise IndexError("no telemetry frames are loaded")
    if index < 0 or index >= len(records):
        raise IndexError(f"frame {index} is outside 0..{len(records) - 1}")
    return records[index]


def filter_audit_rows(
    rows: Sequence[Dict[str, Any]],
    anomaly_type: str | None,
) -> List[Dict[str, Any]]:
    """Keep audit rows for one anomaly label. ``ALL`` and ``None`` keep every row."""
    if not anomaly_type or anomaly_type == "ALL":
        return list(rows)
    return [row for row in rows if row.get("anomaly_type") == anomaly_type]
