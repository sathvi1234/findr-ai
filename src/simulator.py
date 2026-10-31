"""
FINDR AI — Synthetic GPS Scenario Simulator
===========================================
Generates physically bounded synthetic telemetry for e-commerce delivery runs
on motorcycles, scooters, cars, and vans. Coordinates are simulated.

NOTE: All generated coordinates and RF metrics are 100% synthetic mathematical
simulations. No RF signals, radio transmissions, or real hardware are used.
"""

import math
import random
import time
from typing import List, Optional, Tuple, Generator
from src.models import (
    GPSFix,
    DeadReckoningFix,
    DroneMissionState,
    SafeHavenZone,
    PayloadPriority,
    AnomalyType,
    VehicleType,
    DeliveryStatus,
)

# Earth radius in meters
EARTH_RADIUS_M = 6371000.0


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in meters between two coordinates via Haversine formula."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_M * c


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing in degrees, clockwise from true north."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_lambda = math.radians(lon2 - lon1)
    y = math.sin(delta_lambda) * math.cos(phi2)
    x = (
        math.cos(phi1) * math.sin(phi2)
        - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
    )
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def cross_track_distance_m(
    lat: float, lon: float, start_lat: float, start_lon: float, bearing_deg: float
) -> float:
    """Meters from a point to the ray that leaves ``start`` on ``bearing_deg``."""
    distance_m = haversine_distance(start_lat, start_lon, lat, lon)
    if distance_m < 0.5:
        return 0.0
    point_bearing = initial_bearing_deg(start_lat, start_lon, lat, lon)
    delta = math.radians(point_bearing - bearing_deg)
    return abs(math.sin(delta) * distance_m)


def compute_destination_point(
    lat: float, lon: float, distance_m: float, bearing_deg: float
) -> Tuple[float, float]:
    """Compute new lat/lon given a starting coordinate, distance in meters, and bearing."""
    phi1 = math.radians(lat)
    lambda1 = math.radians(lon)
    theta = math.radians(bearing_deg)
    delta = distance_m / EARTH_RADIUS_M

    phi2 = math.asin(
        math.sin(phi1) * math.cos(delta)
        + math.cos(phi1) * math.sin(delta) * math.cos(theta)
    )
    lambda2 = lambda1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2),
    )
    return math.degrees(phi2), math.degrees(lambda2)


def _handoff(zone_id: str, name: str, latitude: float, longitude: float, slots: int) -> SafeHavenZone:
    return SafeHavenZone(
        zone_id=zone_id,
        name=name,
        latitude=latitude,
        longitude=longitude,
        altitude_m=150.0,
        is_secured_perimeter=True,
        landing_capacity=slots,
    )


