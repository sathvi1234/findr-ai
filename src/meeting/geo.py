"""Coordinate formatting and GeoJSON. Longitude is stored before latitude."""

from typing import Optional


def geojson_point(latitude: float, longitude: float) -> dict:
    """GeoJSON Point. MongoDB 2dsphere indexes expect ``[longitude, latitude]``."""
    return {"type": "Point", "coordinates": [float(longitude), float(latitude)]}


def format_latitude(latitude: float) -> str:
    hemisphere = "N" if latitude >= 0 else "S"
    return f"Latitude: {abs(latitude):.4f}° {hemisphere}"


def format_longitude(longitude: float) -> str:
    hemisphere = "E" if longitude >= 0 else "W"
    return f"Longitude: {abs(longitude):.4f}° {hemisphere}"


def format_accuracy(accuracy_m: Optional[float], source: str) -> str:
    """Device accuracy only. A synthetic frame is not given a made-up metre value."""
    if source != "device" or accuracy_m is None:
        return "GPS accuracy: not a device measurement (synthetic demonstration frame)"
    return f"GPS accuracy: ±{accuracy_m:.0f} metres"


def approximate_for_customer(latitude: float, longitude: float) -> tuple:
    """About 100 m precision for the customer view."""
    return round(latitude, 3), round(longitude, 3)


def eta_minutes(distance_m: float, speed_mps: float = 8.0) -> float:
    if distance_m <= 0 or speed_mps <= 0:
        return 0.0
    return distance_m / speed_mps / 60.0


def osm_directions_url(from_lat: float, from_lon: float, to_lat: float, to_lon: float) -> str:
    route = f"{from_lat:.6f}%2C{from_lon:.6f}%3B{to_lat:.6f}%2C{to_lon:.6f}"
    return f"https://www.openstreetmap.org/directions?engine=fossgis_osrm_car&route={route}"
