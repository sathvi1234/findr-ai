"""Meeting-point persistence. MongoDB when it answers, otherwise an in-memory store."""

from typing import Any, Dict, List, Optional

from src.simulator import haversine_distance

INDEXES = (
    ("delivery_orders", [("destination", "2dsphere")]),
    ("delivery_agents", [("last_location", "2dsphere")]),
    ("meeting_points", [("location", "2dsphere")]),
    ("telemetry_frames", [("location", "2dsphere")]),
)

COLLECTIONS = (
    "delivery_orders",
    "delivery_agents",
    "meeting_point_requests",
    "meeting_points",
    "telemetry_frames",
    "handover_records",
    "audit_logs",
)


class MemoryMeetingStore:
    """Same documents as MongoDB, kept in process memory for tests and an offline demo."""

    def __init__(self) -> None:
        self.documents: Dict[str, List[dict]] = {name: [] for name in COLLECTIONS}
        self.indexes = list(INDEXES)

    def ensure_indexes(self) -> None:
        return None

    def upsert(self, collection: str, key: str, key_value: str, document: dict) -> dict:
        rows = self.documents[collection]
        for index, row in enumerate(rows):
            if row.get(key) == key_value:
                rows[index] = document
                return document
        rows.append(document)
        return document

    def find_one(self, collection: str, key: str, key_value: str) -> Optional[dict]:
        for row in self.documents[collection]:
            if row.get(key) == key_value:
                return row
        return None

    def append(self, collection: str, document: dict) -> dict:
        self.documents[collection].append(document)
        return document

    def near(
        self,
        collection: str,
        field: str,
        latitude: float,
        longitude: float,
        max_distance_m: float,
        limit: int = 20,
    ) -> List[dict]:
        """Points inside the radius. Distance is metres. An empty collection returns no places."""
        found: List[dict] = []
        for row in self.documents[collection]:
            coordinates = (row.get(field) or {}).get("coordinates")
            if not coordinates or len(coordinates) < 2:
                continue
            point_lon, point_lat = float(coordinates[0]), float(coordinates[1])
            distance_m = haversine_distance(latitude, longitude, point_lat, point_lon)
            if distance_m <= max_distance_m:
                copy = dict(row)
                copy["distance_m"] = round(distance_m, 1)
                found.append(copy)
        found.sort(key=lambda item: item["distance_m"])
        return found[:limit]


class MongoMeetingStore:
    """GeoJSON documents and 2dsphere indexes on the location fields."""

    def __init__(self, database: Any) -> None:
        self.database = database

    def ensure_indexes(self) -> None:
        for collection, keys in INDEXES:
            self.database[collection].create_index(keys)
        self.database["meeting_point_requests"].create_index("order_id", unique=True)
        self.database["handover_records"].create_index("order_id")
        self.database["audit_logs"].create_index([("order_id", 1), ("created_at", 1)])

    def upsert(self, collection: str, key: str, key_value: str, document: dict) -> dict:
        self.database[collection].replace_one({key: key_value}, document, upsert=True)
        return document

    def find_one(self, collection: str, key: str, key_value: str) -> Optional[dict]:
        return self.database[collection].find_one({key: key_value}, {"_id": 0})

    def append(self, collection: str, document: dict) -> dict:
        self.database[collection].insert_one(dict(document))
        return document

    def near(
        self,
        collection: str,
        field: str,
        latitude: float,
        longitude: float,
        max_distance_m: float,
        limit: int = 20,
    ) -> List[dict]:
        """2dsphere $near query. Longitude is stored before latitude. No documents means no places."""
        point = {"type": "Point", "coordinates": [float(longitude), float(latitude)]}
        cursor = self.database[collection].find(
            {field: {"$near": {"$geometry": point, "$maxDistance": float(max_distance_m)}}},
            {"_id": 0},
        ).limit(limit)
        found = []
        for row in cursor:
            coordinates = (row.get(field) or {}).get("coordinates") or [None, None]
            if coordinates[0] is None:
                continue
            distance_m = haversine_distance(latitude, longitude, float(coordinates[1]), float(coordinates[0]))
            row["distance_m"] = round(distance_m, 1)
            found.append(row)
        return found


def open_meeting_store(uri: Optional[str] = None):
    """Connect with MONGODB_URI. Fall back to memory when Atlas is unset or does not answer."""
    from src.persistence.env import mongodb_settings
    from src.persistence.store import selection_timeout_ms

    configured, database_name = mongodb_settings()
    chosen = uri if uri is not None else configured
    if not chosen or chosen == "memory":
        return MemoryMeetingStore(), "memory"
    try:
        from pymongo import MongoClient

        client = MongoClient(chosen, serverSelectionTimeoutMS=selection_timeout_ms(chosen))
        client.admin.command("ping")
        store = MongoMeetingStore(client[database_name])
        store.ensure_indexes()
        return store, "mongodb"
    except Exception:
        return MemoryMeetingStore(), "memory"
