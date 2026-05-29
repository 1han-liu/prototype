from __future__ import annotations

import gzip
import json
import os
import sys
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT_DIR / ".cache"))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT_DIR / ".cache" / "matplotlib"))
(ROOT_DIR / ".cache" / "matplotlib").mkdir(parents=True, exist_ok=True)

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
DEFAULT_INPUT_CANDIDATES = [
    "data/raw/2026-05-25/2026-05-25T18-00Z_60m_lite.jsonl.gz",
    "data/lite.jsonl",
    "data/lite-one.jsonl",
]

EMPTY_SHA1 = "DA:39:A3:EE:5E:6B:4B:0D:32:55:BF:EF:95:60:18:90:AF:D8:07:09"
EMPTY_SHA256 = "E3:B0:C4:42:98:FC:1C:14:9A:FB:F4:C8:99:6F:B9:24:27:AE:41:E4:64:9B:93:4C:A4:95:99:1B:78:52:B8:55"

EUROPE_TLDS = {
    "ad", "al", "at", "ba", "be", "bg", "by", "ch", "cy", "cz", "de", "dk", "ee", "es", "eu", "fi",
    "fo", "fr", "gg", "gi", "gr", "hr", "hu", "ie", "im", "is", "it", "je", "li", "lt", "lu", "lv",
    "mc", "md", "me", "mk", "mt", "nl", "no", "pl", "pt", "ro", "rs", "se", "si", "sk", "sm", "ua",
    "uk", "va",
}
NORTH_AMERICA_TLDS = {"us", "ca", "mx"}
GLOBAL_GTLD_TLDS = {
    "app", "biz", "cloud", "com", "dev", "info", "io", "net", "online", "org", "shop", "site", "store",
    "tech", "xyz",
}

COLORS = [
    "#2f6f73",
    "#b8572a",
    "#6a5acd",
    "#3267a8",
    "#bb3e6d",
    "#4f7f2a",
    "#8a6d1f",
    "#7d4f50",
]

plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.edgecolor": "#9aa8b5",
    "axes.labelcolor": "#1f2933",
    "axes.titleweight": "bold",
    "axes.grid": True,
    "grid.color": "#e5ebf0",
    "grid.linewidth": 0.8,
    "font.family": "DejaVu Sans",
    "xtick.color": "#53606b",
    "ytick.color": "#53606b",
})


def resolve_project_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    from_cwd = Path.cwd() / path
    if from_cwd.exists():
        return from_cwd.resolve()
    return (ROOT_DIR / path).resolve()


def default_input_file() -> Path:
    for candidate in DEFAULT_INPUT_CANDIDATES:
        resolved = ROOT_DIR / candidate
        if resolved.exists():
            return resolved
    raise FileNotFoundError(f"No default input file found. Tried: {', '.join(DEFAULT_INPUT_CANDIDATES)}")


def get_input_file(argv: list[str] | None = None) -> Path:
    argv = argv or sys.argv
    return resolve_project_path(os.environ.get("INPUT_FILE") or (argv[1] if len(argv) > 1 else None)) or default_input_file()


def get_output_dir() -> Path:
    output_dir = resolve_project_path(os.environ.get("FIGURES_DIR")) or (ROOT_DIR / "figures")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def base_name(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT_DIR).as_posix()
    except ValueError:
        return path.name


