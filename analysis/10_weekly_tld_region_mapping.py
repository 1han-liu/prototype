#!/usr/bin/env python3

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from tld_region_mapping import normalize_continent

SCRIPT_DIR = Path(__file__).resolve().parent
TLD_COUNTS_SCRIPT = SCRIPT_DIR / "08_weekly_tld_counts.py"

REGION_LABELS = {
    "Europe": "Europe ccTLD/geographic TLD",
    "Americas": "Americas ccTLD/geographic TLD",
    "Asia": "Asia ccTLD/geographic TLD",
    "Africa": "Africa ccTLD/geographic TLD",
    "Oceania": "Oceania ccTLD/geographic TLD",
    "Antarctica": "Antarctica ccTLD/geographic TLD",
    "Global": "Global/non-regional TLD",
    "Other": "Other/ambiguous TLD",
}

# Google Search Central treats these formal ccTLDs as generic for geographic
# targeting because users and site owners commonly use them without a country
# target. The list was checked on 2026-08-18. IANA remains the source for their
# formal ccTLD status.
# https://developers.google.com/search/docs/specialty/international/managing-multi-regional-sites
GENERIC_CCTLD_OVERRIDES: dict[str, str] = {
    "ad": "Andorra",
    "ai": "Anguilla",
    "as": "American Samoa",
    "bz": "Belize",
    "cc": "Cocos (Keeling) Islands",
    "cd": "Democratic Republic of the Congo",
    "co": "Colombia",
    "dj": "Djibouti",
    "fm": "Micronesia",
    "io": "British Indian Ocean Territory",
    "la": "Laos",
    "me": "Montenegro",
    "ms": "Montserrat",
    "nu": "Niue",
    "sc": "Seychelles",
    "sr": "Suriname",
    "su": "Soviet Union (legacy)",
    "tk": "Tokelau",
    "tv": "Tuvalu",
    "ws": "Samoa",
}

