"""Request, confirm, and hand over a parcel at a public meeting point."""

import hashlib
import secrets
import time
from typing import Optional

from src.meeting.geo import approximate_for_customer, eta_minutes, geojson_point
from src.meeting.overpass import PublicPlace
from src.models import AnomalyType
from src.simulator import haversine_distance, initial_bearing_deg

HIGH_RISK = {
    AnomalyType.TELEPORTATION_JUMP,
    AnomalyType.INSIDIOUS_DRIFT,
    AnomalyType.RF_POWER_SURGE,
    AnomalyType.CONSTELLATION_FREEZE,
    AnomalyType.FALSE_DELIVERY_ARRIVAL,
}


def issue_otp(order_id: str) -> tuple:
    code = f"{secrets.randbelow(1_000_000):06d}"
    digest = hashlib.sha256(f"{order_id}:{code}".encode("utf-8")).hexdigest()
    return code, digest


def otp_matches(order_id: str, code: str, digest: str) -> bool:
    check = hashlib.sha256(f"{order_id}:{code.strip()}".encode("utf-8")).hexdigest()
    return secrets.compare_digest(check, digest)


def place_document(place: PublicPlace) -> dict:
    return {
        "name": place.name,
        "address": place.address,
        "kind": place.kind,
        "osm_id": place.osm_id,
        "distance_m": round(place.distance_m, 1),
        "location": geojson_point(place.latitude, place.longitude),
        "source": "openstreetmap",
    }


def manual_place_document(name: str, latitude: float, longitude: float, origin_lat: float, origin_lon: float) -> dict:
    return {
        "name": name.strip() or "Manual meeting point",
        "address": "Entered by the delivery partner. Not an OpenStreetMap suggestion.",
        "kind": "manual",
        "osm_id": None,
        "distance_m": round(haversine_distance(origin_lat, origin_lon, latitude, longitude), 1),
        "location": geojson_point(latitude, longitude),
        "source": "manual",
    }


