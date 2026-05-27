#!/usr/bin/env python3

from __future__ import annotations

import os
import sys

from common import base_name, format_number, get_input_file, get_output_dir, load_frames, save_bar_chart, write_csv


def main() -> None:
    input_file = get_input_file(sys.argv)
    output_dir = get_output_dir()
    top_n = int(os.environ.get("TOP_N", "20") or "20")

    events, _ = load_frames(input_file, include_domains=False)
    raw_counts = events.groupby("issuer").size().rename("raw_event_count")
    unique_counts = events.drop_duplicates("cert_key").groupby("issuer").size().rename("unique_certificate_count")
    ca_counts = (
        unique_counts.to_frame()
        .join(raw_counts, how="outer")
        .fillna(0)
        .astype(int)
        .reset_index()
        .sort_values(["unique_certificate_count", "issuer"], ascending=[False, True])
    )
    ca_counts["duplicate_event_count"] = ca_counts["raw_event_count"] - ca_counts["unique_certificate_count"]
    ca_counts["value_text"] = ca_counts.apply(
        lambda row: f"{row.unique_certificate_count:,.0f} unique | {row.raw_event_count:,.0f} raw",
        axis=1,
    )

    csv_file = output_dir / "ca_distribution.csv"
    svg_file = output_dir / "ca_distribution.svg"
    write_csv(ca_counts[["issuer", "unique_certificate_count", "raw_event_count", "duplicate_event_count"]], csv_file)
    save_bar_chart(
        ca_counts.head(top_n),
        label_col="issuer",
        value_col="unique_certificate_count",
        value_text_col="value_text",
        title="Top Issuing Certificate Authorities",
        subtitle=f"{base_name(input_file)} | pandas drop_duplicates(cert_key) | {format_number(events['cert_key'].nunique())} unique certificates",
        output_path=svg_file,
        value_label="unique certificates",
        color="#2f6f73",
    )

    print(f"Wrote {svg_file}")
    print(f"Wrote {csv_file}")
    print(f"Parsed {format_number(len(events))} events; unique certificates: {format_number(events['cert_key'].nunique())}")


if __name__ == "__main__":
    main()
