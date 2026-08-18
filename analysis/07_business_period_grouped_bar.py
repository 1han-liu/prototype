#!/usr/bin/env python3

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
WEEKLY_SCRIPT = SCRIPT_DIR / "06_weekly_business_hour_correlation.py"

BUSINESS_PERIODS = [
    ("weekday_business", "Weekday business"),
    ("weekday_off_hours", "Weekday off-hours"),
    ("weekend", "Weekend"),
]


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
            "Generate only the grouped bar chart comparing weekday business, "
            "weekday off-hours, and weekend FQDN rates by regional ccTLD proxy."
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
        default=os.environ.get("CACHE_DIR", str(weekly.ROOT_DIR / ".cache" / "analysis" / "weekly_region_minutes")),
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


def business_period_rate_summary(
    minute_wide: pd.DataFrame,
    start_hour: int,
    end_hour: int,
) -> pd.DataFrame:
    rows = []
    for window in weekly.BUSINESS_WINDOWS:
        region = window["region_bucket"]
        timezone = window["timezone"]
        local = minute_wide.index.tz_convert(timezone)
        weekday_mask = local.weekday < 5
        business_hour_mask = (local.hour >= start_hour) & (local.hour < end_hour)
        masks = {
            "Weekday business": weekday_mask & business_hour_mask,
            "Weekday off-hours": weekday_mask & ~business_hour_mask,
            "Weekend": local.weekday >= 5,
        }
        values = minute_wide[region]

        for order, (_, period_label) in enumerate(BUSINESS_PERIODS):
            period_values = values[masks[period_label]]
            mean_per_minute = float(period_values.mean()) if len(period_values) else 0.0
            rows.append({
                "region_bucket": region,
                "timezone": timezone,
                "period": period_label,
                "period_order": order,
                "observed_minutes": int(len(period_values)),
                "mean_unique_fqdns_per_minute": round(mean_per_minute, 3),
                "rate_unique_fqdns_per_hour": round(mean_per_minute * 60, 3),
                "total_unique_fqdn_minute_sum": int(period_values.sum()),
            })

    return pd.DataFrame(rows)


def compact_rate(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.0f}k"
    return f"{value:.0f}"


def save_grouped_bar_chart(
    period_summary: pd.DataFrame,
    output_path: Path,
    *,
    start_hour: int,
    end_hour: int,
) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    regions = list(dict.fromkeys(window["region_bucket"] for window in weekly.BUSINESS_WINDOWS))
    timezone_by_region = {window["region_bucket"]: window["timezone"] for window in weekly.BUSINESS_WINDOWS}
    periods = [label for _, label in BUSINESS_PERIODS]
    pivot = (
        period_summary.pivot(index="region_bucket", columns="period", values="rate_unique_fqdns_per_hour")
        .reindex(regions)
        .reindex(columns=periods)
        .fillna(0)
    )

    x_positions = np.arange(len(regions))
    width = 0.24
    fig_width = max(10.8, 1.45 * len(regions) + 2.6)
    fig, ax = plt.subplots(figsize=(fig_width, 6.4))
    period_colors = {
        "Weekday business": "#2f6f73",
        "Weekday off-hours": "#b8572a",
        "Weekend": "#6a5acd",
    }

    for period_index, period in enumerate(periods):
        offset = (period_index - (len(periods) - 1) / 2) * width
        values = pivot[period].to_numpy(dtype=float)
        bars = ax.bar(
            x_positions + offset,
            values,
            width=width,
            label=period,
            color=period_colors[period],
        )
        for bar, value in zip(bars, values, strict=False):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                compact_rate(float(value)),
                ha="center",
                va="bottom",
                fontsize=8,
                color="#36454f",
            )

    labels = [
        f"{region.replace(' ccTLD', '')}\n{timezone_by_region[region].split('/')[-1].replace('_', ' ')}"
        for region in regions
    ]
    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels)
    ax.set_ylabel("mean unique FQDNs per hour")
    ax.set_title("Mean FQDN Rate by Region and Local Time Category", loc="left", fontsize=16, pad=24)
    ax.text(
        0,
        1.02,
        f"Weekday business: Mon-Fri {start_hour:02d}:00-{end_hour:02d}:00 local | "
        "ccTLD regions are proxy buckets",
        transform=ax.transAxes,
        fontsize=9,
        color="#53606b",
    )
    ax.legend(ncols=3, loc="upper center", bbox_to_anchor=(0.5, -0.14), frameon=False)
    ax.grid(axis="y")
    ax.grid(axis="x", visible=False)
    ax.margins(y=0.12)
    fig.tight_layout()
    fig.savefig(output_path, format=output_path.suffix.lstrip(".") or "svg", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    if not 0 <= args.business_start_hour < args.business_end_hour <= 24:
        raise ValueError("Business hours must satisfy 0 <= start < end <= 24.")

    output_dir = weekly.resolve_project_path(args.output_dir) if args.output_dir else weekly.get_output_dir()
    if output_dir is None:
        output_dir = weekly.get_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    tld_region_map = weekly.TldRegionMapping.from_csv(args.tld_region_map)
    print(f"Using TLD region mapping {tld_region_map.path}")

    manifest_rows = weekly.selected_manifest_rows(args)
    minute_counts = weekly.load_or_build_minute_counts(
        manifest_rows,
        Path(args.cache_dir).resolve(),
        args.refresh_cache,
        tld_region_map,
    )
    minutes = weekly.observed_minute_index(manifest_rows)
    minute_wide = weekly.minute_wide_frame(minute_counts, minutes)

    period_summary = business_period_rate_summary(
        minute_wide,
        args.business_start_hour,
        args.business_end_hour,
    )
    csv_path = output_dir / "weekly_business_period_rates.csv"
    svg_path = output_dir / "weekly_business_period_rates_grouped.svg"
    weekly.write_csv(period_summary, csv_path)
    save_grouped_bar_chart(
        period_summary,
        svg_path,
        start_hour=args.business_start_hour,
        end_hour=args.business_end_hour,
    )

    print(f"Wrote {csv_path}")
    print(f"Wrote {svg_path}")


if __name__ == "__main__":
    main()
