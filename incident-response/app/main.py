import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request

from app.telemetry_reader import read_signals

TELEMETRY_LOG_PATH = Path(os.getenv("OTEL_FILE_LOG_PATH", "/telemetry/otel.log"))
INCIDENTS_DIR = Path(os.getenv("INCIDENTS_DIR", "/incidents"))
LOOKBACK_SECONDS = int(os.getenv("INCIDENT_LOOKBACK_SECONDS", "600"))
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://localhost:3000/d/order-tracker-requests/order-tracker")
CLAUDE_COMMAND = os.getenv("CLAUDE_COMMAND", "claude")
SOURCE_DIR = os.getenv("ORDER_TRACKER_SOURCE_DIR", "/workspace")

app = FastAPI(title="Incident Responder")


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.post("/alerts")
async def receive_alert(request: Request):
    payload = await request.json()
    alerts = payload.get("alerts") or [payload]
    incidents = [handle_alert(alert) for alert in alerts]
    return {"received": len(incidents), "incidents": incidents}


def _parse_starts_at(value: str | None) -> datetime:
    if value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _slug(value: str) -> str:
    return value.strip("/").replace("/", "_").replace("{", "").replace("}", "") or "root"


def handle_alert(alert: dict) -> dict:
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})
    status = alert.get("status", "unknown")
    endpoint = labels.get("http_route", "unknown")

    starts_at = _parse_starts_at(alert.get("startsAt"))
    now = datetime.now(timezone.utc)
    since = starts_at - timedelta(seconds=LOOKBACK_SECONDS)

    logs, traces = read_signals(TELEMETRY_LOG_PATH, since, now)

    incident_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}_{_slug(endpoint)}"
    incident_dir = INCIDENTS_DIR / incident_id
    incident_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "incident_id": incident_id,
        "endpoint": endpoint,
        "alertname": labels.get("alertname", "unknown"),
        "status": status,
        "startsAt": alert.get("startsAt"),
        "window": {"since": since.isoformat(), "until": now.isoformat()},
        "summary": annotations.get("summary", ""),
        "description": annotations.get("description", ""),
        "dashboard": alert.get("dashboardURL") or DASHBOARD_URL,
        "log_count": len(logs),
        "trace_count": len(traces),
    }

    (incident_dir / "alert.json").write_text(json.dumps(alert, indent=2))
    (incident_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    (incident_dir / "logs.json").write_text(json.dumps(logs, indent=2))
    (incident_dir / "traces.json").write_text(json.dumps(traces, indent=2))

    if status == "firing":
        launch_assistant(incident_dir, summary)

    return summary


def launch_assistant(incident_dir: Path, summary: dict) -> None:
    prompt = (
        "A production alert fired for the order-tracker service.\n"
        f"Endpoint: {summary['endpoint']}\n"
        f"Alert: {summary['summary']}\n"
        f"Details: {summary['description']}\n"
        f"Dashboard: {summary['dashboard']}\n"
        f"Captured {summary['log_count']} log record(s) and {summary['trace_count']} trace span(s) "
        f"from {summary['window']['since']} to {summary['window']['until']}, saved alongside this "
        "prompt as logs.json, traces.json, and alert.json.\n"
        f"The order-tracker source code is mounted read-write at {SOURCE_DIR}/app.\n"
        "Investigate the root cause using the logs/traces, then fix the bug in that source directory. "
        "Write your findings and a summary of the fix to REPORT.md here."
    )
    (incident_dir / "prompt.txt").write_text(prompt)

    with open(incident_dir / "assistant.log", "wb") as assistant_log:
        subprocess.Popen(
            [CLAUDE_COMMAND, "-p", prompt, "--dangerously-skip-permissions", "--add-dir", SOURCE_DIR],
            cwd=str(incident_dir),
            stdout=assistant_log,
            stderr=subprocess.STDOUT,
        )
