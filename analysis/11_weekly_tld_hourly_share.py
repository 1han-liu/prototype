#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from tld_region_mapping import resolve_mapping_path

SCRIPT_DIR = Path(__file__).resolve().parent
WEEKLY_SCRIPT = SCRIPT_DIR / "06_weekly_business_hour_correlation.py"
TLD_HOURLY_CACHE_VERSION = "weekly-tld-hourly-v1"

ANALYSIS_GROUPS = [
    ("global_tld", "Global/non-regional TLD"),
    ("regional_tld", "ccTLD/geographic TLD"),
]
CANONICAL_REGION_COLUMNS = [
    "Global",
    "Europe",
    "Americas",
    "Asia",
    "Africa",
    "Oceania",
    "Antarctica",
]
PANEL_TITLES = {
    "Global/non-regional TLD": "Top global TLDs",
    "ccTLD/geographic TLD": "Top regional TLDs",
}


def load_weekly_module() -> Any:
    spec = importlib.util.spec_from_file_location("weekly_business_hour_correlation", WEEKLY_SCRIPT)
    if not spec or not spec.loader:
        raise ImportError(f"Unable to load {WEEKLY_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


weekly = load_weekly_module()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate one top-TLD hourly share figure over the weekly domain-only sample. "
            "The figure has one panel for global gTLDs and one panel for ccTLD/geographic TLDs."
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
        default=os.environ.get("CACHE_DIR", str(weekly.ROOT_DIR / ".cache" / "analysis" / "weekly_tld_hourly")),
        help="Directory for per-raw-file hourly TLD cache CSV files.",
    )
    parser.add_argument(
        "--tld-region-map",
        default=os.environ.get("TLD_REGION_MAP", "figures/weekly_tld_region_mapping.csv"),
        help="CSV mapping TLDs to class/continent values. Defaults to figures/weekly_tld_region_mapping.csv.",
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
        help="Pandas resample frequency for the TLD time series. Default: 1h.",
    )
    parser.add_argument(
        "--top-n-per-group",
        type=int,
        default=int(os.environ.get("TOP_N_PER_GROUP", "5") or "5"),
        help="Number of TLDs to plot per panel. Default: 5.",
    )
    parser.add_argument(
        "--display-time-zone",
        default=os.environ.get("DISPLAY_TIME_ZONE", "Europe/Berlin"),
        help="Time zone used for x-axis labels. Default: Europe/Berlin.",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Rebuild per-file hourly TLD cache files even when cache exists.",
    )
    return parser.parse_args()


def cache_file_path(cache_dir: Path, raw_path: Path, bucket_freq: str) -> Path:
    stat = raw_path.stat()
    try:
        rel = raw_path.resolve().relative_to(weekly.ROOT_DIR).as_posix()
    except ValueError:
        rel = raw_path.name
    digest = hashlib.sha1(
        f"{TLD_HOURLY_CACHE_VERSION}:{bucket_freq}:{raw_path.resolve()}:{stat.st_size}:{int(stat.st_mtime)}".encode(
            "utf-8"
        )
    ).hexdigest()[:16]
    safe_name = rel.replace("/", "__").replace(":", "-")
    return cache_dir / f"{TLD_HOURLY_CACHE_VERSION}__{safe_name}__{digest}.csv"


def bucket_from_event(event: dict[str, Any], bucket_freq: str) -> str | None:
    received_at = event.get("received_at")
    if bucket_freq == "1h" and isinstance(received_at, str) and len(received_at) >= 13:
        return f"{received_at[:13]}:00:00Z"

    minute = weekly.minute_from_event(event)
    if not minute:
        return None
    return pd.Timestamp(minute).floor(bucket_freq).isoformat().replace("+00:00", "Z")


def process_raw_file(raw_path: Path, bucket_freq: str, cache_path: Path | None = None) -> pd.DataFrame:
    domains_by_bucket_tld: dict[tuple[str, str], set[str]] = defaultdict(set)
    occurrence_counts: Counter[tuple[str, str]] = Counter()
    parsed_events = 0

    for event in weekly.iter_events(raw_path):
        bucket = bucket_from_event(event, bucket_freq)
        domains = weekly.domains_from_event(event)
        if not bucket or not domains:
            continue

        parsed_events += 1
        for domain in domains:
            tld = weekly.tld_of_normalized(domain)
            if not tld:
                continue
            key = (bucket, tld)
            domains_by_bucket_tld[key].add(domain)
            occurrence_counts[key] += 1

    rows = []
    for bucket, tld in sorted(domains_by_bucket_tld):
        key = (bucket, tld)
        rows.append({
            "source_file": weekly.base_name(raw_path),
            "bucket_utc": bucket,
            "tld": tld,
            "unique_fqdn_count": len(domains_by_bucket_tld[key]),
            "domain_occurrences": occurrence_counts[key],
        })

    result = pd.DataFrame(
        rows,
        columns=["source_file", "bucket_utc", "tld", "unique_fqdn_count", "domain_occurrences"],
    )
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(cache_path, index=False)

    print(f"  parsed {weekly.format_number(parsed_events)} events -> {weekly.format_number(len(result))} TLD-hour rows")
    return result


