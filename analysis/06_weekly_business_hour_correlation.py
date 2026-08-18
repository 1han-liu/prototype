#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from common import (
    COLORS,
    ROOT_DIR,
    base_name,
    event_domains,
    event_time,
    format_number,
    get_output_dir,
    iter_events,
    resolve_project_path,
    save_bar_chart,
    write_csv,
)
from tld_region_mapping import CONTINENT_REGION_COLUMNS, TldRegionMapping

CACHE_VERSION = "weekly-region-v4-mapped-continent"

EUROPE_TLDS = {
    "ad", "al", "at", "ax", "ba", "be", "bg", "by", "ch", "cy", "cz", "de", "dk", "ee", "es", "eu",
    "fi", "fo", "fr", "gg", "gi", "gr", "hr", "hu", "ie", "im", "is", "it", "je", "li", "lt", "lu",
    "lv", "mc", "md", "me", "mk", "mt", "nl", "no", "pl", "pt", "ro", "rs", "se", "si", "sk", "sm",
    "ua", "uk", "va",
}

AMERICAS_TLDS = {
    "ag", "ai", "ar", "aw", "bb", "bl", "bm", "bo", "bq", "br", "bs", "bz", "ca", "cl", "co", "cr",
    "cu", "cw", "dm", "do", "ec", "fk", "gd", "gf", "gl", "gp", "gt", "gy", "hn", "ht", "jm", "kn",
    "ky", "lc", "mf", "mq", "ms", "mx", "ni", "pa", "pe", "pm", "pr", "py", "sr", "sv", "sx", "tc",
    "tt", "us", "uy", "vc", "ve", "vg", "vi",
}

ASIA_TLDS = {
    "ae", "af", "am", "az", "bd", "bh", "bn", "bt", "cc", "cn", "cx", "ge", "hk", "id", "il", "in",
    "io", "iq", "ir", "jo", "jp", "kg", "kh", "kp", "kr", "kw", "kz", "la", "lb", "lk", "mm", "mn",
    "mo", "mv", "my", "np", "om", "ph", "pk", "ps", "qa", "sa", "sg", "sy", "th", "tj", "tm", "tr",
    "tw", "uz", "vn", "ye",
    # Common IDN ccTLDs where the stream is IDNA-encoded.
    "xn--3e0b707e",  # .한국
    "xn--fiqs8s",    # .中国
    "xn--fiqz9s",    # .中國
}

AFRICA_TLDS = {
    "ac", "ao", "bf", "bi", "bj", "bw", "cd", "cf", "cg", "ci", "cm", "cv", "dj", "dz", "eg", "eh",
    "er", "et", "ga", "gh", "gm", "gn", "gq", "gw", "ke", "km", "lr", "ls", "ly", "ma", "mg", "ml",
    "mr", "mu", "mw", "mz", "na", "ne", "ng", "re", "rw", "sc", "sd", "sh", "sl", "sn", "so", "ss",
    "st", "sz", "td", "tg", "tn", "tz", "ug", "yt", "za", "zm", "zw",
}

OCEANIA_TLDS = {
    "as", "au", "ck", "fj", "fm", "gu", "hm", "ki", "mh", "mp", "nc", "nf", "nr", "nu", "nz", "pf",
    "pg", "pn", "pw", "sb", "tk", "to", "tv", "vu", "wf", "ws",
}

KNOWN_CCTLD_TLDS = EUROPE_TLDS | AMERICAS_TLDS | ASIA_TLDS | AFRICA_TLDS | OCEANIA_TLDS

REGION_COLUMNS = CONTINENT_REGION_COLUMNS

CCTLD_REGION_COLUMNS = [
    "Europe",
    "Americas",
    "Asia",
    "Africa",
    "Oceania",
    "Antarctica",
]

BUSINESS_WINDOWS = [
    {
        "label": "Europe Berlin",
        "flag": "business_europe_berlin",
        "region_bucket": "Europe",
        "timezone": "Europe/Berlin",
    },
    {
        "label": "Americas New York",
        "flag": "business_americas_new_york",
        "region_bucket": "Americas",
        "timezone": "America/New_York",
    },
    {
        "label": "Asia Shanghai",
        "flag": "business_asia_shanghai",
        "region_bucket": "Asia",
        "timezone": "Asia/Shanghai",
    },
    {
        "label": "Africa Johannesburg",
        "flag": "business_africa_johannesburg",
        "region_bucket": "Africa",
        "timezone": "Africa/Johannesburg",
    },
    {
        "label": "Oceania Sydney",
        "flag": "business_oceania_sydney",
        "region_bucket": "Oceania",
        "timezone": "Australia/Sydney",
    },
]

