import pandas as pd
import re
import glob

files = glob.glob('data/*.csv')

def read_with_year(path):
    df = pd.read_csv(path)
    year = int(re.search(r'(\d{4})', path).group(1))
    return pd.read_csv(path).assign(year=year)


df = pd.concat((read_with_year(f) for f in files), ignore_index=True)

print(df)