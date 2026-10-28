"""Entry point: the Streamlit app plus the route that receives uploaded images (start with `streamlit run server.py`)."""

from contextlib import asynccontextmanager

import streamlit as st

import analysis


@asynccontextmanager
async def lifespan(app: st.App):
    yield
    # uvicorn ends the process with the stop signal after shutting down, so Python's exit handlers don't run
    analysis.remove_previews()


app = st.App("app.py", routes=analysis.routes, lifespan=lifespan)
