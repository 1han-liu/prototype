#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
HOURLY_SCRIPT = SCRIPT_DIR / "11_weekly_tld_hourly_share.py"
BUSINESS_SCRIPT = SCRIPT_DIR / "12_regional_tld_business_hour_lift.py"
WILDCARD_CACHE_VERSION = "weekly-wildcard-sensitivity-v1"


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise ImportError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


hourly = load_module("weekly_tld_hourly_share", HOURLY_SCRIPT)
business = load_module("regional_tld_business_hour_lift", BUSINESS_SCRIPT)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Test how wildcard normalization and generic ccTLD grouping affect the weekly results."
        )
    )
    parser.add_argument(
        "--manifest",
        default=os.environ.get("MANIFEST_FILE", "data/manifest.csv"),
        help="Manifest CSV written by collect_sample_windows.js.",
    )
    parser.add_argument(
        "--hourly-input",
        default=os.environ.get("TLD_HOURLY_FILE", "figures/weekly_tld_hourly_counts.csv"),
        help="Canonical hourly TLD CSV from analysis 11.",
    )
    parser.add_argument(
        "--tld-region-map",
        default=os.environ.get("TLD_REGION_MAP", "figures/weekly_tld_region_mapping.csv"),
        help="Baseline TLD mapping CSV from analysis 10.",
    )
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("SENSITIVITY_OUTPUT_DIR", "figures/sensitivity"),
        help="Directory for sensitivity CSV files.",
    )
    parser.add_argument(
        "--cache-dir",
        default=os.environ.get(
            "WILDCARD_SENSITIVITY_CACHE_DIR",
            str(hourly.weekly.ROOT_DIR / ".cache" / "analysis" / "weekly_wildcard_sensitivity"),
        ),
        help="Directory for per-file wildcard sensitivity caches.",
    )
    parser.add_argument(
        "--notes-filter",
        default=os.environ.get("NOTES_FILTER", "one-week domains-only collection"),
        help="Optional exact substring filter for manifest notes.",
    )
    parser.add_argument("--start-utc", default=os.environ.get("START_UTC"))
    parser.add_argument("--end-utc", default=os.environ.get("END_UTC"))
    parser.add_argument(
        "--max-files",
        type=int,
        default=int(os.environ.get("MAX_FILES", "0") or "0"),
        help="Optional file limit for a smoke test. 0 uses all selected files.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.environ.get("SENSITIVITY_WORKERS", "2") or "2"),
        help="Number of raw-file workers. Default: 2.",
    )
    parser.add_argument(
        "--display-time-zone",
        default=os.environ.get("DISPLAY_TIME_ZONE", "Europe/Berlin"),
        help="Common timezone for regional hourly summaries.",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Rebuild wildcard caches even when they exist.",
    )
    parser.add_argument(
        "--skip-wildcard-scan",
        action="store_true",
        help="Only run mapping sensitivity from the canonical hourly CSV.",
    )
    return parser.parse_args()


def raw_domains(event: dict[str, Any]) -> list[Any]:
    data = event.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        leaf = data.get("leaf_cert")
        if isinstance(leaf, dict) and isinstance(leaf.get("all_domains"), list):
            return leaf["all_domains"]
    if isinstance(event.get("domains"), list):
        return event["domains"]
    return []


def normalize_domain_with_wildcard(value: Any) -> tuple[str, bool]:
    text = str(value or "").strip().lower().rstrip(".")
    is_wildcard = text.startswith("*.")
    if is_wildcard:
        text = text[2:]
    normalized = hourly.weekly.normalize_domain_fast(text)
    return normalized, is_wildcard


def wildcard_cache_path(cache_dir: Path, raw_path: Path) -> Path:
    stat = raw_path.stat()
    digest = hashlib.sha1(
        f"{WILDCARD_CACHE_VERSION}:{raw_path.resolve()}:{stat.st_size}:{int(stat.st_mtime)}".encode("utf-8")
    ).hexdigest()[:16]
    safe_name = hourly.weekly.base_name(raw_path).replace("/", "__").replace(":", "-")
    return cache_dir / f"{WILDCARD_CACHE_VERSION}__{safe_name}__{digest}.csv"


