import logging
from typing import List, Dict, Tuple, Optional
import pandas as pd
from huggingface_hub import hf_hub_download
import config

logger = logging.getLogger(__name__)


def sanitize_ticker(symbol: str) -> str:
    """
    Normalizes a TradingView stock symbol into Yahoo Finance compatible ticker format.
    E.g.: 'BRK.A' -> 'BRK-A', 'BF.B' -> 'BF-B', 'JPM/PD' -> 'JPM-PD'.
    """
    if not isinstance(symbol, str):
        symbol = str(symbol)
    symbol = symbol.strip().upper()
    return symbol.replace(".", "-").replace("/", "-")


def load_tickers_from_hf(
    repo_id: Optional[str] = None,
    filename: Optional[str] = None,
    hf_token: Optional[str] = None,
) -> Tuple[List[str], Dict[str, str]]:
    """
    Downloads america.csv from Hugging Face TradingView dataset and extracts sanitized tickers.
    
    Returns:
        Tuple containing:
            - List of unique sanitized Yahoo-compatible tickers.
            - Mapping dict of {yahoo_ticker: original_symbol}.
    """
    repo = repo_id or config.TD_DATASET
    file = filename or config.TD_FILENAME
    token = hf_token or config.HF_TOKEN or None

    logger.info(f"Downloading ticker list '{file}' from HF repo '{repo}'...")
    local_path = hf_hub_download(
        repo_id=repo,
        filename=file,
        repo_type="dataset",
        token=token,
    )
    
    df = pd.read_csv(local_path)
    if "Symbol" not in df.columns:
        raise ValueError(f"Expected 'Symbol' column in {file}, but found: {df.columns.tolist()}")

    raw_symbols = df["Symbol"].dropna().astype(str).str.strip().tolist()
    
    ticker_map: Dict[str, str] = {}
    for raw in raw_symbols:
        sanitized = sanitize_ticker(raw)
        if sanitized:
            ticker_map[sanitized] = raw

    unique_tickers = sorted(list(ticker_map.keys()))
    logger.info(f"Loaded {len(unique_tickers)} unique tickers from {repo}/{file}")
    return unique_tickers, ticker_map
