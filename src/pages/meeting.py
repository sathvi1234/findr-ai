"""Partner and customer meeting-point panel. Synthetic fixes stay labeled as synthetic."""

import html

import folium
import streamlit as st
import streamlit.components.v1 as components
from streamlit_folium import st_folium

from src.meeting.geo import (
    eta_minutes,
    format_accuracy,
    format_latitude,
    format_longitude,
    osm_directions_url,
)
from src.meeting.overpass import search_public_places
from src.meeting.service import MeetingService, manual_place_document
from src.meeting.store import open_meeting_store
from src.models import AnomalyType
from src.simulator import haversine_distance


def _safe(value) -> str:
    return html.escape("" if value is None else str(value))


def _store() -> tuple:
    if "meeting_store" not in st.session_state:
        store, kind = open_meeting_store()
        st.session_state.meeting_store = store
        st.session_state.meeting_store_kind = kind
    return st.session_state.meeting_store, st.session_state.meeting_store_kind


def _capture_device_fix() -> None:
    params = st.query_params
    if "device_lat" not in params or "device_lon" not in params:
        return
    try:
        accuracy = float(params.get("device_acc")) if params.get("device_acc") else None
    except ValueError:
        accuracy = None
    st.session_state.device_fix = {
        "latitude": float(params["device_lat"]),
        "longitude": float(params["device_lon"]),
        "accuracy_m": accuracy,
        "updated_at": params.get("device_ts", ""),
        "source": "device",
    }


def _coords_block(latitude: float, longitude: float, source: str, accuracy, updated: str) -> None:
    st.markdown(
        f"**{format_latitude(latitude)}**  \n**{format_longitude(longitude)}**  \n"
        f"{format_accuracy(accuracy, source)}  \nLast GPS update: {_safe(updated) or 'not provided'}"
    )
    if source == "device":
        st.caption("This reading came from the browser geolocation permission. It is device GPS.")
    else:
        st.caption("These coordinates are the selected synthetic telemetry frame. They are not live GPS.")


def render_meeting_point(telemetry, integrity) -> None:
    """Partner request, customer confirmation, and OTP handover for the loaded order."""
    _capture_device_fix()
    store, kind = _store()
    service = MeetingService(store)
    order_id = telemetry.order_id
    if kind == "memory":
        st.warning(
            "MongoDB is not connected. Meeting records stay in this process only. "
            "Set MONGODB_URI to write the delivery_orders, meeting_points, and handover_records collections."
        )
    else:
        st.caption("Meeting records are in MongoDB database findr_ai, with 2dsphere indexes on GeoJSON points.")

    role = st.radio(
        "Demo role",
        ["Delivery partner", "Customer"],
        horizontal=True,
        key="meeting_role",
    )
    request = service.customer_view(order_id)
    destination = (telemetry.destination_coords[0], telemetry.destination_coords[1])

    if role == "Delivery partner":
        _partner(service, telemetry, integrity, request, destination)
    else:
        _customer(service, order_id, request, destination)


