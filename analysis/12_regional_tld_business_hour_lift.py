#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from common import COLORS, get_output_dir, resolve_project_path, write_csv

REGIONAL_GROUP = "ccTLD/geographic TLD"

DEFAULT_TIMEZONE_BY_TLD = {
    # Common ccTLDs in this dataset.
    "de": "Europe/Berlin",
    "uk": "Europe/London",
    "br": "America/Sao_Paulo",
    "cn": "Asia/Shanghai",
    "ru": "Europe/Moscow",
    "nl": "Europe/Amsterdam",
    "fr": "Europe/Paris",
    "au": "Australia/Sydney",
    "eu": "Europe/Brussels",
    "in": "Asia/Kolkata",
    "io": "Indian/Chagos",
    "me": "Europe/Podgorica",
    "co": "America/Bogota",
    "it": "Europe/Rome",
    "ca": "America/Toronto",
    "za": "Africa/Johannesburg",
    "cc": "Indian/Cocos",
    "pl": "Europe/Warsaw",
    "ai": "America/Anguilla",
    "ch": "Europe/Zurich",
    "be": "Europe/Brussels",
    "us": "America/New_York",
    "id": "Asia/Jakarta",
    "to": "Pacific/Tongatapu",
    "jp": "Asia/Tokyo",
    "se": "Europe/Stockholm",
    "at": "Europe/Vienna",
    "es": "Europe/Madrid",
    "cz": "Europe/Prague",
    "hu": "Europe/Budapest",
    "mx": "America/Mexico_City",
    "ro": "Europe/Bucharest",
    "nz": "Pacific/Auckland",
    "dk": "Europe/Copenhagen",
    "cl": "America/Santiago",
    "ir": "Asia/Tehran",
    "tr": "Europe/Istanbul",
    "no": "Europe/Oslo",
    "gr": "Europe/Athens",
    "ar": "America/Argentina/Buenos_Aires",
    "ua": "Europe/Kyiv",
    "vn": "Asia/Ho_Chi_Minh",
    "fi": "Europe/Helsinki",
    "kr": "Asia/Seoul",
    "my": "Asia/Kuala_Lumpur",
    "pt": "Europe/Lisbon",
    "lt": "Europe/Vilnius",
    "ee": "Europe/Tallinn",
    "hk": "Asia/Hong_Kong",
    "tw": "Asia/Taipei",
    "sg": "Asia/Singapore",
    "ie": "Europe/Dublin",
    "il": "Asia/Jerusalem",
    "sk": "Europe/Bratislava",
    "si": "Europe/Ljubljana",
    "hr": "Europe/Zagreb",
    "bg": "Europe/Sofia",
    "by": "Europe/Minsk",
    "rs": "Europe/Belgrade",
    "is": "Atlantic/Reykjavik",
    "lu": "Europe/Luxembourg",
    "lv": "Europe/Riga",
    "th": "Asia/Bangkok",
    "ph": "Asia/Manila",
    "pk": "Asia/Karachi",
    "bd": "Asia/Dhaka",
    "ae": "Asia/Dubai",
    "sa": "Asia/Riyadh",
    "eg": "Africa/Cairo",
    "ng": "Africa/Lagos",
    "ke": "Africa/Nairobi",
    "ma": "Africa/Casablanca",
    "uy": "America/Montevideo",
    "pe": "America/Lima",
    "ve": "America/Caracas",
    "cr": "America/Costa_Rica",
    "ec": "America/Guayaquil",
    "gt": "America/Guatemala",
    # Geographic/cultural gTLDs that may appear in the regional panel.
    "africa": "Africa/Johannesburg",
    "amsterdam": "Europe/Amsterdam",
    "asia": "Asia/Shanghai",
    "barcelona": "Europe/Madrid",
    "bayern": "Europe/Berlin",
    "berlin": "Europe/Berlin",
    "boston": "America/New_York",
    "brussels": "Europe/Brussels",
    "bzh": "Europe/Paris",
    "capetown": "Africa/Johannesburg",
    "cat": "Europe/Madrid",
    "cologne": "Europe/Berlin",
    "corsica": "Europe/Paris",
    "dubai": "Asia/Dubai",
    "durban": "Africa/Johannesburg",
    "eus": "Europe/Madrid",
    "frl": "Europe/Amsterdam",
    "gal": "Europe/Madrid",
    "gent": "Europe/Brussels",
    "hamburg": "Europe/Berlin",
    "irish": "Europe/Dublin",
    "ist": "Europe/Istanbul",
    "istanbul": "Europe/Istanbul",
    "joburg": "Africa/Johannesburg",
    "kiwi": "Pacific/Auckland",
    "koeln": "Europe/Berlin",
    "kyoto": "Asia/Tokyo",
    "lat": "America/Mexico_City",
    "london": "Europe/London",
    "madrid": "Europe/Madrid",
    "melbourne": "Australia/Melbourne",
    "miami": "America/New_York",
    "moscow": "Europe/Moscow",
    "nagoya": "Asia/Tokyo",
    "nrw": "Europe/Berlin",
    "nyc": "America/New_York",
    "osaka": "Asia/Tokyo",
    "paris": "Europe/Paris",
    "quebec": "America/Toronto",
    "rio": "America/Sao_Paulo",
    "ruhr": "Europe/Berlin",
    "saarland": "Europe/Berlin",
    "scot": "Europe/London",
    "swiss": "Europe/Zurich",
    "sydney": "Australia/Sydney",
    "taipei": "Asia/Taipei",
    "tirol": "Europe/Vienna",
    "tokyo": "Asia/Tokyo",
    "vegas": "America/Los_Angeles",
    "vlaanderen": "Europe/Brussels",
    "wales": "Europe/London",
    "wien": "Europe/Vienna",
    "yokohama": "Asia/Tokyo",
    "zuerich": "Europe/Zurich",
    "xn--80adxhks": "Europe/Moscow",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare whether the top regional TLDs from analysis 11 have higher hourly counts "
            "during local weekday business hours than local weekday off-hours."
        )
    )
    parser.add_argument(
        "--input",
        default=os.environ.get("TOP_TLD_HOURLY_SHARE_FILE", "figures/weekly_top_tld_hourly_share.csv"),
        help="Input CSV from analysis/11_weekly_tld_hourly_share.py.",
    )
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("FIGURES_DIR"),
        help="Directory for output CSV/SVG files. Defaults to prototype/figures.",
    )
    parser.add_argument(
        "--timezone-map",
        default=os.environ.get("TLD_TIMEZONE_MAP"),
        help="Optional CSV with columns tld,timezone to override or extend built-in TLD time zones.",
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
        "--bootstrap-samples",
        type=int,
        default=int(os.environ.get("BOOTSTRAP_SAMPLES", "10000") or "10000"),
        help="Number of weekday block-bootstrap samples. Default: 10000.",
    )
    parser.add_argument(
        "--bootstrap-seed",
        type=int,
        default=int(os.environ.get("BOOTSTRAP_SEED", "20260818") or "20260818"),
        help="Random seed for the block bootstrap. Default: 20260818.",
    )
    return parser.parse_args()


