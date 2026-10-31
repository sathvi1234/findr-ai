"""Unit tests for ScenarioSimulator."""

import random

import pytest
from src.simulator import ScenarioSimulator, haversine_distance
from src.models import AnomalyType, PayloadPriority


ALL_SCENARIOS = list(AnomalyType)
ATTACK_SCENARIOS = [scenario for scenario in ALL_SCENARIOS if scenario != AnomalyType.NONE]


def _gap_m(state) -> float:
    return haversine_distance(
        state.reported_gps.latitude,
        state.reported_gps.longitude,
        state.inertial_truth.latitude,
        state.inertial_truth.longitude,
    )


def _reported_step_m(previous, current) -> float:
    return haversine_distance(
        previous.reported_gps.latitude,
        previous.reported_gps.longitude,
        current.reported_gps.latitude,
        current.reported_gps.longitude,
    )


def test_seeded_streams_are_reproducible():
    sim = ScenarioSimulator()
    first = sim.generate_scenario_stream(AnomalyType.NONE, total_steps=5, seed=409)
    second = sim.generate_scenario_stream(AnomalyType.NONE, total_steps=5, seed=409)
    assert first[3].reported_gps.snr_db == second[3].reported_gps.snr_db
    assert first[3].reported_gps.latitude == second[3].reported_gps.latitude


def test_haversine_distance():
    # Austin downtown to domain (~16 km)
    dist = haversine_distance(30.2672, -97.7431, 30.4015, -97.7247)
    assert 14000.0 < dist < 17000.0


def test_simulator_clean_scenario():
    sim = ScenarioSimulator()
    stream = sim.generate_scenario_stream(scenario_type=AnomalyType.NONE, total_steps=10)
    assert len(stream) == 10
    for state in stream:
        assert state.reported_gps.satellites_visible >= 8
        assert state.reported_gps.speed_mps > 10.0
        assert state.battery_pct > 80.0
        assert len(state.safe_havens) == 3


def test_simulator_teleportation_jump():
    sim = ScenarioSimulator()
    stream = sim.generate_scenario_stream(
        scenario_type=AnomalyType.TELEPORTATION_JUMP, total_steps=15, attack_start_step=10
    )
    assert len(stream) == 15
    attack_frame = stream[10]
    prev_frame = stream[9]
    jump_m = haversine_distance(
        prev_frame.reported_gps.latitude, prev_frame.reported_gps.longitude,
        attack_frame.reported_gps.latitude, attack_frame.reported_gps.longitude,
    )
    assert jump_m > 500.0  # Teleportation leap


def test_simulator_rf_power_surge():
    sim = ScenarioSimulator()
    stream = sim.generate_scenario_stream(
        scenario_type=AnomalyType.RF_POWER_SURGE, total_steps=15, attack_start_step=10
    )
    attack_frame = stream[10]
    assert all(snr > 54.0 for snr in attack_frame.reported_gps.snr_db)


def test_simulator_insidious_drift():
    sim = ScenarioSimulator()
    stream = sim.generate_scenario_stream(
        scenario_type=AnomalyType.INSIDIOUS_DRIFT, total_steps=20, attack_start_step=10
    )
    last_frame = stream[-1]
    # In insidious drift, GNSS reported diverges from INS inertial truth
    dr_gap = haversine_distance(
        last_frame.reported_gps.latitude, last_frame.reported_gps.longitude,
        last_frame.inertial_truth.latitude, last_frame.inertial_truth.longitude,
    )
    assert dr_gap > 30.0


@pytest.mark.parametrize("scenario", ALL_SCENARIOS)
def test_every_scenario_honors_length_sequence_and_battery(scenario):
    random.seed(11)
    stream = ScenarioSimulator().generate_scenario_stream(
        scenario_type=scenario, total_steps=12, attack_start_step=5
    )
    assert len(stream) == 12
    assert [state.sequence_id for state in stream] == list(range(12))
    assert stream[0].battery_pct > stream[-1].battery_pct
    assert stream[-1].payload_type == PayloadPriority.ORGAN_TRANSPORT
    assert len(stream[-1].safe_havens) == 3