def load_or_build_hourly_tld_counts(
    rows: pd.DataFrame,
    cache_dir: Path,
    bucket_freq: str,
    refresh_cache: bool,
) -> pd.DataFrame:
    partial_line_limit = int(os.environ.get("MAX_LINES", "0") or "0")
    cache_enabled = partial_line_limit == 0
    if not cache_enabled:
        print("MAX_LINES is set; cache reads/writes are disabled for this partial run.")

    frames = []
    for index, row in rows.iterrows():
        raw_path = Path(row["raw_path"])
        cache_path = cache_file_path(cache_dir, raw_path, bucket_freq)
        print(f"[{index + 1}/{len(rows)}] {weekly.base_name(raw_path)}")
        if cache_enabled and cache_path.exists() and not refresh_cache:
            frame = pd.read_csv(cache_path)
            print(f"  cache hit -> {weekly.format_number(len(frame))} TLD-hour rows")
        else:
            frame = process_raw_file(raw_path, bucket_freq, cache_path if cache_enabled else None)
        frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=["bucket_utc", "tld", "unique_fqdn_count", "domain_occurrences"])

    result = pd.concat(frames, ignore_index=True)
    if result.empty:
        return result

    result["bucket_utc"] = pd.to_datetime(result["bucket_utc"], utc=True)
    return (
        result.groupby(["bucket_utc", "tld"], as_index=False)
        .agg(
            unique_fqdn_count=("unique_fqdn_count", "sum"),
            domain_occurrences=("domain_occurrences", "sum"),
        )
        .sort_values(["bucket_utc", "tld"])
    )


def observed_bucket_index(rows: pd.DataFrame, bucket_freq: str) -> pd.DatetimeIndex:
    minutes = weekly.observed_minute_index(rows)
    if minutes.empty:
        return pd.DatetimeIndex([], tz="UTC")
    return pd.DatetimeIndex(minutes.floor(bucket_freq).unique()).sort_values()


def load_mapping(mapping_path_value: str) -> pd.DataFrame:
    mapping_path = resolve_mapping_path(mapping_path_value)
    mapping = pd.read_csv(mapping_path)
    required = {"tld", "mapped_tld_class", "mapped_continent", "mapped_region_bucket"}
    missing = sorted(required.difference(mapping.columns))
    if missing:
        raise ValueError(f"TLD region mapping is missing required columns: {', '.join(missing)}")
    return mapping


def analysis_group(mapped_tld_class: Any) -> str:
    label = str(mapped_tld_class or "")
    if label in {"global_gTLD", "globalized_ccTLD"}:
        return "Global/non-regional TLD"
    if label in {"ccTLD", "geographic_gTLD"}:
        return "ccTLD/geographic TLD"
    return "Other"


