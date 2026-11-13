"""
Unit tests for calling window maths and regulatory window enforcement (Rule R1).
"""
from datetime import datetime

from solution.app.core.clock import IST
from solution.app.features.dispatch.service import (
    in_window,
    is_window_open,
    next_window_open,
)


def test_in_window_basic():
    # Thursday 12 Nov 2026, 15:00 IST
    t_inside = datetime(2026, 11, 12, 15, 0, tzinfo=IST)
    assert in_window(t_inside, "10:00", "19:00", ["mon", "tue", "wed", "thu", "fri"])

    # Thursday 12 Nov 2026, 09:30 IST (too early)
    t_early = datetime(2026, 11, 12, 9, 30, tzinfo=IST)
    assert not in_window(t_early, "10:00", "19:00", ["mon", "tue", "wed", "thu", "fri"])

    # Thursday 12 Nov 2026, 19:01 IST (too late)
    t_late = datetime(2026, 11, 12, 19, 1, tzinfo=IST)
    assert not in_window(t_late, "10:00", "19:00", ["mon", "tue", "wed", "thu", "fri"])

    # Saturday 14 Nov 2026, 15:00 IST (disallowed day)
    t_sat = datetime(2026, 11, 14, 15, 0, tzinfo=IST)
    assert not in_window(t_sat, "10:00", "19:00", ["mon", "tue", "wed", "thu", "fri"])
    # Saturday allowed if listed
    assert in_window(t_sat, "10:00", "19:00", ["sat", "sun"])


def test_regulatory_window_enforcement():
    camp_window = {"start": "08:00", "end": "22:00", "days": ["thu"]}
    reg_window = {"start": "09:00", "end": "21:00"}

    # 08:30 IST: allowed by campaign, but forbidden by regulatory window
    t1 = datetime(2026, 11, 12, 8, 30, tzinfo=IST)
    assert not is_window_open(t1, camp_window, reg_window)

    # 10:00 IST: allowed by both
    t2 = datetime(2026, 11, 12, 10, 0, tzinfo=IST)
    assert is_window_open(t2, camp_window, reg_window)

    # 21:15 IST: forbidden by regulatory window
    t3 = datetime(2026, 11, 12, 21, 15, tzinfo=IST)
    assert not is_window_open(t3, camp_window, reg_window)


def test_next_window_open_inside():
    # Inside window returns same time
    t = datetime(2026, 11, 12, 15, 30, tzinfo=IST)
    camp_window = {"start": "10:00", "end": "19:00", "days": ["thu"]}
    res = next_window_open(t, camp_window)
    assert res == t


def test_next_window_open_before_start():
    # Same day, before opening
    t = datetime(2026, 11, 12, 7, 30, tzinfo=IST)
    camp_window = {"start": "10:00", "end": "19:00", "days": ["thu"]}
    res = next_window_open(t, camp_window)
    expected = datetime(2026, 11, 12, 10, 0, tzinfo=IST)
    assert res == expected


def test_next_window_open_weekend_jump():
    # Friday 13 Nov 2026, 19:30 IST (after Friday close)
    # Campaign only allows Mon-Fri 10:00-19:00
    t = datetime(2026, 11, 13, 19, 30, tzinfo=IST)
    camp_window = {"start": "10:00", "end": "19:00", "days": ["mon", "tue", "wed", "thu", "fri"]}
    res = next_window_open(t, camp_window)
    # Earliest next open is Monday 16 Nov 2026, 10:00 IST
    expected = datetime(2026, 11, 16, 10, 0, tzinfo=IST)
    assert res == expected