WEEKDAY_NAMES = {
    0: "Mon",
    1: "Tue",
    2: "Wed",
    3: "Thu",
    4: "Fri",
    5: "Sat",
    6: "Sun",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze weekly domain-only Certstream samples by regional TLD proxy, "
            "local business-hour windows, and cross-region rate correlation."
        )
    )
    parser.add_argument(
        "--manifest",
        default=os.environ.get("MANIFEST_FILE", "data/manifest.csv"),
        help="Manifest CSV written by collect_sample_windows.js.",
    )
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("FIGURES_DIR"),
        help="Directory for output CSV/SVG files. Defaults to prototype/figures.",
    )
    parser.add_argument(
        "--cache-dir",
        default=os.environ.get("CACHE_DIR", str(ROOT_DIR / ".cache" / "analysis" / "weekly_region_minutes")),
        help="Directory for per-raw-file minute-region cache CSV files.",
    )
    parser.add_argument(
        "--tld-region-map",
        default=os.environ.get("TLD_REGION_MAP", "figures/weekly_tld_region_mapping.csv"),
        help="CSV mapping TLDs to mapped_continent values. Defaults to figures/weekly_tld_region_mapping.csv.",
    )
    parser.add_argument(
        "--notes-filter",
        default=os.environ.get("NOTES_FILTER", "one-week domains-only collection"),
        help="Optional exact substring filter for manifest notes. Use an empty value to disable.",
    )
    parser.add_argument(
        "--start-utc",
        default=os.environ.get("START_UTC"),
        help="Optional inclusive UTC start filter, for example 2026-05-30T00:00:00Z.",
    )
    parser.add_argument(
        "--end-utc",
        default=os.environ.get("END_UTC"),
        help="Optional exclusive UTC end filter, for example 2026-06-06T00:00:00Z.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=int(os.environ.get("MAX_FILES", "0") or "0"),
        help="Optional file limit for smoke tests. 0 means all selected manifest rows.",
    )
    parser.add_argument(
        "--bucket-freq",
        default=os.environ.get("BUCKET_FREQ", "1h"),
        help="Pandas resample frequency for correlation rate series. Default: 1h.",
    )
    parser.add_argument(
        "--rate-period",
        choices=["weekday", "weekend", "both"],
        default=os.environ.get("RATE_PERIOD", "both"),
        help="Which hourly-rate chart to write. Default: both.",
    )
    parser.add_argument(
        "--rate-time-zone",
        default=os.environ.get("RATE_TIME_ZONE", "Europe/Berlin"),
        help="Time zone used to split and label weekday/weekend rate charts. Default: Europe/Berlin.",
    )
    parser.add_argument(
        "--business-start-hour",
        type=int,
        default=int(os.environ.get("BUSINESS_START_HOUR", "8") or "8"),
        help="Inclusive local business-hour start. Default: 8.",
    )
    parser.add_argument(
        "--business-end-hour",
        type=int,
        default=int(os.environ.get("BUSINESS_END_HOUR", "18") or "18"),
        help="Exclusive local business-hour end. Default: 18.",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Rebuild minute-region cache files even when cache exists.",
    )
    return parser.parse_args()


def selected_manifest_rows(args: argparse.Namespace) -> pd.DataFrame:
    manifest_path = resolve_project_path(args.manifest)
    if not manifest_path or not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {args.manifest}")

    manifest = pd.read_csv(manifest_path)
    required_columns = {
        "file",
        "scheduled_start_utc",
        "scheduled_end_utc",
        "mode",
        "status",
    }
    missing = sorted(required_columns.difference(manifest.columns))
    if missing:
        raise ValueError(f"Manifest is missing required columns: {', '.join(missing)}")

    manifest["scheduled_start_utc"] = pd.to_datetime(manifest["scheduled_start_utc"], utc=True)
    manifest["scheduled_end_utc"] = pd.to_datetime(manifest["scheduled_end_utc"], utc=True)
    selected = manifest[
        (manifest["mode"] == "domains-only")
        & (manifest["status"] == "completed")
        & manifest["file"].astype(str).str.endswith("_domains-only.jsonl.gz")
    ].copy()

    notes_filter = str(args.notes_filter or "").strip()
    if notes_filter and "notes" in selected.columns:
        selected = selected[selected["notes"].fillna("").astype(str).str.contains(notes_filter, regex=False)].copy()

    if args.start_utc:
        selected = selected[selected["scheduled_start_utc"] >= pd.Timestamp(args.start_utc).tz_convert("UTC")]
    if args.end_utc:
        selected = selected[selected["scheduled_start_utc"] < pd.Timestamp(args.end_utc).tz_convert("UTC")]

    selected["raw_path"] = selected["file"].map(lambda value: resolve_project_path(str(value)))
    selected = selected[selected["raw_path"].map(lambda path: bool(path and path.exists()))].copy()
    selected = selected.sort_values("scheduled_start_utc").reset_index(drop=True)

    if args.max_files:
        selected = selected.head(args.max_files).copy()

    if selected.empty:
        raise ValueError("No completed domains-only manifest rows matched the selected filters.")

    return selected


