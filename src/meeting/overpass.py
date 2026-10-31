"""Nearby public places from the Overpass API. Failures return no invented places."""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from src.simulator import haversine_distance

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
PUBLIC_AMENITIES = "cafe|restaurant|pharmacy|fuel|bank|library|community_centre|place_of_worship"
PRIVATE_ACCESS = {"private", "no", "permit", "customers", "residents", "delivery"}


@dataclass
class PublicPlace:
    name: str
    latitude: float
    longitude: float
    distance_m: float
    address: str
    kind: str
    osm_id: int


@dataclass
class PlaceSearch:
    ok: bool
    places: List[PublicPlace] = field(default_factory=list)
    error: str = ""


def _label(tags: dict) -> tuple:
    if tags.get("highway") == "bus_stop" or tags.get("public_transport") in {"stop_position", "platform"}:
        kind = "bus_stop"
    elif tags.get("shop"):
        kind = "shop"
    elif tags.get("amenity"):
        kind = str(tags["amenity"])
    elif tags.get("tourism"):
        kind = str(tags["tourism"])
    else:
        return "", ""
    name = tags.get("name") or tags.get("brand") or kind.replace("_", " ").title()
    street = tags.get("addr:street", "")
    number = tags.get("addr:housenumber", "")
    address = " ".join(part for part in (number, street) if part).strip()
    if not address:
        address = f"OpenStreetMap {kind.replace('_', ' ')} {tags.get('osm_id', '')}".strip()
    return name, address or "Address not published in OpenStreetMap"


def _is_public(tags: dict) -> bool:
    access = str(tags.get("access", "")).lower()
    if access in PRIVATE_ACCESS:
        return False
    if tags.get("military") or tags.get("access") == "private":
        return False
    kind, _address = _label(tags)
    return bool(kind)


def parse_overpass(payload: dict, origin_lat: float, origin_lon: float, limit: int = 12) -> List[PublicPlace]:
    places: List[PublicPlace] = []
    for element in payload.get("elements") or []:
        lat = element.get("lat")
        lon = element.get("lon")
        tags = dict(element.get("tags") or {})
        if lat is None or lon is None or not _is_public(tags):
            continue
        name, address = _label(tags)
        if not name:
            continue
        kind = tags.get("amenity") or tags.get("shop") or tags.get("highway") or tags.get("tourism") or "public"
        places.append(PublicPlace(
            name=name,
            latitude=float(lat),
            longitude=float(lon),
            distance_m=haversine_distance(origin_lat, origin_lon, float(lat), float(lon)),
            address=address,
            kind=str(kind),
            osm_id=int(element.get("id") or 0),
        ))
    places.sort(key=lambda place: place.distance_m)
    return places[:limit]


def overpass_query(latitude: float, longitude: float, radius_m: int) -> str:
    radius = max(50, min(int(radius_m), 2000))
    around = f"(around:{radius},{latitude},{longitude})"
    return (
        f"[out:json][timeout:12];("
        f'node["highway"="bus_stop"]{around};'
        f'node["public_transport"="stop_position"]{around};'
        f'node["amenity"~"{PUBLIC_AMENITIES}"]{around};'
        f'node["shop"]{around};'
        f'node["tourism"~"attraction|museum|viewpoint"]{around};'
        f");out body 25;"
    )


def search_public_places(
    latitude: float,
    longitude: float,
    radius_m: int = 500,
    fetch: Optional[Callable] = None,
) -> PlaceSearch:
    """Search Overpass. A failed call returns an empty list and the error text."""
    query = overpass_query(latitude, longitude, radius_m)
    try:
        if fetch is None:
            status, body = _http_overpass(query)
        else:
            status, body = fetch(OVERPASS_URL, query)
    except Exception as exc:
        return PlaceSearch(ok=False, places=[], error=f"Nearby search failed: {exc}")
    if status != 200:
        return PlaceSearch(ok=False, places=[], error=f"Nearby search returned HTTP {status}. No places were added.")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return PlaceSearch(ok=False, places=[], error="Nearby search returned an unreadable response. No places were added.")
    return PlaceSearch(ok=True, places=parse_overpass(payload, latitude, longitude), error="")


def _http_overpass(query: str) -> tuple:
    request = urllib.request.Request(
        OVERPASS_URL,
        data=query.encode("utf-8"),
        headers={"User-Agent": "FINDR-AI-demo/0.1 (synthetic delivery meeting points)"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
