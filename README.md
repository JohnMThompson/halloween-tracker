# Halloween Tracking Ingestion

This project ingests yearly Halloween counter CSV exports from `data/` into a single MySQL table using idempotent upserts.

The application runs on **Pileated**, the homelab's Ubuntu Server, using a temporary Docker container connected to the existing private MySQL network.

## What the script does

1. Discovers `*.csv` files in a data directory.
2. Normalizes headers (`lowercase`, spaces to `_`, strips non-alphanumeric characters other than `_`).
3. Validates required columns: `time_stamp`, `date`, `time`, `counter_value`, `increment`.
4. Extracts the year from each filename (must include a 4-digit year).
5. Parses and type-checks values.
6. Filters rows where `counter_value == 0`.
7. Converts pandas values into native Python types.
8. Loads records directly into MySQL using parameterized `INSERT ... ON DUPLICATE KEY UPDATE`.
9. Prints an ingestion summary.

The importer processes all available CSV files on each run. Existing records are updated rather than duplicated, using the unique `(source_file, source_row_num)` constraint.

The ingestion process does not create, alter, or drop database tables.

## Project structure

- `data_clean.py`: CLI entrypoint and ingestion implementation
- `data/`: yearly source CSV files, named with a four-digit year
- `tests/test_data_clean.py`: unit and dry-run CLI tests
- `requirements.txt`: Python dependencies
- `Dockerfile`: container image definition
- `.dockerignore`: excludes local files and credentials from Docker builds
- `.env.example`: example database configuration
- `.env`: local database credentials (not committed to Git)

### Deployment locations

| Component | Location |
|---|---|
| Application | `/srv/jobs/halloween-tracker` |
| Source data | `/srv/jobs/halloween-tracker/data/` |
| MySQL deployment | `/srv/services/mysql` |
| Docker image | `halloween-tracker:local` |
| Docker network | `mysql` |
| Database | `halloween` |
| Table | `halloween_tracking` |

## Installation

### Local Python environment

For development, testing, and CSV validation:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Docker image

For production ingestion on Pileated:

```bash
cd /srv/jobs/halloween-tracker

docker build -t halloween-tracker:local .
```

The image includes Python 3.12, application dependencies, and the ingestion script.

Source CSV files and database credentials are supplied at runtime rather than embedded in the image.

## Configuration

Copy `.env.example` to `.env` and configure the database connection.

For Pileated:

```dotenv
MYSQL_HOST=mysql
MYSQL_PORT=3306
MYSQL_USER=halloween_write
MYSQL_PASSWORD=<local-secret>
MYSQL_DATABASE=halloween
MYSQL_TABLE=halloween_tracking
```

`MYSQL_TABLE` is optional and defaults to `halloween_tracking`.

The actual password is stored locally and must not be committed to Git.

Restrict access to the environment file:

```bash
chmod 600 .env
```

### Database connectivity

MySQL runs in a Docker container on the internal Docker network named `mysql`.

The hostname `mysql` resolves inside containers attached to that network. It is not necessarily resolvable from the Ubuntu host.

Consequently, the production ingestion runs in a temporary Docker container attached to the same network.

The `halloween_write` account has `SELECT`, `INSERT`, `UPDATE`, and `DELETE` privileges on the `halloween` database.

Normal ingestion does not require `CREATE`, `ALTER`, or `DROP` privileges.

## Running the importer

### Dry run

Validate and transform the CSV files without writing to MySQL:

```bash
python3 data_clean.py --dry-run
```

For a container-based dry run:

```bash
docker run --rm \
  -v "$PWD/data:/app/data:ro" \
  halloween-tracker:local \
  python data_clean.py --dry-run
```

A dry run does not require database connectivity.

### Production ingestion

From the project directory on Pileated:

```bash
cd /srv/jobs/halloween-tracker

docker run --rm \
  --network mysql \
  --env-file .env \
  -v "$PWD/data:/app/data:ro" \
  halloween-tracker:local
```

This command:

- Creates a temporary ingestion container.
- Connects it to the private MySQL Docker network.
- Supplies database credentials through environment variables.
- Mounts the CSV directory read-only.
- Processes all available yearly CSV files.
- Inserts new records and updates existing records.
- Removes the container when execution completes.