def cache_file_path(cache_dir: Path, raw_path: Path, mapping_signature: str = "legacy") -> Path:
    stat = raw_path.stat()
    try:
        rel = raw_path.resolve().relative_to(ROOT_DIR).as_posix()
    except ValueError:
        rel = raw_path.name
    digest = hashlib.sha1(
        f"{CACHE_VERSION}:{mapping_signature}:{raw_path.resolve()}:{stat.st_size}:{int(stat.st_mtime)}".encode("utf-8")
    ).hexdigest()[:16]
    safe_name = rel.replace("/", "__").replace(":", "-")
    return cache_dir / f"{CACHE_VERSION}__{safe_name}__{digest}.csv"


def detailed_region_for_tld(tld: str) -> str:
    if tld == "com":
        return "Global .com"
    if tld in EUROPE_TLDS:
        return "Europe ccTLD"
    if tld in AMERICAS_TLDS:
        return "Americas ccTLD"
    if tld in ASIA_TLDS:
        return "Asia ccTLD"
    if tld in AFRICA_TLDS:
        return "Africa ccTLD"
    if tld in OCEANIA_TLDS:
        return "Oceania ccTLD"
    if tld in KNOWN_CCTLD_TLDS or len(tld) == 2:
        return "Other ccTLD/territory"
    return "Other gTLD/unknown"


def normalize_domain_fast(domain: Any) -> str:
    stripped = str(domain or "").strip().lower()
    if stripped.startswith("*."):
        stripped = stripped[2:]
    stripped = stripped.rstrip(".")
    if not stripped:
        return ""
    try:
        stripped.encode("ascii")
        return stripped
    except UnicodeEncodeError:
        try:
            return stripped.encode("idna").decode("ascii")
        except UnicodeError:
            return stripped


def tld_of_normalized(domain: str) -> str:
    parts = [part for part in domain.split(".") if part]
    if len(parts) == 4 and all(part.isdigit() and 0 <= int(part) <= 255 for part in parts):
        return "_ipv4"
    return parts[-1] if len(parts) > 1 else "_none"


def minute_from_event(event: dict[str, Any]) -> str | None:
    received_at = event.get("received_at")
    if isinstance(received_at, str) and len(received_at) >= 16:
        return f"{received_at[:16]}:00Z"

    timestamp = event_time(event, "received_at")
    if not timestamp:
        return None
    return timestamp.replace(second=0, microsecond=0).isoformat().replace("+00:00", "Z")


def domains_from_event(event: dict[str, Any]) -> list[str]:
    data = event.get("data")
    if isinstance(data, list):
        return [domain for domain in (normalize_domain_fast(item) for item in data) if domain]
    return event_domains(event)


def process_raw_file(
    raw_path: Path,
    cache_path: Path | None = None,
    tld_region_map: TldRegionMapping | None = None,
) -> pd.DataFrame:
    domain_sets: dict[tuple[str, str], set[str]] = defaultdict(set)
    occurrence_counts: Counter[tuple[str, str]] = Counter()
    event_counts: Counter[tuple[str, str]] = Counter()
    parsed_events = 0

    for event in iter_events(raw_path):
        minute = minute_from_event(event)
        domains = domains_from_event(event)
        if not minute or not domains:
            continue

        parsed_events += 1
        event_regions = set()
        for domain in domains:
            tld = tld_of_normalized(domain)
            region = tld_region_map.region_for_tld(tld) if tld_region_map else detailed_region_for_tld(tld)
            key = (minute, region)
            domain_sets[key].add(domain)
            occurrence_counts[key] += 1
            event_regions.add(region)
        for region in event_regions:
            event_counts[(minute, region)] += 1

    rows = []
    for minute, region in sorted(domain_sets):
        key = (minute, region)
        rows.append({
            "source_file": base_name(raw_path),
            "minute_utc": minute,
            "region_bucket": region,
            "unique_fqdn_count": len(domain_sets[key]),
            "domain_occurrences": occurrence_counts[key],
            "event_count": event_counts[key],
        })

    result = pd.DataFrame(
        rows,
        columns=[
            "source_file",
            "minute_utc",
            "region_bucket",
            "unique_fqdn_count",
            "domain_occurrences",
            "event_count",
        ],
    )
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(cache_path, index=False)

    print(f"  parsed {format_number(parsed_events)} events -> {format_number(len(result))} minute-region rows")
    return result