def _partner(service, telemetry, integrity, request, destination) -> None:
    st.subheader("Can't find the customer door?")
    st.caption(
        f"Order {telemetry.order_id}. Original destination: {telemetry.destination_name}. "
        "A nearby GPS reading does not mark this order delivered."
    )
    source = st.radio(
        "Position used for this request",
        ["Synthetic telemetry frame", "Device GPS"],
        key="meeting_position_source",
    )
    if source == "Device GPS":
        components.html(
            """
            <button id="gps" style="background:#3B82F6;color:white;border:0;border-radius:8px;padding:8px 12px;">
              Use device GPS
            </button>
            <p id="msg" style="color:#94A3B8;font-family:sans-serif;"></p>
            <script>
            document.getElementById("gps").onclick = function () {
              if (!navigator.geolocation) {
                document.getElementById("msg").textContent = "This browser has no geolocation.";
                return;
              }
              navigator.geolocation.getCurrentPosition(function (pos) {
                const url = new URL(window.parent.location.href);
                url.searchParams.set("device_lat", pos.coords.latitude);
                url.searchParams.set("device_lon", pos.coords.longitude);
                url.searchParams.set("device_acc", pos.coords.accuracy);
                url.searchParams.set("device_ts", new Date().toISOString());
                window.parent.location.href = url.toString();
              }, function (err) {
                document.getElementById("msg").textContent = err.message;
              }, {enableHighAccuracy: true, timeout: 10000});
            };
            </script>
            """,
            height=90,
        )
        fix = st.session_state.get("device_fix")
        if not fix:
            st.info("No device fix yet. Allow location, or use the synthetic frame.")
            partner = None
            position_source = "device"
            accuracy = None
            updated = ""
        else:
            partner = (fix["latitude"], fix["longitude"])
            position_source = "device"
            accuracy = fix["accuracy_m"]
            updated = str(fix["updated_at"])
            _coords_block(partner[0], partner[1], "device", accuracy, updated)
    else:
        partner = (telemetry.reported_gps.latitude, telemetry.reported_gps.longitude)
        position_source = "synthetic"
        accuracy = None
        updated = "selected telemetry frame"
        _coords_block(partner[0], partner[1], "synthetic", None, updated)

    radius = st.slider("Search radius (metres)", 100, 1500, 500, step=50, key="meeting_radius")
    if st.button("Search nearby public places", key="meeting_search"):
        if partner is None:
            st.error("Choose a position before searching.")
        else:
            with st.spinner("Asking OpenStreetMap and the saved meeting points. If both are empty, no places will be invented."):
                found = search_public_places(destination[0], destination[1], radius)
                saved = service.nearby_public_points(destination[0], destination[1], radius)
            st.session_state.meeting_search = {
                "ok": found.ok,
                "error": found.error,
                "places": [
                    {
                        "name": place.name,
                        "address": place.address,
                        "kind": place.kind,
                        "osm_id": place.osm_id,
                        "distance_m": round(place.distance_m, 1),
                        "location": {"type": "Point", "coordinates": [place.longitude, place.latitude]},
                        "source": "openstreetmap",
                    }
                    for place in found.places
                ],
                "saved": saved,
            }
    search = st.session_state.get("meeting_search")
    suggestions = []
    if request:
        st.caption(f"Meeting request status: {request.get('status', 'REQUESTED')}.")
    if search:
        saved = search.get("saved") or []
        if not search["ok"]:
            st.error(search["error"])
        if not search["places"] and not saved:
            st.info("No public places were returned in this radius. Enter a meeting point manually. None were invented.")
        else:
            suggestions = list(search["places"]) + list(saved)
            for place in suggestions:
                lon, lat = place["location"]["coordinates"]
                origin = "Saved in MongoDB" if place.get("source") == "mongodb" else "OpenStreetMap"
                st.markdown(
                    f"**{_safe(place['name'])}** · {_safe(place['kind'])} · {place['distance_m']:.0f} m from the destination · {origin}  \n"
                    f"{_safe(place['address'])} · {format_latitude(lat)} · {format_longitude(lon)}"
                )

    manual_name = st.text_input("Manual meeting point name", value="", key="meeting_manual_name")
    manual_lat = st.number_input("Manual latitude", value=float(destination[0]), format="%.6f", key="meeting_manual_lat")
    manual_lon = st.number_input("Manual longitude", value=float(destination[1]), format="%.6f", key="meeting_manual_lon")
    choice_labels = [place["name"] for place in suggestions] + ["Manual coordinates"]
    chosen_label = st.selectbox("Meeting point to request", choice_labels, key="meeting_choice")
    if st.button("Request meeting point", key="meeting_request", type="primary"):
        if partner is None:
            st.error("A partner position is required.")
        else:
            if chosen_label == "Manual coordinates":
                manual = manual_place_document(manual_name, manual_lat, manual_lon, destination[0], destination[1])
                manual["partner_requested"] = True
                send = [{**place, "partner_requested": False} for place in suggestions] + [manual]
            elif not suggestions:
                st.error("Search for public places, or enter manual coordinates.")
                send = []
            else:
                send = [{**place, "partner_requested": place["name"] == chosen_label} for place in suggestions]
            if send:
                service.request_meeting(
                    order_id=telemetry.order_id,
                    agent_id=telemetry.agent_id,
                    vehicle_type=telemetry.vehicle_type.value,
                    partner_lat=partner[0],
                    partner_lon=partner[1],
                    position_source=position_source,
                    accuracy_m=accuracy,
                    destination_name=telemetry.destination_name,
                    destination_lat=destination[0],
                    destination_lon=destination[1],
                    places=send,
                    search_ok=bool(search and search["ok"]),
                    search_error="" if not search else search["error"],
                )
                st.success("The customer can now confirm or reject this meeting point.")
                st.rerun()

    request = service.customer_view(telemetry.order_id)
    device_accuracy = accuracy if position_source == "device" else None
    _meeting_map(telemetry, partner, destination, request, suggestions, device_accuracy)
    reference_jump = None
    if partner is not None:
        reference_jump = haversine_distance(
            telemetry.inertial_truth.latitude,
            telemetry.inertial_truth.longitude,
            partner[0],
            partner[1],
        )
    if request and request.get("customer_confirmed") and request.get("selected"):
        nav = service.navigation(telemetry.order_id) or {}
        selected = request["selected"]
        lon, lat = selected["location"]["coordinates"]
        distance = nav.get("distance_m")
        instruction = nav.get("instruction", "")
        if partner is not None:
            distance = haversine_distance(partner[0], partner[1], lat, lon)
        eta = None if distance is None else round(eta_minutes(distance), 1)
        distance_line = (
            f"Distance: {distance:.0f} m · estimated travel time {eta} min · {instruction}"
            if distance is not None
            else instruction
        )
        st.markdown(
            f"**Confirmed meeting point:** {_safe(selected['name'])}  \n"
            f"{format_latitude(lat)} · {format_longitude(lon)}  \n"
            f"{distance_line}"
        )
        copy_text = f"{format_latitude(lat)}\n{format_longitude(lon)}"
        st.code(copy_text, language=None)
        if partner is not None:
            st.link_button(
                "Open directions",
                osm_directions_url(partner[0], partner[1], lat, lon),
            )
        otp = st.text_input("Order OTP from the customer", key="meeting_otp")
        authorized = False
        risky = integrity.primary_anomaly in {
            AnomalyType.TELEPORTATION_JUMP,
            AnomalyType.INSIDIOUS_DRIFT,
            AnomalyType.RF_POWER_SURGE,
            AnomalyType.CONSTELLATION_FREEZE,
            AnomalyType.FALSE_DELIVERY_ARRIVAL,
        } or (reference_jump is not None and reference_jump > 150.0)
        if risky:
            st.error("This frame is a high-risk GPS reading. Handover needs operator authorization.")
            authorized = st.checkbox("Operator authorizes this high-risk handover", key="meeting_auth")
        if st.button("Confirm parcel handover", key="meeting_handover"):
            result = service.attempt_handover(
                order_id=telemetry.order_id,
                agent_id=telemetry.agent_id,
                otp=otp,
                reported_lat=partner[0] if partner else telemetry.reported_gps.latitude,
                reported_lon=partner[1] if partner else telemetry.reported_gps.longitude,
                reference_lat=telemetry.inertial_truth.latitude,
                reference_lon=telemetry.inertial_truth.longitude,
                frame_anomaly=integrity.primary_anomaly,
                operator_authorized=authorized,
            )
            if result.get("ok"):
                st.success(result["message"])
            else:
                st.error(result["message"])


