"""Delivery-scenario labels, distinct corridors, and the additive audit columns."""

import sqlite3

from src.audit_db import AuditDatabase
from src.integrity_engine import DeterministicIntegrityEngine
from src.models import AnomalyType
from src.simulator import ScenarioSimulator, haversine_distance


def _labels(scenario, steps=16, attack=6):
    stream = ScenarioSimulator().generate_scenario_stream(
        scenario, total_steps=steps, attack_start_step=attack, seed=409
    )
    engine = DeterministicIntegrityEngine()
    return stream, [engine.assess_frame(frame) for frame in stream]


def test_false_arrival_is_not_relabeled_as_a_teleport():
    stream, assessments = _labels(AnomalyType.FALSE_DELIVERY_ARRIVAL)
    attack = assessments[6:]
    assert attack
    assert all(item.primary_anomaly == AnomalyType.FALSE_DELIVERY_ARRIVAL for item in attack)
    assert all(item.is_anomalous for item in attack)
    last = stream[-1]
    reported_to_customer = haversine_distance(
        last.reported_gps.latitude, last.reported_gps.longitude,
        last.destination_coords[0], last.destination_coords[1],
    )
    reference_to_customer = haversine_distance(
        last.inertial_truth.latitude, last.inertial_truth.longitude,
        last.destination_coords[0], last.destination_coords[1],
    )
    assert reported_to_customer < 80
    assert reference_to_customer > 150
    assert last.claimed_arrival is True
    assert last.agent_id == last.drone_id
    assert last.order_id == last.mission_id


def test_route_deviation_agrees_with_the_reference_track():
    stream, assessments = _labels(AnomalyType.ROUTE_DEVIATION, steps=18, attack=6)
    assert assessments[-1].primary_anomaly == AnomalyType.ROUTE_DEVIATION
    assert assessments[-1].is_anomalous is True
    assert assessments[-1].dr_residual_m < 18
    assert all(item.primary_anomaly != AnomalyType.TELEPORTATION_JUMP for item in assessments)
    assert stream[-1].delivery_status.value == "OFF_ROUTE"


def test_suspicious_movement_is_faster_than_a_delivery_run_and_short_of_a_teleport():
    stream, assessments = _labels(AnomalyType.SUSPICIOUS_MOVEMENT)
    assert assessments[6].primary_anomaly == AnomalyType.SUSPICIOUS_MOVEMENT
    assert 55 < assessments[6].kinematic_jump_m <= 150
    assert assessments[6].is_anomalous is True
    assert all(item.primary_anomaly == AnomalyType.NONE for item in assessments[:6])
    assert stream[6].vehicle_type.value in {"MOTORCYCLE", "SCOOTER", "CAR", "VAN"}


def test_dashboard_scenarios_use_different_streets():
    origins = set()
    for scenario in (
        AnomalyType.NONE,
        AnomalyType.RF_POWER_SURGE,
        AnomalyType.INSIDIOUS_DRIFT,
        AnomalyType.TELEPORTATION_JUMP,
        AnomalyType.FALSE_DELIVERY_ARRIVAL,
        AnomalyType.ROUTE_DEVIATION,
        AnomalyType.SUSPICIOUS_MOVEMENT,
    ):
        stream, _assessments = _labels(scenario, steps=4, attack=2)
        origins.add((round(stream[0].pickup_coords[0], 4), round(stream[0].pickup_coords[1], 4)))
        assert stream[0].pickup_coords != stream[0].destination_coords
    assert len(origins) == 7


def test_migration_adds_delivery_columns_without_deleting_rows(tmp_path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE incidents (
            incident_id TEXT PRIMARY KEY,
            drone_id TEXT NOT NULL,
            mission_id TEXT NOT NULL,
            timestamp REAL NOT NULL,
            anomaly_type TEXT NOT NULL,
            anomaly_score REAL NOT NULL,
            is_anomalous INTEGER NOT NULL,
            reported_lat REAL NOT NULL,
            reported_lon REAL NOT NULL,
            reported_alt REAL NOT NULL,
            truth_lat REAL NOT NULL,
            truth_lon REAL NOT NULL,
            truth_alt REAL NOT NULL,
            kinematic_jump_m REAL,
            dr_residual_m REAL,
            snr_mean REAL,
            snr_std REAL,
            rule_explanation TEXT
        )
        """
    )
    connection.execute(
        """
        INSERT INTO incidents VALUES (
            'INC-OLD', 'FINDR-DRONE-07', 'MED-AIR-409', 1, 'INSIDIOUS_DRIFT',
            50, 1, 30.1, -97.7, 1, 30.1, -97.7, 1, 0, 50, 40, 1, 'stored'
        )
        """
    )
    connection.commit()
    connection.close()

    database = AuditDatabase(db_path=path)
    rows = database.list_recent_incidents(limit=5)
    assert rows[0]["anomaly_type"] == "INSIDIOUS_DRIFT"
    assert rows[0]["agent_id"] == "FINDR-DRONE-07"
    assert rows[0]["order_id"] == "MED-AIR-409"
    assert database.verify_integrity()[0] is True