def process_wildcard_file(raw_path_value: str) -> pd.DataFrame:
    raw_path = Path(raw_path_value)
    plain_seen: dict[str, set[str]] = defaultdict(set)
    wildcard_seen: dict[str, set[str]] = defaultdict(set)
    plain_counts: Counter[tuple[str, str]] = Counter()
    wildcard_counts: Counter[tuple[str, str]] = Counter()
    collision_counts: Counter[tuple[str, str]] = Counter()

    for event in hourly.weekly.iter_events(raw_path):
        bucket = hourly.bucket_from_event(event, "1h")
        if not bucket:
            continue
        plain_bucket = plain_seen[bucket]
        wildcard_bucket = wildcard_seen[bucket]

        for raw_domain in raw_domains(event):
            domain, is_wildcard = normalize_domain_with_wildcard(raw_domain)
            if not domain:
                continue
            tld = hourly.weekly.tld_of_normalized(domain)
            key = (bucket, tld)

            if is_wildcard:
                if domain in wildcard_bucket:
                    continue
                if domain in plain_bucket:
                    collision_counts[key] += 1
                wildcard_bucket.add(domain)
                wildcard_counts[key] += 1
            else:
                if domain in plain_bucket:
                    continue
                if domain in wildcard_bucket:
                    collision_counts[key] += 1
                plain_bucket.add(domain)
                plain_counts[key] += 1

    rows = []
    for bucket, tld in sorted(set(plain_counts) | set(wildcard_counts)):
        key = (bucket, tld)
        retained = plain_counts[key] + wildcard_counts[key]
        collisions = collision_counts[key]
        rows.append({
            "source_file": hourly.weekly.base_name(raw_path),
            "bucket_utc": bucket,
            "tld": tld,
            "plain_unique_fqdn_count": plain_counts[key],
            "wildcard_unique_fqdn_count": wildcard_counts[key],
            "wildcard_plain_collision_count": collisions,
            "stripped_unique_fqdn_count": retained - collisions,
            "retained_unique_fqdn_count": retained,
        })
    return pd.DataFrame(rows)


def load_or_build_wildcard_counts(
    manifest_rows: pd.DataFrame,
    cache_dir: Path,
    workers: int,
    refresh_cache: bool,
) -> pd.DataFrame:
    cache_dir.mkdir(parents=True, exist_ok=True)
    frames: list[pd.DataFrame] = []
    files_to_build: list[tuple[Path, Path]] = []

    for row in manifest_rows.itertuples(index=False):
        raw_path = Path(row.raw_path)
        cache_path = wildcard_cache_path(cache_dir, raw_path)
        if cache_path.exists() and not refresh_cache:
            frames.append(pd.read_csv(cache_path))
            print(f"cache hit: {hourly.weekly.base_name(raw_path)}", flush=True)
        else:
            files_to_build.append((raw_path, cache_path))

    if files_to_build:
        pending: dict[Any, tuple[Path, Path]] = {}
        with ProcessPoolExecutor(max_workers=workers) as executor:
            for raw_path, cache_path in files_to_build:
                future = executor.submit(process_wildcard_file, str(raw_path))
                pending[future] = (raw_path, cache_path)

            total_pending = len(pending)
            for completed, future in enumerate(as_completed(pending), start=1):
                raw_path, cache_path = pending[future]
                frame = future.result()
                frame.to_csv(cache_path, index=False)
                frames.append(frame)
                print(
                    f"built {completed}/{total_pending}: {hourly.weekly.base_name(raw_path)} "
                    f"({len(frame):,} TLD-hour rows)",
                    flush=True,
                )

    if not frames:
        raise ValueError("No wildcard sensitivity rows were loaded or built.")

    combined = pd.concat(frames, ignore_index=True)
    combined["bucket_utc"] = pd.to_datetime(combined["bucket_utc"], utc=True)
    count_columns = [
        "plain_unique_fqdn_count",
        "wildcard_unique_fqdn_count",
        "wildcard_plain_collision_count",
        "stripped_unique_fqdn_count",
        "retained_unique_fqdn_count",
    ]
    return (
        combined.groupby(["bucket_utc", "tld"], as_index=False)[count_columns]
        .sum()
        .sort_values(["bucket_utc", "tld"])
    )


def core_hourly_counts(source: pd.DataFrame) -> pd.DataFrame:
    required = {"bucket_utc", "tld", "unique_fqdn_count", "domain_occurrences"}
    missing = sorted(required.difference(source.columns))
    if missing:
        raise ValueError(f"Canonical hourly CSV is missing columns: {', '.join(missing)}")
    result = source[["bucket_utc", "tld", "unique_fqdn_count", "domain_occurrences"]].copy()
    result["bucket_utc"] = pd.to_datetime(result["bucket_utc"], utc=True)
    return result