# Curated overrides for observed geographic, cultural, and city gTLDs.
# These are not ccTLDs; keep tld_class separate from the analysis bucket.
GEOGRAPHIC_GTLD_OVERRIDES: dict[str, tuple[str, str, str, str]] = {
    "abudhabi": ("United Arab Emirates", "Asia", "geographic_gTLD", "Abu Dhabi city/emirate"),
    "africa": ("Africa", "Africa", "geographic_gTLD", "continental geographic TLD"),
    "alsace": ("France", "Europe", "geographic_gTLD", "Alsace region"),
    "amsterdam": ("Netherlands", "Europe", "geographic_gTLD", "Amsterdam city"),
    "asia": ("Asia-Pacific", "Asia", "geographic_gTLD", "regional geographic TLD"),
    "barcelona": ("Spain", "Europe", "geographic_gTLD", "Barcelona city"),
    "bayern": ("Germany", "Europe", "geographic_gTLD", "Bavaria region"),
    "berlin": ("Germany", "Europe", "geographic_gTLD", "Berlin city"),
    "boston": ("United States", "Americas", "geographic_gTLD", "Boston city"),
    "brussels": ("Belgium", "Europe", "geographic_gTLD", "Brussels city/region"),
    "bzh": ("France", "Europe", "geographic_gTLD", "Brittany cultural/geographic TLD"),
    "capetown": ("South Africa", "Africa", "geographic_gTLD", "Cape Town city"),
    "cat": ("Catalan linguistic/cultural community", "Europe", "geographic_gTLD", "Catalan community"),
    "cologne": ("Germany", "Europe", "geographic_gTLD", "Cologne city"),
    "corsica": ("France", "Europe", "geographic_gTLD", "Corsica region"),
    "dubai": ("United Arab Emirates", "Asia", "geographic_gTLD", "Dubai city/emirate"),
    "durban": ("South Africa", "Africa", "geographic_gTLD", "Durban city"),
    "eus": ("Basque linguistic/cultural community", "Europe", "geographic_gTLD", "Basque community"),
    "frl": ("Netherlands", "Europe", "geographic_gTLD", "Friesland region"),
    "gal": ("Spain", "Europe", "geographic_gTLD", "Galicia region"),
    "gent": ("Belgium", "Europe", "geographic_gTLD", "Ghent city"),
    "hamburg": ("Germany", "Europe", "geographic_gTLD", "Hamburg city"),
    "irish": ("Ireland", "Europe", "geographic_gTLD", "Irish community"),
    "ist": ("Turkiye", "Asia", "geographic_gTLD", "Istanbul city abbreviation"),
    "istanbul": ("Turkiye", "Asia", "geographic_gTLD", "Istanbul city"),
    "joburg": ("South Africa", "Africa", "geographic_gTLD", "Johannesburg city"),
    "kiwi": ("New Zealand", "Oceania", "geographic_gTLD", "New Zealand cultural TLD"),
    "koeln": ("Germany", "Europe", "geographic_gTLD", "Cologne city"),
    "kyoto": ("Japan", "Asia", "geographic_gTLD", "Kyoto city/prefecture"),
    "lat": ("Latin America", "Americas", "geographic_gTLD", "Latin American regional/community TLD"),
    "london": ("United Kingdom", "Europe", "geographic_gTLD", "London city"),
    "madrid": ("Spain", "Europe", "geographic_gTLD", "Madrid city"),
    "melbourne": ("Australia", "Oceania", "geographic_gTLD", "Melbourne city"),
    "miami": ("United States", "Americas", "geographic_gTLD", "Miami city"),
    "moscow": ("Russia", "Europe", "geographic_gTLD", "Moscow city; Russia is transcontinental"),
    "nagoya": ("Japan", "Asia", "geographic_gTLD", "Nagoya city"),
    "nrw": ("Germany", "Europe", "geographic_gTLD", "North Rhine-Westphalia region"),
    "nyc": ("United States", "Americas", "geographic_gTLD", "New York City"),
    "osaka": ("Japan", "Asia", "geographic_gTLD", "Osaka city/prefecture"),
    "paris": ("France", "Europe", "geographic_gTLD", "Paris city"),
    "quebec": ("Canada", "Americas", "geographic_gTLD", "Quebec province"),
    "rio": ("Brazil", "Americas", "geographic_gTLD", "Rio de Janeiro city"),
    "ruhr": ("Germany", "Europe", "geographic_gTLD", "Ruhr region"),
    "saarland": ("Germany", "Europe", "geographic_gTLD", "Saarland region"),
    "scot": ("United Kingdom", "Europe", "geographic_gTLD", "Scotland community"),
    "swiss": ("Switzerland", "Europe", "geographic_gTLD", "Swiss community"),
    "sydney": ("Australia", "Oceania", "geographic_gTLD", "Sydney city"),
    "taipei": ("Taiwan", "Asia", "geographic_gTLD", "Taipei city"),
    "tirol": ("Austria", "Europe", "geographic_gTLD", "Tyrol region"),
    "tokyo": ("Japan", "Asia", "geographic_gTLD", "Tokyo city/metropolis"),
    "vegas": ("United States", "Americas", "geographic_gTLD", "Las Vegas city"),
    "vlaanderen": ("Belgium", "Europe", "geographic_gTLD", "Flanders region"),
    "wales": ("United Kingdom", "Europe", "geographic_gTLD", "Wales community"),
    "wien": ("Austria", "Europe", "geographic_gTLD", "Vienna city"),
    "yokohama": ("Japan", "Asia", "geographic_gTLD", "Yokohama city"),
    "zuerich": ("Switzerland", "Europe", "geographic_gTLD", "Zurich city/canton"),
    "xn--80adxhks": ("Russia", "Europe", "geographic_gTLD", "Moscow IDN; Russia is transcontinental"),
}

