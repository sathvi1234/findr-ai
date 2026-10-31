"""Guest-demo navigation. Operates on a mapping so tests do not start Streamlit."""

from typing import Any, Mapping, MutableMapping

LANDING = "landing"
ACCESS = "access"
DASHBOARD = "dashboard"

DEMO_USER = {
    "name": "Demo User",
    "role": "Delivery Operations Operator",
    "access": "Full Demo Dashboard",
    "authentication": "Guest Demo Access",
}


def ensure_nav(state: MutableMapping[str, Any]) -> None:
    """Keep a view and a demo flag across ordinary Streamlit reruns."""
    if "view" not in state:
        state["view"] = LANDING
    if "demo_authenticated" not in state:
        state["demo_authenticated"] = False


def go_home(state: MutableMapping[str, Any]) -> None:
    """Return to the landing page without clearing the mission or the audit log."""
    ensure_nav(state)
    state["view"] = LANDING


def open_demo_access(state: MutableMapping[str, Any]) -> None:
    """Show the guest access card before mission control."""
    ensure_nav(state)
    state["view"] = ACCESS


def continue_as_demo(state: MutableMapping[str, Any]) -> None:
    """Enter mission control as the guest operator."""
    ensure_nav(state)
    state["demo_authenticated"] = True
    state["demo_user"] = dict(DEMO_USER)
    state["view"] = DASHBOARD


def logout(state: MutableMapping[str, Any]) -> None:
    """End the guest session and return to the landing page."""
    ensure_nav(state)
    state["demo_authenticated"] = False
    state["demo_user"] = None
    state["view"] = LANDING


def resolve_view(state: Mapping[str, Any]) -> str:
    """Hide mission control until the guest has continued from the access card."""
    view = state.get("view", LANDING)
    if view == DASHBOARD and not state.get("demo_authenticated"):
        return ACCESS
    if view not in (LANDING, ACCESS, DASHBOARD):
        return LANDING
    return view