def load_or_build_minute_counts(
    rows: pd.DataFrame,
    cache_dir: Path,
    refresh_cache: bool,
    tld_region_map: TldRegionMapping | None = None,
) -> pd.DataFrame:
    tld_region_map = tld_region_map or TldRegionMapping.from_csv()
    partial_line_limit = int(os.environ.get("MAX_LINES", "0") or "0")
    cache_enabled = partial_line_limit == 0
    if not cache_enabled:
        print("MAX_LINES is set; cache reads/writes are disabled for this partial run.")

    frames = []
    for index, row in rows.iterrows():
        raw_path = Path(row["raw_path"])
        cache_path = cache_file_path(cache_dir, raw_path, tld_region_map.signature)
        print(f"[{index + 1}/{len(rows)}] {base_name(raw_path)}")
        if cache_enabled and cache_path.exists() and not refresh_cache:
            frame = pd.read_csv(cache_path)
            print(f"  cache hit -> {format_number(len(frame))} minute-region rows")
        else:
            frame = process_raw_file(raw_path, cache_path if cache_enabled else None, tld_region_map)
        frames.append(frame)

    if not frames:
        return pd.DataFrame()
    minute_counts = pd.concat(frames, ignore_index=True)
    if minute_counts.empty:
        return minute_counts
    minute_counts["minute_utc"] = pd.to_datetime(minute_counts["minute_utc"], utc=True)
    return minute_counts


def observed_minute_index(rows: pd.DataFrame) -> pd.DatetimeIndex:
    indexes = []
    for row in rows.itertuples(index=False):
        start = pd.Timestamp(row.scheduled_start_utc).floor("min")
        end = pd.Timestamp(row.scheduled_end_utc).floor("min")
        if end <= start:
            continue
        indexes.append(pd.date_range(start, end - pd.Timedelta(minutes=1), freq="min", tz="UTC"))
    if not indexes:
        return pd.DatetimeIndex([], tz="UTC")
    result = indexes[0]
    for index in indexes[1:]:
        result = result.union(index)
    return result.sort_values()


def minute_wide_frame(minute_counts: pd.DataFrame, minutes: pd.DatetimeIndex) -> pd.DataFrame:
    if minute_counts.empty:
        return pd.DataFrame(index=minutes, columns=REGION_COLUMNS).fillna(0)

    grouped = (
        minute_counts.groupby(["minute_utc", "region_bucket"], as_index=False)
        .agg(
            unique_fqdn_count=("unique_fqdn_count", "sum"),
            domain_occurrences=("domain_occurrences", "sum"),
            event_count=("event_count", "sum"),
        )
    )
    wide = grouped.pivot(index="minute_utc", columns="region_bucket", values="unique_fqdn_count")
    wide = wide.reindex(minutes, fill_value=0).fillna(0)
    for region in REGION_COLUMNS:
        if region not in wide.columns:
            wide[region] = 0
    return wide[REGION_COLUMNS].sort_index()


def business_mask(index: pd.DatetimeIndex, timezone: str, start_hour: int, end_hour: int) -> pd.Series:
    local = index.tz_convert(timezone)
    return pd.Series(
        (local.weekday < 5) & (local.hour >= start_hour) & (local.hour < end_hour),
        index=index,
    )


def add_business_flags(
    rate_df: pd.DataFrame,
    start_hour: int,
    end_hour: int,
) -> pd.DataFrame:
    result = rate_df.copy()
    bucket_index = pd.DatetimeIndex(result["bucket_utc"])
    for window in BUSINESS_WINDOWS:
        mask = business_mask(bucket_index, window["timezone"], start_hour, end_hour)
        result[window["flag"]] = mask.to_numpy()
    return result


def business_rate_summary(
    minute_wide: pd.DataFrame,
    start_hour: int,
    end_hour: int,
) -> pd.DataFrame:
    rows = []
    for window in BUSINESS_WINDOWS:
        region = window["region_bucket"]
        mask = business_mask(minute_wide.index, window["timezone"], start_hour, end_hour)
        values = minute_wide[region]
        business_values = values[mask]
        off_values = values[~mask]
        business_mean = float(business_values.mean()) if len(business_values) else 0.0
        off_mean = float(off_values.mean()) if len(off_values) else 0.0
        rows.append({
            "region_bucket": region,
            "timezone": window["timezone"],
            "business_window": f"Mon-Fri {start_hour:02d}:00-{end_hour:02d}:00 local",
            "business_minutes": int(mask.sum()),
            "off_hours_minutes": int((~mask).sum()),
            "business_unique_fqdns_per_minute": round(business_mean, 3),
            "off_hours_unique_fqdns_per_minute": round(off_mean, 3),
            "business_rate_unique_fqdns_per_hour": round(business_mean * 60, 3),
            "off_hours_rate_unique_fqdns_per_hour": round(off_mean * 60, 3),
            "business_lift_vs_off_hours": round(business_mean / off_mean, 4) if off_mean else pd.NA,
            "business_total_unique_fqdn_minute_sum": int(business_values.sum()),
            "off_hours_total_unique_fqdn_minute_sum": int(off_values.sum()),
        })
    return pd.DataFrame(rows)


