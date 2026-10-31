"""
FINDR AI — Risk Assessment Agent (Layer 2)
==========================================
Evaluates mission risk, payload sensitivity, flight hazards, and battery reserves
to determine whether immediate rescue or contingency rerouting is required.
"""

from src.models import (
    DroneMissionState,
    IntegrityAssessment,
    InvestigationReport,
    RiskAssessment,
    PayloadPriority,
    AnomalyType,
)


class RiskAssessmentAgent:
    """
    Evaluates multi-factor risk profiles during GNSS integrity events.
    """

    def evaluate_risk(
        self,
        incident_id: str,
        state: DroneMissionState,
        integrity: IntegrityAssessment,
        investigation: InvestigationReport,
    ) -> RiskAssessment:
        risk_score = 0.0

        # 1. Payload Criticality Factor
        if state.payload_type == PayloadPriority.ORGAN_TRANSPORT:
            payload_desc = "ORGAN_TRANSPORT: Life-critical cold-chain payload. Time-sensitive; strict delivery ceiling."
            risk_score += 25.0
        elif state.payload_type == PayloadPriority.HIGH_VALUE:
            payload_desc = "HIGH_VALUE: High-value e-commerce parcel. Loss is costly; it is not a medical payload."
            risk_score += 22.0
        elif state.payload_type in (PayloadPriority.CRITICAL_MEDICAL, PayloadPriority.EXPRESS):
            label = state.payload_type.value
            payload_desc = f"{label}: Time-sensitive delivery. High urgency, ordinary goods handling."
            risk_score += 18.0
        elif state.payload_type == PayloadPriority.URGENT_COMMERCIAL:
            payload_desc = "URGENT_COMMERCIAL: Commercial expedited cargo. Medium economic risk."
            risk_score += 10.0
        else:
            payload_desc = f"{state.payload_type.value}: Routine e-commerce parcel. Low loss consequence."
            risk_score += 5.0

        # 2. Flight Safety & Navigation Hazard Factor
        if integrity.primary_anomaly in (
            AnomalyType.TELEPORTATION_JUMP,
            AnomalyType.INSIDIOUS_DRIFT,
            AnomalyType.RF_POWER_SURGE,
            AnomalyType.CONSTELLATION_FREEZE,
            AnomalyType.FALSE_DELIVERY_ARRIVAL,
        ):
            flight_hazard = (
                "CRITICAL_NAV_LOSS: The reported GPS fix should not be used to close this delivery. "
                "Trusting it can send the parcel to the wrong door or mark it delivered early."
            )
            risk_score += 45.0
        elif integrity.primary_anomaly == AnomalyType.SUSPICIOUS_MOVEMENT:
            flight_hazard = (
                "SUSPICIOUS_PACE: The vehicle track is faster than the delivery bound. "
                "The cause is not identified, so the parcel stays under operator review."
            )
            risk_score += 30.0
        elif integrity.primary_anomaly == AnomalyType.ROUTE_DEVIATION:
            flight_hazard = (
                "OFF_ROUTE: The reference track and the report agree, and both left the planned road."
            )
            risk_score += 22.0
        elif integrity.primary_anomaly == AnomalyType.MULTIPATH_INTERFERENCE:
            flight_hazard = "DEGRADED_ACCURACY: Urban multipath causing minor fix noise, but vehicle control stable."
            risk_score += 15.0
        else:
            flight_hazard = "NOMINAL: Primary navigation systems healthy."

        # 3. Battery Margin & Range
        # Estimate remaining flight minutes at 0.15% per second (~9% per minute)
        battery_margin_min = max(0.0, (state.battery_pct - 15.0) / 9.0)  # Reserve 15% safety floor
        if state.battery_pct < 25.0:
            risk_score += 25.0
            collateral = "HIGH: Vehicle battery is low, so a long handoff detour may not be available."
        elif state.battery_pct < 45.0:
            risk_score += 10.0
            collateral = "MODERATE: Battery can still reach a nearby handoff point."
        else:
            collateral = "LOW: Vehicle battery is above 45 percent."

        # Benign multipath stays below the spoofing bands even for organ payloads.
        # A life-critical payload raises attention; it does not invent an attack.
        if (
            integrity.primary_anomaly == AnomalyType.MULTIPATH_INTERFERENCE
            and not integrity.is_anomalous
        ):
            final_score = min(44.0, risk_score)
            level = "MEDIUM"
            can_continue = True
            requires_immediate = False
            summary = (
                f"MEDIUM RISK ({final_score:.1f}/100): Urban multipath only. "
                "The GNSS fix is noisy but still consistent with inertial flight, "
                "so no hostile-spoofing rescue is required."
            )
        else:
            anomaly_weight = integrity.anomaly_score * 0.3 if integrity.is_anomalous else 0.0
            final_score = min(100.0, max(0.0, risk_score + anomaly_weight))

            if not integrity.is_anomalous and integrity.primary_anomaly == AnomalyType.NONE:
                level = "LOW"
                can_continue = True
                requires_immediate = False
                summary = f"LOW RISK ({final_score:.1f}/100): This delivery frame stayed inside the corridor rules."
            elif final_score >= 70.0:
                level = "CRITICAL"
                can_continue = False
                requires_immediate = True
                summary = (
                    f"CRITICAL RISK ({final_score:.1f}/100): Do not close this order on the reported GPS fix. "
                    "A handoff recommendation is waiting for an operator."
                )
            elif final_score >= 45.0:
                level = "HIGH"
                can_continue = False
                requires_immediate = True
                summary = (
                    f"HIGH RISK ({final_score:.1f}/100): GPS integrity is compromised. Recommend a staffed handoff point."
                )
            elif final_score >= 25.0:
                level = "MEDIUM"
                can_continue = True
                requires_immediate = False
                summary = (
                    f"MEDIUM RISK ({final_score:.1f}/100): Environmental noise or minor signal degradation. "
                    "Hold position and verify navigation sensors."
                )
            else:
                level = "LOW"
                can_continue = True
                requires_immediate = False
                summary = f"LOW RISK ({final_score:.1f}/100): All primary systems nominal."

        return RiskAssessment(
            incident_id=incident_id,
            overall_risk_level=level,
            risk_score=round(final_score, 1),
            payload_criticality=payload_desc,
            flight_safety_hazard=flight_hazard,
            collateral_ground_risk=collateral,
            battery_margin_min=round(battery_margin_min, 1),
            can_continue_autonomous=can_continue,
            requires_immediate_rescue=requires_immediate,
            risk_summary=summary,
        )
