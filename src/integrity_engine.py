"""
FINDR AI — Deterministic Integrity Engine (Layer 1)
===================================================
Executes mathematical and physics-grounded deterministic signal and kinematic
integrity checks on delivery GPS telemetry frames.

This layer is strictly deterministic, fast, and completely separated from LLM reasoning.
It enforces physics bounds, cross-validates GNSS against inertial dead reckoning,
and scrutinizes RF signal metrics to detect GPS spoofing attacks.
"""

import math
from typing import List, Optional, Tuple
from src.models import (
    GPSFix,
    DeadReckoningFix,
    DroneMissionState,
    IntegrityAssessment,
    AnomalyType,
)
from src.simulator import haversine_distance, cross_track_distance_m


class DeterministicIntegrityEngine:
    """
    Evaluates telemetry frames using deterministic mathematical and physical rules.
    """

    # Physics & Operational Thresholds
    MAX_DRONE_SPEED_MPS = 30.0         # Synthetic corridor bound, kept so existing labels stay stable
    MAX_ACCELERATION_MPS2 = 12.0       # Max physical acceleration
    MAX_SINGLE_STEP_JUMP_M = 150.0     # Max reasonable travel in 1 second
    SUSPICIOUS_STEP_M = 55.0           # Faster than a delivery run, short of a teleport
    INS_RESIDUAL_WARNING_M = 18.0      # Warning threshold for INS vs GNSS gap
    INS_RESIDUAL_CRITICAL_M = 45.0     # Critical divergence threshold
    SNR_SUSPICIOUS_HIGH_DB = 51.5      # Typical max genuine satellite C/N0 is ~48 dB
    SNR_SYNTHETIC_MIN_STD = 0.4        # Legitimate satellites have elevation-dependent variance
    HDOP_DEGRADED_THRESHOLD = 2.8      # High dilution of precision

    def __init__(self, history_window: int = 5):
        self.history_window = history_window
        self.reported_history: List[GPSFix] = []

    def reset(self):
        """Reset history buffer."""
        self.reported_history.clear()

    def assess_frame(self, state: DroneMissionState) -> IntegrityAssessment:
        """
        Perform comprehensive deterministic integrity evaluation on current state.
        """
        curr_gps = state.reported_gps
        curr_ins = state.inertial_truth
        timestamp = state.timestamp

        violations: List[str] = []
        anomaly_score = 0.0
        primary_anomaly = AnomalyType.NONE

        # 1. Kinematic Checks (Velocity, Acceleration, Position Jump)
        kinematic_jump_m = 0.0
        velocity_delta_mps = 0.0

        if self.reported_history:
            prev_gps = self.reported_history[-1]
            dt = max(0.001, curr_gps.timestamp - prev_gps.timestamp)

            kinematic_jump_m = haversine_distance(
                prev_gps.latitude, prev_gps.longitude,
                curr_gps.latitude, curr_gps.longitude
            )
            derived_speed = kinematic_jump_m / dt
            velocity_delta_mps = abs(curr_gps.speed_mps - prev_gps.speed_mps) / dt

            # A coarse coordinate leap is teleportation. A step only slightly above
            # cruise speed is left unlabeled here so urban multipath can claim it.
            if kinematic_jump_m > self.MAX_SINGLE_STEP_JUMP_M:
                violations.append(
                    f"KINEMATIC_JUMP_EXCEEDED: Step displacement {kinematic_jump_m:.1f}m (implied speed {derived_speed:.1f} m/s) "
                    f"violates the {self.MAX_SINGLE_STEP_JUMP_M:.0f}m single-step bound."
                )
                anomaly_score += 65.0
                primary_anomaly = AnomalyType.TELEPORTATION_JUMP
            elif derived_speed > self.MAX_DRONE_SPEED_MPS:
                violations.append(
                    f"SPEED_BOUND_EXCEEDED: Implied speed {derived_speed:.1f} m/s over {kinematic_jump_m:.1f}m "
                    f"exceeds {self.MAX_DRONE_SPEED_MPS:.1f} m/s without a coordinate leap."
                )
                anomaly_score += 15.0

            if velocity_delta_mps > self.MAX_ACCELERATION_MPS2:
                violations.append(
                    f"IMPOSSIBLE_ACCELERATION: Velocity change rate {velocity_delta_mps:.1f} m/s² "
                    f"exceeds aerodynamic propulsion maximum {self.MAX_ACCELERATION_MPS2:.1f} m/s²."
                )
                anomaly_score += 20.0

        # 2. Dead-Reckoning (INS) vs GNSS Residual Check
        dr_residual_m = haversine_distance(
            curr_gps.latitude, curr_gps.longitude,
            curr_ins.latitude, curr_ins.longitude
        )

        if dr_residual_m >= self.INS_RESIDUAL_CRITICAL_M:
            violations.append(
                f"INS_GNSS_DIVERGENCE_CRITICAL: Reported GNSS position is {dr_residual_m:.1f}m away from "
                f"integrated inertial navigation state (threshold: {self.INS_RESIDUAL_CRITICAL_M:.1f}m)."
            )
            anomaly_score += 50.0
            if primary_anomaly == AnomalyType.NONE:
                primary_anomaly = AnomalyType.INSIDIOUS_DRIFT
        elif dr_residual_m >= self.INS_RESIDUAL_WARNING_M:
            violations.append(
                f"INS_GNSS_DIVERGENCE_WARNING: GNSS/INS discrepancy {dr_residual_m:.1f}m exceeds nominal tolerance."
            )
            anomaly_score += 20.0

        # A teleport leaves a gross offset after the leap itself. Creeping drift
        # stays well below this distance inside a normal mission window.
        if dr_residual_m >= 400.0 and primary_anomaly != AnomalyType.TELEPORTATION_JUMP:
            violations.append(
                f"GROSS_POSITION_OFFSET: GNSS/INS residual {dr_residual_m:.1f}m is a persisted coordinate injection, not a slow drift."
            )
            anomaly_score = max(anomaly_score, 65.0)
            primary_anomaly = AnomalyType.TELEPORTATION_JUMP

        # A fast step that still agrees with the reference track is a pace problem.
        # A drifted fix has already been labeled from the residual above.
        if (
            self.SUSPICIOUS_STEP_M < kinematic_jump_m <= self.MAX_SINGLE_STEP_JUMP_M
            and dr_residual_m < self.INS_RESIDUAL_WARNING_M
            and primary_anomaly == AnomalyType.NONE
        ):
            violations.append(
                f"SUSPICIOUS_MOVEMENT: Step {kinematic_jump_m:.1f}m is faster than a delivery run, "
                f"shorter than a {self.MAX_SINGLE_STEP_JUMP_M:.0f}m teleport, and still matches the reference track."
            )
            anomaly_score += 25.0
            primary_anomaly = AnomalyType.SUSPICIOUS_MOVEMENT

        # A claimed arrival that sits on the customer pin while the reference
        # track is still on the road is not the same event as a coordinate teleport.
        if state.claimed_arrival:
            reported_to_dest = haversine_distance(
                curr_gps.latitude, curr_gps.longitude,
                state.destination_coords[0], state.destination_coords[1],
            )
            truth_to_dest = haversine_distance(
                curr_ins.latitude, curr_ins.longitude,
                state.destination_coords[0], state.destination_coords[1],
            )
            if reported_to_dest < 80.0 and truth_to_dest > 150.0:
                violations.append(
                    f"FALSE_ARRIVAL_CLAIM: Reported fix is {reported_to_dest:.1f}m from the customer pin "
                    f"while the reference track is still {truth_to_dest:.1f}m away."
                )
                anomaly_score = max(anomaly_score, 72.0)
                primary_anomaly = AnomalyType.FALSE_DELIVERY_ARRIVAL

        # 3. RF Signal Analysis (Mean & Std Dev of Carrier-to-Noise Ratio C/N0)
        snr_mean = 0.0
        snr_std = 0.0
        if curr_gps.snr_db:
            snr_mean = sum(curr_gps.snr_db) / len(curr_gps.snr_db)
            variance = sum((x - snr_mean) ** 2 for x in curr_gps.snr_db) / len(curr_gps.snr_db)
            snr_std = math.sqrt(variance)

            # High power transmitter saturation
            if snr_mean > self.SNR_SUSPICIOUS_HIGH_DB:
                violations.append(
                    f"RF_POWER_OVERDRIVE: Mean satellite C/N0 is {snr_mean:.1f} dB (abnormally saturated, > {self.SNR_SUSPICIOUS_HIGH_DB} dB)."
                )
                anomaly_score += 45.0
                if primary_anomaly == AnomalyType.NONE:
                    primary_anomaly = AnomalyType.RF_POWER_SURGE

            # Uniform artificial signal variance (all satellites exact same power)
            if snr_std < self.SNR_SYNTHETIC_MIN_STD and len(curr_gps.snr_db) >= 6:
                violations.append(
                    f"RF_VARIANCE_COLLAPSE: Satellite SNR standard deviation is {snr_std:.2f} dB. Real satellite constellation "
                    f"geometry requires angular variance > {self.SNR_SYNTHETIC_MIN_STD:.2f} dB."
                )
                anomaly_score += 35.0
                if primary_anomaly in (AnomalyType.NONE, AnomalyType.RF_POWER_SURGE):
                    primary_anomaly = AnomalyType.RF_POWER_SURGE

        # 4. Constellation / Replay Freeze Check
        if len(self.reported_history) >= 3:
            recent_frames = self.reported_history[-3:] + [curr_gps]
            # Check if SNR vectors and HDOP/VDOP are strictly identical while timestamp is advancing
            all_hdop_identical = all(f.hdop == curr_gps.hdop for f in recent_frames)
            all_snr_identical = all(f.snr_db == curr_gps.snr_db for f in recent_frames)
            zero_clock_drift = (curr_gps.clock_drift_ns == 0.0)

            if all_hdop_identical and all_snr_identical and zero_clock_drift:
                violations.append(
                    "CONSTELLATION_REPLAY_FREEZE: Identical satellite constellation geometry, zero clock jitter, "
                    "and constant SNR vector detected across consecutive epochs. Hallmarks of replayed NMEA/UBX stream."
                )
                anomaly_score += 40.0
                if primary_anomaly == AnomalyType.NONE:
                    primary_anomaly = AnomalyType.CONSTELLATION_FREEZE

        # 5. Multipath Interference Disambiguation
        # If HDOP is degraded, but kinematics and INS residual are within reasonable bounds
        if curr_gps.hdop >= self.HDOP_DEGRADED_THRESHOLD and dr_residual_m < self.INS_RESIDUAL_CRITICAL_M:
            if primary_anomaly == AnomalyType.NONE:
                primary_anomaly = AnomalyType.MULTIPATH_INTERFERENCE
                violations.append(
                    f"MULTIPATH_DEGRADATION: Elevated HDOP ({curr_gps.hdop:.2f}) indicates satellite obstruction/reflection, "
                    f"but velocity remains physically consistent."
                )
                anomaly_score = min(25.0, anomaly_score + 15.0)

        # Route deviation: the reference track and the report still agree, and both
        # have left the planned road. Spoofing residuals are handled above.
        if primary_anomaly == AnomalyType.NONE and dr_residual_m < self.INS_RESIDUAL_WARNING_M:
            bearing = state.route_bearing_deg
            if bearing is None:
                bearing = 0.0
                route_ready = False
            else:
                route_ready = True
            if route_ready:
                cross_track_m = cross_track_distance_m(
                    curr_ins.latitude, curr_ins.longitude,
                    state.pickup_coords[0], state.pickup_coords[1],
                    bearing,
                )
                if cross_track_m > 40.0:
                    violations.append(
                        f"ROUTE_DEVIATION: Reference track is {cross_track_m:.1f}m off the planned road "
                        f"and still agrees with the reported fix ({dr_residual_m:.1f}m)."
                    )
                    anomaly_score += 40.0
                    primary_anomaly = AnomalyType.ROUTE_DEVIATION

        # Cap score between 0 and 100
        final_score = min(100.0, max(0.0, anomaly_score))
        is_anomalous = final_score >= 35.0

        if not is_anomalous and primary_anomaly != AnomalyType.MULTIPATH_INTERFERENCE:
            primary_anomaly = AnomalyType.NONE
            explanation = "Nominal GNSS fix: kinematics, signal power, and the reference residual are inside the delivery corridor."
        else:
            explanation = "; ".join(violations)

        # Update history
        self.reported_history.append(curr_gps)
        if len(self.reported_history) > self.history_window:
            self.reported_history.pop(0)

        return IntegrityAssessment(
            timestamp=timestamp,
            is_anomalous=is_anomalous,
            anomaly_score=round(final_score, 1),
            primary_anomaly=primary_anomaly,
            violated_rules=violations,
            kinematic_jump_m=round(kinematic_jump_m, 1),
            velocity_delta_mps=round(velocity_delta_mps, 1),
            dr_residual_m=round(dr_residual_m, 1),
            snr_mean_db=round(snr_mean, 1),
            snr_std_db=round(snr_std, 2),
            hdop=curr_gps.hdop,
            confidence_pct=100.0 if violations else 99.0,
            rule_explanation=explanation,
        )