def minute_derived_hourly_rate_frame(minute_wide: pd.DataFrame, bucket_freq: str) -> pd.DataFrame:
    """Scale mean per-minute unique counts to an hourly observation rate.

    This is a minute-derived rate, not a count of FQDNs deduplicated across an
    entire hour. Canonical hourly unique-FQDN counts are produced by analysis
    11, which deduplicates normalized FQDNs within each one-hour window.
    """
    observed_minutes = minute_wide[REGION_COLUMNS[0]].resample(bucket_freq).size().rename("observed_minutes")
    rates = minute_wide.resample(bucket_freq).mean().mul(60)
    rates = rates[observed_minutes > 0]
    observed_minutes = observed_minutes[observed_minutes > 0]
    result = rates.reset_index(names="bucket_utc")
    result.insert(1, "observed_minutes", observed_minutes.to_numpy())
    for region in REGION_COLUMNS:
        result[region] = result[region].round(3)
    return result


def correlation_matrix(rate_df: pd.DataFrame, regions: list[str], method: str = "pearson") -> pd.DataFrame:
    values = rate_df[regions]
    if method == "spearman":
        values = values.rank()
    return values.corr(method="pearson").round(4)


def pair_correlation(left: pd.Series, right: pd.Series, method: str = "pearson") -> Any:
    aligned = pd.concat([left, right], axis=1).dropna()
    if len(aligned) < 3:
        return pd.NA
    left_values = aligned.iloc[:, 0]
    right_values = aligned.iloc[:, 1]
    if method == "spearman":
        left_values = left_values.rank()
        right_values = right_values.rank()
    value = left_values.corr(right_values, method="pearson")
    return round(float(value), 4) if pd.notna(value) else pd.NA


def windowed_correlations(rate_df: pd.DataFrame, regions: list[str]) -> pd.DataFrame:
    filters: list[tuple[str, pd.Series]] = [
        ("all_observed", pd.Series(True, index=rate_df.index)),
    ]
    flag_by_label = {window["label"]: window["flag"] for window in BUSINESS_WINDOWS}
    for label, flag in flag_by_label.items():
        filters.append((f"{label} business", rate_df[flag].astype(bool)))
    for i, left_label in enumerate(flag_by_label):
        for right_label in list(flag_by_label)[i + 1:]:
            filters.append((
                f"{left_label} and {right_label} business",
                rate_df[flag_by_label[left_label]].astype(bool)
                & rate_df[flag_by_label[right_label]].astype(bool),
            ))

    rows = []
    for label, mask in filters:
        subset = rate_df[mask].copy()
        for i, left in enumerate(regions):
            for right in regions[i + 1:]:
                rows.append({
                    "window": label,
                    "bucket_count": len(subset),
                    "left_region": left,
                    "right_region": right,
                    "pearson": pair_correlation(subset[left], subset[right], "pearson"),
                    "spearman": pair_correlation(subset[left], subset[right], "spearman"),
                })
    return pd.DataFrame(rows)


def local_hour_profiles(
    minute_wide: pd.DataFrame,
    start_hour: int,
    end_hour: int,
) -> pd.DataFrame:
    rows = []
    for window in BUSINESS_WINDOWS:
        local = minute_wide.index.tz_convert(window["timezone"])
        profile = pd.DataFrame({
            "value": minute_wide[window["region_bucket"]].to_numpy(),
            "local_weekday": local.weekday,
            "local_hour": local.hour,
        })
        grouped = (
            profile.groupby(["local_weekday", "local_hour"], as_index=False)
            .agg(
                observed_minutes=("value", "size"),
                mean_unique_fqdns_per_minute=("value", "mean"),
            )
        )
        for item in grouped.itertuples(index=False):
            rows.append({
                "region_bucket": window["region_bucket"],
                "timezone": window["timezone"],
                "local_weekday": WEEKDAY_NAMES[int(item.local_weekday)],
                "local_weekday_num": int(item.local_weekday),
                "local_hour": int(item.local_hour),
                "is_business_hour": (
                    int(item.local_weekday) < 5
                    and start_hour <= int(item.local_hour) < end_hour
                ),
                "observed_minutes": int(item.observed_minutes),
                "mean_unique_fqdns_per_minute": round(float(item.mean_unique_fqdns_per_minute), 3),
                "rate_unique_fqdns_per_hour": round(float(item.mean_unique_fqdns_per_minute) * 60, 3),
            })
    return pd.DataFrame(rows)


