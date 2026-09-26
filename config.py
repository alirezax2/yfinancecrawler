import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# Hugging Face Settings
HF_TOKEN = os.getenv("HF_TOKEN", "").strip()
_raw_dataset = os.getenv("HF_YFINANCE_DATASET", os.getenv("HF_DATASETS", "AmirTrader/YahooFinance")).strip()
HF_YFINANCE_DATASET = _raw_dataset.replace("DATASETS=", "").strip()
TD_DATASET = os.getenv("TD_DATASET", "AmirTrader/TradingViewData").strip()
TD_FILENAME = os.getenv("TD_FILENAME", "america.csv").strip()

# Crawling & Ingestion Configuration (conservative defaults per .gemini/SKILL.md)
HISTORY_PERIOD_YEARS = int(os.getenv("HISTORY_PERIOD_YEARS", "7"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "100"))
MAX_CONCURRENT_BATCHES = int(os.getenv("MAX_CONCURRENT_BATCHES", "2"))
YFINANCE_THREADS = int(os.getenv("YFINANCE_THREADS", "2"))
INTERVAL = "1d"
AUTO_ADJUST = False
RETRY_ATTEMPTS = int(os.getenv("RETRY_ATTEMPTS", "4"))
BACKOFF_SECONDS = [5, 15, 45, 120]

# Local Storage Paths
DATA_DIR = BASE_DIR / "data"
DAILY_DATA_DIR = DATA_DIR / "daily"
STATE_DIR = DATA_DIR / "state"
STATE_FILE = STATE_DIR / "ingestion_state.parquet"

# Required Schema
REQUIRED_COLUMNS = ["date", "open", "high", "low", "close", "adj_close", "volume"]
