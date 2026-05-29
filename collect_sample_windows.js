#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const zlib = require("node:zlib");

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
  },
  lite: {
    endpoint: "/",
  },
  full: {
    endpoint: "/full-stream",
  },
};

const manifestColumns = [
  "file",
  "scheduled_start_utc",
  "scheduled_end_utc",
  "actual_start_utc",
  "actual_end_utc",
  "mode",
  "planned_seconds",
  "actual_seconds",
  "messages",
  "certificate_messages",
  "domains",
  "parse_errors",
  "reconnects",
  "status",
  "notes",
];

function usage() {
  console.log(`Usage:
  CERTSTREAM_MODE=domains-only SAMPLE_MINUTES=15 SAMPLE_WINDOWS=24 SAMPLE_START=next-hour node collect_sample_windows.js

Environment:
  CERTSTREAM_MODE              domains-only, lite, or full. Default: domains-only
  CERTSTREAM_BASE_URL          Certstream WebSocket base URL. Default: ws://127.0.0.1:8080
  CERTSTREAM_WS_URL            Explicit WebSocket URL override.
  SAMPLE_MINUTES               Duration of each capture window. Default: 15
  SAMPLE_SECONDS               Duration override for testing.
  SAMPLE_WINDOWS               Number of windows to collect. 0 means run until interrupted. Default: 1
  SAMPLE_INTERVAL_MINUTES      Start-to-start interval between windows. Default: 60
  SAMPLE_START                 now or next-hour. Default: now
  SAMPLE_OUTPUT_DIR            Raw output directory. Default: data/raw
  SAMPLE_MANIFEST              Manifest CSV path. Default: data/manifest.csv
  SAMPLE_NOTES                 Optional text stored in the manifest.

Output:
  data/raw/YYYY-MM-DD/YYYY-MM-DDTHH-mmZ_15m_domains-only.jsonl.gz
  data/manifest.csv
`);
}

if (process.argv.includes("--help") || process.argv.includes("-h")) {
  usage();
  process.exit(0);
}

function normalizeMode(value) {
  const normalized = String(value || "").trim().toLowerCase();
  const mode = modeAliases.get(normalized);
  if (!mode) {
    throw new Error(`Unsupported CERTSTREAM_MODE '${value}'. Use domains-only, lite, or full.`);
  }

  return mode;
}

function positiveNumber(name, fallback) {
  const raw = process.env[name];
  if (raw === undefined || raw === "") {
    return fallback;
  }

  const value = Number(raw);
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`${name} must be a positive number.`);
  }

  return value;
}

function nonNegativeInteger(name, fallback) {
  const raw = process.env[name];
  if (raw === undefined || raw === "") {
    return fallback;
  }

  const value = Number(raw);
  if (!Number.isInteger(value) || value < 0) {
    throw new Error(`${name} must be a non-negative integer.`);
  }

  return value;
}

function buildWsUrl(baseUrl, endpoint) {
  const base = baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`;
  const cleanEndpoint = endpoint.startsWith("/") ? endpoint.slice(1) : endpoint;
  return new URL(cleanEndpoint, base).toString();
}

function isoUtc(date) {
  return date.toISOString().replace(/\.\d{3}Z$/, "Z");
}

function dateDirName(date) {
  return isoUtc(date).slice(0, 10);
}

function fileTimestamp(date) {
  return isoUtc(date).slice(0, 16).replace(":", "-");
}

function relativePath(targetPath) {
  return path.relative(process.cwd(), targetPath).split(path.sep).join("/");
}

function csvEscape(value) {
  const text = String(value ?? "");
  if (!/[",\n\r]/.test(text)) {
    return text;
  }

  return `"${text.replaceAll('"', '""')}"`;
}

function appendManifest(manifestPath, row) {
  fs.mkdirSync(path.dirname(manifestPath), { recursive: true });

  const needsHeader = !fs.existsSync(manifestPath) || fs.statSync(manifestPath).size === 0;
  const lines = [];
  if (needsHeader) {
    lines.push(manifestColumns.join(","));
  }

  lines.push(manifestColumns.map((column) => csvEscape(row[column])).join(","));
  fs.appendFileSync(manifestPath, `${lines.join("\n")}\n`);
}

