"""Guest-demo navigation without starting Streamlit."""

from src.pages.auth import render_auth
from src.pages.dashboard import render_dashboard
from src.pages.landing import render_landing
from src.session_nav import (
    ACCESS,
    DASHBOARD,
    DEMO_USER,
    LANDING,
    continue_as_demo,
    ensure_nav,
    go_home,
    logout,
    open_demo_access,
    resolve_view,
)


def test_views_are_importable():
    assert callable(render_landing)
    assert callable(render_auth)
    assert callable(render_dashboard)


def test_fresh_session_opens_on_the_landing_page():
    state = {}
    ensure_nav(state)
    assert resolve_view(state) == LANDING
    assert state["demo_authenticated"] is False


def test_launch_demo_opens_the_access_screen_before_the_dashboard():
    state = {}
    open_demo_access(state)
    assert resolve_view(state) == ACCESS
    assert state["demo_authenticated"] is False


def test_continue_as_demo_user_opens_the_dashboard_and_records_the_profile():
    state = {}
    continue_as_demo(state)
    assert resolve_view(state) == DASHBOARD
    assert state["demo_authenticated"] is True
    assert state["demo_user"]["name"] == DEMO_USER["name"]
    assert state["demo_user"]["role"] == "Delivery Operations Operator"
    assert state["demo_user"]["access"] == "Full Demo Dashboard"
    assert state["demo_user"]["authentication"] == "Guest Demo Access"


def test_dashboard_without_demo_access_returns_to_the_access_screen():
    state = {"view": DASHBOARD, "demo_authenticated": False}
    assert resolve_view(state) == ACCESS


def test_ordinary_keys_survive_navigation_and_logout():
    state = {"last_records": ["frame"], "audit_marker": "kept"}
    continue_as_demo(state)
    go_home(state)
    assert resolve_view(state) == LANDING
    assert state["demo_authenticated"] is True
    assert state["last_records"] == ["frame"]
    logout(state)
    assert resolve_view(state) == LANDING
    assert state["demo_authenticated"] is False
    assert state["demo_user"] is None
    assert state["last_records"] == ["frame"]
    assert state["audit_marker"] == "kept"


def test_rerun_keeps_an_authenticated_dashboard_session():
    state = {}
    continue_as_demo(state)
    ensure_nav(state)
    assert resolve_view(state) == DASHBOARD
    assert state["demo_authenticated"] is True