@pytest.mark.parametrize("scenario", ALL_SCENARIOS)
def test_zero_steps_returns_empty_stream(scenario):
    stream = ScenarioSimulator().generate_scenario_stream(
        scenario_type=scenario, total_steps=0, attack_start_step=0
    )
    assert stream == []


@pytest.mark.parametrize("scenario", ATTACK_SCENARIOS)
def test_frames_before_attack_start_stay_nominal(scenario):
    random.seed(3)
    stream = ScenarioSimulator().generate_scenario_stream(
        scenario_type=scenario, total_steps=10, attack_start_step=6
    )
    for state in stream[:6]:
        assert state.reported_gps.satellites_visible >= 9
        assert state.reported_gps.hdop < 2.0
        assert abs(state.reported_gps.speed_mps - 16.0) < 5.0
        assert _gap_m(state) < 20.0


@pytest.mark.parametrize("scenario", ATTACK_SCENARIOS)
def test_attack_start_past_end_leaves_nominal_telemetry(scenario):
    random.seed(19)
    stream = ScenarioSimulator().generate_scenario_stream(
        scenario_type=scenario, total_steps=8, attack_start_step=50
    )
    assert len(stream) == 8
    for state in stream:
        assert state.reported_gps.satellites_visible >= 9
        assert abs(state.reported_gps.speed_mps - 16.0) < 5.0
        assert state.reported_gps.clock_drift_ns != 0.0
        assert _gap_m(state) < 20.0


def test_clean_flight_ignores_attack_window_and_stays_near_ins():
    random.seed(5)
    stream = ScenarioSimulator().generate_scenario_stream(
        scenario_type=AnomalyType.NONE, total_steps=20, attack_start_step=4
    )
    for state in stream:
        assert state.reported_gps.satellites_visible >= 9
        assert state.reported_gps.hdop < 2.0
        assert 12.0 < state.reported_gps.speed_mps < 22.0
        assert _gap_m(state) < 25.0
    # Natural satellite power is not a frozen replay vector.
    assert stream[4].reported_gps.snr_db != stream[10].reported_gps.snr_db


def test_single_step_clean_flight():
    random.seed(2)
    stream = ScenarioSimulator().generate_scenario_stream(
        scenario_type=AnomalyType.NONE, total_steps=1, attack_start_step=0
    )
    assert len(stream) == 1
    assert stream[0].sequence_id == 0
    assert stream[0].reported_gps.satellites_visible >= 9
    assert _gap_m(stream[0]) < 25.0


def test_teleportation_jump_edges():
    random.seed(8)
    stream = ScenarioSimulator().generate_scenario_stream(
        scenario_type=AnomalyType.TELEPORTATION_JUMP,
        total_steps=14,
        attack_start_step=6,
    )
    for index in range(1, 6):
        assert _reported_step_m(stream[index - 1], stream[index]) < 80.0
        assert stream[index].reported_gps.speed_mps < 25.0

    attack = stream[6]
    assert attack.reported_gps.speed_mps == 88.0
    assert attack.reported_gps.clock_drift_ns == 45.0
    assert _reported_step_m(stream[5], attack) > 500.0
    assert _gap_m(attack) > 500.0
    # The leap persists on later attack frames, not only the first one.
    assert stream[-1].reported_gps.speed_mps == 88.0
    assert _gap_m(stream[-1]) > 500.0


def test_teleportation_from_first_frame():
    random.seed(4)
    stream = ScenarioSimulator().generate_scenario_stream(
        scenario_type=AnomalyType.TELEPORTATION_JUMP,
        total_steps=3,
        attack_start_step=0,
    )
    assert stream[0].reported_gps.speed_mps == 88.0
    assert _gap_m(stream[0]) > 500.0


