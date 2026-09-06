# Yahoo Finance Market Data Ingestion Pipeline

An automated, daily ingestion pipeline that fetches 7 years of historical daily OHLCV data for US equities (~6,600+ symbols) from Yahoo Finance using `yfinance`, maintains incremental updates, and syncs individual Parquet files to Hugging Face datasets.

The pipeline runs automatically via **GitHub Actions** after US market close on days following open trading sessions, adhering to the best practices of rate-limiting, controlled concurrency, and atomic Parquet persistence.

---

## Architecture & Workflow

1. **Market Calendar Check**: Validates if the US Market (NYSE/NASDAQ) was open on the previous day using `exchange_calendars`. Skips non-trading days (weekends & market holidays).
2. **Ticker Universe Retrieval**: Downloads `america.csv` from Hugging Face dataset `AmirTrader/TradingViewData`, extracts and sanitizes symbols (`BRK.A` -> `BRK-A`, `JPM/PD` -> `JPM-PD`).
3. **Batch Downloader with Rate Limiting**:
   - Downloads data in batches of 100 tickers with controlled concurrency (2 workers) using `yf.download`.
   - Initial load retrieves 7 years of history (`period="7y"`).
   - Subsequent daily runs retrieve only missing dates (`start_date = last_date + 1`).
   - Exponential backoff (`[5, 15, 45, 120]` seconds) and rate-limit detection (429 / Too Many Requests).
4. **Data Normalization & Storage**:
   - Normalizes columns: `[date, open, high, low, close, adj_close, volume]`.
   - Idempotent deduplication by date and ascending sort.
   - Atomic writes (`.tmp` -> `.parquet`).
   - Maintains state tracking in `data/state/ingestion_state.parquet`.
5. **Hugging Face Sync**:
   - Commits updated Parquet files to Hugging Face dataset `AmirTrader/YahooFinance`.

---

## Dataset Layout

```text
AmirTrader/YahooFinance
├── README.md
└── data/
    ├── daily/
    │   ├── AAPL.parquet
    │   ├── MSFT.parquet
    │   ├── NVDA.parquet
    │   └── ...
    └── state/
        └── ingestion_state.parquet
```

---

## GitHub Actions Workflow

The workflow is located in [`.github/workflows/daily_crawler.yml`](.github/workflows/daily_crawler.yml):

- **Schedule**: `0 1 * * 2-6` (Tuesday through Saturday at 01:00 UTC, after Monday–Friday US market close).
- **Manual Trigger**: Supports `workflow_dispatch` with optional parameters:
  - `force`: Bypass calendar check to run immediately.
  - `tickers_limit`: Limit number of tickers for dry runs (e.g., `10`).
  - `no_upload`: Skip Hugging Face dataset upload.

### GitHub Repository Secrets & Variables

In your GitHub repository under **Settings > Secrets and variables > Actions**:

- **Secrets**:
  - `HF_TOKEN`: Hugging Face User Access Token with **Write** permission.
- **Variables** (Optional, default fallbacks apply):
  - `HF_YFINANCE_DATASET`: Target Hugging Face dataset repo (default: `AmirTrader/YahooFinance`).
  - `TD_DATASET`: Source TradingView dataset repo (default: `AmirTrader/TradingViewData`).

---

## Local Development & Testing

### 1. Install Dependencies with `uv`

```bash
# Install uv if not already installed
# https://docs.astral.sh/uv/
uv sync
```

### 2. Environment Variables

Create or edit `.env`:

```env
HF_TOKEN=hf_your_token_here
HF_YFINANCE_DATASET=AmirTrader/YahooFinance
TD_DATASET=AmirTrader/TradingViewData
```

### 3. Running the Pipeline

```bash
# Run regular daily ingestion (checks market calendar)
uv run python main.py

# Force run for testing with 10 tickers without uploading to HF
uv run python main.py --force --tickers-limit 10 --no-upload

# Run unit tests
uv run pytest
```
