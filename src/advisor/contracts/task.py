from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class ResearchRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    ticker: str | None = Field(default=None, pattern=r"^\d{6}$")
    as_of: date | None = None
    route: Literal["auto", "quick", "standard", "deep"] = "auto"
