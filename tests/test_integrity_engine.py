"""Unit tests for DeterministicIntegrityEngine."""

import pytest
from src.integrity_engine import DeterministicIntegrityEngine
from src.simulator import ScenarioSimulator
from src.models import AnomalyType


def test_clean_flight_integrity():
    engine = DeterministicIntegrityEngine()
    sim = ScenarioSimulator()
    stream = sim.generate_scenario_stream(scenario_type=AnomalyType.NONE, total_steps=8)

    for frame in stream:
        assessment = engine.assess_frame(frame)
        assert assessment.is_anomalous is False
        assert assessment.anomaly_score < 30.0
        assert assessment.primary_anomaly == AnomalyType.NONE


def test_teleportation_jump_detection():
    engine = DeterministicIntegrityEngine()
    sim = ScenarioSimulator()
    stream = sim.generate_scenario_stream(
        scenario_type=AnomalyType.TELEPORTATION_JUMP, total_steps=12, attack_start_step=8
    )

    # Prime history with clean steps
    for frame in stream[:8]:
        engine.assess_frame(frame)

    # Step 8 has the jump
    jump_assessment = engine.assess_frame(stream[8])
    assert jump_assessment.is_anomalous is True
    assert jump_assessment.primary_anomaly == AnomalyType.TELEPORTATION_JUMP
    assert any("KINEMATIC_JUMP_EXCEEDED" in v for v in jump_assessment.violated_rules)


def test_rf_power_surge_detection():
    engine = DeterministicIntegrityEngine()
    sim = ScenarioSimulator()
    stream = sim.generate_scenario_stream(
        scenario_type=AnomalyType.RF_POWER_SURGE, total_steps=12, attack_start_step=8
    )

    for frame in stream[:8]:
        engine.assess_frame(frame)

    surge_assessment = engine.assess_frame(stream[8])
    assert surge_assessment.is_anomalous is True
    assert surge_assessment.primary_anomaly == AnomalyType.RF_POWER_SURGE
    assert any("RF_POWER_OVERDRIVE" in v for v in surge_assessment.violated_rules)


def test_insidious_drift_detection():
    engine = DeterministicIntegrityEngine()
    sim = ScenarioSimulator()
    stream = sim.generate_scenario_stream(
        scenario_type=AnomalyType.INSIDIOUS_DRIFT, total_steps=20, attack_start_step=8
    )

    for frame in stream[:14]:
        engine.assess_frame(frame)

    # By step 18, drift has grown large enough to trigger critical INS divergence
    late_assessment = engine.assess_frame(stream[18])
    assert late_assessment.is_anomalous is True
    assert late_assessment.primary_anomaly == AnomalyType.INSIDIOUS_DRIFT
    assert any("INS_GNSS_DIVERGENCE" in v for v in late_assessment.violated_rules)


def test_constellation_freeze_detection():
    engine = DeterministicIntegrityEngine()
    sim = ScenarioSimulator()
    stream = sim.generate_scenario_stream(
        scenario_type=AnomalyType.CONSTELLATION_FREEZE, total_steps=15, attack_start_step=6
    )

    assessments = []
    for frame in stream:
        assessments.append(engine.assess_frame(frame))

    # After at least 3 identical frames, replay freeze must trigger
    frozen_detected = any(
        a.primary_anomaly == AnomalyType.CONSTELLATION_FREEZE for a in assessments[8:]
    )
    assert frozen_detected is True


def test_multipath_is_not_classified_as_spoofing():
    engine = DeterministicIntegrityEngine()
    sim = ScenarioSimulator()
    stream = sim.generate_scenario_stream(
        scenario_type=AnomalyType.MULTIPATH_INTERFERENCE,
        total_steps=12,
        attack_start_step=6,
        seed=29,
    )
    for frame in stream[:6]:
        assessment = engine.assess_frame(frame)
        assert assessment.primary_anomaly == AnomalyType.NONE
        assert assessment.is_anomalous is False

    multipath_frames = [engine.assess_frame(frame) for frame in stream[6:]]
    assert multipath_frames
    assert all(item.primary_anomaly == AnomalyType.MULTIPATH_INTERFERENCE for item in multipath_frames)
    assert all(item.is_anomalous is False for item in multipath_frames)
    assert all(item.anomaly_score <= 25.0 for item in multipath_frames)
    assert all(item.anomaly_score <= 100.0 for item in multipath_frames)


def test_acceleration_boundary_is_reported_without_calling_every_spike_an_attack():
    from src.models import GPSFix, DeadReckoningFix, DroneMissionState, PayloadPriority, SafeHavenZone

    engine = DeterministicIntegrityEngine()

    def frame(seq: int, speed: float) -> DroneMissionState:
        gps = GPSFix(
            timestamp=1_700_000_000.0 + seq,
            latitude=30.2672,
            longitude=-97.7431,
            altitude_m=120.0,
            speed_mps=speed,
            heading_deg=40.0,
            satellites_visible=10,
            hdop=1.0,
            vdop=1.3,
            snr_db=[40.0, 42.0, 39.5, 41.0, 43.0, 38.5, 40.5, 41.5],
            clock_drift_ns=1.1,
            fix_quality=1,
        )
        truth = DeadReckoningFix(
            timestamp=gps.timestamp,
            latitude=30.2672,
            longitude=-97.7431,
            altitude_m=120.0,
            speed_mps=16.0,
            heading_deg=40.0,
        )
        return DroneMissionState(
            drone_id="FINDR-DRONE-07",
            mission_id="MED-AIR-409",
            sequence_id=seq,
            timestamp=gps.timestamp,
            reported_gps=gps,
            inertial_truth=truth,
            battery_pct=90.0,
            payload_type=PayloadPriority.STANDARD_PARCEL,
            payload_weight_kg=1.0,
            destination_name="Austin Heart Hospital Landing Bay",
            destination_coords=(30.3072, -97.7131),
            safe_havens=[
                SafeHavenZone(
                    zone_id="HAVEN-ALPHA",
                    name="North Austin Regional Landing Pad",
                    latitude=30.2850,
                    longitude=-97.7320,
                    altitude_m=160.0,
                )
            ],
        )

    engine.assess_frame(frame(0, 16.0))
    spiked = engine.assess_frame(frame(1, 80.0))
    assert any("IMPOSSIBLE_ACCELERATION" in rule for rule in spiked.violated_rules)
    assert 0.0 <= spiked.anomaly_score <= 100.0
