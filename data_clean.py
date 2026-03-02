#!/usr/bin/env python3
"""Halloween CSV ingestion pipeline with idempotent MySQL upsert."""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

REQUIRED_COLUMNS = {"time_stamp", "date", "time", "counter_value", "increment"}
DEFAULT_TABLE_NAME = "halloween_tracking"
ALLOWED_INCREMENT_VALUES = {-1, 0, 1}
TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DataValidationError(Exception):
    """Raised when input CSV data does not meet contract requirements."""


@dataclass
class UpsertStats:
    input_rows: int
    mysql_affected_rows: int


@dataclass
class RunStats:
    files_processed: int
    rows_read: int
    rows_filtered_counter_zero: int
    rows_ready_for_upsert: int
    mysql_affected_rows: int
    elapsed_seconds: float


def normalize_columns(columns: Iterable[str]) -> list[str]:
    normalized = []
    for col in columns:
        value = str(col).strip().lower()
        value = re.sub(r"\s+", "_", value)
        value = re.sub(r"[^0-9a-zA-Z_]", "", value)
        normalized.append(value)
    return normalized


def extract_year_from_path(path: Path) -> int:
    match = re.search(r"(\d{4})", path.name)
    if not match:
        raise DataValidationError(
            f"{path}: filename must include a 4-digit year (e.g., tracking_2024.csv)."
        )
    return int(match.group(1))


def validate_table_name(table_name: str) -> str:
    if not TABLE_NAME_RE.match(table_name):
        raise DataValidationError(
            f"Invalid table name '{table_name}'. Use letters, numbers, and underscores only."
        )
    return table_name


def discover_files(data_dir: Path) -> list[Path]:
    files = sorted(data_dir.glob("*.csv"))
    if not files:
        raise DataValidationError(f"No CSV files found in {data_dir}.")
    return files


def _raise_first_bad_value(
    *,
    file_path: Path,
    source_rows: pd.Series,
    bad_mask: pd.Series,
    column: str,
    suggestion: str,
    values: pd.Series,
) -> None:
    bad_index = bad_mask[bad_mask].index[0]
    source_row = int(source_rows.loc[bad_index])
    bad_value = values.loc[bad_index]
    raise DataValidationError(
        f"{file_path}: invalid value in '{column}' at data row {source_row}: {bad_value!r}. "
        f"{suggestion}"
    )


def _coerce_int_column(df: pd.DataFrame, file_path: Path, column: str) -> pd.Series:
    series = df[column]
    numeric = pd.to_numeric(series, errors="coerce")
    bad_mask = numeric.isna() & series.notna()
    if bad_mask.any():
        _raise_first_bad_value(
            file_path=file_path,
            source_rows=df["source_row_num"],
            bad_mask=bad_mask,
            column=column,
            suggestion="Ensure it is an integer.",
            values=series,
        )

    int_mask = numeric.notna() & (numeric % 1 != 0)
    if int_mask.any():
        _raise_first_bad_value(
            file_path=file_path,
            source_rows=df["source_row_num"],
            bad_mask=int_mask,
            column=column,
            suggestion="Only whole numbers are allowed.",
            values=series,
        )

    return numeric.astype("Int64")


def load_and_validate_file(path: Path) -> pd.DataFrame:
    year = extract_year_from_path(path)

    try:
        df = pd.read_csv(path, skipinitialspace=True)
    except Exception as exc:
        raise DataValidationError(f"Failed to read {path}: {exc}") from exc

    df.columns = normalize_columns(df.columns)
    missing = sorted(REQUIRED_COLUMNS - set(df.columns))
    if missing:
        raise DataValidationError(
            f"{path}: missing required columns: {', '.join(missing)}. "
            "Expected: time_stamp, date, time, counter_value, increment."
        )

    # 1-based row number relative to data rows (header excluded).
    df["source_row_num"] = pd.RangeIndex(start=1, stop=len(df) + 1)
    df["source_file"] = path.name
    df["event_year"] = year

    return df