# Observed IDN ccTLDs not covered by the older local dictionary.
IDN_CCTLD_OVERRIDES: dict[str, tuple[str, str, str]] = {
    "xn--p1ai": ("Russia", "Other", "Russian Federation IDN ccTLD"),
    "xn--o3cw4h": ("Thailand", "Asia", "Thailand IDN ccTLD"),
    "xn--90ais": ("Belarus", "Europe", "Belarus IDN ccTLD"),
    "xn--h2brj9c": ("India", "Asia", "India IDN ccTLD"),
    "xn--j1amh": ("Ukraine", "Europe", "Ukraine IDN ccTLD"),
    "xn--90ae": ("Bulgaria", "Europe", "Bulgaria IDN ccTLD"),
    "xn--4dbrk0ce": ("Israel", "Asia", "Israel IDN ccTLD"),
    "xn--j6w193g": ("Hong Kong", "Asia", "Hong Kong IDN ccTLD"),
    "xn--qxam": ("Greece", "Europe", "Greece IDN ccTLD"),
    "xn--90a3ac": ("Serbia", "Europe", "Serbia IDN ccTLD"),
    "xn--gecrj9c": ("India", "Asia", "India IDN ccTLD"),
    "xn--e1a4c": ("European Union", "Europe", "European Union IDN ccTLD"),
    "xn--y9a3aq": ("Armenia", "Asia", "Armenia IDN ccTLD"),
    "xn--54b7fta0cc": ("Bangladesh", "Asia", "Bangladesh IDN ccTLD"),
    "xn--kpry57d": ("Taiwan", "Asia", "Taiwan IDN ccTLD"),
    "xn--mgba3a4f16a": ("Iran", "Asia", "Iran IDN ccTLD"),
    "xn--80ao21a": ("Kazakhstan", "Asia", "Kazakhstan IDN ccTLD"),
    "xn--d1alf": ("North Macedonia", "Europe", "North Macedonia IDN ccTLD"),
    "xn--node": ("Georgia", "Asia", "Georgia IDN ccTLD"),
    "xn--45brj9c": ("India", "Asia", "India IDN ccTLD"),
    "xn--mix891f": ("Macao", "Asia", "Macao IDN ccTLD"),
    "xn--h2brj9c8c": ("India", "Asia", "India IDN ccTLD"),
    "xn--fpcrj9c3d": ("India", "Asia", "India IDN ccTLD"),
    "xn--xkc2dl3a5ee0h": ("India", "Asia", "India IDN ccTLD"),
    "xn--mgbah1a3hjkrd": ("Mauritania", "Africa", "Mauritania IDN ccTLD"),
    "xn--wgbh1c": ("Egypt", "Africa", "Egypt IDN ccTLD"),
    "xn--s9brj9c": ("India", "Asia", "India IDN ccTLD"),
    "xn--fzc2c9e2c": ("Sri Lanka", "Asia", "Sri Lanka IDN ccTLD"),
    "xn--mgbbh1a71e": ("India", "Asia", "India IDN ccTLD"),
    "xn--ogbpf8fl": ("Syria", "Asia", "Syria IDN ccTLD"),
    "xn--45br5cyl": ("India", "Asia", "India IDN ccTLD"),
    "xn--2scrj9c": ("India", "Asia", "India IDN ccTLD"),
    "xn--wgbl6a": ("Qatar", "Asia", "Qatar IDN ccTLD"),
    "xn--mgbaam7a8h": ("United Arab Emirates", "Asia", "United Arab Emirates IDN ccTLD"),
    "xn--ygbi2ammx": ("Palestine", "Asia", "Palestine IDN ccTLD"),
    "xn--mgbpl2fh": ("Sudan", "Africa", "Sudan IDN ccTLD"),
    "xn--lgbbat1ad8j": ("Algeria", "Africa", "Algeria IDN ccTLD"),
    "xn--pgbs0dh": ("Tunisia", "Africa", "Tunisia IDN ccTLD"),
    "xn--xkc2al3hye2a": ("Sri Lanka", "Asia", "Sri Lanka IDN ccTLD"),
    "xn--rvc1e0am3e": ("India", "Asia", "India IDN ccTLD"),
    "xn--mgbgu82a": ("India", "Asia", "India IDN ccTLD"),
    "xn--3hcrj9c": ("India", "Asia", "India IDN ccTLD"),
    "xn--mgbcpq6gpa1a": ("Bahrain", "Asia", "Bahrain IDN ccTLD"),
    "xn--q7ce6a": ("Laos", "Asia", "Laos IDN ccTLD"),
}


def load_tld_counts_module() -> Any:
    spec = importlib.util.spec_from_file_location("weekly_tld_counts", TLD_COUNTS_SCRIPT)
    if not spec or not spec.loader:
        raise ImportError(f"Unable to load {TLD_COUNTS_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tld_counts = load_tld_counts_module()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a unique TLD-to-region mapping table from weekly_tld_counts.csv.")
    parser.add_argument(
        "--input",
        default=os.environ.get("TLD_COUNTS_FILE", "figures/weekly_tld_counts.csv"),
        help="Input weekly TLD count CSV.",
    )
    parser.add_argument(
        "--output",
        default=os.environ.get("TLD_MAPPING_FILE", "figures/weekly_tld_region_mapping.csv"),
        help="Output mapping CSV.",
    )
    return parser.parse_args()


def decode_idn_label(tld: str) -> str:
    if not tld.startswith("xn--"):
        return ""
    try:
        return tld.encode("ascii").decode("idna")
    except UnicodeError:
        return ""


