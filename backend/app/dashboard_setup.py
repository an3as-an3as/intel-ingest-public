"""Compile guided answers into the same PIR catalogue used by the classifier."""
from pydantic import BaseModel, Field, field_validator

from .models import Pir, PirSet


class SetupQuestion(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    question: str = Field(min_length=1, max_length=4000)
    indicators: str = Field(default="", max_length=4000)
    exclusions: str = Field(default="", max_length=4000)
    priority: int = Field(default=2, ge=1, le=3)

    @field_validator("title", "question", "indicators", "exclusions", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class DashboardSetupIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=4000)
    geography: str = Field(default="", max_length=2000)
    actors: str = Field(default="", max_length=2000)
    exclusions: str = Field(default="", max_length=4000)
    profile_ids: list[int] = Field(min_length=1, max_length=100)
    questions: list[SetupQuestion] = Field(min_length=1, max_length=20)
    reclassify_days: int = Field(default=7, ge=0, le=90)

    @field_validator("name", "objective", "geography", "actors", "exclusions", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value


def compile_dashboard(body: DashboardSetupIn, prefix: str = "DRAFT") -> PirSet:
    context = [f"Analysis objective: {body.objective}"]
    if body.geography:
        context.append(f"Geographic scope (event location, not publisher): {body.geography}")
    if body.actors:
        context.append(f"Actors / entities of interest: {body.actors}")
    if body.exclusions:
        context.append(f"Out of scope: {body.exclusions}")
    dashboard = PirSet(name=body.name, description="\n".join(context))
    for i, question in enumerate(body.questions, 1):
        indicators = [f"Relevant evidence / indicators: {question.indicators or 'Reporting that helps answer the question.'}"]
        if question.exclusions:
            indicators.append(f"Do not match: {question.exclusions}")
        indicators.append("Respect the dashboard's geographic, actor and exclusion scope. "
                          "Score relevance from the reporting, not keyword presence alone. "
                          "Explain which evidence answers this question; do not infer unsupported facts.")
        dashboard.pirs.append(Pir(code=f"{prefix}-{i}", title=question.title, question=question.question,
                                 indicators="\n".join(indicators), priority=question.priority, active=True))
    return dashboard
