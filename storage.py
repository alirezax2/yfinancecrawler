import os
import shutil
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
from huggingface_hub import HfApi, hf_hub_download, snapshot_download
import config

logger = logging.getLogger(__name__)


def ensure_directories():
    """Ensures local data directories exist."""
    config.DAILY_DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)


def get_ticker_parquet_path(ticker: str) -> Path:
    """Returns local path for a ticker's Parquet file."""
    return config.DAILY_DATA_DIR / f"{ticker}.parquet"


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalizes OHLCV DataFrame to standard lower-case schema:
    [date, open, high, low, close, adj_close, volume]
    Deduplicates by date and sorts ascending.
    """
    if df.empty:
        return pd.DataFrame(columns=config.REQUIRED_COLUMNS)

    df = df.copy()

    # If date is in index, reset index
    if "Date" in df.index.names or df.index.name == "Date" or isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()

    # Lowercase column names and replace spaces with underscores
    df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]

    # Map possible column variations
    col_mapping = {
        "adj_close": "adj_close",
        "adjclose": "adj_close",
        "adjusted_close": "adj_close",
    }
    df = df.rename(columns=col_mapping)

    # Standardize date column to 'YYYY-MM-DD'
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    else:
        raise ValueError("DataFrame missing 'date' column after reset_index")

    # Filter to required columns that exist
    for col in config.REQUIRED_COLUMNS:
        if col not in df.columns:
            if col == "adj_close" and "close" in df.columns:
                df["adj_close"] = df["close"]
            elif col == "volume":
                df["volume"] = 0
            else:
                df[col] = float("nan")

    df = df[config.REQUIRED_COLUMNS]

    # Ensure numeric types
    numeric_cols = ["open", "high", "low", "close", "adj_close"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")

    # Deduplicate by date and sort
    df = df.dropna(subset=["date", "close"])
    df = df.drop_duplicates(subset=["date"], keep="last").sort_values("date").reset_index(drop=True)
    return df


def update_ticker_parquet(ticker: str, new_data: pd.DataFrame) -> Optional[str]:
    """
    Atomically merges new rows into ticker's Parquet file.
    Returns latest date stored in format 'YYYY-MM-DD' or None if empty.
    """
    ensure_directories()
    target_path = get_ticker_parquet_path(ticker)
    tmp_path = target_path.with_suffix(".parquet.tmp")

    norm_new = normalize_dataframe(new_data)
    if norm_new.empty:
        return None

    if target_path.exists():
        try:
            existing_df = pd.read_parquet(target_path)
            combined = pd.concat([existing_df, norm_new], ignore_index=True)
            combined = (
                combined
                .drop_duplicates(subset=["date"], keep="last")
                .sort_values("date")
                .reset_index(drop=True)
            )
        except Exception as e:
            logger.warning(f"Error reading existing parquet for {ticker}, overwriting: {e}")
            combined = norm_new
    else:
        combined = norm_new

    if combined.empty:
        return None

    # Atomic write
    combined.to_parquet(tmp_path, index=False, engine="pyarrow")
    if tmp_path.exists():
        os.replace(tmp_path, target_path)

    latest_date = str(combined["date"].iloc[-1])
    return latest_date


def load_ingestion_state() -> pd.DataFrame:
    """
    Loads ingestion state Parquet file or returns empty state DataFrame.
    """
    ensure_directories()
    if config.STATE_FILE.exists():
        try:
            df = pd.read_parquet(config.STATE_FILE)
            expected_cols = [
                "ticker", "last_date", "status", "last_attempt",
                "last_success", "failure_count", "last_error"
            ]
            for col in expected_cols:
                if col not in df.columns:
                    df[col] = "" if "date" in col or "last" in col or "status" in col or "error" in col or "ticker" in col else 0
            return df
        except Exception as e:
            logger.warning(f"Error loading ingestion state, creating new: {e}")

    return pd.DataFrame(columns=[
        "ticker", "last_date", "status", "last_attempt",
        "last_success", "failure_count", "last_error"
    ])


def save_ingestion_state(state_df: pd.DataFrame):
    """
    Atomically saves ingestion state Parquet file.
    """
    ensure_directories()
    tmp_path = config.STATE_FILE.with_suffix(".parquet.tmp")
    state_df.to_parquet(tmp_path, index=False, engine="pyarrow")
    if tmp_path.exists():
        os.replace(tmp_path, config.STATE_FILE)


def sync_from_hf(repo_id: Optional[str] = None, token: Optional[str] = None) -> bool:
    """
    Pulls existing state and data from Hugging Face dataset if available.
    """
    repo = repo_id or config.HF_YFINANCE_DATASET
    auth_token = token or config.HF_TOKEN or None
    ensure_directories()

    try:
        logger.info(f"Attempting to download ingestion state from HF repo '{repo}'...")
        state_remote = hf_hub_download(
            repo_id=repo,
            filename="data/state/ingestion_state.parquet",
            repo_type="dataset",
            token=auth_token,
        )
        if state_remote and os.path.exists(state_remote):
            shutil.copy(state_remote, config.STATE_FILE)
            logger.info("Successfully synced ingestion state from Hugging Face.")
            return True
    except Exception as e:
        logger.info(f"No existing remote state found or error syncing ({e}). Starting fresh.")
    return False


def upload_to_hf(
    repo_id: Optional[str] = None,
    token: Optional[str] = None,
    commit_message: Optional[str] = None,
) -> bool:
    """
    Uploads the local data directory and state to Hugging Face dataset repo.
    """
    repo = repo_id or config.HF_YFINANCE_DATASET
    auth_token = token or config.HF_TOKEN

    if not auth_token:
        logger.warning("No HF_TOKEN provided. Skipping Hugging Face upload.")
        return False

    api = HfApi(token=auth_token)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    msg = commit_message or f"Daily market data update - {now_str}"

    try:
        # Create dataset repo if it doesn't exist
        api.create_repo(repo_id=repo, repo_type="dataset", exist_ok=True)
        
        # Ensure a README exists
        readme_path = config.BASE_DIR / "README_DATASET.md"
        if not readme_path.exists():
            with open(readme_path, "w", encoding="utf-8") as f:
                f.write(f"""---
license: mit
task_categories:
- tabular
tags:
- finance
- stock-market
- ohlcv
- yahoo-finance
size_categories:
- 10M<n<100M
---

# US Stock Market Daily OHLCV Dataset (Yahoo Finance)

Daily historical OHLCV data for US equities (retrieved via `yfinance`), stored in individual Parquet files per ticker.

## Data Layout
- `data/daily/{{TICKER}}.parquet`: Historical daily bars with columns `[date, open, high, low, close, adj_close, volume]`.
- `data/state/ingestion_state.parquet`: Pipeline metadata and tracking per ticker.

## Last Updated
{now_str}
""")
        
        # Upload README to repo root
        try:
            api.upload_file(
                path_or_fileobj=str(readme_path),
                path_in_repo="README.md",
                repo_id=repo,
                repo_type="dataset",
            )
        except Exception as e:
            logger.warning(f"Could not upload dataset README: {e}")

        logger.info(f"Uploading data directory to Hugging Face dataset '{repo}'...")
        api.upload_folder(
            folder_path=str(config.DATA_DIR),
            path_in_repo="data",
            repo_id=repo,
            repo_type="dataset",
            commit_message=msg,
        )
        logger.info("Successfully uploaded dataset to Hugging Face!")
        return True
    except Exception as e:
        logger.error(f"Failed to upload to Hugging Face: {e}")
        return False
