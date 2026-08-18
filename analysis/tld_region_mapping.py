from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from common import ROOT_DIR, resolve_project_path

DEFAULT_TLD_REGION_MAPPING = ROOT_DIR / "figures" / "weekly_tld_region_mapping.csv"

CONTINENT_REGION_COLUMNS = [
    "Global",
    "Europe",
    "Americas",
    "Asia",
    "Africa",
    "Oceania",
    "Antarctica",
]

CONTINENT_ORDER = {region: index for index, region in enumerate(CONTINENT_REGION_COLUMNS)}

CONTINENT_BY_AMBIGUOUS_TLD = {
    "ru": "Europe",
    "xn--p1ai": "Europe",
    "su": "Europe",
    "tl": "Asia",
    "aq": "Antarctica",
    "gs": "Antarctica",
    "tf": "Antarctica",
}


def resolve_mapping_path(path_value: str | None = None) -> Path:
    path = resolve_project_path(path_value) if path_value else DEFAULT_TLD_REGION_MAPPING
    if not path or not path.exists():
        raise FileNotFoundError(
            "TLD region mapping not found. Run "
            "`.venv/bin/python analysis/10_weekly_tld_region_mapping.py` first, "
            f"or pass --tld-region-map. Missing: {path_value or DEFAULT_TLD_REGION_MAPPING}"
        )
    return path


def normalize_continent(tld: str, value: Any) -> str:
    label = str(value or "").strip()
    if label in CONTINENT_ORDER:
        return label
    if label == "Other":
        return CONTINENT_BY_AMBIGUOUS_TLD.get(tld, "Global")
    return CONTINENT_BY_AMBIGUOUS_TLD.get(tld, "Global")


@dataclass(frozen=True)
class TldRegionMapping:
    path: Path
    region_by_tld: dict[str, str]
    signature: str

    @classmethod
    def from_csv(cls, path_value: str | Path | None = None) -> "TldRegionMapping":
        path = resolve_mapping_path(str(path_value) if path_value else None)
        df = pd.read_csv(path)
        required = {"tld", "mapped_continent"}
        missing = sorted(required.difference(df.columns))
        if missing:
            raise ValueError(f"TLD mapping is missing required columns: {', '.join(missing)}")

        region_by_tld = {
            str(row.tld).strip().lower(): normalize_continent(str(row.tld).strip().lower(), row.mapped_continent)
            for row in df.itertuples(index=False)
        }

        stat = path.stat()
        digest = hashlib.sha1(f"{path.resolve()}:{stat.st_size}:{int(stat.st_mtime)}".encode("utf-8")).hexdigest()[:16]
        return cls(path=path, region_by_tld=region_by_tld, signature=digest)

    def region_for_tld(self, tld: str) -> str:
        normalized = str(tld or "").strip().lower()
        if not normalized:
            return "Global"
        return self.region_by_tld.get(normalized, CONTINENT_BY_AMBIGUOUS_TLD.get(normalized, "Global"))