def enrich_hourly_counts(hourly_counts: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    mapping_cols = [
        "tld",
        "tld_label",
        "idn_unicode",
        "mapped_tld_class",
        "mapped_country_or_territory",
        "mapped_continent",
        "mapped_region_bucket",
    ]
    available_cols = [column for column in mapping_cols if column in mapping.columns]
    enriched = hourly_counts.merge(mapping[available_cols], on="tld", how="left")
    enriched["tld_label"] = enriched["tld_label"].fillna("." + enriched["tld"].astype(str))
    enriched["mapped_tld_class"] = enriched["mapped_tld_class"].fillna("global_gTLD")
    enriched["mapped_continent"] = enriched["mapped_continent"].fillna("Global")
    enriched["mapped_region_bucket"] = enriched["mapped_region_bucket"].fillna("Global/non-regional TLD")
    enriched["analysis_group"] = enriched["mapped_tld_class"].map(analysis_group)

    totals = (
        enriched.groupby("bucket_utc", as_index=False)["unique_fqdn_count"]
        .sum()
        .rename(columns={"unique_fqdn_count": "total_unique_fqdn_count"})
    )
    enriched = enriched.merge(totals, on="bucket_utc", how="left")
    enriched["unique_fqdn_share"] = enriched["unique_fqdn_count"] / enriched["total_unique_fqdn_count"]
    enriched["unique_fqdn_share_pct"] = (enriched["unique_fqdn_share"] * 100).round(4)
    return enriched


def canonical_hourly_region_counts(
    enriched: pd.DataFrame,
    buckets: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Aggregate canonical one-hour unique-FQDN counts by mapped region.

    ``enriched`` is already deduplicated by (hour, TLD, normalized FQDN).
    Because every normalized FQDN has exactly one TLD, summing the per-TLD
    counts preserves one-hour deduplication while producing regional totals.
    """
    required = {
        "bucket_utc",
        "analysis_group",
        "mapped_continent",
        "unique_fqdn_count",
    }
    missing = sorted(required.difference(enriched.columns))
    if missing:
        raise ValueError(f"Hourly TLD data is missing required columns: {', '.join(missing)}")

    canonical = enriched.copy()
    canonical["bucket_utc"] = pd.to_datetime(canonical["bucket_utc"], utc=True)
    canonical["canonical_region"] = canonical["mapped_continent"]
    canonical.loc[
        canonical["analysis_group"] == "Global/non-regional TLD",
        "canonical_region",
    ] = "Global"

    unexpected_regions = sorted(
        set(canonical["canonical_region"].dropna().astype(str)).difference(CANONICAL_REGION_COLUMNS)
    )
    if unexpected_regions:
        raise ValueError(
            "Canonical hourly aggregation encountered unmapped regions: "
            + ", ".join(unexpected_regions)
        )

    grouped = (
        canonical.groupby(["bucket_utc", "canonical_region"], as_index=False)["unique_fqdn_count"]
        .sum()
        .pivot(index="bucket_utc", columns="canonical_region", values="unique_fqdn_count")
        .reindex(index=buckets, columns=CANONICAL_REGION_COLUMNS)
        .fillna(0)
        .astype("int64")
    )

    source_totals = (
        canonical.groupby("bucket_utc")["unique_fqdn_count"]
        .sum()
        .reindex(buckets, fill_value=0)
        .astype("int64")
    )
    regional_totals = grouped.sum(axis=1).astype("int64")
    if not regional_totals.equals(source_totals):
        mismatched = int((regional_totals != source_totals).sum())
        raise ValueError(
            f"Canonical regional totals do not match hourly TLD totals in {mismatched} buckets."
        )

    result = grouped.reset_index(names="bucket_utc")
    result.insert(1, "total_unique_fqdn_count", regional_totals.to_numpy())
    return result


def summarize_canonical_hourly_regions(
    regional_hourly: pd.DataFrame,
    display_time_zone: str,
) -> pd.DataFrame:
    """Build the reproducible summary used by paper Table 2.

    Weekday/weekend membership and the weekday clock-hour profile use one
    common reference timezone. The peak value is the mean across weekday
    observations at the reported local clock hour, not the largest individual
    one-hour observation.
    """
    required = {"bucket_utc", *CANONICAL_REGION_COLUMNS}
    missing = sorted(required.difference(regional_hourly.columns))
    if missing:
        raise ValueError(f"Canonical regional data is missing columns: {', '.join(missing)}")

    summary_source = regional_hourly.copy()
    summary_source["bucket_utc"] = pd.to_datetime(summary_source["bucket_utc"], utc=True)
    local_time = summary_source["bucket_utc"].dt.tz_convert(display_time_zone)
    weekday_mask = local_time.dt.weekday < 5

    rows = []
    for region in CANONICAL_REGION_COLUMNS:
        values = pd.to_numeric(summary_source[region], errors="raise")
        weekday_profile = (
            pd.DataFrame({"value": values[weekday_mask].to_numpy(), "local_hour": local_time[weekday_mask].dt.hour})
            .groupby("local_hour")["value"]
            .mean()
        )
        if weekday_profile.empty:
            raise ValueError(f"No weekday observations available for region {region}.")

        peak_hour = int(weekday_profile.idxmax())
        rows.append({
            "region_bucket": region,
            "reference_time_zone": display_time_zone,
            "observed_hour_buckets": int(len(values)),
            "weekday_hour_buckets": int(weekday_mask.sum()),
            "weekend_hour_buckets": int((~weekday_mask).sum()),
            "overall_mean_unique_fqdns_per_hour": int(round(float(values.mean()))),
            "min_unique_fqdns_per_hour": int(values.min()),
            "max_unique_fqdns_per_hour": int(values.max()),
            "weekday_peak_hour": f"{peak_hour:02d}:00",
            "weekday_peak_mean_unique_fqdns_per_hour": int(round(float(weekday_profile.loc[peak_hour]))),
            "weekday_mean_unique_fqdns_per_hour": int(round(float(values[weekday_mask].mean()))),
            "weekend_mean_unique_fqdns_per_hour": int(round(float(values[~weekday_mask].mean()))),
        })

    return pd.DataFrame(rows)


def select_top_tlds(enriched: pd.DataFrame, top_n_per_group: int) -> pd.DataFrame:
    total_unique_fqdns = int(enriched["unique_fqdn_count"].sum())
    totals = (
        enriched[enriched["analysis_group"].isin([label for _, label in ANALYSIS_GROUPS])]
        .groupby(["analysis_group", "tld", "tld_label", "mapped_tld_class", "mapped_continent"], as_index=False)
        .agg(
            selected_unique_fqdn_sum=("unique_fqdn_count", "sum"),
            selected_domain_occurrences=("domain_occurrences", "sum"),
        )
        .sort_values(["analysis_group", "selected_unique_fqdn_sum", "selected_domain_occurrences", "tld"], ascending=[True, False, False, True])
    )
    totals["weekly_unique_fqdn_share_pct"] = (
        totals["selected_unique_fqdn_sum"] / total_unique_fqdns * 100
    ).round(4)
    return (
        totals.groupby("analysis_group", group_keys=False)
        .head(top_n_per_group)
        .sort_values(["analysis_group", "selected_unique_fqdn_sum"], ascending=[True, False])
        .reset_index(drop=True)
    )


def selected_time_series(
    enriched: pd.DataFrame,
    selected_tlds: pd.DataFrame,
    buckets: pd.DatetimeIndex,
) -> pd.DataFrame:
    if selected_tlds.empty:
        return pd.DataFrame()

    selected_rows = []
    totals = enriched.groupby("bucket_utc")["total_unique_fqdn_count"].max().reindex(buckets, fill_value=0)
    metadata = selected_tlds.set_index("tld").to_dict(orient="index")
    indexed = enriched[enriched["tld"].isin(selected_tlds["tld"])].set_index(["bucket_utc", "tld"])

    for tld, item in metadata.items():
        for bucket in buckets:
            if (bucket, tld) in indexed.index:
                row = indexed.loc[(bucket, tld)]
                unique_count = int(row["unique_fqdn_count"])
                occurrence_count = int(row["domain_occurrences"])
            else:
                unique_count = 0
                occurrence_count = 0
            total = int(totals.loc[bucket]) if bucket in totals.index else 0
            share = unique_count / total if total else 0.0
            selected_rows.append({
                "bucket_utc": bucket,
                "analysis_group": item["analysis_group"],
                "tld": tld,
                "tld_label": item["tld_label"],
                "mapped_tld_class": item["mapped_tld_class"],
                "mapped_continent": item["mapped_continent"],
                "unique_fqdn_count": unique_count,
                "domain_occurrences": occurrence_count,
                "total_unique_fqdn_count": total,
                "unique_fqdn_share": round(share, 6),
                "unique_fqdn_share_pct": round(share * 100, 4),
            })

    return pd.DataFrame(selected_rows).sort_values(["analysis_group", "tld", "bucket_utc"])


def save_top_tld_share_chart(
    selected_series: pd.DataFrame,
    output_path: Path,
    *,
    bucket_freq: str,
    display_time_zone: str,
    show_title: bool = True,
) -> None:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    if selected_series.empty:
        raise ValueError("No selected TLD rows to plot.")

    color_palette = weekly.COLORS + [
        "#4477aa",
        "#cc6677",
        "#228833",
        "#aa3377",
        "#66ccee",
        "#ee6677",
    ]
    fig, axes = plt.subplots(
        nrows=2,
        ncols=1,
        figsize=(13.8, 9.3),
        sharex=True,
        gridspec_kw={"hspace": 0.48},
    )
    x_min = pd.to_datetime(selected_series["bucket_utc"], utc=True).min().tz_convert(display_time_zone)
    x_max = pd.to_datetime(selected_series["bucket_utc"], utc=True).max().tz_convert(display_time_zone)

    color_offset = 0
    for panel_index, (ax, (_, group_label)) in enumerate(zip(axes, ANALYSIS_GROUPS, strict=False)):
        group_df = selected_series[selected_series["analysis_group"] == group_label].copy()
        legend_handles = []
        legend_labels = []
        for index, (tld_label, tld_df) in enumerate(group_df.groupby("tld_label", sort=False)):
            x_values = pd.to_datetime(tld_df["bucket_utc"], utc=True).dt.tz_convert(display_time_zone)
            line, = ax.plot(
                x_values,
                tld_df["unique_fqdn_share_pct"],
                label=tld_label,
                color=color_palette[(color_offset + index) % len(color_palette)],
                linewidth=2,
            )
            legend_handles.append(line)
            legend_labels.append(tld_label)

        color_offset += group_df["tld_label"].nunique()
        ax.set_ylabel("Share of hourly unique FQDNs (%)")
        ax.set_title(PANEL_TITLES.get(group_label, group_label), loc="left", fontsize=12, pad=8)
        ax.grid(axis="y")
        ax.grid(axis="x", color="#eef3f6", linewidth=0.7)
        ax.legend(
            legend_handles,
            legend_labels,
            ncols=min(5, len(legend_labels)),
            loc="upper center",
            bbox_to_anchor=(0.5, -0.14 if panel_index == 0 else -0.24),
            frameon=False,
            fontsize=8,
        )

    axes[-1].set_xlim(x_min, x_max + pd.Timedelta(hours=1))
    axes[-1].xaxis.set_major_locator(mdates.DayLocator())
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%a\n%m-%d", tz=x_min.tz))
    axes[-1].xaxis.set_minor_locator(mdates.HourLocator(byhour=[12]))
    axes[-1].xaxis.set_minor_formatter(mdates.DateFormatter("%H:%M", tz=x_min.tz))
    axes[-1].tick_params(axis="x", which="major", pad=12)
    axes[-1].tick_params(axis="x", which="minor", labelsize=8, pad=2, length=3)
    axes[-1].set_xlabel(f"Local time ({display_time_zone})")

    top_margin = 0.91
    if show_title:
        fig.suptitle(
            "Hourly Share of Top Global and Regional TLDs",
            x=0.08,
            y=0.985,
            ha="left",
            fontsize=16,
            fontweight="bold",
        )
    else:
        top_margin = 0.955
    fig.subplots_adjust(left=0.08, right=0.985, top=top_margin, bottom=0.18, hspace=0.48)
    fig.savefig(output_path, format=output_path.suffix.lstrip(".") or "svg", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    output_dir = weekly.resolve_project_path(args.output_dir) if args.output_dir else weekly.get_output_dir()
    if output_dir is None:
        output_dir = weekly.get_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows = weekly.selected_manifest_rows(args)
    print(
        "Selected "
        f"{weekly.format_number(len(manifest_rows))} windows from "
        f"{manifest_rows['scheduled_start_utc'].min()} to {manifest_rows['scheduled_end_utc'].max()}"
    )

    mapping = load_mapping(args.tld_region_map)
    print(f"Using TLD region mapping {resolve_mapping_path(args.tld_region_map)}")

    hourly_counts = load_or_build_hourly_tld_counts(
        manifest_rows,
        Path(args.cache_dir).resolve(),
        args.bucket_freq,
        args.refresh_cache,
    )
    buckets = observed_bucket_index(manifest_rows, args.bucket_freq)
    hourly_counts = hourly_counts[hourly_counts["bucket_utc"].isin(buckets)].copy()
    enriched = enrich_hourly_counts(hourly_counts, mapping)
    regional_hourly = canonical_hourly_region_counts(enriched, buckets)
    regional_summary = summarize_canonical_hourly_regions(
        regional_hourly,
        args.display_time_zone,
    )
    selected = select_top_tlds(enriched, args.top_n_per_group)
    selected_series = selected_time_series(enriched, selected, buckets)

    all_csv = output_dir / "weekly_tld_hourly_counts.csv"
    regional_hourly_csv = output_dir / "weekly_region_hourly_unique_fqdn_counts.csv"
    regional_summary_csv = output_dir / "weekly_region_hourly_summary.csv"
    selected_csv = output_dir / "weekly_top_tld_hourly_share.csv"
    selected_tlds_csv = output_dir / "weekly_top_tld_selection.csv"
    svg_path = output_dir / "weekly_top_tld_hourly_share.svg"

    weekly.write_csv(enriched, all_csv)
    weekly.write_csv(regional_hourly, regional_hourly_csv)
    weekly.write_csv(regional_summary, regional_summary_csv)
    weekly.write_csv(selected_series, selected_csv)
    weekly.write_csv(selected, selected_tlds_csv)
    save_top_tld_share_chart(
        selected_series,
        svg_path,
        bucket_freq=args.bucket_freq,
        display_time_zone=args.display_time_zone,
    )

    print(f"Wrote {all_csv}")
    print(f"Wrote {regional_hourly_csv}")
    print(f"Wrote {regional_summary_csv}")
    print(f"Wrote {selected_csv}")
    print(f"Wrote {selected_tlds_csv}")
    print(f"Wrote {svg_path}")


if __name__ == "__main__":
    main()
