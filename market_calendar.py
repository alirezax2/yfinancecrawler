import datetime
import logging
from typing import Optional
import exchange_calendars as xcals

logger = logging.getLogger(__name__)


def get_nyse_calendar():
    """Returns the NYSE exchange calendar instance."""
    return xcals.get_calendar("XNYS")


def was_market_open_on_date(check_date: datetime.date) -> bool:
    """
    Checks whether the US market (NYSE/NASDAQ) was open on a specific calendar date.
    
    Args:
        check_date: The date to check.
        
    Returns:
        bool: True if the market was open for regular trading, False otherwise.
    """
    cal = get_nyse_calendar()
    date_str = check_date.isoformat()
    try:
        return cal.is_session(date_str)
    except Exception as e:
        logger.error(f"Error checking trading session for {date_str}: {e}")
        # Fallback to weekday check if calendar query fails
        return check_date.weekday() < 5


def was_market_open_previous_day(reference_date: Optional[datetime.date] = None) -> bool:
    """
    Checks whether the US market was open on the day prior to reference_date (defaulting to today).
    
    Args:
        reference_date: Optional reference date (defaults to UTC today).
        
    Returns:
        bool: True if the previous day was an active market session.
    """
    if reference_date is None:
        reference_date = datetime.datetime.now(datetime.timezone.utc).date()
    
    previous_day = reference_date - datetime.timedelta(days=1)
    is_open = was_market_open_on_date(previous_day)
    logger.info(
        f"Checking previous day ({previous_day}) relative to {reference_date}: "
        f"Market open = {is_open}"
    )
    return is_open


def get_last_market_session(reference_date: Optional[datetime.date] = None) -> datetime.date:
    """
    Finds the most recent past market session on or before reference_date.
    """
    if reference_date is None:
        reference_date = datetime.datetime.now(datetime.timezone.utc).date()
    
    cal = get_nyse_calendar()
    current = reference_date
    for _ in range(15):  # Look back up to 15 days
        if cal.is_session(current.isoformat()):
            return current
        current -= datetime.timedelta(days=1)
    
    return reference_date - datetime.timedelta(days=1)
