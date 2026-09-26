import argparse
import logging
import sys
from datetime import datetime, timezone
import config
import storage
from ticker_loader import load_tickers_from_hf
from downloader import BatchDownloader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("yfinance_pipeline")


def parse_args():
    parser = argparse.ArgumentParser(description="Yahoo Finance Daily Market Data Ingestion Pipeline")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force execution even if the previous day was not an active market trading session",
    )
    parser.add_argument(
        "--tickers-limit",
        type=int,
        default=None,
        help="Optional limit on the number of tickers to process (useful for testing/dry-runs)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=config.BATCH_SIZE,
        help=f"Number of tickers per batch (default: {config.BATCH_SIZE})",
    )
    parser.add_argument(
        "--max-concurrent-batches",
        type=int,
        default=config.MAX_CONCURRENT_BATCHES,
        help=f"Max concurrent batch workers (default: {config.MAX_CONCURRENT_BATCHES})",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Skip uploading updated data to Hugging Face dataset",
    )
    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="Skip initial remote state sync from Hugging Face",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    logger.info("==================================================")
    logger.info(" Starting Yahoo Finance Daily Ingestion Pipeline ")
    logger.info("==================================================")

    # 1. Sync existing state from Hugging Face if enabled
    if not args.no_sync:
        storage.sync_from_hf()

    # 3. Load tickers from Hugging Face TradingView dataset
    try:
        tickers, ticker_map = load_tickers_from_hf()
    except Exception as e:
        logger.error(f"Failed to load tickers from Hugging Face: {e}")
        return 1

    if args.tickers_limit:
        tickers = tickers[: args.tickers_limit]
        logger.info(f"Limiting ticker list to {len(tickers)} tickers for this run.")

    # 4. Run ingestion
    downloader = BatchDownloader(
        batch_size=args.batch_size,
        max_concurrent_batches=args.max_concurrent_batches,
        history_years=config.HISTORY_PERIOD_YEARS,
    )
    
    start_time = datetime.now(timezone.utc)
    state_df = downloader.run_ingestion(tickers=tickers, tickers_limit=args.tickers_limit)
    duration = (datetime.now(timezone.utc) - start_time).total_seconds()

    success_count = (state_df["status"] == "success").sum() if not state_df.empty else 0
    failed_count = (state_df["status"] == "failed").sum() if not state_df.empty else 0
    empty_count = (state_df["status"] == "empty").sum() if not state_df.empty else 0

    logger.info("==================================================")
    logger.info(" Ingestion Summary")
    logger.info(f" Duration: {duration:.1f}s")
    logger.info(f" Total Tickers Evaluated: {len(tickers)}")
    logger.info(f" Success: {success_count} | Failed: {failed_count} | Empty: {empty_count}")
    logger.info("==================================================")

    # 5. Upload to Hugging Face
    if not args.no_upload:
        uploaded = storage.upload_to_hf()
        if not uploaded:
            logger.warning("Hugging Face upload was skipped or failed. Check logs/HF_TOKEN.")
    else:
        logger.info("Hugging Face upload skipped (--no-upload).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
