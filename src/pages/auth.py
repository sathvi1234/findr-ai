"""Guest access card. Demonstration only — no password and no identity provider."""

import streamlit as st

from src.session_nav import DEMO_USER, continue_as_demo, go_home


def render_auth() -> None:
    st.markdown(
        """
        <style>
            section[data-testid="stSidebar"] { display: none; }
            [data-testid="stAppViewContainer"] {
                background:
                    radial-gradient(900px 420px at 80% -10%, rgba(56, 189, 248, 0.16), transparent 60%),
                    radial-gradient(700px 380px at 0% 100%, rgba(124, 58, 237, 0.18), transparent 55%),
                    #070b14;
                color: #e2e8f0;
            }
            .auth-kicker {
                letter-spacing: 0.18em;
                text-transform: uppercase;
                color: #67e8f9;
                font-size: 0.78rem;
                margin-bottom: 0.4rem;
            }
            .auth-card {
                border: 1px solid rgba(103, 232, 249, 0.35);
                border-radius: 18px;
                padding: 28px 28px 8px;
                background: linear-gradient(180deg, rgba(15, 23, 42, 0.92), rgba(7, 11, 20, 0.92));
                box-shadow: 0 0 40px rgba(34, 211, 238, 0.08);
            }
            .auth-card h1 { margin: 0 0 8px; font-size: 2rem; }
            .auth-row { display: flex; justify-content: space-between; gap: 16px; padding: 10px 0; border-bottom: 1px solid rgba(148, 163, 184, 0.18); }
            .auth-row span { color: #94a3b8; }
            .auth-note { color: #94a3b8; margin-top: 16px; }
            [data-testid="stBaseButton-primary"] {
                background: linear-gradient(90deg, #0369a1, #22d3ee) !important;
                border: 1px solid rgba(103, 232, 249, 0.7) !important;
                color: #041018 !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )
    _, center, _ = st.columns([1, 1.3, 1])
    with center:
        rows = "".join(
            f"<div class='auth-row'><span>{label}</span><b>{value}</b></div>"
            for label, value in (
                ("Name", DEMO_USER["name"]),
                ("Role", DEMO_USER["role"]),
                ("Access", DEMO_USER["access"]),
                ("Authentication", DEMO_USER["authentication"]),
            )
        )
        st.markdown(
            f"""
            <div class="auth-card">
                <div class="auth-kicker">Guest demo access</div>
                <h1>Continue as Demo User</h1>
                <p>This card opens the delivery operations dashboard. No email, password, OTP, or external account is used.</p>
                {rows}
                <p class="auth-note">The session stays on this browser tab until you log out. It is a hackathon demonstration, not a production identity system.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Continue as Demo User", type="primary", width="stretch", key="continue_demo"):
            continue_as_demo(st.session_state)
            st.rerun()
        if st.button("Back to home", width="stretch", key="auth_home"):
            go_home(st.session_state)
            st.rerun()
