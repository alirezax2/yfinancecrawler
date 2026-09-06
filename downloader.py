import math
import random
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple
import pandas as pd
import yfinance as yf

import config
import storage

logger = logging.getLogger(__name__)


def extract_ticker_data(batch_df: pd.DataFrame, ticker: str) -> Optional[pd.DataFrame]:
    """
    Extracts OHLCV DataFrame for a single ticker from a multi-ticker yf.download result.
    Handles MultiIndex formats (both group_by='column' and group_by='ticker').
    """
    if batch_df is None or batch_df.empty:
        return None

    try:
        # Case 1: Single index (only one ticker downloaded or flattened)
        if not isinstance(batch_df.columns, pd.MultiIndex):
            return batch_df.copy()

        # Case 2: MultiIndex columns
        col_tuples = batch_df.columns
        level_0 = col_tuples.get_level_values(0)
        level_1 = col_tuples.get_level_values(1)

        # Check if ticker is in level 1 (group_by='column': e.g. ('Close', 'AAPL'))
        if ticker in level_1:
            df = batch_df.xs(ticker, axis=1, level=1, drop_level=True).copy()
            return df

        # Check if ticker is in level 0 (group_by='ticker': e.g. ('AAPL', 'Close'))
        if ticker in level_0:
            df = batch_df.xs(ticker, axis=1, level=0, drop_level=True).copy()
            return df

        # Fallback: exact match across tuples
        matching_cols = [c for c in col_tuples if ticker in c]
        if matching_cols:
            sub_df = batch_df[matching_cols].copy()
            sub_df.columns = [c[0] if c[1] == ticker else c[1] for c in matching_cols]
            return sub_df

    except Exception as e:
        logger.error(f"Error extracting ticker {ticker} from batch DataFrame: {e}")

    return None


class RateLimitError(Exception):
    """Raised when Yahoo Finance rate limit is encountered."""
    pass


