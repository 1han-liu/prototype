#!/usr/bin/env python3

from __future__ import annotations

import os
import sys

import pandas as pd

from common import (
    base_name,
    complete_minute_index,
    format_number,
    get_input_file,
    get_output_dir,
    load_frames,
    local_window_label,
    save_bar_chart,
    save_line_chart,
    trim_sparse_edge_rows,
    write_csv,
)

REGION_TIMEZONES = [
    {"region_bucket": "Europe ccTLD", "timezone": "Europe/Berlin"},
    {"region_bucket": "North America ccTLD", "timezone": "America/New_York"},
    {"region_bucket": "North America ccTLD", "timezone": "America/Los_Angeles"},
]

TLD_GROUP_SERIES = [
    ("Europe ccTLD", "#2f6f73"),
    ("North America ccTLD", "#3267a8"),
    ("Global/unknown gTLD", "#b8572a"),
    ("Other/unknown", "#6a5acd"),
]


def main() -> None:
    input_file = get_input_file(sys.argv)
    output_dir = get_output_dir()
    time_field = os.environ.get("TIME_FIELD", "received_at")
    display_time_zone = os.environ.get("DISPLAY_TIME_ZONE", "Europe/Berlin")
    tld_group_freq = os.environ.get("TLD_GROUP_FREQ", "5min")
    top_n = int(os.environ.get("TOP_N", "20") or "20")

    events, domains = load_frames(input_file, include_domains=True, time_field=time_field)
    domains = domains if domains is not None else pd.DataFrame()

    tld_counts = (
        domains.groupby(["tld", "region_bucket"])
        .agg(unique_fqdn_count=("domain", "nunique"), domain_occurrences=("domain", "size"))
        .reset_index()
        .sort_values(["unique_fqdn_count", "tld"], ascending=[False, True])
    )
    tld_counts["tld"] = "." + tld_counts["tld"].astype(str)
    tld_counts["value_text"] = tld_counts.apply(
        lambda row: f"{row.unique_fqdn_count:,.0f} unique | {row.domain_occurrences:,.0f} raw",
        axis=1,
    )

    region_counts = (
        domains.groupby("region_bucket")
        .agg(unique_fqdn_count=("domain", "nunique"), domain_occurrences=("domain", "size"))
        .reset_index()
        .sort_values(["unique_fqdn_count", "region_bucket"], ascending=[False, True])
    )

    write_csv(tld_counts[["tld", "region_bucket", "unique_fqdn_count", "domain_occurrences"]], output_dir / "tld_region_counts.csv")
    write_csv(region_counts, output_dir / "region_counts.csv")
    save_bar_chart(
        tld_counts.assign(label=tld_counts["tld"] + " (" + tld_counts["region_bucket"] + ")").head(top_n),
        label_col="label",
        value_col="unique_fqdn_count",
        value_text_col="value_text",
        title="Top TLDs by Unique FQDN Count",
        subtitle=f"{base_name(input_file)} | pandas groupby/nunique | TLDs are used as regional proxies",
        output_path=output_dir / "tld_region_counts.svg",
        value_label="unique FQDNs",
        color="#b8572a",
    )

    minutes = complete_minute_index(events["minute_utc"])
    minute_counts = (
        events.groupby("minute_utc").size().reindex(minutes, fill_value=0).rename("stream_messages").reset_index()
    )
    minute_counts = minute_counts.rename(columns={"index": "minute_utc"})
    minute_counts = trim_sparse_edge_rows(minute_counts, "stream_messages").reset_index(drop=True)
    trimmed_minutes = minute_counts["minute_utc"]
    minute_region = (
        domains.groupby(["minute_utc", "region_bucket"])["domain"]
        .nunique()
        .unstack(fill_value=0)
        .reindex(trimmed_minutes, fill_value=0)
    )
    minute_region.index = pd.DatetimeIndex(minute_region.index)

    domains_for_rate = domains.copy()
    if not trimmed_minutes.empty:
        domains_for_rate = domains_for_rate[
            (domains_for_rate["minute_utc"] >= trimmed_minutes.min())
            & (domains_for_rate["minute_utc"] <= trimmed_minutes.max())
        ].copy()
    domains_for_rate["bucket_utc"] = domains_for_rate["minute_utc"].dt.floor(tld_group_freq)
    bucket_index = pd.DatetimeIndex(sorted(trimmed_minutes.dt.floor(tld_group_freq).unique()))
    observed_minutes = (
        pd.Series(1, index=trimmed_minutes.dt.floor(tld_group_freq))
        .groupby(level=0)
        .sum()
        .reindex(bucket_index, fill_value=0)
        .rename("observed_minutes")
    )
    bucket_counts = (
        domains_for_rate.groupby(["bucket_utc", "region_bucket"])["domain"]
        .nunique()
        .unstack(fill_value=0)
        .reindex(bucket_index, fill_value=0)
    )
    for group, _ in TLD_GROUP_SERIES:
        if group not in bucket_counts.columns:
            bucket_counts[group] = 0
    rate_over_time = bucket_counts[[group for group, _ in TLD_GROUP_SERIES]]
    rate_over_time = rate_over_time.div(observed_minutes.replace(0, pd.NA), axis=0).mul(60).fillna(0).round(3)
    rate_over_time = rate_over_time.reset_index(names="bucket_utc")
    rate_over_time.insert(1, "bucket_local", rate_over_time["bucket_utc"].dt.tz_convert(display_time_zone).dt.strftime("%m-%d %H:%M"))
    rate_over_time.insert(2, "display_timezone", display_time_zone)
    rate_over_time.insert(3, "observed_minutes", observed_minutes.to_numpy())
    write_csv(rate_over_time, output_dir / "tld_group_rate_over_time.csv")
    save_line_chart(
        rate_over_time,
        x_col="bucket_utc",
        series=[(group, group, color) for group, color in TLD_GROUP_SERIES],
        title="TLD Group Rate Over Time",
        subtitle=(
            f"{base_name(input_file)} | pandas groupby/nunique/floor('{tld_group_freq}') | "
            f"rate normalized to unique FQDNs/hour | time field: {time_field}"
        ),
        output_path=output_dir / "tld_group_rate_over_time.svg",
        y_label="unique FQDNs per hour",
        display_time_zone=display_time_zone,
    )

    business_rows = []
    for item in REGION_TIMEZONES:
        region = item["region_bucket"]
        time_zone = item["timezone"]
        local_minutes = trimmed_minutes.dt.tz_convert(time_zone)
        business_mask = (local_minutes.dt.weekday < 5) & (local_minutes.dt.hour >= 8) & (local_minutes.dt.hour < 18)
        region_series = minute_region[region] if region in minute_region.columns else pd.Series(0, index=trimmed_minutes)
        business_values = region_series[business_mask.to_numpy()]
        off_values = region_series[(~business_mask).to_numpy()]
        business_minutes = int(business_mask.sum())
        off_hours_minutes = int((~business_mask).sum())
        unique_total = int(region_counts.loc[region_counts["region_bucket"] == region, "unique_fqdn_count"].sum())
        business_rows.append({
            "region_bucket": region,
            "timezone": time_zone,
            "local_window": local_window_label(trimmed_minutes.iloc[0], trimmed_minutes.iloc[-1], time_zone)
            if not trimmed_minutes.empty else "n/a",
            "unique_fqdn_total": unique_total,
            "business_minutes": business_minutes,
            "off_hours_minutes": off_hours_minutes,
            "business_unique_fqdn_minute_sum": int(business_values.sum()),
            "off_hours_unique_fqdn_minute_sum": int(off_values.sum()),
            "business_rate_unique_fqdns_per_minute": f"{business_values.mean():.3f}" if business_minutes else "n/a",
            "off_hours_rate_unique_fqdns_per_minute": f"{off_values.mean():.3f}" if off_hours_minutes else "n/a",
        })

    business_df = pd.DataFrame(business_rows)
    write_csv(business_df, output_dir / "regional_business_hour_rates.csv")

    bars = []
    for _, row in business_df.iterrows():
        base_label = f"{row['region_bucket'].replace(' ccTLD', '')} / {row['timezone'].split('/')[-1].replace('_', ' ')}"
        for suffix, rate_col, color in [
            ("business", "business_rate_unique_fqdns_per_minute", "#2f6f73"),
            ("off-hours", "off_hours_rate_unique_fqdns_per_minute", "#b8572a"),
        ]:
            rate = row[rate_col]
            bars.append({
                "label": f"{base_label} {suffix}",
                "rate": 0 if rate == "n/a" else float(rate),
                "value_text": "n/a" if rate == "n/a" else f"{rate}/min",
                "color": color,
            })
    bars_df = pd.DataFrame(bars)
    save_bar_chart(
        bars_df,
        label_col="label",
        value_col="rate",
        value_text_col="value_text",
        title="Business-Hour Rate by Regional TLD Proxy",
        subtitle=f"{base_name(input_file)} | pandas timezone conversion | business hours: Mon-Fri 08:00-18:00 local",
        output_path=output_dir / "regional_business_hour_rates.svg",
        value_label="unique FQDNs per minute",
        color="#2f6f73",
    )

    print(f"Wrote {output_dir / 'tld_region_counts.svg'}")
    print(f"Wrote {output_dir / 'tld_group_rate_over_time.svg'}")
    print(f"Wrote {output_dir / 'regional_business_hour_rates.svg'}")
    print(f"Wrote {output_dir / 'tld_region_counts.csv'}")
    print(f"Wrote {output_dir / 'tld_group_rate_over_time.csv'}")
    print(f"Wrote {output_dir / 'regional_business_hour_rates.csv'}")
    print(f"Parsed {format_number(len(events))} events")


if __name__ == "__main__":
    main()