def transform(df: pd.DataFrame, source_file: str) -> pd.DataFrame:
    file_path = Path(source_file)

    ts_series = pd.to_datetime(df["time_stamp"], errors="coerce")
    bad_ts = ts_series.isna() & df["time_stamp"].notna()
    if bad_ts.any():
        _raise_first_bad_value(
            file_path=file_path,
            source_rows=df["source_row_num"],
            bad_mask=bad_ts,
            column="time_stamp",
            suggestion="Use ISO-like timestamps, e.g., 2025-10-31 18:34:47.8360.",
            values=df["time_stamp"],
        )

    date_series = pd.to_datetime(df["date"], errors="coerce")
    bad_date = date_series.isna() & df["date"].notna()
    if bad_date.any():
        _raise_first_bad_value(
            file_path=file_path,
            source_rows=df["source_row_num"],
            bad_mask=bad_date,
            column="date",
            suggestion="Use YYYY-MM-DD format.",
            values=df["date"],
        )

    time_series = pd.to_datetime(df["time"], format="%H:%M:%S", errors="coerce")
    bad_time = time_series.isna() & df["time"].notna()
    if bad_time.any():
        _raise_first_bad_value(
            file_path=file_path,
            source_rows=df["source_row_num"],
            bad_mask=bad_time,
            column="time",
            suggestion="Use HH:MM:SS 24-hour format.",
            values=df["time"],
        )

    counter_value = _coerce_int_column(df, file_path, "counter_value")
    increment = _coerce_int_column(df, file_path, "increment")

    bad_increment = ~increment.isin(ALLOWED_INCREMENT_VALUES)
    if bad_increment.any():
        _raise_first_bad_value(
            file_path=file_path,
            source_rows=df["source_row_num"],
            bad_mask=bad_increment,
            column="increment",
            suggestion="Allowed increment values are -1, 0, and 1.",
            values=df["increment"],
        )

    transformed = pd.DataFrame(
        {
            "event_ts": ts_series,
            "event_date": date_series.dt.date,
            "event_time": time_series.dt.time,
            "counter_value": counter_value,
            "increment": increment,
            "event_year": df["event_year"].astype("Int64"),
            "source_file": df["source_file"],
            "source_row_num": df["source_row_num"].astype("Int64"),
        }
    )

    null_required = transformed[
        [
            "event_ts",
            "event_date",
            "event_time",
            "counter_value",
            "increment",
            "event_year",
            "source_file",
            "source_row_num",
        ]
    ].isna().any(axis=1)
    if null_required.any():
        idx = null_required[null_required].index[0]
        row_num = int(transformed.loc[idx, "source_row_num"])
        raise DataValidationError(
            f"{file_path}: transformed row {row_num} contains null required fields. "
            "Check input values for missing data."
        )

    return transformed


def get_engine_from_env() -> Engine:
    load_dotenv()

    host = os.getenv("MYSQL_HOST")
    port = os.getenv("MYSQL_PORT", "3306")
    user = os.getenv("MYSQL_USER")
    password = os.getenv("MYSQL_PASSWORD")
    database = os.getenv("MYSQL_DATABASE")

    missing = [
        name
        for name, value in {
            "MYSQL_HOST": host,
            "MYSQL_USER": user,
            "MYSQL_PASSWORD": password,
            "MYSQL_DATABASE": database,
        }.items()
        if not value
    ]
    if missing:
        raise DataValidationError(
            "Missing required environment variables: "
            f"{', '.join(missing)}. See .env.example for expected values."
        )

    url = (
        f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"
    )
    return create_engine(url)


def ensure_schema(engine: Engine, table_name: str) -> None:
    table_name = validate_table_name(table_name)

    create_table_sql = f"""
    CREATE TABLE IF NOT EXISTS `{table_name}` (
      `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
      `event_ts` DATETIME(6) NOT NULL,
      `event_date` DATE NOT NULL,
      `event_time` TIME NOT NULL,
      `counter_value` INT UNSIGNED NOT NULL,
      `increment` TINYINT NOT NULL,
      `event_year` SMALLINT UNSIGNED NOT NULL,
      `source_file` VARCHAR(255) NOT NULL,
      `source_row_num` INT UNSIGNED NOT NULL,
      `ingested_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (`id`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """

    with engine.begin() as conn:
        conn.execute(text(create_table_sql))

        index_exists = conn.execute(
            text(
                """
                SELECT 1
                FROM information_schema.statistics
                WHERE table_schema = DATABASE()
                  AND table_name = :table_name
                  AND index_name = :index_name
                LIMIT 1
                """
            ),
            {"table_name": table_name, "index_name": "idx_event_ts"},
        ).scalar()
        if not index_exists:
            conn.execute(
                text(
                    f"ALTER TABLE `{table_name}` ADD INDEX `idx_event_ts` (`event_ts`)"
                )
            )

        year_index_exists = conn.execute(
            text(
                """
                SELECT 1
                FROM information_schema.statistics
                WHERE table_schema = DATABASE()
                  AND table_name = :table_name
                  AND index_name = :index_name
                LIMIT 1
                """
            ),
            {"table_name": table_name, "index_name": "idx_event_year"},
        ).scalar()
        if not year_index_exists:
            conn.execute(
                text(
                    f"ALTER TABLE `{table_name}` ADD INDEX `idx_event_year` (`event_year`)"
                )
            )

        unique_exists = conn.execute(
            text(
                """
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_schema = DATABASE()
                  AND table_name = :table_name
                  AND constraint_type = 'UNIQUE'
                  AND constraint_name = :constraint_name
                LIMIT 1
                """
            ),
            {"table_name": table_name, "constraint_name": "uq_source_row"},
        ).scalar()
        if not unique_exists:
            conn.execute(
                text(
                    f"ALTER TABLE `{table_name}` "
                    "ADD CONSTRAINT `uq_source_row` UNIQUE (`source_file`, `source_row_num`)"
                )
            )


