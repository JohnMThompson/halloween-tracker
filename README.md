# Halloween Tracking Ingestion

This project ingests yearly Halloween counter CSV exports from `data/` into a single MySQL table with idempotent upserts.

## What the script does

1. Discovers `*.csv` files in a data directory.
2. Normalizes headers (`lowercase`, spaces to `_`, strips non-alphanumeric `_`).
3. Validates required columns: `time_stamp`, `date`, `time`, `counter_value`, `increment`.
4. Extracts year from each filename (must include a 4-digit year).
5. Parses and type-checks values.
6. Filters rows where `counter_value == 0`.
7. Loads to MySQL using staging + `INSERT ... ON DUPLICATE KEY UPDATE`.
8. Prints a run summary.

## Project structure

- `data_clean.py`: CLI entrypoint and ingestion implementation (`python3 data_clean.py`)
- `data/`: source CSV files
- `tests/test_data_clean.py`: unit + dry-run CLI tests
- `.env.example`: required database settings

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env` and set values:

```bash
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=your_username
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=your_database
MYSQL_TABLE=halloween_tracking
```

`MYSQL_TABLE` is optional; default is `halloween_tracking`.

## Run

Dry run (validates/parses only, no DB writes):

```bash
python3 data_clean.py --dry-run
```

Full ingestion:

```bash
python3 data_clean.py
```

Optional flags:

- `--data-dir data`
- `--table halloween_tracking`
- `--dry-run`
- `--verbose`

## Target table

Default table: `halloween_tracking`

Columns:

- `id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY
- `event_ts` DATETIME(6) NOT NULL
- `event_date` DATE NOT NULL
- `event_time` TIME NOT NULL
- `counter_value` INT UNSIGNED NOT NULL
- `increment` TINYINT NOT NULL
- `event_year` SMALLINT UNSIGNED NOT NULL
- `source_file` VARCHAR(255) NOT NULL
- `source_row_num` INT UNSIGNED NOT NULL
- `ingested_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP

Indexes/constraints:

- `idx_event_ts (event_ts)`
- `idx_event_year (event_year)`
- unique `uq_source_row (source_file, source_row_num)`

## Validation behavior

The script fails fast (non-zero exit) for:

- Missing required columns
- Invalid timestamps/dates/times
- Invalid integers in `counter_value`/`increment`
- `increment` values outside `-1, 0, 1`
- Filenames without a 4-digit year
- Missing DB env vars / DB connectivity issues

Errors include file, column, first failing row, offending value, and suggested fix.

## Testing

Run tests:

```bash
python3 -m unittest discover -s tests -v
```