def base_region_from_existing_bucket(bucket: str) -> str:
    for region in ["Europe", "Americas", "Asia", "Africa", "Oceania"]:
        if str(bucket).startswith(region):
            return region
    if str(bucket).startswith("Global"):
        return "Global"
    return "Other"


def classify_tld(row: pd.Series) -> dict[str, Any]:
    tld = str(row["tld"]).strip().lower()
    existing_class = str(row.get("tld_type", "") or "")
    existing_country = row.get("country_or_territory")
    existing_bucket = str(row.get("region_bucket", "") or "")

    if tld in GENERIC_CCTLD_OVERRIDES:
        return {
            "mapped_tld_class": "globalized_ccTLD",
            "mapped_country_or_territory": GENERIC_CCTLD_OVERRIDES[tld],
            "mapped_continent": "Global",
            "mapped_region_bucket": REGION_LABELS["Global"],
            "mapping_basis": "google_search_generic_cctld_list",
            "mapping_note": "Formal ccTLD treated as generic for geographic analysis; list checked 2026-08-18.",
        }

    if tld in IDN_CCTLD_OVERRIDES:
        country, region, note = IDN_CCTLD_OVERRIDES[tld]
        region = normalize_continent(tld, region)
        return {
            "mapped_tld_class": "ccTLD",
            "mapped_country_or_territory": country,
            "mapped_continent": region,
            "mapped_region_bucket": REGION_LABELS[region],
            "mapping_basis": "curated_idn_cctld_override",
            "mapping_note": note,
        }

    if existing_class == "ccTLD":
        region = base_region_from_existing_bucket(existing_bucket)
        region = normalize_continent(tld, region)
        return {
            "mapped_tld_class": "ccTLD",
            "mapped_country_or_territory": existing_country,
            "mapped_continent": region,
            "mapped_region_bucket": REGION_LABELS[region],
            "mapping_basis": "existing_iso_cctld_mapping",
            "mapping_note": "",
        }

    if tld in GEOGRAPHIC_GTLD_OVERRIDES:
        country, region, mapped_class, note = GEOGRAPHIC_GTLD_OVERRIDES[tld]
        return {
            "mapped_tld_class": mapped_class,
            "mapped_country_or_territory": country,
            "mapped_continent": region,
            "mapped_region_bucket": REGION_LABELS[region],
            "mapping_basis": "curated_geographic_gtld_override",
            "mapping_note": note,
        }

    return {
        "mapped_tld_class": "global_gTLD" if tld != "arpa" else "infrastructure_TLD",
        "mapped_country_or_territory": "Global" if tld != "arpa" else "Internet infrastructure",
        "mapped_continent": "Global",
        "mapped_region_bucket": REGION_LABELS["Global"],
        "mapping_basis": "default_non_geographic_tld",
        "mapping_note": "Non-ccTLD and not in curated geographic gTLD overrides.",
    }


def build_mapping(df: pd.DataFrame) -> pd.DataFrame:
    if "tld" not in df.columns:
        raise ValueError("Input CSV must contain a tld column.")

    rows = []
    for _, row in df.drop_duplicates("tld").iterrows():
        mapped = classify_tld(row)
        rows.append({
            "tld_label": "." + str(row["tld"]).strip().lower(),
            "tld": str(row["tld"]).strip().lower(),
            "idn_unicode": decode_idn_label(str(row["tld"]).strip().lower()),
            "source_tld_type": row.get("tld_type"),
            "source_country_or_territory": row.get("country_or_territory"),
            "source_region_bucket": row.get("region_bucket"),
            **mapped,
            "observed_windows": row.get("observed_windows"),
            "window_unique_fqdn_sum": row.get("window_unique_fqdn_sum"),
            "domain_occurrences": row.get("domain_occurrences"),
            "window_unique_fqdn_share_pct": row.get("window_unique_fqdn_share_pct"),
            "occurrence_share_pct": row.get("occurrence_share_pct"),
        })
    return pd.DataFrame(rows).sort_values(
        ["window_unique_fqdn_sum", "domain_occurrences", "tld"],
        ascending=[False, False, True],
    )


def main() -> None:
    args = parse_args()
    input_path = tld_counts.weekly.resolve_project_path(args.input)
    if not input_path or not input_path.exists():
        raise FileNotFoundError(f"Input not found: {args.input}")
    output_path = tld_counts.weekly.resolve_project_path(args.output) or Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    source = pd.read_csv(input_path)
    mapping = build_mapping(source)
    tld_counts.weekly.write_csv(mapping, output_path)
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
