# Certstream Prototype

This is a minimal prototype around `certstream-server-go`.

The collector connects to one of the live WebSocket streams, writes raw events to JSONL, and exposes aggregate metrics for Prometheus. Grafana reads Prometheus and displays the dashboard.

## Data Flow

```text
certstream-server-go -> collector.js -> /metrics -> Prometheus -> Grafana
                         |
                         -> data/*.jsonl
```

Prometheus is for numeric time-series metrics. The raw CT events are stored separately as JSONL.

## 1. Start certstream-server-go

```bash
cd /Users/yihanliu/Desktop/seminar/certstream-server-go

docker run -d \
  --name certstream-server-go \
  -p 8080:8080 \
  0rickyy0/certstream-server-go:latest
```

Verify:

```bash
curl http://127.0.0.1:8080/domains-only/example.json
curl http://127.0.0.1:8080/example.json
curl http://127.0.0.1:8080/full-stream/example.json
```

## 2. Start the Collector

```bash
cd /Users/yihanliu/Desktop/seminar/prototype
node collector.js
```

The default mode is `domains-only`, which connects to `ws://127.0.0.1:8080/domains-only`.

Mode switch:

```bash
CERTSTREAM_MODE=domains-only node collector.js
CERTSTREAM_MODE=lite node collector.js
CERTSTREAM_MODE=full node collector.js
```

The modes map to `certstream-server-go` endpoints like this:

```text
domains-only -> /domains-only -> data/domains.jsonl
lite         -> /            -> data/lite.jsonl
full         -> /full-stream -> data/full-stream.jsonl
```

`CERTSTREAM_WS_URL` still works as an explicit override. If `CERTSTREAM_MODE` is not set, the collector tries to infer the mode from that URL.

Collector endpoints:

```text
http://127.0.0.1:9101/healthz
http://127.0.0.1:9101/metrics
```

The raw stream is written to the selected mode's JSONL file:

```text
data/domains.jsonl
data/lite.jsonl
data/full-stream.jsonl
```

Optional environment variables:

```bash
CERTSTREAM_MODE=domains-only
CERTSTREAM_BASE_URL=ws://127.0.0.1:8080
CERTSTREAM_WS_URL=ws://127.0.0.1:8080/domains-only
METRICS_HOST=0.0.0.0
METRICS_PORT=9101
OUTPUT_FILE=/tmp/domains.jsonl
MAX_MESSAGES=1000
```

Example bounded run:

```bash
MAX_MESSAGES=1000 node collector.js
```

## 3. Start Prometheus and Grafana

Keep the collector running, then in another terminal:

```bash
cd /Users/yihanliu/Desktop/seminar/prototype
docker compose -f docker-compose.monitoring.yml up -d
```

Open:

```text
Prometheus: http://127.0.0.1:9090
Grafana:    http://127.0.0.1:3000
```

Grafana login:

```text
admin / admin
```

The dashboard is provisioned under:

```text
Certstream / Certstream Prototype Overview
```

## 4. Stop the Programs

Stop the collector by pressing `Ctrl + C` in the terminal where it is running.

Stop `certstream-server-go`:

```bash
docker stop certstream-server-go
```

Start it again later:

```bash
docker start certstream-server-go
```

Stop Prometheus and Grafana:

```bash
docker compose -f docker-compose.monitoring.yml down
```

## What This Prototype Shows

- A working live connection to `certstream-server-go`.
- Raw live CT events collected in JSONL.
- Prometheus metrics for live monitoring.
- Grafana visualization of collector status, stream mode, domain counts, ingestion rate, wildcard domains, TLD distribution, and certificate metadata when using `lite` or `full`.

## Metrics Exposed

```text
ct_collector_up
ct_collector_mode_info{mode="...",endpoint="..."}
ct_collector_reconnects_total
ct_collector_messages_total
ct_collector_parse_errors_total
ct_collector_certificate_messages_total
ct_collector_domains_total
ct_collector_unique_domains
ct_collector_wildcard_domains_total
ct_collector_last_message_timestamp_seconds
ct_collector_chain_certs_total
ct_collector_der_bytes_total
ct_collector_message_type_total{message_type="..."}
ct_collector_update_type_total{update_type="..."}
ct_collector_source_total{source="..."}
ct_collector_issuer_total{issuer="..."}
ct_collector_tld_total{tld="..."}
```

`lite` and `full` both provide certificate metadata such as issuer, source CT log, and update type. Only `full` includes `chain` and `leaf_cert.as_der`, so `ct_collector_chain_certs_total` and `ct_collector_der_bytes_total` are only populated in `full` mode.
