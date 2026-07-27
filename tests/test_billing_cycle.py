"""
The statement-cycle boundaries in app/services/billing_cycle.py are
transcribed from the household's real spreadsheet, so these assert the
exact dates that spreadsheet uses -- a change that silently shifts a
past cycle would restate a month that's already been settled.
"""
import datetime

from app.services.billing_cycle import get_cycle


def test_pre_transition_cycles_are_calendar_months():
    assert get_cycle(2026, 1) == (datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
    assert get_cycle(2026, 2) == (datetime.date(2026, 2, 1), datetime.date(2026, 2, 28))
    assert get_cycle(2026, 6) == (datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))


def test_july_2026_is_the_short_transition_cycle():
    # Closes out the calendar-month scheme early so the statement-cycle
    # scheme can start on 7/14.
    assert get_cycle(2026, 7) == (datetime.date(2026, 7, 1), datetime.date(2026, 7, 13))


def test_statement_cycles_match_the_spreadsheet():
    assert get_cycle(2026, 8) == (datetime.date(2026, 7, 14), datetime.date(2026, 8, 13))
    assert get_cycle(2026, 9) == (datetime.date(2026, 8, 14), datetime.date(2026, 9, 12))
    assert get_cycle(2026, 10) == (datetime.date(2026, 9, 13), datetime.date(2026, 10, 13))
    assert get_cycle(2026, 11) == (datetime.date(2026, 10, 14), datetime.date(2026, 11, 12))
    assert get_cycle(2026, 12) == (datetime.date(2026, 11, 13), datetime.date(2026, 12, 13))


def test_cycle_length_equals_days_in_the_labeled_month():
    for month, expected_length in [(8, 31), (9, 30), (10, 31), (11, 30), (12, 31)]:
        start, end = get_cycle(2026, month)
        assert (end - start).days + 1 == expected_length


def test_cycles_are_contiguous_with_no_gaps_or_overlaps():
    """Every day belongs to exactly one cycle -- a gap would drop
    transactions out of the split entirely, an overlap would double-count
    them."""
    year, month = 2026, 1
    _, previous_end = get_cycle(year, month)
    for _ in range(48):  # four years past the transition
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        start, end = get_cycle(year, month)
        assert start == previous_end + datetime.timedelta(days=1), f"gap/overlap before {year}-{month}"
        previous_end = end


def test_cycles_generate_indefinitely_past_the_hardcoded_range():
    start, end = get_cycle(2030, 3)
    assert start < end
    assert (end - start).days + 1 == 31  # March
