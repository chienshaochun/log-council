"""Exercise the committed Streamlit entrypoint using deployment dependencies."""

import os
from pathlib import Path

from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INCIDENT = (
    '{"id":"E1","ts":"2026-09-01T10:00:00Z","level":"ERROR",'
    '"service":"cartservice","message":"OverflowException converting Int32"}\n'
    '{"id":"E2","ts":"2026-09-01T10:00:01Z","level":"ERROR",'
    '"service":"frontend","message":"request error"}'
)
EXPECTED_TABS = ["Overview", "Evidence", "Agents", "Handoffs", "Data quality"]


def _fail_on_render_error(app: AppTest) -> None:
    if app.exception:
        messages = "; ".join(str(item.value) for item in app.exception)
        raise RuntimeError(f"Streamlit app failed: {messages}")
    if app.error:
        messages = "; ".join(str(item.value) for item in app.error)
        raise RuntimeError(f"Streamlit app rendered an error: {messages}")


def main() -> None:
    os.chdir(PROJECT_ROOT)
    app = AppTest.from_file(PROJECT_ROOT / "app.py", default_timeout=30).run()
    _fail_on_render_error(app)
    if not app.title or app.title[0].value != "LogCouncil":
        raise RuntimeError("Streamlit entrypoint did not render the LogCouncil title")

    app.text_area[0].set_value(INCIDENT)
    app.button[0].click()
    app.run()
    _fail_on_render_error(app)

    tabs = [item.label for item in app.tabs]
    if tabs != EXPECTED_TABS:
        raise RuntimeError(f"Expected tabs {EXPECTED_TABS!r}, received {tabs!r}")
    if len(app.metric) != 4:
        raise RuntimeError(f"Expected 4 summary metrics, received {len(app.metric)}")
    if len(app.get("download_button")) != 1:
        raise RuntimeError("Safe JSON download button did not render")
    if "analysis_payload" not in app.session_state:
        raise RuntimeError("Analysis result was not stored in Streamlit session state")

    print("deployment smoke test: LogCouncil analysis flow passed")


if __name__ == "__main__":
    main()