def profile_correlations(profile_df: pd.DataFrame) -> pd.DataFrame:
    keys = ["local_weekday_num", "local_hour"]
    series_by_label = {}
    for (region, timezone), group in profile_df.groupby(["region_bucket", "timezone"]):
        label = f"{region} / {timezone}"
        series = group.set_index(keys)["rate_unique_fqdns_per_hour"].sort_index()
        series_by_label[label] = series

    aligned = pd.DataFrame(series_by_label).dropna()
    rows = []
    labels = list(aligned.columns)
    for i, left in enumerate(labels):
        for right in labels[i + 1:]:
            rows.append({
                "left_profile": left,
                "right_profile": right,
                "aligned_weekday_hour_points": len(aligned),
                "pearson": pair_correlation(aligned[left], aligned[right], "pearson"),
                "spearman": pair_correlation(aligned[left], aligned[right], "spearman"),
            })
    return pd.DataFrame(rows)


def period_rate_frame(
    rate_df: pd.DataFrame,
    period: str,
    display_time_zone: str = "Europe/Berlin",
) -> pd.DataFrame:
    if period not in {"weekday", "weekend"}:
        raise ValueError(f"Unsupported rate period: {period}")

    result = rate_df.copy()
    result["_display_time"] = pd.to_datetime(result["bucket_utc"], utc=True).dt.tz_convert(display_time_zone)
    result["_display_date"] = result["_display_time"].dt.date
    result["_display_weekday"] = result["_display_time"].dt.weekday

    is_weekend = result["_display_weekday"] >= 5
    result = result[is_weekend if period == "weekend" else ~is_weekend].copy()
    return result


def save_period_rate_chart(
    rate_df: pd.DataFrame,
    output_path: Path,
    *,
    period: str,
    bucket_freq: str,
    display_time_zone: str = "Europe/Berlin",
) -> bool:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    chart_df = period_rate_frame(rate_df, period, display_time_zone)
    if chart_df.empty:
        return False

    period_label = "Weekend" if period == "weekend" else "Weekday"
    dates = sorted(chart_df["_display_date"].unique())
    fig_width = 10.2 if period == "weekend" else 14.2
    fig, ax = plt.subplots(figsize=(fig_width, 6.4))

    for index, region in enumerate(REGION_COLUMNS):
        ax.plot(
            chart_df["_display_time"],
            chart_df[region] / 1_000_000,
            label=region,
            color=COLORS[index % len(COLORS)],
            linewidth=2,
        )

    x_start = pd.Timestamp(dates[0]).tz_localize(display_time_zone)
    x_end = pd.Timestamp(dates[-1]).tz_localize(display_time_zone) + pd.Timedelta(days=1)
    major_ticks = [pd.Timestamp(date).tz_localize(display_time_zone) for date in dates]
    major_labels = [tick.strftime("%a\n%m-%d") for tick in major_ticks]
    minor_ticks = [
        pd.Timestamp(date).tz_localize(display_time_zone) + pd.Timedelta(hours=hour)
        for date in dates
        for hour in (6, 12, 18)
    ]

    ax.set_xlim(x_start, x_end)
    ax.set_xticks(major_ticks)
    ax.set_xticklabels(major_labels)
    ax.set_xticks(minor_ticks, minor=True)
    ax.xaxis.set_minor_formatter(mdates.DateFormatter("%H:%M", tz=chart_df["_display_time"].dt.tz))
    ax.tick_params(axis="x", which="major", pad=18)
    ax.tick_params(axis="x", which="minor", labelsize=8, pad=2, length=3)
    ax.set_xlabel(f"Local time ({display_time_zone})")
    ax.set_ylabel("Minute-derived FQDN rate (millions/hour)")
    ax.set_title(f"Minute-Derived FQDN Observation Rate by TLD Region - {period_label}", loc="left", fontsize=16, pad=22)
    ax.legend(ncols=2, loc="upper center", bbox_to_anchor=(0.5, -0.16), frameon=False)
    ax.grid(axis="y")
    ax.grid(axis="x", which="major", color="#dde6ed")
    ax.grid(axis="x", which="minor", color="#eef3f6", linewidth=0.6)
    fig.tight_layout()
    fig.savefig(output_path, format=output_path.suffix.lstrip(".") or "svg", bbox_inches="tight")
    plt.close(fig)
    return True


