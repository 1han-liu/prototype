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
cd /path/to/certstream-server-go

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
cd /path/to/prototype
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

### Sampled Research Collection

For the weekday/weekend and business-hour analysis, use the sampled collector instead of appending everything to `data/lite.jsonl`.

Run one 15-minute `lite` sample immediately:

```bash
CERTSTREAM_MODE=lite SAMPLE_MINUTES=15 SAMPLE_WINDOWS=1 node collect_sample_windows.js
```

Run 24 hourly samples, starting at the next UTC hour:

```bash
CERTSTREAM_MODE=lite SAMPLE_MINUTES=15 SAMPLE_WINDOWS=24 SAMPLE_START=next-hour node collect_sample_windows.js
```

For a short test:

```bash
CERTSTREAM_MODE=lite SAMPLE_SECONDS=30 SAMPLE_WINDOWS=1 node collect_sample_windows.js
```

The sampled collector writes compressed raw JSONL files and a manifest:

```text
data/raw/YYYY-MM-DD/YYYY-MM-DDTHH-mmZ_15m_lite.jsonl.gz
data/manifest.csv
```

Use UTC in file names. The Python analysis scripts convert timestamps to `Europe/Berlin`, `America/New_York`, or `America/Los_Angeles` for local-time and business-hour analysis.

## 3. Start Prometheus and Grafana

Keep the collector running, then in another terminal:

```bash
cd /path/to/prototype
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

## 5. Offline Analysis Scripts

The Python scripts in `analysis/` read collected JSONL data into pandas DataFrames, use pandas `groupby`, `nunique`, `drop_duplicates`, and timezone conversion for aggregation, and use matplotlib to write SVG charts plus CSV summaries to `figures/`.

Install the analysis dependencies first:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Default input resolution:

```text
data/raw/2026-05-25/2026-05-25T18-00Z_60m_lite.jsonl.gz
data/lite.jsonl
data/lite-one.jsonl
```

Use `INPUT_FILE` to analyze a different sample and `FIGURES_DIR` to change the output directory:

```bash
INPUT_FILE=data/raw/2026-05-25/2026-05-25T18-00Z_60m_lite.jsonl.gz .venv/bin/python analysis/01_ct_log_sources.py
```

Use `TIME_FIELD` for time-series scripts. The default is `received_at`, which describes when the prototype observed the event. Other supported values are `not_before`, `seen`, and `source_timestamp`. Time-series charts default to `DISPLAY_TIME_ZONE=Europe/Berlin` for local display, while CSV files keep UTC as well.

```bash
TIME_FIELD=received_at DISPLAY_TIME_ZONE=Europe/Berlin .venv/bin/python analysis/02_per_minute_issuance.py
TIME_FIELD=received_at .venv/bin/python analysis/04_tld_region_business_hours.py
```

By default, the time-series scripts remove sparse first/last edge minutes when they are likely partial collection-window artifacts. Set `TRIM_EDGE_MINUTES=0` to keep them.

Analysis scripts:

```text
analysis/01_ct_log_sources.py
  figures/ct_log_sources.svg
  figures/ct_log_sources.csv

analysis/02_per_minute_issuance.py
  figures/per_minute_issuance.svg
  figures/per_minute_issuance.csv
  figures/per_minute_gaps.csv

analysis/03_ca_distribution.py
  figures/ca_distribution.svg
  figures/ca_distribution.csv

analysis/04_tld_region_business_hours.py
  figures/tld_region_counts.svg
  figures/tld_region_counts.csv
  figures/region_counts.csv
  figures/regional_business_hour_rates.svg
  figures/regional_business_hour_rates.csv

analysis/05_dedup_summary.py
  figures/dedup_summary.svg
  figures/dedup_summary.csv
```

The regional/business-hour script uses ccTLDs as a regional proxy. European ccTLDs such as `.de`, `.fr`, `.nl`, `.eu`, and `.uk` are mapped to `Europe/Berlin`; North American ccTLDs such as `.us`, `.ca`, and `.mx` are evaluated under both `America/New_York` and `America/Los_Angeles`. Generic TLDs such as `.com`, `.net`, and `.org` are kept as global/unknown rather than assigned to the United States.