class MeetingService:
    def __init__(self, store) -> None:
        self.store = store

    def _audit(self, order_id: str, event: str, detail: dict) -> None:
        self.store.append("audit_logs", {
            "order_id": order_id,
            "event": event,
            "detail": detail,
            "created_at": time.time(),
        })

    def request_meeting(
        self,
        order_id: str,
        agent_id: str,
        vehicle_type: str,
        partner_lat: float,
        partner_lon: float,
        position_source: str,
        accuracy_m: Optional[float],
        destination_name: str,
        destination_lat: float,
        destination_lon: float,
        places: list,
        search_ok: bool,
        search_error: str,
    ) -> dict:
        now = time.time()
        self.store.upsert("delivery_orders", "order_id", order_id, {
            "order_id": order_id,
            "agent_id": agent_id,
            "destination_name": destination_name,
            "destination": geojson_point(destination_lat, destination_lon),
            "status": "MEETING_REQUESTED",
            "updated_at": now,
        })
        self.store.upsert("delivery_agents", "agent_id", agent_id, {
            "agent_id": agent_id,
            "vehicle_type": vehicle_type,
            "last_location": geojson_point(partner_lat, partner_lon),
            "position_source": position_source,
            "accuracy_m": accuracy_m,
            "updated_at": now,
        })
        self.store.append("telemetry_frames", {
            "order_id": order_id,
            "agent_id": agent_id,
            "location": geojson_point(partner_lat, partner_lon),
            "position_source": position_source,
            "accuracy_m": accuracy_m,
            "created_at": now,
        })
        suggestions = [place_document(place) if isinstance(place, PublicPlace) else place for place in places]
        request = {
            "order_id": order_id,
            "agent_id": agent_id,
            "status": "REQUESTED",
            "partner_location": geojson_point(partner_lat, partner_lon),
            "position_source": position_source,
            "accuracy_m": accuracy_m,
            "destination": geojson_point(destination_lat, destination_lon),
            "suggestions": suggestions,
            "search_ok": search_ok,
            "search_error": search_error,
            "selected": None,
            "customer_confirmed": False,
            "otp_sha256": None,
            "share_partner_location": False,
            "updated_at": now,
        }
        self.store.upsert("meeting_point_requests", "order_id", order_id, request)
        self._audit(order_id, "meeting_requested", {
            "suggestion_count": len(suggestions),
            "search_ok": search_ok,
            "position_source": position_source,
        })
        return request

    def customer_choice(self, order_id: str, place: Optional[dict], decision: str, share_location: bool) -> dict:
        request = self.store.find_one("meeting_point_requests", "order_id", order_id)
        if request is None:
            raise ValueError("No meeting request exists for this order.")
        if decision == "reject":
            request["status"] = "REJECTED"
            request["selected"] = None
            request["customer_confirmed"] = False
            request["otp_sha256"] = None
            request["share_partner_location"] = False
            self._audit(order_id, "meeting_rejected", {})
        elif decision == "confirm" and place is not None:
            code, digest = issue_otp(order_id)
            request["status"] = "CONFIRMED"
            request["selected"] = place
            request["customer_confirmed"] = True
            request["otp_sha256"] = digest
            request["share_partner_location"] = share_location
            request["_otp_once"] = code
            point = {
                "order_id": order_id,
                "name": place["name"],
                "address": place["address"],
                "kind": place.get("kind"),
                "source": place.get("source") or "openstreetmap",
                "location": place["location"],
                "confirmed": True,
                "status": "CONFIRMED",
                "updated_at": time.time(),
            }
            self.store.upsert("meeting_points", "order_id", order_id, point)
            self._audit(order_id, "meeting_confirmed", {"name": place["name"]})
        else:
            raise ValueError("Confirm a listed or manual point, or reject the suggestion.")
        request["updated_at"] = time.time()
        one_time = request.pop("_otp_once", None)
        self.store.upsert("meeting_point_requests", "order_id", order_id, request)
        if one_time:
            request = dict(request)
            request["otp_preview_for_customer"] = one_time
        return request

    def nearby_public_points(self, latitude: float, longitude: float, radius_m: float) -> list:
        """Saved public points from the 2dsphere index. Manual points and an empty radius stay empty."""
        rows = self.store.near("meeting_points", "location", latitude, longitude, radius_m)
        places = []
        seen = set()
        for row in rows:
            if row.get("source") != "openstreetmap" or row.get("kind") == "manual":
                continue
            location = row.get("location") or {}
            coordinates = location.get("coordinates")
            if not coordinates or not row.get("name"):
                continue
            identity = (row["name"], round(float(coordinates[0]), 5), round(float(coordinates[1]), 5))
            if identity in seen:
                continue
            seen.add(identity)
            places.append({
                "name": row["name"],
                "address": row.get("address") or "Saved public meeting point",
                "kind": row.get("kind") or "public",
                "osm_id": row.get("osm_id"),
                "distance_m": row.get("distance_m", 0),
                "location": location,
                "source": "mongodb",
            })
        return places

    def customer_view(self, order_id: str) -> Optional[dict]:
        request = self.store.find_one("meeting_point_requests", "order_id", order_id)
        if request is None:
            return None
        view = dict(request)
        if request.get("share_partner_location") and request.get("partner_location"):
            lon, lat = request["partner_location"]["coordinates"]
            approx_lat, approx_lon = approximate_for_customer(lat, lon)
            selected = request.get("selected") or {}
            target = selected.get("location", {}).get("coordinates")
            distance = None
            if target:
                distance = haversine_distance(lat, lon, target[1], target[0])
            view["partner_approximate"] = {
                "latitude": approx_lat,
                "longitude": approx_lon,
                "eta_minutes": None if distance is None else round(eta_minutes(distance), 1),
                "note": "Approximate location shared with customer consent. Not a live tracking feed.",
            }
        else:
            view["partner_approximate"] = None
        return view

    def attempt_handover(
        self,
        order_id: str,
        agent_id: str,
        otp: str,
        reported_lat: float,
        reported_lon: float,
        reference_lat: float,
        reference_lon: float,
        frame_anomaly: AnomalyType,
        operator_authorized: bool,
    ) -> dict:
        request = self.store.find_one("meeting_point_requests", "order_id", order_id)
        if request is None or not request.get("customer_confirmed") or not request.get("selected"):
            return self._blocked(order_id, "The customer has not confirmed a meeting point.")
        if request.get("agent_id") != agent_id:
            return self._blocked(order_id, "This order is assigned to a different delivery agent.")
        if not otp_matches(order_id, otp, request.get("otp_sha256") or ""):
            self._audit(order_id, "handover_otp_rejected", {"submitted_length": len(otp or "")})
            return self._blocked(order_id, "The order OTP does not match.")
        jump_m = haversine_distance(reference_lat, reference_lon, reported_lat, reported_lon)
        high_risk = frame_anomaly in HIGH_RISK or jump_m > 150.0
        if high_risk and not operator_authorized:
            self._audit(order_id, "handover_blocked_risk", {"jump_m": round(jump_m, 1), "anomaly": frame_anomaly.value})
            return self._blocked(
                order_id,
                "Location consistency failed. A high-risk GPS reading needs operator authorization before handover.",
            )
        meeting = request["selected"]["location"]["coordinates"]
        distance_to_meeting = haversine_distance(reported_lat, reported_lon, meeting[1], meeting[0])
        record = {
            "order_id": order_id,
            "agent_id": agent_id,
            "meeting_point": request["selected"],
            "handed_over_at": time.time(),
            "reported_location": geojson_point(reported_lat, reported_lon),
            "reference_jump_m": round(jump_m, 1),
            "distance_to_meeting_m": round(distance_to_meeting, 1),
            "frame_anomaly": frame_anomaly.value,
            "operator_authorized": operator_authorized,
            "delivered_because_near_destination": False,
        }
        self.store.append("handover_records", record)
        request["status"] = "HANDED_OVER"
        request["otp_preview_for_customer"] = None
        self.store.upsert("meeting_point_requests", "order_id", order_id, request)
        order = self.store.find_one("delivery_orders", "order_id", order_id) or {"order_id": order_id}
        order["status"] = "HANDED_OVER_AT_MEETING_POINT"
        order["updated_at"] = record["handed_over_at"]
        self.store.upsert("delivery_orders", "order_id", order_id, order)
        self._audit(order_id, "handover_recorded", {
            "agent_id": agent_id,
            "meeting": request["selected"]["name"],
        })
        record["ok"] = True
        record["message"] = "Handover recorded at the confirmed meeting point."
        return record

    def navigation(self, order_id: str) -> Optional[dict]:
        request = self.store.find_one("meeting_point_requests", "order_id", order_id)
        if not request or not request.get("selected"):
            return None
        partner = request["partner_location"]["coordinates"]
        meeting = request["selected"]["location"]["coordinates"]
        distance_m = haversine_distance(partner[1], partner[0], meeting[1], meeting[0])
        bearing = initial_bearing_deg(partner[1], partner[0], meeting[1], meeting[0])
        return {
            "distance_m": round(distance_m, 1),
            "bearing_deg": round(bearing, 0),
            "instruction": f"Head {bearing:.0f}° for {distance_m:.0f} m to {request['selected']['name']}.",
        }

    def _blocked(self, order_id: str, message: str) -> dict:
        return {"ok": False, "order_id": order_id, "message": message}
