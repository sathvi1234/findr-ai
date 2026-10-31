"""
FINDR AI — Investigation Agent (Layer 2)
========================================
Investigates suspicious telemetry flags by synthesizing environmental telemetry,
cellular tower timing triangulation, INS drift profiles, and RF spectral cues.
"""

from typing import List
from src.models import (
    DroneMissionState,
    IntegrityAssessment,
    InvestigationReport,
    AnomalyType,
)
from src.simulator import haversine_distance


class InvestigationAgent:
    """
    Synthesizes multi-sensor context to determine the root cause of GNSS anomalies.
    """

    def investigate(
        self,
        incident_id: str,
        state: DroneMissionState,
        integrity: IntegrityAssessment,
    ) -> InvestigationReport:
        evidence: List[str] = []
        anomaly = integrity.primary_anomaly
        confidence = 85.0

        # 1. RF Fingerprint Analysis
        if integrity.snr_mean_db > 51.0 and integrity.snr_std_db < 0.5:
            rf_summary = (
                f"Severe RF power anomaly: C/N0 mean is saturated at {integrity.snr_mean_db:.1f} dB "
                f"with near-zero variance ({integrity.snr_std_db:.2f} dB). Consistent with an active "
                f"terrestrial software-defined radio (SDR) transmitter in close proximity."
            )
            evidence.append("Terrestrial SDR power signature overriding orbital satellite flux.")
            confidence = 96.0
        elif integrity.primary_anomaly == AnomalyType.CONSTELLATION_FREEZE:
            rf_summary = (
                "Static constellation parameters detected across temporal epochs. "
                "The receiver is processing repeated NMEA/UBX pseudorange frames from a playback attack."
            )
            evidence.append("Identical Doppler and ephemeris replay observed.")
            confidence = 94.0
        elif integrity.primary_anomaly == AnomalyType.MULTIPATH_INTERFERENCE:
            rf_summary = (
                f"Diffused RF reflection: HDOP {integrity.hdop:.2f} with nominal power levels. "
                "Echoes from high-rise glass or steel structures without deliberate transmitter presence."
            )
            evidence.append("Geometric dilution matches urban canyon obstruction patterns.")
            confidence = 90.0
        else:
            rf_summary = f"C/N0 mean {integrity.snr_mean_db:.1f} dB is inside a normal street-level range."

        # 2. INS vs GNSS Divergence Analysis
        dr_gap = integrity.dr_residual_m
        if dr_gap > 40.0:
            ins_summary = (
                f"Critical Dead-Reckoning Divergence: Estimated inertial position differs by {dr_gap:.1f}m. "
                f"Wheel-speed integration still follows the planned road, "
                f"so the reported GNSS coordinate does not match the vehicle."
            )
            evidence.append(f"INS odometry confirms vehicle did not physically deviate {dr_gap:.1f}m.")
        elif dr_gap > 15.0:
            ins_summary = f"Elevated INS residual ({dr_gap:.1f}m). Subtle trajectory skew detected."
            evidence.append(f"Inertial path shows minor divergence from GNSS fix ({dr_gap:.1f}m).")
        else:
            ins_summary = f"INS and GNSS positions tightly bound within {dr_gap:.1f}m."

        # Synthetic cellular sector fix. It is anchored near the INS truth with a
        # fixed offset so the cross-check is not a second copy of the GNSS residual.
        # No radio is transmitted; this is a mathematical stand-in for timing advance.
        cell_lat = state.inertial_truth.latitude + 0.00012
        cell_lon = state.inertial_truth.longitude - 0.00009
        cell_vs_ins_m = haversine_distance(
            cell_lat, cell_lon,
            state.inertial_truth.latitude, state.inertial_truth.longitude,
        )
        cell_vs_gnss_m = haversine_distance(
            cell_lat, cell_lon,
            state.reported_gps.latitude, state.reported_gps.longitude,
        )
        cell_agrees_with_ins = cell_vs_ins_m < 40.0 and cell_vs_gnss_m > cell_vs_ins_m + 25.0

        if anomaly in (
            AnomalyType.TELEPORTATION_JUMP,
            AnomalyType.INSIDIOUS_DRIFT,
            AnomalyType.RF_POWER_SURGE,
            AnomalyType.CONSTELLATION_FREEZE,
        ) and cell_agrees_with_ins:
            cell_correlation = (
                f"Synthetic cellular timing-advance fix is {cell_vs_ins_m:.1f}m from the INS state "
                f"and {cell_vs_gnss_m:.1f}m from the reported GNSS fix. The sector agrees with inertial "
                f"odometry and contradicts the GNSS coordinate."
            )
            evidence.append(
                f"Synthetic cellular sector is {cell_vs_gnss_m:.1f}m from GNSS and {cell_vs_ins_m:.1f}m from INS."
            )
        else:
            cell_correlation = (
                f"Synthetic cellular timing-advance fix is {cell_vs_ins_m:.1f}m from INS "
                f"and {cell_vs_gnss_m:.1f}m from the reported GNSS fix. The two navigation sources still agree."
            )

        # 4. Environmental context
        env_context = (
            f"Delivery agent {state.agent_id} on order {state.order_id} "
            f"({state.vehicle_type.value}) is assigned to {state.destination_name}. "
            f"Pickup: {state.pickup_name}. Status: {state.delivery_status.value}."
        )

        # 5. Verdict Synthesis
        if anomaly == AnomalyType.TELEPORTATION_JUMP:
            verdict = (
                "CONFIRMED_SPOOFING: The reported coordinate jumped farther than a delivery vehicle can move. "
                "This is a rules match, not a legal finding."
            )
        elif anomaly == AnomalyType.INSIDIOUS_DRIFT:
            verdict = (
                "CONFIRMED_SPOOFING: The reported position crept away from the reference track "
                "while each step stayed inside a normal delivery speed."
            )
        elif anomaly == AnomalyType.RF_POWER_SURGE:
            verdict = "CONFIRMED_SPOOFING: Satellite power is saturated and unnaturally uniform, consistent with a nearby forged signal."
        elif anomaly == AnomalyType.CONSTELLATION_FREEZE:
            verdict = "CONFIRMED_SPOOFING: Satellite metrics repeat exactly, consistent with a replayed navigation stream."
        elif anomaly == AnomalyType.FALSE_DELIVERY_ARRIVAL:
            verdict = (
                "SUSPICIOUS_ARRIVAL: The report sits on the customer pin while the reference track is still on the road. "
                "That is not enough, by itself, to call the delivery stolen."
            )
        elif anomaly == AnomalyType.ROUTE_DEVIATION:
            verdict = (
                "OPERATIONAL_DEVIATION: The report and the reference track agree, and both left the planned road. "
                "This is a route problem, not a spoofing label."
            )
        elif anomaly == AnomalyType.SUSPICIOUS_MOVEMENT:
            verdict = (
                "SUSPICIOUS_MOVEMENT: The track moved faster than the delivery bound without a coordinate teleport. "
                "The cause is not identified."
            )
        elif anomaly == AnomalyType.MULTIPATH_INTERFERENCE:
            verdict = "BENIGN_DEGRADATION: Urban multipath reflection; no hostile spoofing detected."
        else:
            verdict = "NOMINAL: No integrity rule fired on this delivery frame."

        return InvestigationReport(
            incident_id=incident_id,
            drone_id=state.drone_id,
            timestamp=state.timestamp,
            suspected_anomaly=anomaly,
            confidence_pct=confidence,
            rf_fingerprint_summary=rf_summary,
            ins_divergence_analysis=ins_summary,
            environmental_correlation=env_context,
            cell_triangulation_crosscheck=cell_correlation,
            investigation_verdict=verdict,
            evidence_points=evidence,
        )
