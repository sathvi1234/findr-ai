"""
FINDR AI — Data Models and Schemas
==================================
Defines strongly-typed Pydantic schemas for synthetic GPS telemetry,
dead-reckoning states, deterministic integrity scores, agent reports,
rescue recovery workflows, and audit persistence.
"""

from enum import Enum
from typing import List, Optional, Tuple, Dict, Any
from pydantic import BaseModel, Field


class AnomalyType(str, Enum):
    NONE = "NONE"
    TELEPORTATION_JUMP = "TELEPORTATION_JUMP"
    INSIDIOUS_DRIFT = "INSIDIOUS_DRIFT"
    RF_POWER_SURGE = "RF_POWER_SURGE"
    CONSTELLATION_FREEZE = "CONSTELLATION_FREEZE"
    MULTIPATH_INTERFERENCE = "MULTIPATH_INTERFERENCE"
    FALSE_DELIVERY_ARRIVAL = "FALSE_DELIVERY_ARRIVAL"
    ROUTE_DEVIATION = "ROUTE_DEVIATION"
    SUSPICIOUS_MOVEMENT = "SUSPICIOUS_MOVEMENT"


class VehicleType(str, Enum):
    MOTORCYCLE = "MOTORCYCLE"
    SCOOTER = "SCOOTER"
    CAR = "CAR"
    VAN = "VAN"


class DeliveryStatus(str, Enum):
    IN_TRANSIT = "IN_TRANSIT"
    CLAIMED_ARRIVAL = "CLAIMED_ARRIVAL"
    OFF_ROUTE = "OFF_ROUTE"
    HELD = "HELD"


class PayloadPriority(str, Enum):
    # Current e-commerce classes. Older medical labels remain so stored rows still parse.
    HIGH_VALUE = "HIGH_VALUE"
    EXPRESS = "EXPRESS"
    STANDARD = "STANDARD"
    CRITICAL_MEDICAL = "CRITICAL_MEDICAL"
    ORGAN_TRANSPORT = "ORGAN_TRANSPORT"
    URGENT_COMMERCIAL = "URGENT_COMMERCIAL"
    STANDARD_PARCEL = "STANDARD_PARCEL"


class RescueActionType(str, Enum):
    MAINTAIN_COURSE = "MAINTAIN_COURSE"
    SWITCH_TO_INERTIAL_NAV = "SWITCH_TO_INERTIAL_NAV"
    HOVER_HOLD_VERIFY = "HOVER_HOLD_VERIFY"
    REROUTE_SAFE_HAVEN = "REROUTE_SAFE_HAVEN"
    RETURN_TO_BASE = "RETURN_TO_BASE"
    EMERGENCY_CONTROLLED_LAND = "EMERGENCY_CONTROLLED_LAND"


class ApprovalStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    OVERRIDDEN = "OVERRIDDEN"


class GPSFix(BaseModel):
    """Simulated reported GNSS receiver fix."""
    timestamp: float
    latitude: float
    longitude: float
    altitude_m: float
    speed_mps: float
    heading_deg: float
    satellites_visible: int
    hdop: float
    vdop: float
    snr_db: List[float] = Field(default_factory=list)
    clock_drift_ns: float = 0.0
    fix_quality: int = 1  # 1 = Standard 3D GNSS fix


class DeadReckoningFix(BaseModel):
    """Simulated ground-truth / Inertial Navigation System (INS) odometry."""
    timestamp: float
    latitude: float
    longitude: float
    altitude_m: float
    speed_mps: float
    heading_deg: float
    accel_x: float = 0.0
    accel_y: float = 0.0
    accel_z: float = 9.81
    gyro_z: float = 0.0


class SafeHavenZone(BaseModel):
    """Staffed parcel handoff point. ``landing_capacity`` is the number of open handoff slots."""
    zone_id: str
    name: str
    latitude: float
    longitude: float
    altitude_m: float
    is_secured_perimeter: bool = True
    landing_capacity: int = 2


