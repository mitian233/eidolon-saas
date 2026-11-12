"""The calendar's days (GLOSSARY.md「日历」): Japan's national holidays for a year, as the
calendar shows them. What she is told of the day in her prompts — her birthday and the
birthdays of the user's own characters — `test_her_now` and `test_engine_prompts` have."""

import pytest

from tests.conftest import ClientFactory
from tests.fakes import FakeLLM


async def test_holidays_of_a_year_are_japans_national_ones_by_date_kept_by_the_browser_a_day(
    make_client: ClientFactory,
):
    client = make_client(FakeLLM())

    res = await client.get("/api/calendar/holidays", params={"year": 2026})

    assert res.status_code == 200
    holidays = res.json()
    assert {"date": "2026-11-03", "name": "文化の日"} in holidays
    assert {"date": "2026-05-06", "name": "振替休日"} in holidays  # for 憲法記念日 on a Sunday
    assert {"date": "2026-09-22", "name": "国民の休日"} in holidays
    dates = [h["date"] for h in holidays]
    assert "2026-12-31" not in dates and "2026-01-02" not in dates  # the New Year's break
    assert dates == sorted(dates)
    assert all(d.startswith("2026-") for d in dates)
    assert res.headers["Cache-Control"] == "private, max-age=86400"


@pytest.mark.parametrize("year", ["twenty", "２０２６", "1900"])  # the library knows none in 1900
async def test_holidays_of_a_year_there_are_none_known_for_are_none(
    make_client: ClientFactory, year: str
):
    client = make_client(FakeLLM())

    res = await client.get("/api/calendar/holidays", params={"year": year})

    assert res.status_code == 200
    assert res.json() == []


async def test_holidays_are_for_those_signed_in(make_client: ClientFactory):
    client = make_client(FakeLLM(), user=None)

    res = await client.get("/api/calendar/holidays", params={"year": 2026})

    assert res.status_code == 401