def _customer(service, order_id, request, destination) -> None:
    st.subheader("Customer meeting confirmation")
    if request is None:
        st.info("The delivery partner has not reported a problem finding this address.")
        return
    st.warning("The delivery partner cannot find the exact address and asked for a public meeting point.")
    if request.get("search_error"):
        st.caption(request["search_error"])
    suggestions = request.get("suggestions") or []
    if not suggestions:
        st.info("No suggested place was stored. Ask the partner to search again or enter a manual point.")
        return
    requested = next((place["name"] for place in suggestions if place.get("partner_requested")), None)
    if requested:
        st.caption(f"The delivery partner asked for {requested}. You can confirm that place or choose another suggestion.")
    labels = [place["name"] for place in suggestions]
    default_index = labels.index(requested) if requested in labels else 0
    picked = st.selectbox("Suggested meeting point", labels, index=default_index, key="customer_pick")
    share = st.checkbox(
        "Share an approximate partner location and an estimated arrival with me",
        value=bool(request.get("share_partner_location")),
        key="customer_share",
    )
    place = next(item for item in suggestions if item["name"] == picked)
    col1, col2 = st.columns(2)
    if col1.button("Confirm this meeting point", key="customer_confirm", type="primary"):
        confirmed = service.customer_choice(order_id, place, "confirm", share)
        st.session_state.customer_otp = confirmed.get("otp_preview_for_customer")
        st.rerun()
    if col2.button("Reject suggestions", key="customer_reject"):
        service.customer_choice(order_id, None, "reject", False)
        st.session_state.customer_otp = None
        st.rerun()
    if request.get("customer_confirmed"):
        code = st.session_state.get("customer_otp") or request.get("otp_preview_for_customer")
        st.success("Meeting point confirmed. Give this order OTP to the delivery partner in person.")
        if code:
            st.code(code, language=None)
        else:
            st.caption("The OTP was already used or cleared.")
    approx = request.get("partner_approximate")
    if approx:
        st.markdown(
            f"Approximate partner location: {format_latitude(approx['latitude'])}, "
            f"{format_longitude(approx['longitude'])}. "
            f"Estimated arrival: {approx['eta_minutes']} min. {approx['note']}"
        )
    elif request.get("status") == "REQUESTED":
        st.caption("The partner's location stays hidden until you consent and confirm a point.")


