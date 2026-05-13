#!/usr/bin/env node

const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const modeAliases = new Map([
  ["domain", "domains-only"],
  ["domains", "domains-only"],
  ["domain-only", "domains-only"],
  ["domains-only", "domains-only"],
  ["only-domain", "domains-only"],
  ["only-domains", "domains-only"],
  ["lite", "lite"],
  ["full", "full"],
  ["full-stream", "full"],
]);

const modeConfig = {
  "domains-only": {
    endpoint: "/domains-only",
    outputName: "domains.jsonl",
  },
  lite: {
    endpoint: "/",
    outputName: "lite.jsonl",
  },
  full: {
    endpoint: "/full-stream",
    outputName: "full-stream.jsonl",
  },
};

function inferModeFromUrl(url) {
  if (!url) {
    return null;
  }

  try {
    const pathname = new URL(url).pathname.replace(/\/+$/, "") || "/";
    if (pathname === "/full-stream") {
      return "full";
    }
    if (pathname === "/domains-only") {
      return "domains-only";
    }
    if (pathname === "/") {
      return "lite";
    }
  } catch {
    return null;
  }

  return null;
}

function normalizeMode(value) {
  const normalized = String(value || "").trim().toLowerCase();
  const mode = modeAliases.get(normalized);
  if (!mode) {
    throw new Error(`Unsupported CERTSTREAM_MODE '${value}'. Use domains-only, lite, or full.`);
  }

  return mode;
}