def load_timezone_map(path_value: str | None) -> dict[str, str]:
    result = dict(DEFAULT_TIMEZONE_BY_TLD)
    if not path_value:
        return result

    path = resolve_project_path(path_value)
    if not path or not path.exists():
        raise FileNotFoundError(f"TLD timezone map not found: {path_value}")
    overrides = pd.read_csv(path)
    required = {"tld", "timezone"}
    missing = sorted(required.difference(overrides.columns))
    if missing:
        raise ValueError(f"TLD timezone map is missing required columns: {', '.join(missing)}")
    for row in overrides.itertuples(index=False):
        result[str(row.tld).strip().lower()] = str(row.timezone).strip()
    return result


def period_masks(local_time: pd.Series, start_hour: int, end_hour: int) -> dict[str, pd.Series]:
    weekday = local_time.dt.weekday < 5
    business = (local_time.dt.hour >= start_hour) & (local_time.dt.hour < end_hour)
    return {
        "weekday_business": weekday & business,
        "weekday_off_hours": weekday & ~business,
        "weekend": ~weekday,
    }


def first_value(df: pd.DataFrame, column: str, fallback: str = "") -> Any:
    if column not in df.columns or df[column].empty:
        return fallback
    return df[column].iloc[0]


def count_lift(counts: np.ndarray, business_mask: np.ndarray, off_mask: np.ndarray) -> float:
    business_mean = float(counts[business_mask].mean())
    off_mean = float(counts[off_mask].mean())
    return business_mean / off_mean if off_mean else float("nan")


