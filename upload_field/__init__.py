"""Drag & drop field that sends images one by one to the upload route (see upload.js and analysis.upload)."""

from pathlib import Path

import streamlit as st

_DIR = Path(__file__).parent
_component = st.components.v2.component(
    "image_upload",
    html=(_DIR / "upload.html").read_text(encoding="utf-8"),
    css=(_DIR / "upload.css").read_text(encoding="utf-8"),
    js=(_DIR / "upload.js").read_text(encoding="utf-8"),
)


def upload_field(api_url: str, texts: dict, key: str = "upload_field") -> bool:
    """Show the upload field for the session's API (see analysis.API_ROUTE) with the given texts (see i18n.TEXTS) and
    return whether an upload is running."""
    result = _component(key=key, data={"api": api_url, "texts": texts}, default={"uploading": False},
                        on_uploading_change=lambda: None)
    return bool(result.uploading)