class ScenarioSimulator:
    """Generates synthetic delivery telemetry for one selected scenario."""

    # Default metro delivery route. Individual scenarios override this.
    ORIGIN_LAT = 30.2672
    ORIGIN_LON = -97.7431
    DEST_LAT = 30.3072
    DEST_LON = -97.7131

    DEFAULT_SAFE_HAVENS = [
        _handoff("HANDOFF-ALPHA", "North Austin Parcel Handoff", 30.2850, -97.7320, 3),
        _handoff("HANDOFF-BRAVO", "Mueller Depot Counter", 30.2980, -97.7050, 2),
        _handoff("HANDOFF-CHARLIE", "Capitol Courier Cage", 30.2740, -97.7400, 1),
    ]

    # Real Austin coordinates used as a synthetic street corridor. Not a live agent.
    ROUTES = {
        AnomalyType.NONE: {
            "origin": (30.2672, -97.7431),
            "dest": (30.2855, -97.7265),
            "pickup": "Congress Avenue Dispatch",
            "customer": "East 12th Street Customer",
            "vehicle": VehicleType.MOTORCYCLE,
        },
        AnomalyType.RF_POWER_SURGE: {
            "origin": (30.2490, -97.7498),
            "dest": (30.2648, -97.7288),
            "pickup": "South Congress Pickup Locker",
            "customer": "Rainey Street Customer",
            "vehicle": VehicleType.SCOOTER,
        },
        AnomalyType.INSIDIOUS_DRIFT: {
            "origin": (30.2950, -97.7388),
            "dest": (30.3125, -97.7195),
            "pickup": "Hyde Park Dispatch",
            "customer": "Windsor Road Customer",
            "vehicle": VehicleType.CAR,
        },
        AnomalyType.TELEPORTATION_JUMP: {
            "origin": (30.2642, -97.7715),
            "dest": (30.2748, -97.7462),
            "pickup": "Zilker Depot",
            "customer": "Lavaca Street Customer",
            "vehicle": VehicleType.VAN,
        },
        AnomalyType.FALSE_DELIVERY_ARRIVAL: {
            "origin": (30.2428, -97.7248),
            "dest": (30.2595, -97.7145),
            "pickup": "Riverside Sort Point",
            "customer": "Govalle Customer Door",
            "vehicle": VehicleType.MOTORCYCLE,
        },
        AnomalyType.ROUTE_DEVIATION: {
            "origin": (30.3078, -97.7242),
            "dest": (30.3205, -97.7395),
            "pickup": "Mueller Staging Bay",
            "customer": "North Loop Customer",
            "vehicle": VehicleType.CAR,
        },
        AnomalyType.SUSPICIOUS_MOVEMENT: {
            "origin": (30.2572, -97.7598),
            "dest": (30.2465, -97.7695),
            "pickup": "Barton Springs Cage",
            "customer": "South Lamar Customer",
            "vehicle": VehicleType.SCOOTER,
        },
    }

    def __init__(
        self,
        drone_id: str = "FINDR-AGENT-07",
        mission_id: str = "ORD-2026-409",
        cruise_speed_mps: float = 16.0,  # ~58 km/h urban delivery cruise
        cruise_altitude_m: float = 1.5,
        payload_type: PayloadPriority = PayloadPriority.ORGAN_TRANSPORT,
        vehicle_type: Optional[VehicleType] = None,
    ):
        self.drone_id = drone_id
        self.mission_id = mission_id
        self.cruise_speed_mps = cruise_speed_mps
        self.cruise_altitude_m = cruise_altitude_m
        self.payload_type = payload_type
        self.vehicle_type = vehicle_type

    @staticmethod
    def _handoffs_near(
        origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float
    ) -> List[SafeHavenZone]:
        mid_lat = (origin_lat + dest_lat) / 2.0
        mid_lon = (origin_lon + dest_lon) / 2.0
        return [
            _handoff("HANDOFF-ALPHA", "Pickup-side Handoff Cage", origin_lat + 0.004, origin_lon + 0.003, 3),
            _handoff("HANDOFF-BRAVO", "Mid-route Depot Counter", mid_lat, mid_lon, 2),
            _handoff("HANDOFF-CHARLIE", "Customer-side Courier Cage", dest_lat - 0.003, dest_lon + 0.002, 1),
        ]

    def generate_scenario_stream(
        self,
        scenario_type: AnomalyType,
        total_steps: int = 30,
        step_dt_seconds: float = 1.0,
        attack_start_step: int = 12,
        seed: Optional[int] = None,
    ) -> List[DroneMissionState]:
        """
        Generate a complete synthetic telemetry timeline for a chosen scenario.

        Pass ``seed`` to replay the same atmospheric noise. Omitting it keeps the
        historical unseeded behavior used by existing callers.
        """
        if seed is not None:
            random.seed(seed)
        states: List[DroneMissionState] = []
        base_time = time.time() - (total_steps * step_dt_seconds)

        route = self.ROUTES.get(scenario_type)
        origin_lat = route["origin"][0] if route else self.ORIGIN_LAT
        origin_lon = route["origin"][1] if route else self.ORIGIN_LON
        dest_lat = route["dest"][0] if route else self.DEST_LAT
        dest_lon = route["dest"][1] if route else self.DEST_LON
        pickup_name = route["pickup"] if route else "East Austin Dispatch Bay"
        customer_name = route["customer"] if route else "Customer door"
        vehicle = self.vehicle_type or (route["vehicle"] if route else VehicleType.MOTORCYCLE)
        handoffs = self._handoffs_near(origin_lat, origin_lon, dest_lat, dest_lon)

        bearing = initial_bearing_deg(origin_lat, origin_lon, dest_lat, dest_lon)

        curr_truth_lat = origin_lat
        curr_truth_lon = origin_lon
        battery_pct = 94.0

        # Spoofing accumulators
        spoof_lat_offset = 0.0
        spoof_lon_offset = 0.0

        # Frozen metrics for replay attacks
        frozen_snr = [42.1, 41.5, 43.0, 39.8, 44.2, 40.0, 42.8, 41.9]

        for step in range(total_steps):
            timestamp = base_time + (step * step_dt_seconds)
            step_distance = self.cruise_speed_mps * step_dt_seconds

            # Advance true physical position (Inertial Navigation truth)
            curr_truth_lat, curr_truth_lon = compute_destination_point(
                curr_truth_lat, curr_truth_lon, step_distance, bearing
            )
            battery_pct -= 0.15

            # Base physical truth state (Dead-Reckoning)
            truth_fix = DeadReckoningFix(
                timestamp=timestamp,
                latitude=curr_truth_lat,
                longitude=curr_truth_lon,
                altitude_m=self.cruise_altitude_m + random.uniform(-0.3, 0.3),
                speed_mps=self.cruise_speed_mps + random.uniform(-0.2, 0.2),
                heading_deg=bearing + random.uniform(-0.5, 0.5),
                accel_x=random.gauss(0.0, 0.05),
                accel_y=random.gauss(0.0, 0.05),
                accel_z=9.81 + random.gauss(0.0, 0.03),
                gyro_z=random.gauss(0.0, 0.01),
            )

            # Default healthy reported GNSS fix
            gps_lat = curr_truth_lat + random.gauss(0.0, 0.00001)  # ~1m noise
            gps_lon = curr_truth_lon + random.gauss(0.0, 0.00001)
            gps_alt = self.cruise_altitude_m + random.gauss(0.0, 0.8)
            gps_speed = self.cruise_speed_mps + random.gauss(0.0, 0.3)
            gps_heading = bearing + random.gauss(0.0, 1.0)
            satellites = random.randint(9, 12)
            hdop = random.uniform(0.85, 1.15)
            vdop = random.uniform(1.2, 1.5)
            snr_db = [round(random.gauss(41.0, 2.5), 1) for _ in range(satellites)]
            clock_drift = random.gauss(1.2, 0.4)

            claimed_arrival = False
            delivery_status = DeliveryStatus.IN_TRANSIT

            # Inject scenario anomalies once attack_start_step is reached
            is_attack_active = (step >= attack_start_step) and (scenario_type != AnomalyType.NONE)

            if is_attack_active:
                if scenario_type == AnomalyType.TELEPORTATION_JUMP:
                    # Instantaneous coordinate leap > 900 meters away
                    gps_lat += 0.0085  # ~940m north
                    gps_lon += 0.0090  # ~860m east
                    gps_speed = 88.0  # Physically impossible velocity
                    clock_drift = 45.0

                elif scenario_type == AnomalyType.INSIDIOUS_DRIFT:
                    # Subtle creeping drift (deflecting drone away from corridor)
                    # Constant gentle deflection: ~4m per second lateral drift
                    # Stays within kinematic limits (< 30 m/s), but accumulates major INS residual
                    spoof_lat_offset += 0.000038
                    spoof_lon_offset -= 0.000028
                    gps_lat += spoof_lat_offset
                    gps_lon += spoof_lon_offset
                    # Reported speed looks normal, but discrepancies mount against INS

                elif scenario_type == AnomalyType.RF_POWER_SURGE:
                    # High power spoofing transmitter drowning out authentic GNSS
                    # Abnormally high SNR with artificial zero variance across all PRNs
                    satellites = 12
                    hdop = 0.5  # Suspiciously "perfect" geometry
                    vdop = 0.6
                    snr_db = [56.2, 56.5, 56.1, 56.4, 56.3, 56.6, 56.2, 56.4, 56.5, 56.3, 56.4, 56.2]
                    clock_drift = 12.0

                elif scenario_type == AnomalyType.CONSTELLATION_FREEZE:
                    # Replay attack: satellite metrics, DOP, and exact SNR vector frozen identically
                    satellites = 8
                    hdop = 1.05
                    vdop = 1.30
                    snr_db = frozen_snr.copy()
                    clock_drift = 0.000  # Zero drift over time is unnatural

                elif scenario_type == AnomalyType.MULTIPATH_INTERFERENCE:
                    # Benign urban canyon: degraded DOP and noisy SNR, but bounded velocity
                    satellites = 6
                    hdop = 3.8
                    vdop = 4.2
                    snr_db = [round(random.gauss(27.0, 5.0), 1) for _ in range(6)]
                    gps_lat += random.gauss(0.0, 0.000025)  # ~3m reflection, inside the speed bound
                    gps_lon += random.gauss(0.0, 0.000025)
                    gps_speed = self.cruise_speed_mps + random.gauss(0.0, 1.2)

                elif scenario_type == AnomalyType.FALSE_DELIVERY_ARRIVAL:
                    gps_lat = dest_lat + 0.00004
                    gps_lon = dest_lon + 0.00003
                    gps_speed = 1.2
                    claimed_arrival = True
                    delivery_status = DeliveryStatus.CLAIMED_ARRIVAL

                elif scenario_type == AnomalyType.ROUTE_DEVIATION:
                    curr_truth_lat, curr_truth_lon = compute_destination_point(
                        curr_truth_lat, curr_truth_lon, 18.0, (bearing + 90.0) % 360.0
                    )
                    truth_fix = truth_fix.model_copy(update={
                        "latitude": curr_truth_lat,
                        "longitude": curr_truth_lon,
                    })
                    gps_lat = curr_truth_lat + random.gauss(0.0, 0.000008)
                    gps_lon = curr_truth_lon + random.gauss(0.0, 0.000008)
                    delivery_status = DeliveryStatus.OFF_ROUTE

                elif scenario_type == AnomalyType.SUSPICIOUS_MOVEMENT:
                    curr_truth_lat, curr_truth_lon = compute_destination_point(
                        curr_truth_lat, curr_truth_lon, 62.0, bearing
                    )
                    truth_fix = truth_fix.model_copy(update={
                        "latitude": curr_truth_lat,
                        "longitude": curr_truth_lon,
                    })
                    gps_lat = curr_truth_lat + random.gauss(0.0, 0.000008)
                    gps_lon = curr_truth_lon + random.gauss(0.0, 0.000008)
                    gps_speed = 78.0

            reported_fix = GPSFix(
                timestamp=timestamp,
                latitude=gps_lat,
                longitude=gps_lon,
                altitude_m=gps_alt,
                speed_mps=gps_speed,
                heading_deg=gps_heading,
                satellites_visible=satellites,
                hdop=round(hdop, 2),
                vdop=round(vdop, 2),
                snr_db=snr_db,
                clock_drift_ns=round(clock_drift, 3),
                fix_quality=1,
            )

            state = DroneMissionState(
                drone_id=self.drone_id,
                mission_id=self.mission_id,
                sequence_id=step,
                timestamp=timestamp,
                reported_gps=reported_fix,
                inertial_truth=truth_fix,
                battery_pct=round(battery_pct, 1),
                payload_type=self.payload_type,
                payload_weight_kg=2.8,
                destination_name=customer_name,
                destination_coords=(dest_lat, dest_lon),
                safe_havens=handoffs,
                vehicle_type=vehicle,
                delivery_status=delivery_status,
                claimed_arrival=claimed_arrival,
                pickup_name=pickup_name,
                pickup_coords=(origin_lat, origin_lon),
                route_bearing_deg=bearing,
            )
            states.append(state)

        return states