def _meeting_map(telemetry, partner, destination, request, suggestions, device_accuracy) -> None:
    center = partner or destination
    meeting_map = folium.Map(location=[center[0], center[1]], zoom_start=15, tiles="OpenStreetMap", control_scale=True)
    folium.Marker(
        location=[destination[0], destination[1]],
        tooltip="Original customer destination",
        icon=folium.Icon(color="red", icon="home", prefix="fa"),
    ).add_to(meeting_map)
    if partner is not None:
        folium.Marker(
            location=[partner[0], partner[1]],
            tooltip="Delivery partner reported position",
            icon=folium.Icon(color="blue", icon="user", prefix="fa"),
        ).add_to(meeting_map)
        if device_accuracy:
            folium.Circle(
                location=[partner[0], partner[1]],
                radius=float(device_accuracy),
                color="#3B82F6",
                fill=True,
                fill_opacity=0.15,
                tooltip="Reported device GPS uncertainty",
            ).add_to(meeting_map)
    for place in suggestions:
        lon, lat = place["location"]["coordinates"]
        folium.Marker(
            location=[lat, lon],
            tooltip=place["name"],
            icon=folium.Icon(color="cadetblue", icon="info-sign"),
        ).add_to(meeting_map)
    selected = (request or {}).get("selected") if request and request.get("customer_confirmed") else None
    if selected:
        lon, lat = selected["location"]["coordinates"]
        folium.Marker(
            location=[lat, lon],
            tooltip=f"Confirmed meeting point: {selected['name']}",
            icon=folium.Icon(color="green", icon="ok-sign"),
        ).add_to(meeting_map)
        if partner is not None:
            folium.PolyLine(
                [[partner[0], partner[1]], [lat, lon]],
                color="#22C55E",
                weight=4,
                tooltip="Partner to confirmed meeting point",
            ).add_to(meeting_map)
    partner_key = "none" if partner is None else f"{partner[0]:.5f},{partner[1]:.5f}"
    st_folium(
        meeting_map,
        width=1100,
        height=420,
        returned_objects=[],
        key=f"meeting-map-{telemetry.order_id}-{telemetry.sequence_id}-{partner_key}",
    )
