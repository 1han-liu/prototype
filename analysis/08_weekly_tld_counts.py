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

SCRIPT_DIR = Path(__file__).resolve().parent
WEEKLY_SCRIPT = SCRIPT_DIR / "06_weekly_business_hour_correlation.py"
TLD_CACHE_VERSION = "weekly-tld-counts-v1"

COUNTRY_OR_TERRITORY_BY_TLD = {
    "ac": "Ascension Island",
    "ad": "Andorra",
    "ae": "United Arab Emirates",
    "af": "Afghanistan",
    "ag": "Antigua and Barbuda",
    "ai": "Anguilla",
    "al": "Albania",
    "am": "Armenia",
    "ao": "Angola",
    "aq": "Antarctica",
    "ar": "Argentina",
    "as": "American Samoa",
    "at": "Austria",
    "au": "Australia",
    "aw": "Aruba",
    "ax": "Aland Islands",
    "az": "Azerbaijan",
    "ba": "Bosnia and Herzegovina",
    "bb": "Barbados",
    "bd": "Bangladesh",
    "be": "Belgium",
    "bf": "Burkina Faso",
    "bg": "Bulgaria",
    "bh": "Bahrain",
    "bi": "Burundi",
    "bj": "Benin",
    "bm": "Bermuda",
    "bn": "Brunei Darussalam",
    "bo": "Bolivia",
    "bq": "Bonaire, Sint Eustatius and Saba",
    "br": "Brazil",
    "bs": "Bahamas",
    "bt": "Bhutan",
    "bv": "Bouvet Island",
    "bw": "Botswana",
    "by": "Belarus",
    "bz": "Belize",
    "ca": "Canada",
    "cc": "Cocos (Keeling) Islands",
    "cd": "Democratic Republic of the Congo",
    "cf": "Central African Republic",
    "cg": "Republic of the Congo",
    "ch": "Switzerland",
    "ci": "Cote d'Ivoire",
    "ck": "Cook Islands",
    "cl": "Chile",
    "cm": "Cameroon",
    "cn": "China",
    "co": "Colombia",
    "cr": "Costa Rica",
    "cu": "Cuba",
    "cv": "Cabo Verde",
    "cw": "Curacao",
    "cx": "Christmas Island",
    "cy": "Cyprus",
    "cz": "Czechia",
    "de": "Germany",
    "dj": "Djibouti",
    "dk": "Denmark",
    "dm": "Dominica",
    "do": "Dominican Republic",
    "dz": "Algeria",
    "ec": "Ecuador",
    "ee": "Estonia",
    "eg": "Egypt",
    "er": "Eritrea",
    "es": "Spain",
    "et": "Ethiopia",
    "eu": "European Union",
    "fi": "Finland",
    "fj": "Fiji",
    "fk": "Falkland Islands",
    "fm": "Micronesia",
    "fo": "Faroe Islands",
    "fr": "France",
    "ga": "Gabon",
    "gb": "United Kingdom",
    "gd": "Grenada",
    "ge": "Georgia",
    "gf": "French Guiana",
    "gg": "Guernsey",
    "gh": "Ghana",
    "gi": "Gibraltar",
    "gl": "Greenland",
    "gm": "Gambia",
    "gn": "Guinea",
    "gp": "Guadeloupe",
    "gq": "Equatorial Guinea",
    "gr": "Greece",
    "gs": "South Georgia and the South Sandwich Islands",
    "gt": "Guatemala",
    "gu": "Guam",
    "gw": "Guinea-Bissau",
    "gy": "Guyana",
    "hk": "Hong Kong",
    "hm": "Heard Island and McDonald Islands",
    "hn": "Honduras",
    "hr": "Croatia",
    "ht": "Haiti",
    "hu": "Hungary",
    "id": "Indonesia",
    "ie": "Ireland",
    "il": "Israel",
    "im": "Isle of Man",
    "in": "India",
    "io": "British Indian Ocean Territory",
    "iq": "Iraq",
    "ir": "Iran",
    "is": "Iceland",
    "it": "Italy",
    "je": "Jersey",
    "jm": "Jamaica",
    "jo": "Jordan",
    "jp": "Japan",
    "ke": "Kenya",
    "kg": "Kyrgyzstan",
    "kh": "Cambodia",
    "ki": "Kiribati",
    "km": "Comoros",
    "kn": "Saint Kitts and Nevis",
    "kp": "North Korea",
    "kr": "South Korea",
    "kw": "Kuwait",
    "ky": "Cayman Islands",
    "kz": "Kazakhstan",
    "la": "Laos",
    "lb": "Lebanon",
    "lc": "Saint Lucia",
    "li": "Liechtenstein",
    "lk": "Sri Lanka",
    "lr": "Liberia",
    "ls": "Lesotho",
    "lt": "Lithuania",
    "lu": "Luxembourg",
    "lv": "Latvia",
    "ly": "Libya",
    "ma": "Morocco",
    "mc": "Monaco",
    "md": "Moldova",
    "me": "Montenegro",
    "mg": "Madagascar",
    "mh": "Marshall Islands",
    "mk": "North Macedonia",
    "ml": "Mali",
    "mm": "Myanmar",
    "mn": "Mongolia",
    "mo": "Macao",
    "mp": "Northern Mariana Islands",
    "mq": "Martinique",
    "mr": "Mauritania",
    "ms": "Montserrat",
    "mt": "Malta",
    "mu": "Mauritius",
    "mv": "Maldives",
    "mw": "Malawi",
    "mx": "Mexico",
    "my": "Malaysia",
    "mz": "Mozambique",
    "na": "Namibia",
    "nc": "New Caledonia",
    "ne": "Niger",
    "nf": "Norfolk Island",
    "ng": "Nigeria",
    "ni": "Nicaragua",
    "nl": "Netherlands",
    "no": "Norway",
    "np": "Nepal",
    "nr": "Nauru",
    "nu": "Niue",
    "nz": "New Zealand",
    "om": "Oman",
    "pa": "Panama",
    "pe": "Peru",
    "pf": "French Polynesia",
    "pg": "Papua New Guinea",
    "ph": "Philippines",
    "pk": "Pakistan",
    "pl": "Poland",
    "pm": "Saint Pierre and Miquelon",
    "pn": "Pitcairn",
    "pr": "Puerto Rico",
    "ps": "Palestine",
    "pt": "Portugal",
    "pw": "Palau",
    "py": "Paraguay",
    "qa": "Qatar",
    "re": "Reunion",
    "ro": "Romania",
    "rs": "Serbia",
    "ru": "Russia",
    "rw": "Rwanda",
    "sa": "Saudi Arabia",
    "sb": "Solomon Islands",
    "sc": "Seychelles",
    "sd": "Sudan",
    "se": "Sweden",
    "sg": "Singapore",
    "sh": "Saint Helena",
    "si": "Slovenia",
    "sj": "Svalbard and Jan Mayen",
    "sk": "Slovakia",
    "sl": "Sierra Leone",
    "sm": "San Marino",
    "sn": "Senegal",
    "so": "Somalia",
    "sr": "Suriname",
    "ss": "South Sudan",
    "st": "Sao Tome and Principe",
    "su": "Soviet Union (legacy)",
    "sv": "El Salvador",
    "sx": "Sint Maarten",
    "sy": "Syria",
    "sz": "Eswatini",
    "tc": "Turks and Caicos Islands",
    "td": "Chad",
    "tf": "French Southern Territories",
    "tg": "Togo",
    "th": "Thailand",
    "tj": "Tajikistan",
    "tk": "Tokelau",
    "tl": "Timor-Leste",
    "tm": "Turkmenistan",
    "tn": "Tunisia",
    "to": "Tonga",
    "tr": "Turkiye",
    "tt": "Trinidad and Tobago",
    "tv": "Tuvalu",
    "tw": "Taiwan",
    "tz": "Tanzania",
    "ua": "Ukraine",
    "ug": "Uganda",
    "uk": "United Kingdom",
    "um": "United States Minor Outlying Islands",
    "us": "United States",
    "uy": "Uruguay",
    "uz": "Uzbekistan",
    "va": "Vatican City",
    "vc": "Saint Vincent and the Grenadines",
    "ve": "Venezuela",
    "vg": "British Virgin Islands",
    "vi": "United States Virgin Islands",
    "vn": "Vietnam",
    "vu": "Vanuatu",
    "wf": "Wallis and Futuna",
    "ws": "Samoa",
    "ye": "Yemen",
    "yt": "Mayotte",
    "za": "South Africa",
    "zm": "Zambia",
    "zw": "Zimbabwe",
    "xn--3e0b707e": "South Korea (.한국)",
    "xn--fiqs8s": "China (.中国)",
    "xn--fiqz9s": "China (.中國)",
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
    parser = argparse.ArgumentParser(description="Generate weekly TLD count and share CSV from domain-only samples.")
    parser.add_argument(
        "--manifest",
        default=os.environ.get("MANIFEST_FILE", "data/manifest.csv"),
        help="Manifest CSV written by collect_sample_windows.js.",
    )
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("FIGURES_DIR"),
        help="Directory for output CSV files. Defaults to prototype/figures.",
    )
    parser.add_argument(
        "--cache-dir",
        default=os.environ.get("CACHE_DIR", str(weekly.ROOT_DIR / ".cache" / "analysis" / "weekly_tld_counts")),
        help="Directory for per-raw-file TLD cache CSV files.",
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
        "--refresh-cache",
        action="store_true",
        help="Rebuild per-file TLD cache files even when cache exists.",
    )
    return parser.parse_args()


