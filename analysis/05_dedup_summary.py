#!/usr/bin/env python3

from __future__ import annotations

import sys

import pandas as pd

from common import base_name, format_number, get_input_file, get_output_dir, load_frames, save_bar_chart, write_csv


def main() -> None:
    input_file = get_input_file(sys.argv)
    output_dir = get_output_dir()

    events, domains = load_frames(input_file, include_domains=True)
    domains = domains if domains is not None else pd.DataFrame()
    certificate_events = events[events["event_kind"] == "certificate"]
    raw_certificate_events = len(certificate_events)
    unique_certificates = certificate_events["cert_key"].nunique()
    domain_occurrences = len(domains)
    unique_fqdns = domains["domain"].nunique()

    rows = pd.DataFrame([
        {
            "metric": "raw_certificate_events",
            "value": raw_certificate_events,
            "meaning": "Raw certificate_update messages observed in the stream.",
        },
        {
            "metric": "unique_certificates",
            "value": unique_certificates,
            "meaning": "Deduplicated certificates using sha256, then issuer + serial fallback.",
        },
        {
            "metric": "duplicate_certificate_events",
            "value": raw_certificate_events - unique_certificates,
            "meaning": "Raw certificate events minus unique certificates.",
        },
        {
            "metric": "domain_occurrences",
            "value": domain_occurrences,
            "meaning": "All SAN/domain names counted as they appear in events.",
        },
        {
            "metric": "unique_fqdns",
            "value": unique_fqdns,
            "meaning": "Deduplicated normalized fully qualified domain names.",
        },
        {
            "metric": "duplicate_domain_occurrences",
            "value": domain_occurrences - unique_fqdns,
            "meaning": "Domain occurrences minus unique FQDNs.",
        },
    ])
    rows["value_text"] = rows["value"].map(lambda value: f"{value:,.0f}")

    csv_file = output_dir / "dedup_summary.csv"
    svg_file = output_dir / "dedup_summary.svg"
    write_csv(rows[["metric", "value", "meaning"]], csv_file)
    save_bar_chart(
        rows,
        label_col="metric",
        value_col="value",
        value_text_col="value_text",
        title="Raw Counts vs Deduplicated Counts",
        subtitle=f"{base_name(input_file)} | pandas nunique/drop_duplicates | {format_number(raw_certificate_events)} parsed events",
        output_path=svg_file,
        value_label="count",
        color="#6a5acd",
    )

    print(f"Wrote {svg_file}")
    print(f"Wrote {csv_file}")


if __name__ == "__main__":
    main()
