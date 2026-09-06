import datetime
import os
import shutil
import tempfile
from pathlib import Path
import pandas as pd
import pytest

import config
import storage
import market_calendar
from ticker_loader import sanitize_ticker
from downloader import extract_ticker_data, BatchDownloader


def test_sanitize_ticker():
    assert sanitize_ticker("aapl") == "AAPL"
    assert sanitize_ticker("BRK.A") == "BRK-A"
    assert sanitize_ticker("BRK.B") == "BRK-B"
    assert sanitize_ticker("BF.B") == "BF-B"
    assert sanitize_ticker("JPM/PD") == "JPM-PD"
    assert sanitize_ticker("  msft  ") == "MSFT"


def test_market_calendar():
    # Test known holiday (July 4th 2024)
    july_4th = datetime.date(2024, 7, 4)
    assert not market_calendar.was_market_open_on_date(july_4th)

    # Test regular Friday session (July 5th 2024)
    july_5th = datetime.date(2024, 7, 5)
    assert market_calendar.was_market_open_on_date(july_5th)

    # Test weekend (July 6th 2024 - Saturday)
    july_6th = datetime.date(2024, 7, 6)
    assert not market_calendar.was_market_open_on_date(july_6th)


def test_normalize_dataframe():
    raw_data = {
        "Date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-03"]),
        "Open": [100.0, 102.0, 103.0],
        "High": [105.0, 106.0, 107.0],
        "Low": [99.0, 101.0, 102.0],
        "Close": [104.0, 105.0, 106.0],
        "Adj Close": [104.0, 105.0, 106.0],
        "Volume": [1000, 2000, 3000],
    }
    df = pd.DataFrame(raw_data)
    norm = storage.normalize_dataframe(df)

    assert list(norm.columns) == config.REQUIRED_COLUMNS
    assert len(norm) == 2  # Deduplicated duplicate date 2024-01-03
    assert norm["date"].tolist() == ["2024-01-02", "2024-01-03"]
    assert norm["close"].iloc[-1] == 106.0  # Kept last


def test_atomic_parquet_update(tmp_path, monkeypatch):
    # Set temp directory for daily parquets
    test_daily = tmp_path / "daily"
    test_state = tmp_path / "state"
    monkeypatch.setattr(config, "DAILY_DATA_DIR", test_daily)
    monkeypatch.setattr(config, "STATE_DIR", test_state)
    monkeypatch.setattr(config, "STATE_FILE", test_state / "ingestion_state.parquet")

    # Initial batch
    df1 = pd.DataFrame({
        "Date": ["2024-01-02", "2024-01-03"],
        "Open": [100.0, 102.0],
        "High": [105.0, 106.0],
        "Low": [99.0, 101.0],
        "Close": [104.0, 105.0],
        "Adj Close": [104.0, 105.0],
        "Volume": [1000, 2000],
    })
    latest = storage.update_ticker_parquet("TEST", df1)
    assert latest == "2024-01-03"

    parquet_file = storage.get_ticker_parquet_path("TEST")
    assert parquet_file.exists()
    saved_df = pd.read_parquet(parquet_file)
    assert len(saved_df) == 2

    # Incremental batch
    df2 = pd.DataFrame({
        "Date": ["2024-01-03", "2024-01-04"],
        "Open": [102.0, 105.0],
        "High": [106.0, 108.0],
        "Low": [101.0, 104.0],
        "Close": [105.5, 107.0],
        "Adj Close": [105.5, 107.0],
        "Volume": [2500, 3500],
    })
    latest2 = storage.update_ticker_parquet("TEST", df2)
    assert latest2 == "2024-01-04"

    saved_df2 = pd.read_parquet(parquet_file)
    assert len(saved_df2) == 3
    assert saved_df2["date"].tolist() == ["2024-01-02", "2024-01-03", "2024-01-04"]
    assert saved_df2.loc[saved_df2["date"] == "2024-01-03", "close"].values[0] == 105.5


def test_extract_ticker_data():
    tuples = [
        ("Open", "AAPL"), ("Open", "MSFT"),
        ("Close", "AAPL"), ("Close", "MSFT"),
        ("Volume", "AAPL"), ("Volume", "MSFT"),
    ]
    index = pd.to_datetime(["2024-01-02", "2024-01-03"])
    multi_df = pd.DataFrame(
        [
            [150.0, 350.0, 155.0, 355.0, 10000, 20000],
            [152.0, 352.0, 157.0, 358.0, 12000, 22000],
        ],
        index=index,
        columns=pd.MultiIndex.from_tuples(tuples, names=["Metric", "Ticker"])
    )

    aapl_df = extract_ticker_data(multi_df, "AAPL")
    assert aapl_df is not None
    assert "Close" in aapl_df.columns
    assert aapl_df["Close"].tolist() == [155.0, 157.0]

    msft_df = extract_ticker_data(multi_df, "MSFT")
    assert msft_df is not None
    assert msft_df["Close"].tolist() == [355.0, 358.0]