def tld_cache_file_path(cache_dir: Path, raw_path: Path) -> Path:
    stat = raw_path.stat()
    try:
        rel = raw_path.resolve().relative_to(weekly.ROOT_DIR).as_posix()
    except ValueError:
        rel = raw_path.name
    digest = hashlib.sha1(
        f"{TLD_CACHE_VERSION}:{raw_path.resolve()}:{stat.st_size}:{int(stat.st_mtime)}".encode("utf-8")
    ).hexdigest()[:16]
    safe_name = rel.replace("/", "__").replace(":", "-")
    return cache_dir / f"{TLD_CACHE_VERSION}__{safe_name}__{digest}.csv"


def tld_type(tld: str) -> str:
    if tld == "com":
        return "global_gTLD"
    if tld in weekly.KNOWN_CCTLD_TLDS or len(tld) == 2:
        return "ccTLD"
    if tld.startswith("xn--") and tld in COUNTRY_OR_TERRITORY_BY_TLD:
        return "ccTLD"
    if tld.startswith("_"):
        return "special"
    return "gTLD_or_unknown"


def country_or_territory(tld: str) -> str:
    if tld == "com":
        return "Global .com"
    if tld in COUNTRY_OR_TERRITORY_BY_TLD:
        return COUNTRY_OR_TERRITORY_BY_TLD[tld]
    if tld_type(tld) == "ccTLD":
        return "Unknown ccTLD/territory"
    return "n/a"