def open_jsonl(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("rt", encoding="utf-8")


def iter_events(path: Path) -> Iterator[dict[str, Any]]:
    max_lines = int(os.environ.get("MAX_LINES", "0") or "0")
    with open_jsonl(path) as handle:
        for line_no, line in enumerate(handle, start=1):
            if max_lines and line_no > max_lines:
                break
            if not line.strip():
                continue
            yield json.loads(line)


def safe_label(value: Any, fallback: str = "unknown") -> str:
    label = str(value or "").strip()
    return label or fallback


def get_leaf(event: dict[str, Any]) -> dict[str, Any] | None:
    data = event.get("data")
    leaf = data.get("leaf_cert") if isinstance(data, dict) else None
    return leaf if isinstance(leaf, dict) else None


def is_certificate_event(event: dict[str, Any]) -> bool:
    return event.get("message_type") == "certificate_update" and get_leaf(event) is not None


def is_domain_list_event(event: dict[str, Any]) -> bool:
    return isinstance(event.get("data"), list)


def issuer_label(issuer: dict[str, Any] | None) -> str:
    if not isinstance(issuer, dict):
        return "unknown"
    return safe_label(issuer.get("O") or issuer.get("CN") or issuer.get("aggregated"))


def source_info(event: dict[str, Any]) -> tuple[str, str, str]:
    data = event.get("data")
    source = data.get("source", {}) if isinstance(data, dict) else {}
    return (
        safe_label(source.get("name") or source.get("url")),
        safe_label(source.get("url"), ""),
        safe_label(source.get("type"), ""),
    )


def normalize_hash(value: Any) -> str:
    return str(value or "").strip().upper()


def cert_key(event: dict[str, Any]) -> str | None:
    leaf = get_leaf(event)
    if not leaf:
        return None

    sha256 = normalize_hash(leaf.get("sha256"))
    if sha256 and sha256 != EMPTY_SHA256:
        return f"sha256:{sha256}"

    issuer = issuer_label(leaf.get("issuer"))
    serial = safe_label(leaf.get("serial_number"), "")
    if serial:
        return f"issuer-serial:{issuer}:{serial}"

    sha1 = normalize_hash(leaf.get("sha1") or leaf.get("fingerprint"))
    if sha1 and sha1 != EMPTY_SHA1:
        return f"sha1:{sha1}"

    source_name, _, _ = source_info(event)
    return f"source-index:{source_name}:{safe_label(event.get('data', {}).get('cert_index'))}"


def normalize_domain(domain: Any) -> str:
    stripped = str(domain or "").strip().lower()
    if stripped.startswith("*."):
        stripped = stripped[2:]
    stripped = stripped.rstrip(".")
    if not stripped:
        return ""
    try:
        return stripped.encode("idna").decode("ascii")
    except UnicodeError:
        return stripped


def event_domains(event: dict[str, Any]) -> list[str]:
    leaf = get_leaf(event)
    if leaf and isinstance(leaf.get("all_domains"), list):
        raw_domains = leaf["all_domains"]
    elif isinstance(event.get("domains"), list):
        raw_domains = event["domains"]
    elif isinstance(event.get("data"), list):
        raw_domains = event["data"]
    else:
        raw_domains = []
    return [domain for domain in (normalize_domain(item) for item in raw_domains) if domain]


def tld_of(domain: str) -> str:
    parts = [part for part in normalize_domain(domain).split(".") if part]
    if len(parts) == 4 and all(part.isdigit() and 0 <= int(part) <= 255 for part in parts):
        return "_ipv4"
    return parts[-1] if len(parts) > 1 else "_none"


def region_for_tld(tld: str) -> str:
    if tld in EUROPE_TLDS:
        return "Europe ccTLD"
    if tld in NORTH_AMERICA_TLDS:
        return "North America ccTLD"
    if tld in GLOBAL_GTLD_TLDS:
        return "Global/unknown gTLD"
    return "Other/unknown"


def parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def event_time(event: dict[str, Any], preferred: str | None = None) -> datetime | None:
    preferred = preferred or os.environ.get("TIME_FIELD", "received_at")
    leaf = get_leaf(event) or {}
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    source = data.get("source", {}) if isinstance(data, dict) else {}
    candidates: dict[str, Callable[[], datetime | None]] = {
        "received_at": lambda: parse_iso_datetime(event.get("received_at")),
        "not_before": lambda: datetime.fromtimestamp(float(leaf.get("not_before")), timezone.utc)
        if leaf.get("not_before") else None,
        "seen": lambda: datetime.fromtimestamp(float(data.get("seen")), timezone.utc)
        if data.get("seen") else None,
        "source_timestamp": lambda: datetime.fromtimestamp(float(source.get("timestamp")), timezone.utc)
        if source.get("timestamp") else None,
    }
    for field in [preferred, "received_at", "seen", "source_timestamp", "not_before"]:
        if field not in candidates:
            continue
        try:
            value = candidates[field]()
        except (TypeError, ValueError, OSError):
            value = None
        if value:
            return value
    return None


def load_frames(
    input_file: Path,
    *,
    include_domains: bool = False,
    time_field: str | None = None,
    include_domain_only_events: bool | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    event_rows: list[dict[str, Any]] = []
    domain_rows: list[dict[str, Any]] = []
    time_field = time_field or os.environ.get("TIME_FIELD", "received_at")
    if include_domain_only_events is None:
        include_domain_only_events = include_domains

    for event in iter_events(input_file):
        domains_for_event = event_domains(event)
        certificate_event = is_certificate_event(event)
        domain_only_event = include_domain_only_events and is_domain_list_event(event) and bool(domains_for_event)
        if not certificate_event and not domain_only_event:
            continue
        leaf = get_leaf(event) or {}
        timestamp = event_time(event, time_field)
        if not timestamp:
            continue
        source_name, source_url, source_type = source_info(event)
        key = cert_key(event) if certificate_event else None
        issuer = issuer_label(leaf.get("issuer"))
        event_rows.append({
            "timestamp": timestamp,
            "minute_utc": pd.Timestamp(timestamp).floor("min"),
            "event_kind": "certificate" if certificate_event else "domains-only",
            "stream_mode": safe_label(event.get("stream_mode"), "domains-only" if domain_only_event else "unknown"),
            "message_type": safe_label(event.get("message_type")),
            "domain_count": len(domains_for_event),
            "cert_key": key,
            "issuer": issuer,
            "source": source_name,
            "source_url": source_url,
            "source_type": source_type,
        })

        if include_domains:
            for domain in domains_for_event:
                tld = tld_of(domain)
                domain_rows.append({
                    "timestamp": timestamp,
                    "minute_utc": pd.Timestamp(timestamp).floor("min"),
                    "cert_key": key,
                    "domain": domain,
                    "tld": tld,
                    "region_bucket": region_for_tld(tld),
                })

    event_columns = [
        "timestamp",
        "minute_utc",
        "event_kind",
        "stream_mode",
        "message_type",
        "domain_count",
        "cert_key",
        "issuer",
        "source",
        "source_url",
        "source_type",
    ]
    events = pd.DataFrame(event_rows, columns=event_columns)
    if not events.empty:
        events["timestamp"] = pd.to_datetime(events["timestamp"], utc=True)
        events["minute_utc"] = pd.to_datetime(events["minute_utc"], utc=True)

    domains = None
    if include_domains:
        domain_columns = ["timestamp", "minute_utc", "cert_key", "domain", "tld", "region_bucket"]
        domains = pd.DataFrame(domain_rows, columns=domain_columns)
        if not domains.empty:
            domains["timestamp"] = pd.to_datetime(domains["timestamp"], utc=True)
            domains["minute_utc"] = pd.to_datetime(domains["minute_utc"], utc=True)

    return events, domains


def complete_minute_index(minutes: pd.Series) -> pd.DatetimeIndex:
    if minutes.empty:
        return pd.DatetimeIndex([], tz="UTC")
    return pd.date_range(minutes.min(), minutes.max(), freq="min", tz="UTC")


def trim_sparse_edge_rows(df: pd.DataFrame, count_col: str) -> pd.DataFrame:
    if os.environ.get("TRIM_EDGE_MINUTES") == "0" or len(df) < 5:
        return df
    threshold = float(os.environ.get("TRIM_EDGE_THRESHOLD", "0.1"))
    middle = df.iloc[1:-1][count_col]
    middle = middle[middle > 0]
    if middle.empty:
        return df
    baseline = middle.median()
    result = df
    if result.iloc[-1][count_col] < baseline * threshold:
        result = result.iloc[:-1]
    if not result.empty and result.iloc[0][count_col] < baseline * threshold:
        result = result.iloc[1:]
    return result


def add_local_minute_columns(df: pd.DataFrame, time_zone: str) -> pd.DataFrame:
    result = df.copy()
    result["minute_local_dt"] = result["minute_utc"].dt.tz_convert(time_zone)
    result["minute_local"] = result["minute_local_dt"].dt.strftime("%m-%d %H:%M")
    result["display_timezone"] = time_zone
    return result


def zero_ranges(df: pd.DataFrame, count_col: str) -> list[dict[str, Any]]:
    ranges: list[dict[str, Any]] = []
    start_idx: int | None = None
    previous_idx: int | None = None
    for idx, value in enumerate(df[count_col].tolist()):
        if value == 0 and start_idx is None:
            start_idx = idx
            previous_idx = idx
        elif value == 0:
            previous_idx = idx
        elif start_idx is not None and previous_idx is not None:
            ranges.append({"start": df.iloc[start_idx], "end": df.iloc[previous_idx], "zero_minutes": previous_idx - start_idx + 1})
            start_idx = None
            previous_idx = None
    if start_idx is not None and previous_idx is not None:
        ranges.append({"start": df.iloc[start_idx], "end": df.iloc[previous_idx], "zero_minutes": previous_idx - start_idx + 1})
    return ranges


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def save_bar_chart(
    df: pd.DataFrame,
    *,
    label_col: str,
    value_col: str,
    title: str,
    subtitle: str,
    output_path: Path,
    value_label: str = "count",
    value_text_col: str | None = None,
    color: str = COLORS[0],
) -> None:
    plot_df = df.copy()
    plot_df[label_col] = plot_df[label_col].astype(str)
    height = max(4.5, 0.32 * len(plot_df) + 1.8)
    fig, ax = plt.subplots(figsize=(12, height))
    colors = plot_df["color"].tolist() if "color" in plot_df.columns else color
    ax.barh(plot_df[label_col], plot_df[value_col], color=colors)
    ax.invert_yaxis()
    ax.set_xlabel(value_label)
    ax.set_title(title, loc="left", fontsize=16, pad=22)
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=9, color="#53606b")
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    max_value = max(float(plot_df[value_col].max()), 1.0)
    for position, (_, row) in enumerate(plot_df.iterrows()):
        text = str(row[value_text_col]) if value_text_col else f"{row[value_col]:,.0f}"
        ax.text(float(row[value_col]) + max_value * 0.01, position, text, va="center", fontsize=8, color="#36454f")
    fig.tight_layout()
    fig.savefig(output_path, format=output_path.suffix.lstrip(".") or "svg", bbox_inches="tight")
    plt.close(fig)


def save_line_chart(
    df: pd.DataFrame,
    *,
    x_col: str,
    series: list[tuple[str, str, str]],
    title: str,
    subtitle: str,
    output_path: Path,
    y_label: str = "count",
    display_time_zone: str = "Europe/Berlin",
) -> None:
    fig, ax = plt.subplots(figsize=(12.8, 6.4))
    x_values = pd.to_datetime(df[x_col]).dt.tz_convert(display_time_zone)
    for label, column, color in series:
        ax.plot(x_values, df[column], label=label, color=color, linewidth=2)
    ax.set_ylabel(y_label)
    ax.set_title(title, loc="left", fontsize=16, pad=22)
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=9, color="#53606b")
    ax.legend(ncols=2, loc="upper center", bbox_to_anchor=(0.5, -0.14), frameon=False)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M", tz=x_values.dt.tz))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=7))
    fig.autofmt_xdate(rotation=0, ha="center")
    fig.tight_layout()
    fig.savefig(output_path, format=output_path.suffix.lstrip(".") or "svg", bbox_inches="tight")
    plt.close(fig)


def local_window_label(start: pd.Timestamp, end: pd.Timestamp, time_zone: str) -> str:
    if pd.isna(start) or pd.isna(end):
        return "n/a"
    start_local = start.tz_convert(time_zone)
    end_local = (end + pd.Timedelta(seconds=59)).tz_convert(time_zone)
    return f"{start_local:%d/%m, %H:%M}-{end_local:%d/%m, %H:%M}"


def format_number(value: Any) -> str:
    return f"{int(value):,}"