def weekday_block_bootstrap_ci(
    counts: np.ndarray,
    weekdays: np.ndarray,
    hours: np.ndarray,
    start_hour: int,
    end_hour: int,
    samples: int,
    seed: int,
) -> tuple[float, float]:
    business_sums = []
    off_sums = []
    business_counts = []
    off_counts = []

    for weekday in range(5):
        day = weekdays == weekday
        business = day & (hours >= start_hour) & (hours < end_hour)
        off = day & ~((hours >= start_hour) & (hours < end_hour))
        if int(day.sum()) != 24:
            raise ValueError("Each weekday must contain 24 hourly observations for the block bootstrap.")
        business_sums.append(float(counts[business].sum()))
        off_sums.append(float(counts[off].sum()))
        business_counts.append(int(business.sum()))
        off_counts.append(int(off.sum()))

    rng = np.random.default_rng(seed)
    sampled_days = rng.integers(0, 5, size=(samples, 5))
    business_means = np.asarray(business_sums)[sampled_days].sum(axis=1) / np.asarray(business_counts)[
        sampled_days
    ].sum(axis=1)
    off_means = np.asarray(off_sums)[sampled_days].sum(axis=1) / np.asarray(off_counts)[sampled_days].sum(
        axis=1
    )
    lifts = business_means / off_means
    low, high = np.quantile(lifts, [0.025, 0.975])
    return float(low), float(high)


def circular_shift_permutation_p_value(
    counts: np.ndarray,
    weekdays: np.ndarray,
    hours: np.ndarray,
    start_hour: int,
    end_hour: int,
) -> float:
    weekday = weekdays < 5
    window_length = end_hour - start_hour
    shifted_lifts = []

    for shift in range(24):
        business = weekday & (((hours - (start_hour + shift)) % 24) < window_length)
        off = weekday & ~business
        shifted_lifts.append(count_lift(counts, business, off))

    observed_distance = abs(np.log(shifted_lifts[0]))
    distances = np.abs(np.log(np.asarray(shifted_lifts)))
    return float(np.count_nonzero(distances >= observed_distance - 1e-12) / len(distances))


def holm_adjusted_p_values(p_values: pd.Series) -> pd.Series:
    values = pd.to_numeric(p_values, errors="raise").to_numpy(dtype=float)
    order = np.argsort(values, kind="stable")
    adjusted = np.empty(len(values), dtype=float)
    running_max = 0.0

    for rank, index in enumerate(order):
        candidate = min(1.0, (len(values) - rank) * values[index])
        running_max = max(running_max, candidate)
        adjusted[index] = running_max

    return pd.Series(adjusted, index=p_values.index)


