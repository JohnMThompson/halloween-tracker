import pandas as pd
import re
import glob
import config
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.types import Integer, BigInteger, Date, Time, DateTime

# Import data

files = glob.glob('data/*.csv')

def read_with_year(path):
    df = pd.read_csv(path, skipinitialspace=True)
    df.columns = (
        df.columns
        .str.strip()
        .str.replace(r'\s+', '_', regex=True)
        .str.replace(r'[^0-9a-zA-Z_]', '', regex=True)
        .str.lower()
    )
    year = int(re.search(r'(\d{4})', path).group(1))
    return df.assign(year=year)

# Concatenate all dataframes

df = pd.concat((read_with_year(f) for f in files), ignore_index=True)

# Filter rows where 'Counter Value' is not 0

df = df[df['counter_value'] != 0]

df['time_stamp'] = pd.to_datetime(df['time_stamp'], errors='coerce')
df = df.drop(columns=['date', 'time',])

tz = "America/Chicago"
df["time_stamp"] = (
    df["time_stamp"]
      .dt.tz_localize(tz, nonexistent="shift_forward", ambiguous="NaT")
      .dt.tz_convert("UTC")
      .dt.tz_localize(None)
)

dtype_map = {
    'time_stamp': DateTime(),
    'date': Date(),
    'counter_value': BigInteger(),
    'increment': Integer()
    }

# Load to database

def get_engine():
    user = config.USER
    password = config.PASS
    host = config.HOST
    port = config.PORT
    database = config.DB
    return create_engine(
        f"mysql+pymysql://{USER}:{PASS}@{HOST}:{PORT}/{DB}?charset=utf8mb4"
        )

engine = get_engine()

df.to_sql(
    name='halloween_tracking',
    con=engine,
    if_exists='replace',
    index=False,
    chunksize=10_000,
    method='multi',
    dtype=dtype_map
)

TABLE = "halloween_tracking"

with engine.begin() as conn:
    conn.execute(text(f"""
        ALTER TABLE `{TABLE}`
        ADD COLUMN id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY;
    """))

with engine.begin() as conn:
    conn.execute(text(f"CREATE INDEX idx_time_stamp ON `{TABLE}` (time_stamp);"))
    conn.execute(text(f"CREATE INDEX idx_year ON `{TABLE}` (year);"))