function uniqueOutputPath(basePath) {
  if (!fs.existsSync(basePath)) {
    return basePath;
  }

  const parsed = path.parse(basePath);
  for (let i = 2; ; i += 1) {
    const candidate = path.join(parsed.dir, `${parsed.name}_run${i}${parsed.ext}`);
    if (!fs.existsSync(candidate)) {
      return candidate;
    }
  }
}

function normalizeDomain(domain) {
  return String(domain || "").trim().toLowerCase().replace(/^\*\./, "").replace(/\.$/, "");
}

function extractDomains(event) {
  if (Array.isArray(event?.data)) {
    return event.data;
  }

  const domains = event?.data?.leaf_cert?.all_domains;
  return Array.isArray(domains) ? domains : [];
}

function isCertificateEvent(event) {
  return Boolean(event?.data?.leaf_cert && typeof event.data.leaf_cert === "object");
}

const streamMode = normalizeMode(process.env.CERTSTREAM_MODE || "domains-only");
const sampleSeconds = process.env.SAMPLE_SECONDS
  ? positiveNumber("SAMPLE_SECONDS", 0)
  : positiveNumber("SAMPLE_MINUTES", 15) * 60;
const sampleMs = Math.round(sampleSeconds * 1000);
const sampleWindows = nonNegativeInteger("SAMPLE_WINDOWS", 1);
const intervalMs = Math.round(positiveNumber("SAMPLE_INTERVAL_MINUTES", 60) * 60 * 1000);
const startMode = String(process.env.SAMPLE_START || "now").trim().toLowerCase();
const outputDir = path.resolve(process.env.SAMPLE_OUTPUT_DIR || path.join("data", "raw"));
const manifestPath = path.resolve(process.env.SAMPLE_MANIFEST || path.join("data", "manifest.csv"));
const sampleNotes = process.env.SAMPLE_NOTES || "";
const wsUrl = process.env.CERTSTREAM_WS_URL || buildWsUrl(
  process.env.CERTSTREAM_BASE_URL || "ws://127.0.0.1:8080",
  modeConfig[streamMode].endpoint,
);

if (!["now", "next-hour"].includes(startMode)) {
  throw new Error("SAMPLE_START must be 'now' or 'next-hour'.");
}

if (typeof WebSocket === "undefined") {
  throw new Error("This script requires a Node.js runtime with global WebSocket support.");
}

let interrupted = false;
let activeStop = null;

function requestStop() {
  interrupted = true;
  if (activeStop) {
    activeStop("interrupted");
    return;
  }

  console.log("interrupted");
  process.exit(130);
}

process.on("SIGINT", requestStop);
process.on("SIGTERM", requestStop);

function nextHourStart(fromDate) {
  const next = new Date(fromDate);
  next.setUTCMinutes(0, 0, 0);
  next.setUTCHours(next.getUTCHours() + 1);
  return next;
}

