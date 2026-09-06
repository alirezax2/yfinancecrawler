"""
Script to download daily OHLCV data for a specific ticker from Hugging Face.

Usage:
    python test/download_ticker_daily.py AAPL
    python test/download_ticker_daily.py MSFT --output-dir ./downloaded_data
    python test/download_ticker_daily.py NVDA --dataset AmirTrader/YahooFinance
"""

import os
import argparse
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from huggingface_hub import hf_hub_download, HfApi

# Load environment variables (.env) if present
load_dotenv()


def download_ticker_daily(
    ticker: str,
    dataset_name: str = "AmirTrader/YahooFinance",
    token: str = None,
    output_dir: str = None,
) -> pd.DataFrame:
    """
    Downloads the daily parquet file for a given ticker from Hugging Face.

    Args:
        ticker (str): Stock ticker symbol (e.g., 'AAPL', 'MSFT', 'BRK-A')
        dataset_name (str): Hugging Face dataset repo ID (e.g., 'AmirTrader/YahooFinance')
        token (str, optional): Hugging Face API token (defaults to HF_TOKEN from .env)
        output_dir (str, optional): If provided, copies/saves the parquet file to this folder

    Returns:
        pd.DataFrame: DataFrame containing daily OHLCV data
    """
    auth_token = token or os.getenv("HF_TOKEN") or None
    ticker_clean = str(ticker).strip().upper().replace(".", "-").replace("/", "-")
    hf_path = f"data/daily/{ticker_clean}.parquet"

    print(f"[*] Downloading '{hf_path}' from dataset '{dataset_name}'...")

    try:
        local_cached_file = hf_hub_download(
            repo_id=dataset_name,
            filename=hf_path,
            repo_type="dataset",
            token=auth_token,
        )
        print(f"[+] Downloaded to HF cache: {local_cached_file}")

        df = pd.read_parquet(local_cached_file)
        print(f"[+] Successfully loaded {len(df)} rows for {ticker_clean}.")

        if output_dir:
            out_path = Path(output_dir)
            out_path.mkdir(parents=True, exist_ok=True)
            destination = out_path / f"{ticker_clean}.parquet"
            df.to_parquet(destination, index=False)
            print(f"[+] Saved copy to: {destination}")

        return df

    except Exception as e:
        print(f"[-] Failed to download daily data for '{ticker_clean}': {e}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download daily OHLCV parquet for a ticker from Hugging Face."
    )
    parser.add_argument(
        "ticker",
        type=str,
        nargs="?",
        default="AAPL",
        help="Ticker symbol to download (e.g. AAPL, MSFT, TSLA). Default: AAPL",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default=os.getenv("HF_YFINANCE_DATASET", "AmirTrader/YahooFinance"),
        help="Hugging Face dataset repository ID.",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="Hugging Face access token (optional, defaults to HF_TOKEN from .env).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./test/output",
        help="Directory to save downloaded parquet file. Default: ./test/output",
    )
    parser.add_argument(
        "--head",
        type=int,
        default=5,
        help="Number of head/tail rows to display. Default: 5",
    )

    args = parser.parse_args()

    try:
        data = download_ticker_daily(
            ticker=args.ticker,
            dataset_name=args.dataset,
            token=args.token,
            output_dir=args.output_dir,
        )

        print("\n--- First 5 rows ---")
        print(data.head(args.head))
        print("\n--- Last 5 rows ---")
        print(data.tail(args.head))
        print("\n--- Columns & Info ---")
        print(data.info())

    except Exception as err:
        print(f"\nError: {err}")