def _configure_period_axis(
    ax: Any,
    chart_df: pd.DataFrame,
    *,
    panel_title: str,
    display_time_zone: str,
    y_limit: tuple[float, float],
) -> None:
    import matplotlib.dates as mdates

    dates = sorted(chart_df["_display_date"].unique())
    for index, region in enumerate(REGION_COLUMNS):
        ax.plot(
            chart_df["_display_time"],
            chart_df[region] / 1_000_000,
            label=region,
            color=COLORS[index % len(COLORS)],
            linewidth=1.9,
        )

    x_start = pd.Timestamp(dates[0]).tz_localize(display_time_zone)
    x_end = pd.Timestamp(dates[-1]).tz_localize(display_time_zone) + pd.Timedelta(days=1)
    major_ticks = [pd.Timestamp(date).tz_localize(display_time_zone) for date in dates]
    major_labels = [tick.strftime("%a\n%m-%d") for tick in major_ticks]
    minor_ticks = [
        pd.Timestamp(date).tz_localize(display_time_zone) + pd.Timedelta(hours=hour)
        for date in dates
        for hour in (6, 12, 18)
    ]

    ax.set_xlim(x_start, x_end)
    ax.set_ylim(*y_limit)
    ax.set_xticks(major_ticks)
    ax.set_xticklabels(major_labels)
    ax.set_xticks(minor_ticks, minor=True)
    ax.xaxis.set_minor_formatter(mdates.DateFormatter("%H:%M", tz=chart_df["_display_time"].dt.tz))
    ax.tick_params(axis="x", which="major", pad=18)
    ax.tick_params(axis="x", which="minor", labelsize=8, pad=2, length=3)
    ax.set_xlabel(f"Local time ({display_time_zone})")
    ax.set_title(panel_title, loc="left", fontsize=12, pad=10)
    ax.grid(axis="y")
    ax.grid(axis="x", which="major", color="#dde6ed")
    ax.grid(axis="x", which="minor", color="#eef3f6", linewidth=0.6)


def save_combined_period_rate_chart(
    rate_df: pd.DataFrame,
    output_path: Path,
    *,
    display_time_zone: str = "Europe/Berlin",
    show_title: bool = True,
) -> bool:
    import matplotlib.pyplot as plt

    weekday_df = period_rate_frame(rate_df, "weekday", display_time_zone)
    weekend_df = period_rate_frame(rate_df, "weekend", display_time_zone)
    if weekday_df.empty or weekend_df.empty:
        return False

    y_max = max(
        float(weekday_df[REGION_COLUMNS].max().max()),
        float(weekend_df[REGION_COLUMNS].max().max()),
    ) / 1_000_000
    y_limit = (0.0, y_max * 1.08 if y_max > 0 else 1.0)

    fig, axes = plt.subplots(2, 1, figsize=(14.2, 9.2), sharey=True)
    _configure_period_axis(
        axes[0],
        weekday_df,
        panel_title="(a) Weekdays",
        display_time_zone=display_time_zone,
        y_limit=y_limit,
    )
    _configure_period_axis(
        axes[1],
        weekend_df,
        panel_title="(b) Weekend",
        display_time_zone=display_time_zone,
        y_limit=y_limit,
    )

    handles, labels = axes[0].get_legend_handles_labels()
    layout_top = 0.95
    if show_title:
        fig.suptitle(
            "Minute-Derived FQDN Observation Rate by TLD Region",
            x=0.08,
            y=0.985,
            ha="left",
            fontsize=17,
            fontweight="bold",
        )
    else:
        layout_top = 0.985
    fig.text(
        0.015,
        0.5,
        "Minute-derived FQDN rate (millions/hour)",
        va="center",
        rotation="vertical",
        fontsize=11,
        color="#1f2933",
    )
    fig.legend(
        handles,
        labels,
        ncols=min(4, len(labels)),
        loc="lower center",
        bbox_to_anchor=(0.5, 0.01),
        frameon=False,
    )
    fig.tight_layout(rect=(0.035, 0.07, 1.0, layout_top))
    fig.savefig(output_path, format=output_path.suffix.lstrip(".") or "svg", bbox_inches="tight")
    plt.close(fig)
    return True


def save_correlation_heatmap(corr: pd.DataFrame, output_path: Path, title: str, subtitle: str) -> None:
    import matplotlib.pyplot as plt

    size = max(7.2, 0.8 * len(corr.columns) + 2.0)
    fig, ax = plt.subplots(figsize=(size, size * 0.82))
    image = ax.imshow(corr.to_numpy(), vmin=-1, vmax=1, cmap="coolwarm")
    ax.set_xticks(range(len(corr.columns)))
    ax.set_xticklabels(corr.columns, rotation=35, ha="right")
    ax.set_yticks(range(len(corr.index)))
    ax.set_yticklabels(corr.index)
    ax.set_title(title, loc="left", fontsize=15, pad=24)
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=9, color="#53606b")
    for row in range(len(corr.index)):
        for col in range(len(corr.columns)):
            value = corr.iloc[row, col]
            ax.text(col, row, f"{value:.2f}", ha="center", va="center", fontsize=9, color="#1f2933")
    fig.colorbar(image, ax=ax, shrink=0.82, label="correlation")
    fig.tight_layout()
    fig.savefig(output_path, format=output_path.suffix.lstrip(".") or "svg", bbox_inches="tight")
    plt.close(fig)


