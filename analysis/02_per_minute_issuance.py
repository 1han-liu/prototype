#!/usr/bin/env python3

from __future__ import annotations

import os
import sys

import pandas as pd

from common import (
    add_local_minute_columns,
    base_name,
    complete_minute_index,
    format_number,
    get_input_file,
    get_output_dir,
    load_frames,
    save_line_chart,
    trim_sparse_edge_rows,
    write_csv,
    zero_ranges,
)


def main() -> None:
    input_file = get_input_file(sys.argv)
    output_dir = get_output_dir()
    time_field = os.environ.get("TIME_FIELD", "received_at")
    display_time_zone = os.environ.get("DISPLAY_TIME_ZONE", "Europe/Berlin")

    events, domains = load_frames(input_file, include_domains=True, time_field=time_field)
    domains = domains if domains is not None else pd.DataFrame()
    minutes = complete_minute_index(events["minute_utc"])

    per_minute = pd.DataFrame({"minute_utc": minutes})
    per_minute["certificate_events"] = (
        events.groupby("minute_utc").size().reindex(minutes, fill_value=0).astype(int).to_numpy()
    )
    per_minute["unique_certificates"] = (
        events.groupby("minute_utc")["cert_key"].nunique().reindex(minutes, fill_value=0).astype(int).to_numpy()
    )
    per_minute["domain_occurrences"] = (
        domains.groupby("minute_utc").size().reindex(minutes, fill_value=0).astype(int).to_numpy()
    )
    per_minute["unique_fqdns"] = (
        domains.groupby("minute_utc")["domain"].nunique().reindex(minutes, fill_value=0).astype(int).to_numpy()
    )
    per_minute = trim_sparse_edge_rows(per_minute, "certificate_events").reset_index(drop=True)
    per_minute = add_local_minute_columns(per_minute, display_time_zone)

    output_columns = [
        "minute_utc",
        "minute_local",
        "display_timezone",
        "certificate_events",
        "unique_certificates",
        "domain_occurrences",
        "unique_fqdns",
    ]
    csv_file = output_dir / "per_minute_issuance.csv"
    gap_csv_file = output_dir / "per_minute_gaps.csv"
    svg_file = output_dir / "per_minute_issuance.svg"
    write_csv(per_minute[output_columns], csv_file)

    gap_rows = []
    for item in zero_ranges(per_minute, "certificate_events"):
        start = item["start"]
        end = item["end"]
        gap_rows.append({
            "start_minute_utc": start["minute_utc"],
            "end_minute_utc": end["minute_utc"],
            "start_minute_local": start["minute_local"],
            "end_minute_local": end["minute_local"],
            "display_timezone": display_time_zone,
            "zero_minutes": item["zero_minutes"],
        })
    write_csv(pd.DataFrame(gap_rows), gap_csv_file)

    local_window = (
        f"{per_minute.iloc[0]['minute_local']} to {per_minute.iloc[-1]['minute_local']} {display_time_zone}"
        if not per_minute.empty
        else f"n/a {display_time_zone}"
    )
    save_line_chart(
        per_minute,
        x_col="minute_utc",
        series=[
            ("unique certificates", "unique_certificates", "#2f6f73"),
            ("unique FQDNs", "unique_fqdns", "#b8572a"),
            ("domain occurrences", "domain_occurrences", "#6a5acd"),
            ("raw certificate events", "certificate_events", "#3267a8"),
        ],
        title="Per-Minute Certificate and Domain Rate",
        subtitle=f"{local_window} | pandas resample/groupby | time field: {time_field} | {format_number(len(events))} parsed events",
        output_path=svg_file,
        y_label="per-minute count",
        display_time_zone=display_time_zone,
    )

    print(f"Wrote {svg_file}")
    print(f"Wrote {csv_file}")
    print(f"Wrote {gap_csv_file}")
    print(f"Input {base_name(input_file)}")


if __name__ == "__main__":
    main()
