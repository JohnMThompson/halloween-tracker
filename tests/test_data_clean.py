import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

import pandas as pd

import data_clean
from data_clean import DataValidationError


class DataCleanUnitTests(unittest.TestCase):
    def test_normalize_columns(self):
        columns = [" Time Stamp ", "Counter Value", "Increment%"]
        normalized = data_clean.normalize_columns(columns)
        self.assertEqual(normalized, ["time_stamp", "counter_value", "increment"])

    def test_extract_year_from_path(self):
        year = data_clean.extract_year_from_path(Path("tracking_2024.csv"))
        self.assertEqual(year, 2024)

    def test_extract_year_from_path_fails_without_year(self):
        with self.assertRaises(DataValidationError):
            data_clean.extract_year_from_path(Path("tracking.csv"))

    def test_load_and_validate_file_fails_missing_columns(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "tracking_2024.csv"
            file_path.write_text("Time Stamp,Date\n2024-10-31 18:00:00,2024-10-31\n")

            with self.assertRaises(DataValidationError) as exc:
                data_clean.load_and_validate_file(file_path)

            self.assertIn("missing required columns", str(exc.exception))

    def test_transform_fails_bad_timestamp(self):
        df = pd.DataFrame(
            {
                "time_stamp": ["not-a-timestamp"],
                "date": ["2024-10-31"],
                "time": ["18:00:00"],
                "counter_value": [1],
                "increment": [1],
                "source_row_num": [1],
                "source_file": ["tracking_2024.csv"],
                "event_year": [2024],
            }
        )

        with self.assertRaises(DataValidationError) as exc:
            data_clean.transform(df, "tracking_2024.csv")

        self.assertIn("invalid value in 'time_stamp'", str(exc.exception))


class DataCleanCliTests(unittest.TestCase):
    def test_cli_dry_run_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "tracking_2024.csv"
            csv_path.write_text(
                textwrap.dedent(
                    """\
                    Time Stamp, Date, Time, Counter Value, Increment
                    2024-10-31 18:00:00.0000, 2024-10-31, 18:00:00, 0, 0
                    2024-10-31 18:01:00.0000, 2024-10-31, 18:01:00, 1, 1
                    """
                )
            )

            result = subprocess.run(
                ["python3", "data_clean.py", "--data-dir", tmp_dir, "--dry-run"],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("rows_read: 2", result.stdout)
            self.assertIn("rows_ready_for_upsert: 1", result.stdout)


if __name__ == "__main__":
    unittest.main()
