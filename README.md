# Order Tracker

A small order tracking app for the AI Dev Tools Zoomcamp observability homework. It includes a web page, API, tests, and a Docker Compose setup. You add telemetry, alerts, and an incident responder in Homework 4.

The main user flow is creating an order and checking its status. Three sample orders are created on first startup.

## Run it

You need Docker with Compose. To run the tests, you also need Python 3.11+ and `uv`.

```bash
docker compose up --build -d --wait
```

Open <http://127.0.0.1:8000>. The API is at `/api/orders`, and the health check is at `/healthz`. Data is stored in a Docker volume and survives container recreation.

If port 8000 is occupied, set `ORDER_TRACKER_PORT`, for example:

```bash
ORDER_TRACKER_PORT=18080 docker compose up --build -d --wait
```

Run tests with `uv run --frozen pytest -q`. Stop the app with `docker compose down`. Add `-v` only if you also want to delete the order data.

## Observability

The app exports traces, metrics, and logs via OpenTelemetry. Traces and logs print to the console (`docker compose logs app`); metrics are also exposed at `/metrics` for Prometheus to scrape.

Prometheus is at <http://127.0.0.1:9090>, and Grafana is at <http://127.0.0.1:3000> (anonymous access, no login needed) with a provisioned "Order Tracker" dashboard showing request counts by route and HTTP status code.

A Grafana alert rule fires when any endpoint returns a 5xx response in the last 5 minutes (it stays "Normal" during quiet periods instead of going to "no data"). It routes to the `incident-responder` service below.

## Incident responder

`incident-response/` is a small FastAPI service that receives Grafana's alert webhook at `POST :8001/alerts`. For each firing alert it:

1. Saves the alert payload, plus the logs and trace spans from the affected time window, to `incident-response/incidents/<timestamp>_<endpoint>/`.
2. Launches Claude Code in headless mode (`claude -p ...`) in that directory to investigate and write `REPORT.md`.

The app writes its console-exported logs/traces a second time to a shared file (`incident-response/telemetry/otel.log`) so the responder can read them without needing Docker socket access.

**Before starting it**, put your Anthropic API key in a `.env` file at the repo root (already gitignored):

```
ANTHROPIC_API_KEY=sk-ant-...
```

**Security note:** this service has no auth on `/alerts` and invokes Claude Code with `--dangerously-skip-permissions` (needed since it's unattended and non-interactive), using untrusted alert text in the prompt. That's acceptable for this local homework setup but would need a shared-secret check on the webhook and a narrower permission scope before running anywhere reachable by untrusted traffic.

To try it, build and start everything (this pulls Node and installs `@anthropic-ai/claude-code` in the image, so it takes longer than the other services):

```bash
docker compose up --build -d --wait
```

Then trigger a real 500 and watch a new folder appear under `incident-response/incidents/`:

```bash
curl http://localhost:8000/api/orders/express-1002   # hits a real bug: the estimated-delivery date calculation
                                                      # overflows the month for some seed dates and raises unhandled
tail -f incident-response/incidents/*/assistant.log
```

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | Web page |
| GET | `/healthz` | Database health check |
| GET | `/api/orders` | List orders |
| POST | `/api/orders` | Create an order |
| GET | `/api/orders/{id}` | Check an order |
| PATCH | `/api/orders/{id}` | Change an order status |

The app uses SQLite to keep setup small. Run one app container at a time. The course exercise is about detecting and handling an incident, not scaling the database.
