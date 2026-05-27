#!/usr/bin/env python3

from __future__ import annotations

import os
import sys

import pandas as pd

from common import base_name, format_number, get_input_file, get_output_dir, load_frames, save_bar_chart, write_csv


def main() -> None:
    input_file = get_input_file(sys.argv)
    output_dir = get_output_dir()
    top_n = int(os.environ.get("TOP_N", "20") or "20")

    events, _ = load_frames(input_file, include_domains=False)
    counts = (
        events.groupby(["source", "source_type", "source_url"], dropna=False)
        .size()
        .reset_index(name="event_count")
        .sort_values(["event_count", "source"], ascending=[False, True])
    )
    counts["share_percent"] = (counts["event_count"] / max(1, len(events)) * 100).round(3)
    counts["value_text"] = counts.apply(lambda row: f"{row.event_count:,.0f} ({row.share_percent:.3f}%)", axis=1)

    csv_file = output_dir / "ct_log_sources.csv"
    svg_file = output_dir / "ct_log_sources.svg"
    write_csv(counts, csv_file)
    save_bar_chart(
        counts.head(top_n),
        label_col="source",
        value_col="event_count",
        value_text_col="value_text",
        title="CT Log Sources Observed in Stream",
        subtitle=f"{base_name(input_file)} | pandas groupby | {format_number(len(events))} parsed events | top {min(top_n, len(counts))}",
        output_path=svg_file,
        value_label="certificate events",
        color="#3267a8",
    )

    print(f"Wrote {svg_file}")
    print(f"Wrote {csv_file}")


if __name__ == "__main__":
    main()