class BatchDownloader:
    """
    Downloader managing batched Yahoo Finance ingestion with rate limiting,
    exponential backoff, controlled concurrency, and atomic persistence.
    """

    def __init__(
        self,
        batch_size: int = config.BATCH_SIZE,
        max_concurrent_batches: int = config.MAX_CONCURRENT_BATCHES,
        history_years: int = config.HISTORY_PERIOD_YEARS,
    ):
        self.batch_size = batch_size
        self.max_concurrent_batches = max_concurrent_batches
        self.history_years = history_years
        self.backoff_schedule = config.BACKOFF_SECONDS
        self.max_retries = config.RETRY_ATTEMPTS

    def _execute_download_with_retry(
        self,
        tickers: List[str],
        start_date: Optional[str] = None,
        period: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Executes yf.download with exponential backoff and rate limit handling.
        """
        for attempt in range(self.max_retries):
            try:
                kwargs = {
                    "tickers": tickers,
                    "interval": config.INTERVAL,
                    "auto_adjust": config.AUTO_ADJUST,
                    "progress": False,
                    "threads": config.YFINANCE_THREADS,
                    "group_by": "column",
                }
                if start_date:
                    kwargs["start"] = start_date
                elif period:
                    kwargs["period"] = period
                else:
                    kwargs["period"] = f"{self.history_years}y"

                df = yf.download(**kwargs)
                return df

            except Exception as e:
                err_str = str(e).lower()
                is_rate_limit = any(
                    x in err_str
                    for x in ["429", "too many requests", "ratelimit", "rate limit", "yfratelimiterror"]
                )

                if attempt < self.max_retries - 1:
                    base_delay = self.backoff_schedule[min(attempt, len(self.backoff_schedule) - 1)]
                    jitter = random.uniform(0.5, 2.5)
                    delay = base_delay + jitter

                    if is_rate_limit:
                        delay += 30.0  # Extra backoff on rate limits
                        logger.warning(
                            f"[Rate Limit] Detected on attempt {attempt + 1}/{self.max_retries}. "
                            f"Sleeping {delay:.1f}s before retry..."
                        )
                    else:
                        logger.warning(
                            f"[Network/Fetch Error] {e} on attempt {attempt + 1}/{self.max_retries}. "
                            f"Sleeping {delay:.1f}s before retry..."
                        )

                    time.sleep(delay)
                else:
                    logger.error(f"Failed batch download after {self.max_retries} attempts: {e}")
                    raise

        return pd.DataFrame()

    def process_batch(
        self,
        batch_tickers: List[str],
        start_date: Optional[str] = None,
        period: Optional[str] = None,
    ) -> Dict[str, Dict]:
        """
        Processes a single batch of tickers:
        1. Downloads OHLCV data.
        2. Validates and saves each ticker to its Parquet file.
        3. Returns status metadata dictionary for state tracking.
        """
        results: Dict[str, Dict] = {}
        now_iso = datetime.now(timezone.utc).isoformat()

        if not batch_tickers:
            return results

        try:
            batch_df = self._execute_download_with_retry(
                tickers=batch_tickers,
                start_date=start_date,
                period=period,
            )
        except Exception as e:
            for t in batch_tickers:
                results[t] = {
                    "ticker": t,
                    "status": "failed",
                    "last_attempt": now_iso,
                    "last_error": str(e),
                }
            return results

        for ticker in batch_tickers:
            try:
                t_df = extract_ticker_data(batch_df, ticker)
                if t_df is None or t_df.empty:
                    # Mark empty/no data
                    results[ticker] = {
                        "ticker": ticker,
                        "status": "empty",
                        "last_attempt": now_iso,
                        "last_error": "No data returned by Yahoo Finance",
                    }
                    continue

                # Update Parquet file
                latest_date = storage.update_ticker_parquet(ticker, t_df)
                if latest_date:
                    results[ticker] = {
                        "ticker": ticker,
                        "last_date": latest_date,
                        "status": "success",
                        "last_attempt": now_iso,
                        "last_success": now_iso,
                        "last_error": "",
                    }
                else:
                    results[ticker] = {
                        "ticker": ticker,
                        "status": "empty",
                        "last_attempt": now_iso,
                        "last_error": "Parsed data was empty after validation",
                    }

            except Exception as e:
                logger.error(f"Error persisting ticker {ticker}: {e}")
                results[ticker] = {
                    "ticker": ticker,
                    "status": "failed",
                    "last_attempt": now_iso,
                    "last_error": str(e),
                }

        return results

    def run_ingestion(
        self,
        tickers: List[str],
        tickers_limit: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Executes full or incremental ingestion across the entire ticker universe.
        """
        if tickers_limit and tickers_limit > 0:
            tickers = tickers[:tickers_limit]

        state_df = storage.load_ingestion_state()
        state_map: Dict[str, Dict] = {}
        if not state_df.empty:
            for _, row in state_df.iterrows():
                state_map[row["ticker"]] = row.to_dict()

        today_utc = datetime.now(timezone.utc).date()
        cutoff_7y = (today_utc - timedelta(days=self.history_years * 365 + 10)).strftime("%Y-%m-%d")

        # Segregate into:
        # 1. Initial loads (no previous last_date or last_date < cutoff) -> period="7y"
        # 2. Incremental loads (has last_date) -> grouped by start_date
        initial_tickers: List[str] = []
        incremental_groups: Dict[str, List[str]] = {}

        for t in tickers:
            t_state = state_map.get(t, {})
            last_date_str = str(t_state.get("last_date", "")).strip()

            # Check if parquet actually exists locally
            parquet_path = storage.get_ticker_parquet_path(t)
            if not parquet_path.exists() or not last_date_str or last_date_str == "nan":
                initial_tickers.append(t)
            else:
                try:
                    last_dt = datetime.strptime(last_date_str, "%Y-%m-%d").date()
                    # If already up to date with today or yesterday, might need only latest day
                    start_fetch = (last_dt + timedelta(days=1)).strftime("%Y-%m-%d")
                    if last_dt >= today_utc:
                        # Already completely up to date
                        continue
                    incremental_groups.setdefault(start_fetch, []).append(t)
                except Exception:
                    initial_tickers.append(t)

        logger.info(
            f"Ingestion summary: Total tickers={len(tickers)} | "
            f"Initial loads={len(initial_tickers)} | "
            f"Incremental loads={sum(len(v) for v in incremental_groups.values())}"
        )

        # Build batches
        batch_tasks: List[Tuple[List[str], Optional[str], Optional[str]]] = []

        # Batches for initial loads
        for i in range(0, len(initial_tickers), self.batch_size):
            chunk = initial_tickers[i : i + self.batch_size]
            batch_tasks.append((chunk, None, f"{self.history_years}y"))

        # Batches for incremental loads
        for start_date, group in incremental_groups.items():
            for i in range(0, len(group), self.batch_size):
                chunk = group[i : i + self.batch_size]
                batch_tasks.append((chunk, start_date, None))

        logger.info(f"Total batches to execute: {len(batch_tasks)}")

        all_results: Dict[str, Dict] = {}

        # Concurrency control per SKILL.md
        with ThreadPoolExecutor(max_workers=self.max_concurrent_batches) as executor:
            future_to_batch = {
                executor.submit(self.process_batch, b_tickers, s_date, period): (b_tickers, s_date)
                for b_tickers, s_date, period in batch_tasks
            }

            for future in as_completed(future_to_batch):
                b_tickers, s_date = future_to_batch[future]
                try:
                    res = future.result()
                    all_results.update(res)
                    success_count = sum(1 for v in res.values() if v.get("status") == "success")
                    logger.info(f"Batch ({len(b_tickers)} tickers) finished: {success_count} succeeded.")
                except Exception as e:
                    logger.error(f"Batch execution error: {e}")
                    for t in b_tickers:
                        all_results[t] = {
                            "ticker": t,
                            "status": "failed",
                            "last_attempt": datetime.now(timezone.utc).isoformat(),
                            "last_error": str(e),
                        }

        # Update and save state table
        for t, res in all_results.items():
            existing = state_map.get(t, {})
            merged = {**existing, **res}
            if res.get("status") == "failed":
                merged["failure_count"] = int(existing.get("failure_count", 0) or 0) + 1
            elif res.get("status") == "success":
                merged["failure_count"] = 0
            state_map[t] = merged

        updated_state_df = pd.DataFrame(list(state_map.values()))
        storage.save_ingestion_state(updated_state_df)
        logger.info("Ingestion state successfully updated.")

        return updated_state_df