def upsert_dataframe(engine: Engine, table_name: str, df: pd.DataFrame) -> UpsertStats:
    table_name = validate_table_name(table_name)
    if df.empty:
        return UpsertStats(input_rows=0, mysql_affected_rows=0)

    staging_table = f"{table_name}_staging_{uuid.uuid4().hex[:8]}"
    staging_table = validate_table_name(staging_table)

    mysql_affected_rows = 0
    with engine.begin() as conn:
        try:
            df.to_sql(staging_table, con=conn, if_exists="replace", index=False, method="multi")

            upsert_sql = text(
                f"""
                INSERT INTO `{table_name}` (
                    `event_ts`,
                    `event_date`,
                    `event_time`,
                    `counter_value`,
                    `increment`,
                    `event_year`,
                    `source_file`,
                    `source_row_num`
                )
                SELECT
                    `event_ts`,
                    `event_date`,
                    `event_time`,
                    `counter_value`,
                    `increment`,
                    `event_year`,
                    `source_file`,
                    `source_row_num`
                FROM `{staging_table}`
                ON DUPLICATE KEY UPDATE
                    `event_ts` = VALUES(`event_ts`),
                    `event_date` = VALUES(`event_date`),
                    `event_time` = VALUES(`event_time`),
                    `counter_value` = VALUES(`counter_value`),
                    `increment` = VALUES(`increment`),
                    `event_year` = VALUES(`event_year`)
                """
            )
            result = conn.execute(upsert_sql)
            mysql_affected_rows = int(result.rowcount or 0)
        finally:
            conn.execute(text(f"DROP TABLE IF EXISTS `{staging_table}`"))

    return UpsertStats(input_rows=len(df), mysql_affected_rows=mysql_affected_rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest Halloween CSV files into MySQL.")
    parser.add_argument("--data-dir", default="data", help="Directory containing CSV files.")
    parser.add_argument(
        "--table",
        default=os.getenv("MYSQL_TABLE", DEFAULT_TABLE_NAME),
        help="Destination MySQL table name.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and transform data without writing to MySQL.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-file processing details.",
    )
    return parser


def run(args: argparse.Namespace) -> RunStats:
    start = time.monotonic()
    table_name = validate_table_name(args.table)

    data_dir = Path(args.data_dir)
    files = discover_files(data_dir)

    frames: list[pd.DataFrame] = []
    total_rows_read = 0

    for file_path in files:
        raw_df = load_and_validate_file(file_path)
        total_rows_read += len(raw_df)
        transformed = transform(raw_df, file_path.name)
        frames.append(transformed)
        if args.verbose:
            print(f"Processed {file_path} ({len(raw_df)} rows)")

    combined = pd.concat(frames, ignore_index=True)

    zero_mask = combined["counter_value"] == 0
    rows_filtered_zero = int(zero_mask.sum())
    cleaned = combined[~zero_mask].reset_index(drop=True)

    mysql_affected_rows = 0
    if args.dry_run:
        if args.verbose:
            print("Dry run enabled; skipped database write.")
    else:
        engine = get_engine_from_env()
        ensure_schema(engine, table_name)
        upsert_stats = upsert_dataframe(engine, table_name, cleaned)
        mysql_affected_rows = upsert_stats.mysql_affected_rows

    elapsed = time.monotonic() - start
    return RunStats(
        files_processed=len(files),
        rows_read=total_rows_read,
        rows_filtered_counter_zero=rows_filtered_zero,
        rows_ready_for_upsert=len(cleaned),
        mysql_affected_rows=mysql_affected_rows,
        elapsed_seconds=elapsed,
    )


def print_summary(stats: RunStats, dry_run: bool) -> None:
    print("Ingestion summary")
    print(f"- files_processed: {stats.files_processed}")
    print(f"- rows_read: {stats.rows_read}")
    print(f"- rows_filtered_counter_zero: {stats.rows_filtered_counter_zero}")
    print(f"- rows_ready_for_upsert: {stats.rows_ready_for_upsert}")
    if not dry_run:
        print(f"- mysql_affected_rows: {stats.mysql_affected_rows}")
    print(f"- elapsed_seconds: {stats.elapsed_seconds:.3f}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        stats = run(args)
        print_summary(stats, dry_run=args.dry_run)
        return 0
    except DataValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover
        print(f"ERROR: Unexpected failure: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