def test_insidious_drift_stays_inside_step_bounds_while_residual_grows():
    random.seed(13)
    stream = ScenarioSimulator().generate_scenario_stream(
        scenario_type=AnomalyType.INSIDIOUS_DRIFT,
        total_steps=18,
        attack_start_step=5,
    )
    residuals = [_gap_m(state) for state in stream]
    assert residuals[4] < 20.0
    assert residuals[5] < residuals[-1]
    assert residuals[-1] > 40.0
    for index in range(1, len(stream)):
        assert _reported_step_m(stream[index - 1], stream[index]) < 80.0
        assert stream[index].reported_gps.speed_mps < 25.0


def test_rf_power_surge_is_uniform_and_confined_to_attack_window():
    random.seed(17)
    stream = ScenarioSimulator().generate_scenario_stream(
        scenario_type=AnomalyType.RF_POWER_SURGE,
        total_steps=12,
        attack_start_step=7,
    )
    for state in stream[:7]:
        assert not all(snr > 54.0 for snr in state.reported_gps.snr_db)
        assert state.reported_gps.hdop > 0.7

    for state in stream[7:]:
        snr = state.reported_gps.snr_db
        assert state.reported_gps.satellites_visible == 12
        assert len(snr) == 12
        assert all(value > 54.0 for value in snr)
        assert max(snr) - min(snr) < 1.0
        assert state.reported_gps.hdop == 0.5
        assert state.reported_gps.vdop == 0.6
        assert state.reported_gps.clock_drift_ns == 12.0


def test_constellation_freeze_replays_identical_metrics():
    random.seed(21)
    stream = ScenarioSimulator().generate_scenario_stream(
        scenario_type=AnomalyType.CONSTELLATION_FREEZE,
        total_steps=12,
        attack_start_step=4,
    )
    frozen = stream[4].reported_gps
    assert frozen.satellites_visible == 8
    assert frozen.hdop == 1.05
    assert frozen.vdop == 1.30
    assert frozen.clock_drift_ns == 0.0
    assert len(frozen.snr_db) == 8

    for state in stream[4:]:
        gps = state.reported_gps
        assert gps.snr_db == frozen.snr_db
        assert gps.hdop == frozen.hdop
        assert gps.vdop == frozen.vdop
        assert gps.satellites_visible == 8
        assert gps.clock_drift_ns == 0.0

    # Pre-attack epochs are not a replay of that frozen vector.
    assert stream[3].reported_gps.snr_db != frozen.snr_db
    assert stream[3].reported_gps.clock_drift_ns != 0.0


def test_constellation_freeze_from_first_frame_is_constant():
    stream = ScenarioSimulator().generate_scenario_stream(
        scenario_type=AnomalyType.CONSTELLATION_FREEZE,
        total_steps=4,
        attack_start_step=0,
    )
    first = stream[0].reported_gps
    assert all(state.reported_gps.snr_db == first.snr_db for state in stream)
    assert all(state.reported_gps.clock_drift_ns == 0.0 for state in stream)


def test_multipath_degrades_geometry_without_a_kinematic_break():
    random.seed(29)
    stream = ScenarioSimulator().generate_scenario_stream(
        scenario_type=AnomalyType.MULTIPATH_INTERFERENCE,
        total_steps=12,
        attack_start_step=5,
    )
    for state in stream[:5]:
        assert state.reported_gps.satellites_visible >= 9
        assert state.reported_gps.hdop < 2.0

    for state in stream[5:]:
        gps = state.reported_gps
        assert gps.satellites_visible == 6
        assert len(gps.snr_db) == 6
        assert gps.hdop >= 3.5
        assert gps.vdop >= 4.0
        assert gps.speed_mps < 30.0
        assert _gap_m(state) < 80.0
        assert sum(gps.snr_db) / len(gps.snr_db) < 45.0