def mapping_scenarios(baseline: pd.DataFrame) -> dict[str, pd.DataFrame]:
    strict_cctld = baseline.copy()
    globalized = strict_cctld["mapped_tld_class"] == "globalized_ccTLD"
    strict_cctld.loc[globalized, "mapped_tld_class"] = "ccTLD"
    strict_cctld.loc[globalized, "mapped_continent"] = strict_cctld.loc[
        globalized, "source_region_bucket"
    ].str.extract(r"^(Europe|Americas|Asia|Africa|Oceania|Antarctica)", expand=False)
    strict_cctld.loc[globalized, "mapped_region_bucket"] = (
        strict_cctld.loc[globalized, "mapped_continent"] + " ccTLD/geographic TLD"
    )
    strict_cctld.loc[globalized, "mapping_basis"] = "sensitivity_all_cctlds_regional"

    suffix_only = strict_cctld.copy()
    geographic_gtld = suffix_only["mapped_tld_class"] == "geographic_gTLD"
    suffix_only.loc[geographic_gtld, "mapped_tld_class"] = "global_gTLD"
    suffix_only.loc[geographic_gtld, "mapped_continent"] = "Global"
    suffix_only.loc[geographic_gtld, "mapped_region_bucket"] = "Global/non-regional TLD"
    suffix_only.loc[geographic_gtld, "mapping_basis"] = "sensitivity_suffix_type_only"

    return {
        "baseline_google_generic_cctlds": baseline,
        "all_cctlds_regional": strict_cctld,
        "suffix_type_only": suffix_only,
    }


