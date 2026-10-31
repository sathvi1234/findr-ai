"""Meeting-point search, confirmation, OTP, and handover gates."""

import json

from src.meeting.geo import format_accuracy, format_latitude, format_longitude, geojson_point
from src.meeting.overpass import parse_overpass, search_public_places
from src.meeting.service import MeetingService, manual_place_document
from src.meeting.store import INDEXES, MemoryMeetingStore
from src.models import AnomalyType


AUSTIN = {
    "elements": [
        {
            "type": "node",
            "id": 10,
            "lat": 30.2674,
            "lon": -97.7434,
            "tags": {"amenity": "cafe", "name": "Congress Coffee", "addr:street": "Congress Avenue", "addr:housenumber": "200"},
        },
        {
            "type": "node",
            "id": 11,
            "lat": 30.2680,
            "lon": -97.7420,
            "tags": {"highway": "bus_stop", "name": "6th Street Stop"},
        },
        {
            "type": "node",
            "id": 12,
            "lat": 30.2671,
            "lon": -97.7430,
            "tags": {"shop": "convenience", "name": "Private Cage", "access": "private"},
        },
        {
            "type": "node",
            "id": 13,
            "lat": 30.2700,
            "lon": -97.7400,
            "tags": {"military": "office", "name": "Restricted Yard"},
        },
    ]
}


def test_coordinates_use_longitude_first_and_a_hemisphere_label():
    point = geojson_point(16.5062, 80.6480)
    assert point["coordinates"] == [80.6480, 16.5062]
    assert format_latitude(16.5062) == "Latitude: 16.5062° N"
    assert format_longitude(80.6480) == "Longitude: 80.6480° E"
    assert format_latitude(-30.2672) == "Latitude: 30.2672° S"
    assert "not a device measurement" in format_accuracy(12, "synthetic")
    assert format_accuracy(12, "device") == "GPS accuracy: ±12 metres"


def test_overpass_keeps_public_places_and_drops_private_ones():
    places = parse_overpass(AUSTIN, 30.2672, -97.7431)
    names = [place.name for place in places]
    assert "Congress Coffee" in names
    assert "6th Street Stop" in names
    assert "Private Cage" not in names
    assert "Restricted Yard" not in names
    coffee = next(place for place in places if place.name == "Congress Coffee")
    assert coffee.address == "200 Congress Avenue"
    assert coffee.distance_m >= 0


def test_failed_search_adds_no_places():
    failed = search_public_places(30.2672, -97.7431, fetch=lambda _url, _query: (504, ""))
    assert failed.ok is False
    assert failed.places == []
    assert "504" in failed.error
    broken = search_public_places(30.2672, -97.7431, fetch=lambda _url, _query: (200, "not-json"))
    assert broken.places == []


def test_customer_must_confirm_and_otp_before_handover():
    service = MeetingService(MemoryMeetingStore())
    places = parse_overpass(AUSTIN, 30.2672, -97.7431)
    service.request_meeting(
        order_id="ORD-2026-409",
        agent_id="FINDR-AGENT-07",
        vehicle_type="MOTORCYCLE",
        partner_lat=30.2672,
        partner_lon=-97.7431,
        position_source="synthetic",
        accuracy_m=None,
        destination_name="East 12th Street Customer",
        destination_lat=30.2855,
        destination_lon=-97.7265,
        places=places,
        search_ok=True,
        search_error="",
    )
    near_only = service.attempt_handover(
        "ORD-2026-409", "FINDR-AGENT-07", "000000",
        30.2855, -97.7265, 30.2854, -97.7264,
        AnomalyType.NONE, False,
    )
    assert near_only["ok"] is False
    chosen = service.customer_view("ORD-2026-409")["suggestions"][0]
    confirmed = service.customer_choice("ORD-2026-409", chosen, "confirm", share_location=True)
    code = confirmed["otp_preview_for_customer"]
    persisted = service.store.find_one("meeting_point_requests", "order_id", "ORD-2026-409")
    assert code not in json.dumps(persisted)
    wrong = service.attempt_handover(
        "ORD-2026-409", "FINDR-AGENT-07", "999999",
        30.2673, -97.7432, 30.2672, -97.7431,
        AnomalyType.NONE, False,
    )
    assert wrong["ok"] is False
    done = service.attempt_handover(
        "ORD-2026-409", "FINDR-AGENT-07", code,
        30.2673, -97.7432, 30.2672, -97.7431,
        AnomalyType.NONE, False,
    )
    assert done["ok"] is True
    assert done["delivered_because_near_destination"] is False
    stored = service.store.find_one("meeting_points", "order_id", "ORD-2026-409")
    assert stored["location"]["coordinates"][0] == chosen["location"]["coordinates"][0]
    view = service.customer_view("ORD-2026-409")
    assert view["partner_approximate"]["note"].startswith("Approximate")
    assert "audit_logs" in service.store.documents
    assert any(row["event"] == "handover_recorded" for row in service.store.documents["audit_logs"])