function sleep(ms) {
  if (ms <= 0) {
    return Promise.resolve();
  }

  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function collectWindow(windowIndex, scheduledStart) {
  const scheduledEnd = new Date(scheduledStart.getTime() + sampleMs);
  const durationLabel = sampleSeconds < 60 ? `${Math.round(sampleSeconds)}s` : `${Math.round(sampleSeconds / 60)}m`;
  const dayDir = path.join(outputDir, dateDirName(scheduledStart));
  fs.mkdirSync(dayDir, { recursive: true });

  const baseName = `${fileTimestamp(scheduledStart)}Z_${durationLabel}_${streamMode}.jsonl.gz`;
  const outputPath = uniqueOutputPath(path.join(dayDir, baseName));
  const gzip = zlib.createGzip({ level: 6 });
  const out = fs.createWriteStream(outputPath);
  gzip.pipe(out);

  const state = {
    messages: 0,
    certificateMessages: 0,
    domains: 0,
    parseErrors: 0,
    reconnects: 0,
  };

  const actualStart = new Date();
  let ws = null;
  let reconnectTimer = null;
  let stopTimer = null;
  let stopped = false;
  let status = "completed";

  console.log(`[window ${windowIndex}] writing ${relativePath(outputPath)}`);
  console.log(`[window ${windowIndex}] connecting to ${wsUrl}`);

  function writeEvent(event) {
    const receivedAt = new Date();
    const domains = extractDomains(event);

    state.messages += 1;
    if (isCertificateEvent(event)) {
      state.certificateMessages += 1;
    }

    for (const domain of domains) {
      if (normalizeDomain(domain)) {
        state.domains += 1;
      }
    }

    const row = {
      received_at: receivedAt.toISOString(),
      stream_mode: streamMode,
      message_type: event.message_type,
      data: event.data,
    };

    if (isCertificateEvent(event)) {
      row.domains = domains;
    }

    gzip.write(`${JSON.stringify(row)}\n`);
  }

  let resolveDone;
  const done = new Promise((resolve) => {
    resolveDone = resolve;
  });

  function stop(nextStatus = "completed") {
    if (stopped) {
      return;
    }

    stopped = true;
    status = nextStatus;
    activeStop = null;

    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
    }

    if (stopTimer) {
      clearTimeout(stopTimer);
    }

    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
      try {
        ws.close();
      } catch {
        // Ignore close failures during shutdown.
      }
    }

    gzip.end();
  }

  activeStop = stop;

  out.on("finish", () => {
    const actualEnd = new Date();
    const row = {
      file: relativePath(outputPath),
      scheduled_start_utc: isoUtc(scheduledStart),
      scheduled_end_utc: isoUtc(scheduledEnd),
      actual_start_utc: isoUtc(actualStart),
      actual_end_utc: isoUtc(actualEnd),
      mode: streamMode,
      planned_seconds: Math.round(sampleSeconds),
      actual_seconds: ((actualEnd.getTime() - actualStart.getTime()) / 1000).toFixed(3),
      messages: state.messages,
      certificate_messages: state.certificateMessages,
      domains: state.domains,
      parse_errors: state.parseErrors,
      reconnects: state.reconnects,
      status,
      notes: sampleNotes,
    };

    appendManifest(manifestPath, row);
    console.log(
      `[window ${windowIndex}] ${status}: messages=${state.messages} domains=${state.domains} output=${relativePath(outputPath)}`,
    );
    resolveDone(row);
  });

  function connect() {
    if (stopped) {
      return;
    }

    ws = new WebSocket(wsUrl);

    ws.addEventListener("open", () => {
      console.log(`[window ${windowIndex}] websocket open`);
    });

    ws.addEventListener("message", (event) => {
      if (stopped) {
        return;
      }

      try {
        writeEvent(JSON.parse(event.data));
      } catch (err) {
        state.parseErrors += 1;
        console.error(`[window ${windowIndex}] failed to parse message: ${err.message}`);
      }
    });

    ws.addEventListener("error", (event) => {
      if (!stopped) {
        console.error(`[window ${windowIndex}] websocket error`, event.message || event.type || event);
      }
    });

    ws.addEventListener("close", (event) => {
      if (stopped) {
        return;
      }

      state.reconnects += 1;
      console.error(`[window ${windowIndex}] websocket closed code=${event.code} reason=${event.reason || ""}`);
      reconnectTimer = setTimeout(connect, 3000);
    });
  }

  stopTimer = setTimeout(() => stop("completed"), sampleMs);
  connect();

  return done;
}

async function main() {
  const now = new Date();
  const firstStart = startMode === "next-hour" ? nextHourStart(now) : now;

  console.log(`mode=${streamMode} sample_seconds=${sampleSeconds} windows=${sampleWindows || "until-interrupted"}`);
  console.log(`output_dir=${relativePath(outputDir)} manifest=${relativePath(manifestPath)}`);

  let windowIndex = 1;
  while (!interrupted && (sampleWindows === 0 || windowIndex <= sampleWindows)) {
    const scheduledStart = new Date(firstStart.getTime() + (windowIndex - 1) * intervalMs);
    const waitMs = scheduledStart.getTime() - Date.now();

    if (waitMs > 0) {
      console.log(`[window ${windowIndex}] waiting until ${isoUtc(scheduledStart)}`);
      await sleep(waitMs);
    } else if (windowIndex > 1) {
      console.warn(`[window ${windowIndex}] scheduled start already passed by ${Math.round(Math.abs(waitMs) / 1000)}s`);
    }

    if (interrupted) {
      break;
    }

    await collectWindow(windowIndex, scheduledStart);
    windowIndex += 1;
  }
}

main().catch((err) => {
  console.error(err.stack || err.message || err);
  process.exit(1);
});