def summarize_scenarios(
    counts_by_scenario: dict[str, pd.DataFrame],
    mappings_by_scenario: dict[str, pd.DataFrame],
    buckets: pd.DatetimeIndex,
    display_time_zone: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    baseline_scenario = next(iter(counts_by_scenario))
    summaries = []
    top_tlds = []
    enriched_by_scenario = {}

    for scenario, counts in counts_by_scenario.items():
        mapping = mappings_by_scenario[scenario]
        enriched = hourly.enrich_hourly_counts(counts, mapping)
        enriched_by_scenario[scenario] = enriched
        regional = hourly.canonical_hourly_region_counts(enriched, buckets)
        summary = hourly.summarize_canonical_hourly_regions(regional, display_time_zone)
        summary.insert(0, "scenario", scenario)
        summaries.append(summary)

        selected = hourly.select_top_tlds(enriched, 5).copy()
        selected["rank_in_group"] = selected.groupby("analysis_group").cumcount() + 1
        selected.insert(0, "scenario", scenario)
        top_tlds.append(selected)

    summary_df = pd.concat(summaries, ignore_index=True)
    baseline_means = (
        summary_df[summary_df["scenario"] == baseline_scenario]
        .set_index("region_bucket")["overall_mean_unique_fqdns_per_hour"]
    )
    summary_df["baseline_mean_unique_fqdns_per_hour"] = summary_df["region_bucket"].map(baseline_means)
    summary_df["mean_change_vs_baseline_pct"] = (
        (
            summary_df["overall_mean_unique_fqdns_per_hour"]
            / summary_df["baseline_mean_unique_fqdns_per_hour"]
            - 1
        )
        * 100
    ).round(3)
    return summary_df, pd.concat(top_tlds, ignore_index=True), enriched_by_scenario


def wildcard_business_summary(
    enriched_by_scenario: dict[str, pd.DataFrame],
    buckets: pd.DatetimeIndex,
) -> pd.DataFrame:
    frames = []
    for scenario, enriched in enriched_by_scenario.items():
        selected = hourly.select_top_tlds(enriched, 5)
        selected_series = hourly.selected_time_series(enriched, selected, buckets)
        lift = business.summarize_lift(
            selected_series,
            business.DEFAULT_TIMEZONE_BY_TLD,
            8,
            18,
            10_000,
            20_260_818,
        )
        lift.insert(0, "scenario", scenario)
        frames.append(lift)
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    args = parse_args()
    if args.workers <= 0:
        raise ValueError("Workers must be greater than zero.")

    output_dir = hourly.weekly.resolve_project_path(args.output_dir) or Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    hourly_input = hourly.weekly.resolve_project_path(args.hourly_input)
    if not hourly_input or not hourly_input.exists():
        raise FileNotFoundError(f"Canonical hourly input not found: {args.hourly_input}")

    canonical_source = pd.read_csv(hourly_input)
    baseline_counts = core_hourly_counts(canonical_source)
    buckets = pd.DatetimeIndex(sorted(baseline_counts["bucket_utc"].unique()))
    baseline_mapping = hourly.load_mapping(args.tld_region_map)

    mapping_summary, mapping_top, mapping_enriched = summarize_scenarios(
        {name: baseline_counts for name in mapping_scenarios(baseline_mapping)},
        mapping_scenarios(baseline_mapping),
        buckets,
        args.display_time_zone,
    )
    mapping_lift = wildcard_business_summary(mapping_enriched, buckets)
    hourly.weekly.write_csv(mapping_summary, output_dir / "tld_mapping_region_summary.csv")
    hourly.weekly.write_csv(mapping_top, output_dir / "tld_mapping_top_tlds.csv")
    hourly.weekly.write_csv(mapping_lift, output_dir / "tld_mapping_business_hour_lift.csv")

    if args.skip_wildcard_scan:
        print("Skipped wildcard scan.")
        return

    manifest_rows = hourly.weekly.selected_manifest_rows(args)
    wildcard_counts = load_or_build_wildcard_counts(
        manifest_rows,
        Path(args.cache_dir).resolve(),
        args.workers,
        args.refresh_cache,
    )
    wildcard_counts = wildcard_counts[wildcard_counts["bucket_utc"].isin(buckets)].copy()

    validation = baseline_counts.merge(
        wildcard_counts[["bucket_utc", "tld", "stripped_unique_fqdn_count"]],
        on=["bucket_utc", "tld"],
        how="outer",
    ).fillna(0)
    mismatch = validation[
        validation["unique_fqdn_count"].astype("int64")
        != validation["stripped_unique_fqdn_count"].astype("int64")
    ]
    if not mismatch.empty:
        raise ValueError(
            f"Wildcard scan does not reproduce the canonical stripped counts in {len(mismatch)} TLD-hour rows."
        )

    wildcard_detail = wildcard_counts.merge(
        baseline_counts[["bucket_utc", "tld", "domain_occurrences"]],
        on=["bucket_utc", "tld"],
        how="left",
    )
    wildcard_detail["unique_count_change_pct"] = (
        (
            wildcard_detail["retained_unique_fqdn_count"]
            / wildcard_detail["stripped_unique_fqdn_count"]
            - 1
        )
        * 100
    ).round(4)
    hourly.weekly.write_csv(wildcard_detail, output_dir / "wildcard_hourly_tld_counts.csv")

    retained_counts = wildcard_detail[
        ["bucket_utc", "tld", "retained_unique_fqdn_count", "domain_occurrences"]
    ].rename(columns={"retained_unique_fqdn_count": "unique_fqdn_count"})
    wildcard_scenarios = {
        "strip_wildcard_prefix": baseline_counts,
        "retain_wildcard_distinct": retained_counts,
    }
    wildcard_mappings = {name: baseline_mapping for name in wildcard_scenarios}
    wildcard_summary, wildcard_top, wildcard_enriched = summarize_scenarios(
        wildcard_scenarios,
        wildcard_mappings,
        buckets,
        args.display_time_zone,
    )
    wildcard_lift = wildcard_business_summary(wildcard_enriched, buckets)
    hourly.weekly.write_csv(wildcard_summary, output_dir / "wildcard_region_summary.csv")
    hourly.weekly.write_csv(wildcard_top, output_dir / "wildcard_top_tlds.csv")
    hourly.weekly.write_csv(wildcard_lift, output_dir / "wildcard_business_hour_lift.csv")

    overall = wildcard_detail[
        ["stripped_unique_fqdn_count", "retained_unique_fqdn_count", "wildcard_plain_collision_count"]
    ].sum()
    print(
        "Wildcard sensitivity complete: "
        f"stripped={int(overall['stripped_unique_fqdn_count']):,}, "
        f"retained={int(overall['retained_unique_fqdn_count']):,}, "
        f"difference={int(overall['wildcard_plain_collision_count']):,}",
        flush=True,
    )


if __name__ == "__main__":
    main()
