# Daily Yahoo Finance Market Data Ingestion

## Purpose

Download and maintain daily OHLCV market data for a large universe of stock tickers using `yfinance`, while minimizing unnecessary requests and handling Yahoo Finance rate limiting gracefully.

This skill is designed for a large ticker universe refreshed once per trading day.

## Requirements

* Python 3.12+
* `yfinance`
* `pandas`
* `pyarrow` for Parquet storage

Install:

```bash
pip install yfinance pandas pyarrow
```

## Core Principles

### 1. Never create one simultaneous request per ticker

Do not create an unrestricted worker for every ticker:

```python
for ticker in tickers:
    yf.Ticker(ticker).history(...)
```

with a large thread pool.

Instead, use `yf.download()` with batches of tickers.

Recommended starting configuration:

```text
Batch size:             100–200 tickers
Concurrent batches:     2–4
Interval:               1d
```

These are starting points, not guaranteed Yahoo Finance limits. Tune conservatively based on observed behavior.

### 2. Download only missing data

After the initial historical load, do not download a full history every day.

Maintain the latest successfully stored date for each ticker.

Example state:

```text
ticker    last_date
AAPL      2026-09-04
MSFT      2026-09-04
NVDA      2026-09-04
```

The next run should request only the missing period.

### 3. Store data as Parquet

Use one Parquet file per ticker.

Recommended structure:

```text
data/
├── daily/
│   ├── AAPL.parquet
│   ├── MSFT.parquet
│   ├── NVDA.parquet
│   └── ...
└── state/
    └── ingestion_state.parquet
```

Each ticker file should contain normalized daily OHLCV data.

Example schema:

```text
date
open
high
low
close
adj_close
volume
```

Parquet should be the canonical persisted format.

Do not create CSV files as part of the ingestion pipeline.

### 4. Cache everything

Successful responses should be persisted immediately.

The system must be restartable. A successfully downloaded ticker should not need to be downloaded again simply because another ticker or batch failed.

### 5. Use retries with exponential backoff

Transient failures should be retried.

Suggested schedule:

```text
attempt 1 → wait 5 seconds
attempt 2 → wait 15 seconds
attempt 3 → wait 45 seconds
attempt 4 → wait 120 seconds
```

Add random jitter to avoid synchronized retries.

If Yahoo begins returning rate-limit responses, reduce concurrency rather than increasing it.

### 6. Rate limiting is global

Treat Yahoo rate limiting as a signal that the downloader is making too many requests.

Do not allow each worker to independently continue making requests.

When a rate-limit response occurs:

```text
pause workers
      ↓
increase backoff
      ↓
reduce concurrency
      ↓
retry later
```

## Initial Historical Load

For the first load, split the ticker universe into batches.

Example:

```python
import yfinance as yf

def download_batch(tickers):
    return yf.download(
        tickers=tickers,
        period="max",
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=True,
        group_by="column",
    )
```

Do not assume that `period="max"` is appropriate for every workload. If only a defined historical period is required, request that period instead.

## Daily Incremental Load

The daily job should:

1. Load the ticker universe.
2. Remove duplicate symbols.
3. Determine each ticker's latest stored date.
4. Identify tickers requiring an update.
5. Group tickers into batches.
6. Download missing daily data.
7. Validate the response.
8. Merge new rows with the existing Parquet file.
9. Remove duplicate dates.
10. Atomically replace the ticker's Parquet file.
11. Update ingestion state.
12. Record failures for retry.

Pseudo-flow:

```text
                    ticker universe
                           │
                           ▼
                    deduplicate
                           │
                           ▼
                 read ingestion state
                           │
                           ▼
                find missing dates
                           │
                           ▼
                  create batches
                           │
                           ▼
                  limited workers
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
           success                   failure
              │                         │
              ▼                         ▼
          validate                 classify error
              │                         │
              ▼                         ▼
       merge into Parquet          retry/backoff
              │
              ▼
        update state
```

## Concurrency

Start conservatively:

```python
BATCH_SIZE = 100
MAX_CONCURRENT_BATCHES = 2
```

If this operates reliably for a sustained period, test:

```python
BATCH_SIZE = 200
MAX_CONCURRENT_BATCHES = 3
```

Do not increase concurrency simply because the first few requests succeed.

Yahoo Finance availability and rate limiting can vary over time.

## Important: yfinance Threads

`yf.download()` has its own `threads` argument.

For a large ingestion workload, avoid stacking aggressive concurrency:

```text
your ThreadPoolExecutor
        +
large yf.download(threads=N)
```

because this can create significantly more concurrent work than intended.

Prefer a controlled combination such as:

```text
2–4 application-level batches
        +
small yfinance thread count
```

or benchmark one controlled approach against the other.

## Error Handling

Classify failures into categories.

### Rate limit

Examples:

```text
429
Too Many Requests
YFRateLimitError
```

Action:

```text
global backoff
reduce concurrency
retry later
```

### Temporary network error

Examples:

```text
timeout
connection reset
DNS/network failure
```

Action:

```text
retry with exponential backoff
```

### Invalid ticker

If a ticker consistently produces no valid data, record it as a ticker-level failure.

Do not continuously retry an invalid symbol.

### Delisted/inactive ticker

Record the ticker state and avoid requesting it indefinitely unless the ticker universe changes.

## Data Validation

Never assume a successful request means valid market data.

For each ticker verify:

* DataFrame is non-empty when data is expected.
* Date index exists and contains valid dates.
* OHLC columns are present.
* Dates are valid.
* No unexpected duplicate dates.
* Prices are numeric.
* Volume is numeric where applicable.
* Latest date is plausible.

Example:

```python
required_columns = {
    "Open",
    "High",
    "Low",
    "Close",
    "Volume",
}

missing = required_columns - set(df.columns)

if missing:
    raise ValueError(f"Missing columns: {missing}")
```

## Parquet Storage

Each ticker should have its own Parquet file:

```text
data/daily/AAPL.parquet
data/daily/MSFT.parquet
data/daily/NVDA.parquet
```

A ticker's Parquet file should contain all available historical daily records for that ticker.

Example:

```text
date        open     high     low      close    adj_close    volume
2026-09-01  ...
2026-09-02  ...
2026-09-03  ...
2026-09-04  ...
```

### Atomic writes

Never overwrite a production Parquet file directly while it is being written.

Use a temporary file:

```text
AAPL.parquet.tmp
```

Then atomically rename it:

```text
AAPL.parquet.tmp
        ↓
AAPL.parquet
```

This prevents a process interruption from leaving a corrupted or partially written data file.

### Updating an existing ticker

When new data arrives:

```text
existing AAPL.parquet
          +
new daily rows
          ↓
concatenate
          ↓
deduplicate by date
          ↓
sort by date
          ↓
write temporary Parquet
          ↓
atomic rename
```

Example:

```python
import os
import pandas as pd

def update_parquet(path, new_data):
    if os.path.exists(path):
        existing = pd.read_parquet(path)
        combined = pd.concat([existing, new_data])
    else:
        combined = new_data

    combined = (
        combined
        .reset_index()
        .drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
    )

    tmp_path = f"{path}.tmp"
    combined.to_parquet(tmp_path, index=False)
    os.replace(tmp_path, path)
```

## Duplicate Prevention

The storage layer must be idempotent.

Running the same daily job twice must not create duplicate rows.

The logical uniqueness constraint is:

```text
(ticker, date)
```

Because each ticker has its own Parquet file, `date` should be unique within each file.

## Missing Trading Days

Do not treat weekends and market holidays as missing data.

For example:

```text
Friday
Saturday  ← expected absence
Sunday    ← expected absence
Monday
```

The ingestion system should compare against an appropriate trading calendar rather than simply expecting a row for every calendar day.

For multiple exchanges, use the relevant exchange calendar.

## Adjusted vs Unadjusted Prices

Decide explicitly which data is required.

For raw OHLCV:

```python
auto_adjust=False
```

If adjusted historical prices are required, use yfinance's adjustment behavior consistently.

Do not mix adjusted and unadjusted data without explicitly identifying the fields and methodology.

## Recommended Dataset

Each Parquet file should use a normalized schema:

```text
date
open
high
low
close
adj_close
volume
```

Optional metadata can include:

```text
ticker
source
downloaded_at
```

Avoid storing unnecessary Yahoo Finance metadata alongside every daily row.

## Ingestion State

Maintain a separate Parquet state file:

```text
data/state/ingestion_state.parquet
```

Example:

```text
ticker    last_date    status
AAPL      2026-09-04   success
MSFT      2026-09-04   success
NVDA      2026-09-04   success
```

Optional fields:

```text
last_attempt
last_success
failure_count
last_error
```

The state file is used to determine which tickers require an update.

The actual Parquet data files remain the source of truth for market data.

## Logging

Every batch should produce structured logs.

Example:

```text
2026-09-06 02:00:00 INFO  Starting daily ingestion
2026-09-06 02:00:01 INFO  Universe loaded
2026-09-06 02:00:01 INFO  Tickers requiring update: 6592
2026-09-06 02:00:02 INFO  Created batches
2026-09-06 02:00:15 INFO  Batch 1 completed
2026-09-06 02:00:17 INFO  Batch 2 completed
2026-09-06 02:00:20 WARN  Rate limit detected; backing off
2026-09-06 02:01:20 INFO  Resuming with reduced concurrency
```

Track at minimum:

```text
total_tickers
updated_tickers
successful_tickers
failed_tickers
rate_limit_events
retry_count
duration_seconds
```

## Failure Recovery

The job must be restartable.

If the process crashes partway through the run:

```text
completed batches → already persisted
remaining batches → remain pending
```

On restart, the state and existing Parquet files should determine what still needs downloading.

Never require a complete historical reload because one batch failed.

## Scheduling

Run once per trading day, preferably after the relevant market's daily data is expected to be available.

Do not assume that midnight UTC means the trading day's data is available.

For multiple exchanges, account for their different market close times.

## Operational Strategy

### First run

Use:

```text
batch size:       100
concurrency:      2
historical data:  required historical period
Parquet storage:  enabled
```

Monitor:

```text
request failures
rate-limit responses
completion time
missing tickers
data validation failures
```

### Normal daily operation

Use:

```text
incremental dates only
batch size:       100–200
concurrency:      2–4
Parquet storage:  required
```

### If rate limits appear

Immediately:

```text
1. Stop launching new requests.
2. Allow in-flight requests to finish.
3. Back off.
4. Reduce concurrency.
5. Retry failed batches later.
```

Do not respond to rate limiting by multiplying workers or attempting to bypass Yahoo's controls.

## Configuration

Example:

```python
CONFIG = {
    "batch_size": 100,
    "max_concurrent_batches": 2,
    "yfinance_threads": 2,
    "interval": "1d",
    "auto_adjust": False,
    "retry_attempts": 4,
    "backoff_seconds": [5, 15, 45, 120],
    "storage_format": "parquet",
    "data_directory": "data/daily",
    "state_file": "data/state/ingestion_state.parquet",
}
```

These values are intentionally conservative. Benchmark and tune them rather than treating them as Yahoo Finance guarantees.

## Success Criteria

A successful daily run should satisfy:

```text
[✓] All eligible tickers evaluated
[✓] New daily data persisted
[✓] One Parquet file per ticker
[✓] No duplicate ticker/date records
[✓] Failed batches recorded
[✓] Rate-limit events recorded
[✓] Job can resume after interruption
[✓] Existing historical data is not unnecessarily redownloaded
[✓] Parquet writes are atomic
```

## Design Rule

The system should optimize request efficiency through:

* batching
* caching
* incremental updates
* controlled concurrency
* exponential backoff
* deduplication
* persistent Parquet storage
* restartable processing

Do not attempt to circumvent Yahoo Finance's rate limits or access controls.