The Docker image must be rebuilt after changes to `data_clean.py` or its dependencies.

### CLI options

- `--data-dir data`: source CSV directory
- `--table halloween_tracking`: destination table
- `--dry-run`: validate without database writes
- `--verbose`: print additional processing details

## Annual Halloween import procedure

The following process should be used after Halloween each year.

### 1. Export the counter data

Export the year's data as a CSV file.

Name it using the four-digit year:

```text
data/2027.csv
```

Retain previous years' files in the same directory.

### 2. Validate the data

```bash
cd /srv/jobs/halloween-tracker

source .venv/bin/activate
python3 data_clean.py --dry-run
```

Review the ingestion summary for unexpected row counts or validation errors.

### 3. Update the application if needed

If application code or dependencies have changed, pull the latest committed changes and rebuild:

```bash
git pull
docker build -t halloween-tracker:local .
```

Rebuilding is unnecessary when only the CSV data has changed.

### 4. Run the ingestion

```bash
docker run --rm \
  --network mysql \
  --env-file .env \
  -v "$PWD/data:/app/data:ro" \
  halloween-tracker:local
```

### 5. Verify the results

Query the existing MySQL container:

```bash
docker exec mysql sh -c '
MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -u root halloween -e "
  SELECT
    event_year,
    COUNT(*) AS records,
    MIN(event_ts) AS first_event,
    MAX(event_ts) AS last_event
  FROM halloween_tracking
  GROUP BY event_year
  ORDER BY event_year;
"
'
```

Confirm that the new year appears and previous years retain their expected record counts.

### 6. Confirm idempotency if needed

Run the ingestion a second time and confirm that the total record count does not increase.

Re-running the importer is safe because the unique source-row constraint prevents duplicate records.

## Target table

Database: `halloween`

Default table: `halloween_tracking`

### Columns

| Column | Type |
|---|---|
| `id` | BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY |
| `event_ts` | DATETIME(6) NOT NULL |
| `event_date` | DATE NOT NULL |
| `event_time` | TIME NOT NULL |
| `counter_value` | INT UNSIGNED NOT NULL |
| `increment` | TINYINT NOT NULL |
| `event_year` | SMALLINT UNSIGNED NOT NULL |
| `source_file` | VARCHAR(255) NOT NULL |
| `source_row_num` | INT UNSIGNED NOT NULL |
| `ingested_at` | TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP |

### Indexes and constraints

- `PRIMARY (id)`
- `idx_event_ts (event_ts)`
- `idx_event_year (event_year)`
- `uq_source_row (source_file, source_row_num)` — unique

The table and indexes are provisioned separately from the normal ingestion process.

The `ensure_schema()` function remains in the source code but is not invoked during ingestion.

## Validation behavior

The script fails with a non-zero exit code for:

- Missing required columns
- Invalid timestamps, dates, or times
- Invalid integers in `counter_value` or `increment`
- `increment` values outside `-1, 0, 1`
- Filenames without a four-digit year
- Missing required database environment variables
- Database connectivity or permission failures

Validation errors identify the relevant file, column, failing row, offending value, and suggested correction where applicable.

## Testing

Run the unit and CLI tests:

```bash
python3 -m unittest discover -s tests -v
```

Run the CSV validation:

```bash
python3 data_clean.py --dry-run
```

The current tests cover CSV transformation, validation, year extraction, and dry-run behavior.

Database upsert behavior has additionally been verified against the deployed MySQL instance, but is not yet covered by automated integration tests.

## Deployment verification

Initial successful deployment: November 2026.

| Year | Records |
|---|---:|
| 2024 | 62 |
| 2025 | 45 |
| 2026 | 45 |
| **Total** | **152** |

The importer was executed successfully and rerun to confirm idempotency. The second execution left the database at 152 records.

## Future improvements

Potential enhancements:

- Add automated integration tests for direct MySQL upserts.
- Add a `--year` option to process only a selected year's CSV.
- Add a separate schema-provisioning command for fresh installations.
- Add automated backup or verification steps before annual ingestion.

These enhancements are optional; the current implementation supports the annual import workflow.