def process_raw_file(raw_path: Path, cache_path: Path | None = None) -> pd.DataFrame:
    domains_by_tld: dict[str, set[str]] = defaultdict(set)
    occurrence_counts: Counter[str] = Counter()
    parsed_events = 0

    for event in weekly.iter_events(raw_path):
        domains = weekly.domains_from_event(event)
        if not domains:
            continue
        parsed_events += 1
        for domain in domains:
            tld = weekly.tld_of_normalized(domain)
            if not tld:
                continue
            domains_by_tld[tld].add(domain)
            occurrence_counts[tld] += 1

    rows = [
        {
            "source_file": weekly.base_name(raw_path),
            "tld": tld,
            "window_unique_fqdn_count": len(domains),
            "domain_occurrences": occurrence_counts[tld],
        }
        for tld, domains in sorted(domains_by_tld.items())
    ]
    result = pd.DataFrame(
        rows,
        columns=["source_file", "tld", "window_unique_fqdn_count", "domain_occurrences"],
    )
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(cache_path, index=False)

    print(f"  parsed {weekly.format_number(parsed_events)} events -> {weekly.format_number(len(result))} TLD rows")
    return result


def load_or_build_tld_counts(rows: pd.DataFrame, cache_dir: Path, refresh_cache: bool) -> pd.DataFrame:
    partial_line_limit = int(os.environ.get("MAX_LINES", "0") or "0")
    cache_enabled = partial_line_limit == 0
    if not cache_enabled:
        print("MAX_LINES is set; cache reads/writes are disabled for this partial run.")

    frames = []
    for index, row in rows.iterrows():
        raw_path = Path(row["raw_path"])
        cache_path = tld_cache_file_path(cache_dir, raw_path)
        print(f"[{index + 1}/{len(rows)}] {weekly.base_name(raw_path)}")
        if cache_enabled and cache_path.exists() and not refresh_cache:
            frame = pd.read_csv(cache_path)
            print(f"  cache hit -> {weekly.format_number(len(frame))} TLD rows")
        else:
            frame = process_raw_file(raw_path, cache_path if cache_enabled else None)
        frames.append(frame)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def aggregate_tld_counts(tld_counts: pd.DataFrame) -> pd.DataFrame:
    if tld_counts.empty:
        return pd.DataFrame()

    grouped = (
        tld_counts.groupby("tld", as_index=False)
        .agg(
            observed_windows=("source_file", "nunique"),
            window_unique_fqdn_sum=("window_unique_fqdn_count", "sum"),
            domain_occurrences=("domain_occurrences", "sum"),
        )
    )
    total_window_unique = grouped["window_unique_fqdn_sum"].sum()
    total_occurrences = grouped["domain_occurrences"].sum()
    grouped["tld_label"] = "." + grouped["tld"].astype(str)
    grouped["tld_type"] = grouped["tld"].map(tld_type)
    grouped["country_or_territory"] = grouped["tld"].map(country_or_territory)
    grouped["region_bucket"] = grouped["tld"].map(weekly.detailed_region_for_tld)
    grouped["window_unique_fqdn_share"] = (grouped["window_unique_fqdn_sum"] / total_window_unique).round(6)
    grouped["occurrence_share"] = (grouped["domain_occurrences"] / total_occurrences).round(6)
    grouped["window_unique_fqdn_share_pct"] = (grouped["window_unique_fqdn_share"] * 100).round(3)
    grouped["occurrence_share_pct"] = (grouped["occurrence_share"] * 100).round(3)
    return grouped[
        [
            "tld_label",
            "tld",
            "tld_type",
            "country_or_territory",
            "region_bucket",
            "observed_windows",
            "window_unique_fqdn_sum",
            "domain_occurrences",
            "window_unique_fqdn_share",
            "occurrence_share",
            "window_unique_fqdn_share_pct",
            "occurrence_share_pct",
        ]
    ].sort_values(["window_unique_fqdn_sum", "domain_occurrences", "tld"], ascending=[False, False, True])


def main() -> None:
    args = parse_args()
    output_dir = weekly.resolve_project_path(args.output_dir) if args.output_dir else weekly.get_output_dir()
    if output_dir is None:
        output_dir = weekly.get_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows = weekly.selected_manifest_rows(args)
    tld_counts = load_or_build_tld_counts(
        manifest_rows,
        Path(args.cache_dir).resolve(),
        args.refresh_cache,
    )
    summary = aggregate_tld_counts(tld_counts)
    output_path = output_dir / "weekly_tld_counts.csv"
    weekly.write_csv(summary, output_path)
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