def summarize_lift(
    top_tld_share: pd.DataFrame,
    timezone_by_tld: dict[str, str],
    start_hour: int,
    end_hour: int,
    bootstrap_samples: int,
    bootstrap_seed: int,
) -> pd.DataFrame:
    required = {
        "bucket_utc",
        "analysis_group",
        "tld",
        "tld_label",
        "unique_fqdn_count",
        "unique_fqdn_share_pct",
    }
    missing = sorted(required.difference(top_tld_share.columns))
    if missing:
        raise ValueError(f"Input CSV is missing required columns: {', '.join(missing)}")

    regional = top_tld_share[top_tld_share["analysis_group"] == REGIONAL_GROUP].copy()
    if regional.empty:
        raise ValueError(f"No rows found for analysis_group={REGIONAL_GROUP!r}. Run analysis 11 first.")

    regional["bucket_utc"] = pd.to_datetime(regional["bucket_utc"], utc=True)
    rows = []
    missing_timezones = []

    for tld, group in regional.groupby("tld", sort=False):
        timezone = timezone_by_tld.get(str(tld).lower())
        if not timezone:
            missing_timezones.append(str(tld))
            continue

        local_time = group["bucket_utc"].dt.tz_convert(timezone)
        masks = period_masks(local_time, start_hour, end_hour)
        shares = pd.to_numeric(group["unique_fqdn_share_pct"], errors="coerce")
        counts = pd.to_numeric(group.get("unique_fqdn_count", pd.Series(index=group.index)), errors="coerce")

        if counts.isna().any():
            raise ValueError(f"Missing unique_fqdn_count values for TLD {tld!r}.")

        count_values = counts.to_numpy(dtype=float)
        local_weekdays = local_time.dt.weekday.to_numpy()
        local_hours = local_time.dt.hour.to_numpy()
        stable_tld_seed = bootstrap_seed + sum(
            (position + 1) * ord(character) for position, character in enumerate(str(tld))
        )
        ci_low, ci_high = weekday_block_bootstrap_ci(
            count_values,
            local_weekdays,
            local_hours,
            start_hour,
            end_hour,
            bootstrap_samples,
            stable_tld_seed,
        )
        permutation_p_value = circular_shift_permutation_p_value(
            count_values,
            local_weekdays,
            local_hours,
            start_hour,
            end_hour,
        )

        business_share = shares[masks["weekday_business"]]
        off_share = shares[masks["weekday_off_hours"]]
        weekend_share = shares[masks["weekend"]]
        business_count = counts[masks["weekday_business"]]
        off_count = counts[masks["weekday_off_hours"]]

        business_mean = float(business_share.mean()) if len(business_share) else 0.0
        off_mean = float(off_share.mean()) if len(off_share) else 0.0
        weekend_mean = float(weekend_share.mean()) if len(weekend_share) else 0.0
        count_business_mean = float(business_count.mean()) if len(business_count) else 0.0
        count_off_mean = float(off_count.mean()) if len(off_count) else 0.0

        rows.append({
            "tld": tld,
            "tld_label": group["tld_label"].iloc[0],
            "mapped_tld_class": first_value(group, "mapped_tld_class"),
            "mapped_continent": first_value(group, "mapped_continent"),
            "timezone": timezone,
            "business_window": f"Mon-Fri {start_hour:02d}:00-{end_hour:02d}:00 local",
            "business_buckets": int(masks["weekday_business"].sum()),
            "weekday_off_hours_buckets": int(masks["weekday_off_hours"].sum()),
            "weekend_buckets": int(masks["weekend"].sum()),
            "business_mean_share_pct": round(business_mean, 4),
            "weekday_off_hours_mean_share_pct": round(off_mean, 4),
            "weekend_mean_share_pct": round(weekend_mean, 4),
            "business_lift_vs_weekday_off_hours": round(business_mean / off_mean, 4) if off_mean else pd.NA,
            "business_mean_unique_fqdn_count": round(count_business_mean, 3),
            "weekday_off_hours_mean_unique_fqdn_count": round(count_off_mean, 3),
            "count_lift_vs_weekday_off_hours": round(count_business_mean / count_off_mean, 4) if count_off_mean else pd.NA,
            "count_lift_ci95_low": round(ci_low, 4),
            "count_lift_ci95_high": round(ci_high, 4),
            "permutation_p_value": permutation_p_value,
            "bootstrap_samples": bootstrap_samples,
            "permutation_shifts": 24,
        })

    if missing_timezones:
        raise ValueError(
            "Missing timezone mapping for TLDs: "
            + ", ".join(sorted(missing_timezones))
            + ". Pass --timezone-map with columns tld,timezone."
        )

    result = pd.DataFrame(rows)
    result["holm_adjusted_p_value"] = holm_adjusted_p_values(result["permutation_p_value"])
    result["permutation_p_value"] = result["permutation_p_value"].round(4)
    result["holm_adjusted_p_value"] = result["holm_adjusted_p_value"].round(4)
    return result.sort_values("count_lift_vs_weekday_off_hours", ascending=False).reset_index(drop=True)


