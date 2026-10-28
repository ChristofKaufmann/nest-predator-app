"""Ending the program from the UI: the page says so, then the server stops (and with it a Docker container)."""

import os
import signal
import threading

import streamlit as st

# Replaces the whole page, because once the server is gone the browser would otherwise show Streamlit's connection
# error, which looks like a crash.
_ended_page = st.components.v2.component("ended_page", js="""
export default function ({ data }) {
  const style = document.createElement("style");
  style.textContent = `
    body { margin: 0 !important; min-height: 100vh; display: grid !important; place-items: center;
           font-family: system-ui, -apple-system, "Segoe UI", sans-serif !important;
           background: #ffffff !important; color: #31333f !important; }
    @media (prefers-color-scheme: dark) { body { background: #0e1117 !important; color: #fafafa !important; } }
    body > :not(main) { display: none !important; }  /* e.g. Streamlit's connection error dialog */
    main { max-width: 32rem; padding: 1rem; text-align: center; }
    p { opacity: 0.8; }`;
  const heading = Object.assign(document.createElement("h1"), { textContent: data.title });
  const text = Object.assign(document.createElement("p"), { textContent: data.text });
  const main = document.createElement("main");
  main.append(heading, text);
  document.title = data.title;
  document.head.append(style);
  document.body.replaceChildren(main);
}
""")


def end_program(title: str, text: str) -> None:
    """Show the final page instead of the app and stop the server shortly after, once the page has been sent."""
    _ended_page(data={"title": title, "text": text})
    threading.Timer(1.0, os.kill, (os.getpid(), signal.SIGTERM)).start()
    st.stop()
