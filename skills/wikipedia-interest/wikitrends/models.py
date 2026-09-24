"""Value objects shared across the package."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

# Earliest day served by the pageviews API (verified by probing).
DATA_FLOOR = date(2015, 7, 1)

DailyCounts = dict[date, int]


@dataclass(frozen=True, slots=True)
class DateRange:
    """Inclusive range of calendar days."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError(f"start {self.start} is after end {self.end}")

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def dates(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range(self.days)]

    def clamp(self, floor: date, ceiling: date) -> DateRange:
        return DateRange(max(self.start, floor), min(self.end, ceiling))

    def __contains__(self, day: object) -> bool:
        return isinstance(day, date) and self.start <= day <= self.end


@dataclass(frozen=True, slots=True)
class TrafficFilter:
    """API slice; numerator and denominator must always share it."""

    access: str = "all-access"
    agent: str = "user"

    @property
    def key(self) -> str:
        return f"{self.access}/{self.agent}"


@dataclass(frozen=True, slots=True)
class Article:
    """A canonical article title in one language edition."""

    lang: str
    title: str

    @property
    def project(self) -> str:
        return f"{self.lang}.wikipedia"

    @property
    def api_title(self) -> str:
        return self.title.replace(" ", "_")

    def __str__(self) -> str:
        return f"{self.lang}:{self.title}"


@dataclass(frozen=True, slots=True)
class Edition:
    """An open Wikipedia language edition."""

    lang: str
    dbname: str
