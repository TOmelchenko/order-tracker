import json
from datetime import datetime, timezone
from pathlib import Path


def extract_json_objects(text: str) -> list[dict]:
    """Pull consecutive pretty-printed JSON objects out of a text stream.

    The OTel console exporters print each span/log record as its own
    `json.dumps(..., indent=...)` call with no delimiter between records, so this
    walks the text looking for '{' and lets json's own decoder find where each
    object ends (it handles the internal newlines/nesting on its own).
    """
    decoder = json.JSONDecoder()
    objects = []
    idx, length = 0, len(text)
    while idx < length:
        while idx < length and text[idx] in " \t\r\n":
            idx += 1
        if idx >= length:
            break
        if text[idx] != "{":
            newline = text.find("\n", idx)
            idx = newline + 1 if newline != -1 else length
            continue
        try:
            obj, end = decoder.raw_decode(text, idx)
            objects.append(obj)
            idx = end
        except json.JSONDecodeError:
            newline = text.find("\n", idx)
            idx = newline + 1 if newline != -1 else length
    return objects


def _parse_timestamp(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def read_signals(telemetry_log_path: Path, since: datetime, until: datetime):
    """Read the shared telemetry file and split it into logs and traces within a window."""
    if not telemetry_log_path.exists():
        return [], []

    text = telemetry_log_path.read_text(errors="replace")
    logs, traces = [], []
    for obj in extract_json_objects(text):
        if "severity_number" in obj:
            ts = _parse_timestamp(obj.get("timestamp"))
            if ts is None or since <= ts <= until:
                logs.append(obj)
        elif "context" in obj and isinstance(obj.get("context"), dict) and "trace_id" in obj["context"]:
            ts = _parse_timestamp(obj.get("start_time"))
            if ts is None or since <= ts <= until:
                traces.append(obj)
    return logs, traces