def save_lift_chart(summary: pd.DataFrame, output_path: Path, *, show_title: bool = True) -> None:
    import matplotlib.pyplot as plt

    chart_df = summary.copy().sort_values("count_lift_vs_weekday_off_hours")
    values = pd.to_numeric(chart_df["count_lift_vs_weekday_off_hours"], errors="coerce")
    colors = [COLORS[0] if value >= 1 else COLORS[1] for value in values]
    x_min = 0.98
    x_max = 1.06

    height = max(4.8, 0.52 * len(chart_df) + 1.8)
    fig, ax = plt.subplots(figsize=(10.4, height))
    bars = ax.barh(chart_df["tld_label"], values, color=colors)
    ax.axvline(1.0, color="#53606b", linewidth=1.2, linestyle="--")
    ax.set_xlim(x_min, x_max)
    ax.set_xlabel("Business-hour / off-hour mean count ratio")
    ax.set_ylabel("Top 5 Regional TLD")
    if show_title:
        ax.set_title("Business-Hour Lift in FQDN Counts for Top 5 Regional TLDs", loc="left", fontsize=16, pad=22)
        ax.text(
            0,
            1.02,
            "Ratio > 1 indicates higher mean hourly counts during local weekday business hours.",
            transform=ax.transAxes,
            fontsize=9,
            color="#53606b",
        )
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)

    for bar, value in zip(bars, values, strict=False):
        label_x = min(float(value) + 0.0012, x_max - 0.004)
        ax.text(
            label_x,
            bar.get_y() + bar.get_height() / 2,
            f"{value:.2f}x",
            va="center",
            fontsize=8,
            color="#36454f",
        )

    fig.tight_layout()
    fig.savefig(output_path, format=output_path.suffix.lstrip(".") or "svg", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    if not 0 <= args.business_start_hour < args.business_end_hour <= 24:
        raise ValueError("Business hours must satisfy 0 <= start < end <= 24.")
    if args.bootstrap_samples <= 0:
        raise ValueError("Bootstrap samples must be greater than zero.")

    input_path = resolve_project_path(args.input)
    if not input_path or not input_path.exists():
        raise FileNotFoundError(
            f"Input not found: {args.input}. Run `.venv/bin/python analysis/11_weekly_tld_hourly_share.py` first."
        )

    output_dir = resolve_project_path(args.output_dir) if args.output_dir else get_output_dir()
    if output_dir is None:
        output_dir = get_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    top_tld_share = pd.read_csv(input_path)
    timezone_by_tld = load_timezone_map(args.timezone_map)
    summary = summarize_lift(
        top_tld_share,
        timezone_by_tld,
        args.business_start_hour,
        args.business_end_hour,
        args.bootstrap_samples,
        args.bootstrap_seed,
    )

    csv_path = output_dir / "regional_tld_business_hour_count_lift.csv"
    svg_path = output_dir / "regional_tld_business_hour_count_lift.svg"
    write_csv(summary, csv_path)
    save_lift_chart(summary, svg_path)

    print(f"Wrote {csv_path}")
    print(f"Wrote {svg_path}")


if __name__ == "__main__":
    main()