def save_business_lift_chart(summary: pd.DataFrame, output_path: Path) -> None:
    chart_df = summary.copy()
    chart_df["label"] = chart_df["region_bucket"] + " / " + chart_df["timezone"].str.split("/").str[-1].str.replace("_", " ")
    chart_df["value_text"] = chart_df["business_lift_vs_off_hours"].map(
        lambda value: "n/a" if pd.isna(value) else f"{float(value):.2f}x"
    )
    chart_df["business_lift_vs_off_hours"] = pd.to_numeric(chart_df["business_lift_vs_off_hours"], errors="coerce").fillna(0)
    chart_df["color"] = [COLORS[index % len(COLORS)] for index in range(len(chart_df))]
    save_bar_chart(
        chart_df,
        label_col="label",
        value_col="business_lift_vs_off_hours",
        value_text_col="value_text",
        title="Business-Hour Lift by Regional TLD Proxy",
        subtitle="Mon-Fri local business hours compared with all other observed minutes",
        output_path=output_path,
        value_label="business/off-hours rate ratio",
    )


def write_manifest_summary(rows: pd.DataFrame, output_path: Path) -> None:
    summary = pd.DataFrame([{
        "selected_windows": len(rows),
        "scheduled_start_utc": rows["scheduled_start_utc"].min(),
        "scheduled_end_utc": rows["scheduled_end_utc"].max(),
        "planned_hours": round(float(rows.get("planned_seconds", pd.Series(dtype=float)).fillna(0).sum()) / 3600, 3)
        if "planned_seconds" in rows.columns else pd.NA,
        "messages": int(rows.get("messages", pd.Series(dtype=float)).fillna(0).sum())
        if "messages" in rows.columns else pd.NA,
        "domains": int(rows.get("domains", pd.Series(dtype=float)).fillna(0).sum())
        if "domains" in rows.columns else pd.NA,
        "first_file": rows["file"].astype(str).iloc[0],
        "last_file": rows["file"].astype(str).iloc[-1],
    }])
    write_csv(summary, output_path)


def main() -> None:
    args = parse_args()
    if not 0 <= args.business_start_hour < args.business_end_hour <= 24:
        raise ValueError("Business hours must satisfy 0 <= start < end <= 24.")

    output_dir = resolve_project_path(args.output_dir) if args.output_dir else get_output_dir()
    if output_dir is None:
        output_dir = get_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(args.cache_dir).resolve()
    tld_region_map = TldRegionMapping.from_csv(args.tld_region_map)

    manifest_rows = selected_manifest_rows(args)
    write_manifest_summary(manifest_rows, output_dir / "weekly_domain_only_manifest_summary.csv")
    print(
        "Selected "
        f"{format_number(len(manifest_rows))} windows from "
        f"{manifest_rows['scheduled_start_utc'].min()} to {manifest_rows['scheduled_end_utc'].max()}"
    )
    print(f"Using TLD region mapping {tld_region_map.path}")

    minute_counts = load_or_build_minute_counts(manifest_rows, cache_dir, args.refresh_cache, tld_region_map)
    minutes = observed_minute_index(manifest_rows)
    minute_wide = minute_wide_frame(minute_counts, minutes)
    minute_rates = minute_wide.reset_index(names="minute_utc")
    write_csv(minute_rates, output_dir / "weekly_region_minute_rates.csv")

    minute_derived_hourly_rates = minute_derived_hourly_rate_frame(minute_wide, args.bucket_freq)
    minute_derived_hourly_rates = add_business_flags(
        minute_derived_hourly_rates,
        args.business_start_hour,
        args.business_end_hour,
    )
    write_csv(
        minute_derived_hourly_rates,
        output_dir / "weekly_region_minute_derived_hourly_rates.csv",
    )

    if args.rate_period == "both":
        output_path = output_dir / "weekly_region_minute_derived_hourly_rates.svg"
        if save_combined_period_rate_chart(
            minute_derived_hourly_rates,
            output_path,
            display_time_zone=args.rate_time_zone,
        ):
            print(f"Wrote {output_path}")
        else:
            print(f"Skipped {output_path}; weekday or weekend hourly rows were missing.")
    else:
        period = args.rate_period
        output_path = output_dir / f"weekly_region_minute_derived_hourly_rates_{period}.svg"
        if save_period_rate_chart(
            minute_derived_hourly_rates,
            output_path,
            period=period,
            bucket_freq=args.bucket_freq,
            display_time_zone=args.rate_time_zone,
        ):
            print(f"Wrote {output_path}")
        else:
            print(f"Skipped {output_path}; no {period} hourly rows matched the selected windows.")

    print(f"Wrote {output_dir / 'weekly_domain_only_manifest_summary.csv'}")
    print(f"Wrote {output_dir / 'weekly_region_minute_rates.csv'}")
    print(f"Wrote {output_dir / 'weekly_region_minute_derived_hourly_rates.csv'}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise
