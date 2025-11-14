# 🎃 Halloween Tracking ETL Pipeline

A small, reliable ETL script for ingesting yearly CSV files of Halloween
counter data, cleaning and standardizing the dataset, and loading it
into a MySQL database with proper indexing.

## 📌 Overview

This script performs the following:

1. **Loads multiple CSV files** from `data/*.csv`\
2. **Cleans and normalizes column names**\
3. **Extracts the year** from each filename and appends it as a field\
4. **Filters invalid rows** (`counter_value != 0`)\
5. **Parses timestamps** into proper datetime\
6. **Writes the dataset to a MySQL table**, replacing any existing
    data\
7. **Adds an auto-increment primary key**\
8. **Creates useful indexes** on `time_stamp` and `year` for query
    performance

## 📁 Project Structure

    .
    ├── data/
    │   ├── tracking_2023.csv
    │   ├── tracking_2024.csv
    │   └── ...
    ├── .gitignore
    ├── config.py
    ├── data-clean.py
    └── README.md

## 📊 Data Requirements

### 1. CSV files

Place CSVs in the `data/` directory.\
Each filename must contain a **4-digit year** (e.g.,
`tracking_2024.csv`).

### 2. Required columns

Your CSVs should contain:

  Column Name   |    Purpose
  ----------------- | -------------------------------------
  `counter_value`   | Used to filter out zeroes
  `increment`       | Stored as integer
  `time_stamp`      | Parsed into datetime
  `date`, `time`    | Dropped once `time_stamp` is parsed

Columns are auto-cleaned to:

- lowercase
- underscores instead of spaces
- no special characters

## 🔧 Configuration

Create a `config.py` file:

    ``` python
    USER = "your_username"
    PASS = "your_password"
    HOST = "localhost"
    PORT = 3306
    DB   = "your_database"
    ```

## 🏗️ How It Works

### 1. Load & Clean Data

CSV files are loaded, cleaned, and concatenated.

### 2. Filtering

Rows where `counter_value == 0` are removed.

### 3. Timestamp Handling

`time_stamp` is parsed with `pd.to_datetime`.

### 4. Loading to MySQL

Data is written with appropriate MySQL types and replaced each run.

### 5. Post-Load SQL Operations

- Adds `id` BIGINT AUTO_INCREMENT primary key\
- Adds indexes on `time_stamp` and `year`

## ▶️ Running the Script

Install dependencies:

    ``` bash
    pip install pandas sqlalchemy pymysql pypandoc
    ```

Run:

    ``` bash
    python3 data-clean.py
    ```

## 🧪 Example Query

    ``` sql
    SELECT *
    FROM halloween_tracking
    WHERE year = 2024
    ORDER BY time_stamp DESC
    LIMIT 50;
    ```

## 📄 License

This project is licensed under the **MIT License**.\
See the `LICENSE` file for full details.

## Additional Info

This README.md was created with the assistance of AI.