def test_high_risk_jump_needs_authorization_and_rejection_clears_the_point():
    service = MeetingService(MemoryMeetingStore())
    manual = manual_place_document("Depot gate", 30.2680, -97.7420, 30.2672, -97.7431)
    assert "Not an OpenStreetMap" in manual["address"]
    service.request_meeting(
        order_id="ORD-1",
        agent_id="FINDR-AGENT-07",
        vehicle_type="SCOOTER",
        partner_lat=30.2672,
        partner_lon=-97.7431,
        position_source="device",
        accuracy_m=12,
        destination_name="Customer",
        destination_lat=30.2700,
        destination_lon=-97.7400,
        places=[manual],
        search_ok=False,
        search_error="Nearby search failed",
    )
    confirmed = service.customer_choice("ORD-1", manual, "confirm", share_location=False)
    blocked = service.attempt_handover(
        "ORD-1", "FINDR-AGENT-07", confirmed["otp_preview_for_customer"],
        30.2800, -97.7300, 30.2672, -97.7431,
        AnomalyType.TELEPORTATION_JUMP, False,
    )
    assert blocked["ok"] is False
    allowed = service.attempt_handover(
        "ORD-1", "FINDR-AGENT-07", confirmed["otp_preview_for_customer"],
        30.2800, -97.7300, 30.2672, -97.7431,
        AnomalyType.TELEPORTATION_JUMP, True,
    )
    assert allowed["ok"] is True
    service.request_meeting(
        order_id="ORD-2",
        agent_id="FINDR-AGENT-07",
        vehicle_type="CAR",
        partner_lat=30.26,
        partner_lon=-97.74,
        position_source="synthetic",
        accuracy_m=None,
        destination_name="Customer",
        destination_lat=30.27,
        destination_lon=-97.73,
        places=[manual],
        search_ok=True,
        search_error="",
    )
    rejected = service.customer_choice("ORD-2", None, "reject", False)
    assert rejected["status"] == "REJECTED"
    assert rejected["customer_confirmed"] is False


def test_nearby_public_points_use_the_radius_and_skip_manual_places():
    store = MemoryMeetingStore()
    store.upsert("meeting_points", "order_id", "NEAR", {
        "order_id": "NEAR",
        "name": "Congress Coffee",
        "address": "200 Congress Avenue",
        "kind": "cafe",
        "source": "openstreetmap",
        "location": geojson_point(30.2674, -97.7434),
    })
    store.upsert("meeting_points", "order_id", "FAR", {
        "order_id": "FAR",
        "name": "Far Depot",
        "kind": "library",
        "source": "openstreetmap",
        "location": geojson_point(30.40, -97.70),
    })
    store.upsert("meeting_points", "order_id", "MANUAL", {
        "order_id": "MANUAL",
        "name": "Private porch",
        "kind": "manual",
        "source": "manual",
        "location": geojson_point(30.2675, -97.7432),
    })
    service = MeetingService(store)
    places = service.nearby_public_points(30.2672, -97.7431, 500)
    assert [place["name"] for place in places] == ["Congress Coffee"]
    assert places[0]["source"] == "mongodb"
    assert places[0]["location"]["coordinates"][0] == -97.7434
    assert service.nearby_public_points(0, 0, 100) == []


def test_mongodb_index_plan_uses_sphere_indexes_on_geojson_points():
    fields = {collection: keys for collection, keys in INDEXES}
    assert fields["meeting_points"] == [("location", "2dsphere")]
    assert fields["delivery_orders"] == [("destination", "2dsphere")]
    sample = json.dumps(geojson_point(30.2672, -97.7431))
    assert sample.index("-97.7431") < sample.index("30.2672")


def test_dashboard_exposes_one_meeting_point_surface():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    dashboard = (root / "src" / "pages" / "dashboard.py").read_text(encoding="utf-8")
    meeting = (root / "src" / "pages" / "meeting.py").read_text(encoding="utf-8")
    assert dashboard.count("Can't find customer location?") == 1
    assert dashboard.count("render_meeting_point(") == 1
    assert 'icon=folium.Icon(color="blue"' in meeting
    assert 'icon=folium.Icon(color="red"' in meeting
    assert 'icon=folium.Icon(color="green"' in meeting
    assert "not live GPS" in meeting
    assert "no places will be invented" in meeting.lower() or "If this fails, no places will be invented" in meeting