function buildWsUrl(baseUrl, endpoint) {
  const base = baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`;
  const cleanEndpoint = endpoint.startsWith("/") ? endpoint.slice(1) : endpoint;
  return new URL(cleanEndpoint, base).toString();
}

function endpointFromUrl(url, fallback) {
  try {
    return new URL(url).pathname || "/";
  } catch {
    return fallback;
  }
}

const streamMode = normalizeMode(process.env.CERTSTREAM_MODE || inferModeFromUrl(process.env.CERTSTREAM_WS_URL) || "domains-only");
const wsUrl = process.env.CERTSTREAM_WS_URL || buildWsUrl(process.env.CERTSTREAM_BASE_URL || "ws://127.0.0.1:8080", modeConfig[streamMode].endpoint);
const wsEndpoint = endpointFromUrl(wsUrl, modeConfig[streamMode].endpoint);
const metricsHost = process.env.METRICS_HOST || "0.0.0.0";
const metricsPort = Number(process.env.METRICS_PORT || 9101);
const outputFile = process.env.OUTPUT_FILE || path.join(__dirname, "data", modeConfig[streamMode].outputName);
const maxMessages = Number(process.env.MAX_MESSAGES || 0);

const outputDir = path.dirname(outputFile);
fs.mkdirSync(outputDir, { recursive: true });

const state = {
  connected: 0,
  reconnects: 0,
  messages: 0,
  parseErrors: 0,
  domains: 0,
  wildcardDomains: 0,
  certificateMessages: 0,
  chainCerts: 0,
  derBytes: 0,
  uniqueDomains: new Set(),
  tlds: new Map(),
  messageTypes: new Map(),
  updateTypes: new Map(),
  sources: new Map(),
  issuers: new Map(),
  lastMessageAt: 0,
};

function escapeLabel(value) {
  return String(value).replaceAll("\\", "\\\\").replaceAll("\n", "\\n").replaceAll('"', '\\"');
}

function normalizeDomain(domain) {
  return String(domain).trim().toLowerCase().replace(/^\*\./, "").replace(/\.$/, "");
}

function tldOf(domain) {
  const normalized = normalizeDomain(domain);
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(normalized)) {
    return "_ipv4";
  }

  const parts = normalized.split(".").filter(Boolean);
  return parts.length > 1 ? parts.at(-1) : "_none";
}

function incMap(map, key, amount = 1) {
  map.set(key, (map.get(key) || 0) + amount);
}

function safeLabel(value, fallback = "unknown") {
  const label = String(value || "").trim();
  return label || fallback;
}

function subjectLabel(subject) {
  if (!subject || typeof subject !== "object") {
    return "unknown";
  }

  return safeLabel(subject.O || subject.CN || subject.aggregated);
}

function byteLengthBase64(value) {
  if (!value) {
    return 0;
  }

  return Buffer.byteLength(String(value), "base64");
}

function extractEvent(event) {
  if (!event || typeof event !== "object") {
    return null;
  }

  if (Array.isArray(event.data)) {
    return {
      domains: event.data,
      source: null,
      issuer: null,
      updateType: null,
      chainLength: 0,
      derBytes: 0,
      certificate: false,
    };
  }

  const leafCert = event.data?.leaf_cert;
  if (!leafCert || typeof leafCert !== "object") {
    return null;
  }

  return {
    domains: Array.isArray(leafCert.all_domains) ? leafCert.all_domains : [],
    source: safeLabel(event.data?.source?.name || event.data?.source?.url),
    issuer: subjectLabel(leafCert.issuer),
    updateType: safeLabel(event.data?.update_type),
    chainLength: Array.isArray(event.data?.chain) ? event.data.chain.length : 0,
    derBytes: byteLengthBase64(leafCert.as_der),
    certificate: true,
  };
}

function recordEvent(event) {
  const extracted = extractEvent(event);
  if (!extracted) {
    state.parseErrors += 1;
    return;
  }

  const receivedAt = new Date();
  state.messages += 1;
  state.lastMessageAt = receivedAt.getTime() / 1000;
  incMap(state.messageTypes, safeLabel(event.message_type));

  if (extracted.certificate) {
    state.certificateMessages += 1;
    state.chainCerts += extracted.chainLength;
    state.derBytes += extracted.derBytes;
    incMap(state.updateTypes, extracted.updateType);
    incMap(state.sources, extracted.source);
    incMap(state.issuers, extracted.issuer);
  }

  for (const domain of extracted.domains) {
    const normalized = normalizeDomain(domain);
    if (!normalized) {
      continue;
    }

    state.domains += 1;
    state.uniqueDomains.add(normalized);
    incMap(state.tlds, tldOf(normalized));

    if (String(domain).startsWith("*.")) {
      state.wildcardDomains += 1;
    }
  }

  const row = {
    received_at: receivedAt.toISOString(),
    stream_mode: streamMode,
    message_type: event.message_type,
    data: event.data,
  };

  if (extracted.certificate) {
    row.domains = extracted.domains;
  }

  fs.appendFile(outputFile, `${JSON.stringify(row)}\n`, (err) => {
    if (err) {
      console.error("failed to write JSONL:", err.message);
    }
  });
}

function appendMapMetric(lines, name, labels, map) {
  const sorted = [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  for (const [label, count] of sorted) {
    lines.push(`${name}{${labels}="${escapeLabel(label)}"} ${count}`);
  }
}

function renderMetrics() {
  const lines = [
    "# HELP ct_collector_mode_info Certstream collector stream mode and endpoint.",
    "# TYPE ct_collector_mode_info gauge",
    `ct_collector_mode_info{mode="${escapeLabel(streamMode)}",endpoint="${escapeLabel(wsEndpoint)}"} 1`,
    "# HELP ct_collector_up Whether the collector WebSocket is currently open.",
    "# TYPE ct_collector_up gauge",
    `ct_collector_up ${state.connected}`,
    "# HELP ct_collector_reconnects_total Number of WebSocket reconnect attempts.",
    "# TYPE ct_collector_reconnects_total counter",
    `ct_collector_reconnects_total ${state.reconnects}`,
    "# HELP ct_collector_messages_total Number of Certstream WebSocket messages received.",
    "# TYPE ct_collector_messages_total counter",
    `ct_collector_messages_total ${state.messages}`,
    "# HELP ct_collector_parse_errors_total Number of Certstream messages that could not be parsed.",
    "# TYPE ct_collector_parse_errors_total counter",
    `ct_collector_parse_errors_total ${state.parseErrors}`,
    "# HELP ct_collector_certificate_messages_total Number of certificate_update messages received.",
    "# TYPE ct_collector_certificate_messages_total counter",
    `ct_collector_certificate_messages_total ${state.certificateMessages}`,
    "# HELP ct_collector_domains_total Number of domain entries observed.",
    "# TYPE ct_collector_domains_total counter",
    `ct_collector_domains_total ${state.domains}`,
    "# HELP ct_collector_unique_domains Number of unique normalized domains observed since startup.",
    "# TYPE ct_collector_unique_domains gauge",
    `ct_collector_unique_domains ${state.uniqueDomains.size}`,
    "# HELP ct_collector_wildcard_domains_total Number of wildcard domain entries observed.",
    "# TYPE ct_collector_wildcard_domains_total counter",
    `ct_collector_wildcard_domains_total ${state.wildcardDomains}`,
    "# HELP ct_collector_last_message_timestamp_seconds Unix timestamp of the latest received message.",
    "# TYPE ct_collector_last_message_timestamp_seconds gauge",
    `ct_collector_last_message_timestamp_seconds ${state.lastMessageAt}`,
    "# HELP ct_collector_chain_certs_total Number of certificate chain entries observed. This is populated by full stream messages.",
    "# TYPE ct_collector_chain_certs_total counter",
    `ct_collector_chain_certs_total ${state.chainCerts}`,
    "# HELP ct_collector_der_bytes_total Approximate decoded DER bytes observed from leaf certificates. This is populated by full stream messages.",
    "# TYPE ct_collector_der_bytes_total counter",
    `ct_collector_der_bytes_total ${state.derBytes}`,
    "# HELP ct_collector_message_type_total Number of messages grouped by Certstream message_type.",
    "# TYPE ct_collector_message_type_total counter",
  ];

  appendMapMetric(lines, "ct_collector_message_type_total", "message_type", state.messageTypes);

  lines.push(
    "# HELP ct_collector_update_type_total Number of certificate messages grouped by update_type.",
    "# TYPE ct_collector_update_type_total counter",
  );
  appendMapMetric(lines, "ct_collector_update_type_total", "update_type", state.updateTypes);

  lines.push(
    "# HELP ct_collector_source_total Number of certificate messages grouped by CT log source.",
    "# TYPE ct_collector_source_total counter",
  );
  appendMapMetric(lines, "ct_collector_source_total", "source", state.sources);

  lines.push(
    "# HELP ct_collector_issuer_total Number of certificate messages grouped by issuer organization or common name.",
    "# TYPE ct_collector_issuer_total counter",
  );
  appendMapMetric(lines, "ct_collector_issuer_total", "issuer", state.issuers);

  lines.push(
    "# HELP ct_collector_tld_total Number of observed domains grouped by last DNS label.",
    "# TYPE ct_collector_tld_total counter",
  );
  appendMapMetric(lines, "ct_collector_tld_total", "tld", state.tlds);

  return `${lines.join("\n")}\n`;
}

const metricsServer = http.createServer((req, res) => {
  if (req.url === "/healthz") {
    res.writeHead(state.connected ? 200 : 503, { "content-type": "text/plain; charset=utf-8" });
    res.end(state.connected ? "ok\n" : "websocket disconnected\n");
    return;
  }

  if (req.url === "/metrics") {
    res.writeHead(200, { "content-type": "text/plain; version=0.0.4; charset=utf-8" });
    res.end(renderMetrics());
    return;
  }

  res.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
  res.end("not found\n");
});

metricsServer.listen(metricsPort, metricsHost, () => {
  const address = metricsServer.address();
  const boundPort = typeof address === "object" && address ? address.port : metricsPort;
  const displayHost = metricsHost === "0.0.0.0" ? "127.0.0.1" : metricsHost;
  console.log(`metrics listening on http://${displayHost}:${boundPort}/metrics`);
});

function connect() {
  console.log(`mode=${streamMode} output=${outputFile}`);
  console.log(`connecting to ${wsUrl}`);
  const ws = new WebSocket(wsUrl);

  ws.addEventListener("open", () => {
    state.connected = 1;
    console.log("websocket open");
  });

  ws.addEventListener("message", (event) => {
    try {
      recordEvent(JSON.parse(event.data));
      if (maxMessages > 0 && state.messages >= maxMessages) {
        console.log(`reached MAX_MESSAGES=${maxMessages}; closing`);
        ws.close();
        process.exit(0);
      }
    } catch (err) {
      console.error("failed to parse message:", err.message);
    }
  });

  ws.addEventListener("error", (event) => {
    console.error("websocket error", event.message || event.type || event);
  });

  ws.addEventListener("close", (event) => {
    state.connected = 0;
    console.error(`websocket closed code=${event.code} reason=${event.reason || ""}`);
    if (maxMessages > 0 && state.messages >= maxMessages) {
      return;
    }

    state.reconnects += 1;
    setTimeout(connect, 3000);
  });
}

connect();