class DroneMissionState(BaseModel):
    """One synthetic delivery-assignment frame.

    ``drone_id`` and ``mission_id`` are the stored field names so older audit
    payloads and tests still load. ``agent_id`` and ``order_id`` are the
    delivery names for those same values.
    """
    drone_id: str
    mission_id: str
    sequence_id: int
    timestamp: float
    reported_gps: GPSFix
    inertial_truth: DeadReckoningFix
    battery_pct: float
    payload_type: PayloadPriority
    payload_weight_kg: float
    destination_name: str
    destination_coords: Tuple[float, float]
    safe_havens: List[SafeHavenZone] = Field(default_factory=list)
    vehicle_type: VehicleType = VehicleType.MOTORCYCLE
    delivery_status: DeliveryStatus = DeliveryStatus.IN_TRANSIT
    claimed_arrival: bool = False
    pickup_name: str = "East Austin Dispatch Bay"
    pickup_coords: Tuple[float, float] = (30.2672, -97.7431)
    route_bearing_deg: Optional[float] = None

    @property
    def agent_id(self) -> str:
        return self.drone_id

    @property
    def order_id(self) -> str:
        return self.mission_id


class IntegrityAssessment(BaseModel):
    """Layer 1: Deterministic Signal & Kinematic Integrity Score."""
    timestamp: float
    is_anomalous: bool
    anomaly_score: float = Field(ge=0.0, le=100.0)
    primary_anomaly: AnomalyType
    violated_rules: List[str] = Field(default_factory=list)
    kinematic_jump_m: float = 0.0
    velocity_delta_mps: float = 0.0
    dr_residual_m: float = 0.0
    snr_mean_db: float = 0.0
    snr_std_db: float = 0.0
    hdop: float = 1.0
    confidence_pct: float = 100.0
    rule_explanation: str


class InvestigationReport(BaseModel):
    """Layer 2 Agent: Environmental and Signal Investigation."""
    incident_id: str
    drone_id: str
    timestamp: float
    suspected_anomaly: AnomalyType
    confidence_pct: float
    rf_fingerprint_summary: str
    ins_divergence_analysis: str
    environmental_correlation: str
    cell_triangulation_crosscheck: str
    investigation_verdict: str
    evidence_points: List[str] = Field(default_factory=list)


class RiskAssessment(BaseModel):
    """Layer 2 Agent: Flight & Mission Risk Scorer."""
    incident_id: str
    overall_risk_level: str  # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    risk_score: float = Field(ge=0.0, le=100.0)
    payload_criticality: str
    flight_safety_hazard: str
    collateral_ground_risk: str
    battery_margin_min: float
    can_continue_autonomous: bool
    requires_immediate_rescue: bool
    risk_summary: str


class RescuePlan(BaseModel):
    """Layer 2 Agent: Delivery Rescue and Safe Haven Planner."""
    incident_id: str
    recommended_action: RescueActionType
    target_zone: Optional[SafeHavenZone] = None
    target_coordinates: Optional[Tuple[float, float]] = None
    flight_mode_switch: str  # e.g., "INS_ONLY", "HOLD_ALTITUDE", "DIVERT_SAFE_HAVEN"
    rescue_rationale: str
    urgency_level: str  # "IMMEDIATE", "URGENT", "ADVISORY"
    requires_human_approval: bool = True
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    operator_notes: Optional[str] = None
    approved_by: Optional[str] = None
    approval_timestamp: Optional[float] = None
    execution_status: str = "AWAITING_APPROVAL"  # "EXECUTED", "CANCELLED", "ABORTED"


class IncidentRecord(BaseModel):
    """Complete aggregated incident for persistence and UI."""
    incident_id: str
    drone_id: str
    mission_id: str
    timestamp: float
    telemetry: DroneMissionState

    @property
    def agent_id(self) -> str:
        return self.drone_id

    @property
    def order_id(self) -> str:
        return self.mission_id
    integrity: IntegrityAssessment
    investigation: Optional[InvestigationReport] = None
    risk: Optional[RiskAssessment] = None
    rescue: Optional[RescuePlan] = None
