"""The shapes of our data, checked by Pydantic.

RawIssue  = one Issue exactly as GitHub's GraphQL API sends it (flattened a little).
CleanIssue = one Issue after cleaning: the row the rest of the project works with.

If GitHub ever sends something unexpected (a missing field, a wrong type),
Pydantic raises an error naming the field, instead of letting bad data slip through.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class Actor(BaseModel):
    login: str
    type: str = Field(alias="__typename")  # "User" or "Bot"


class Label(BaseModel):
    id: str
    name: str


class LabelEvent(BaseModel):
    kind: str = Field(alias="__typename")  # "LabeledEvent" or "UnlabeledEvent"
    created_at: datetime = Field(alias="createdAt")
    actor: Actor | None  # None when the account has since been deleted
    label: Label


class CommentAuthor(BaseModel):
    login: str


class Comment(BaseModel):
    body: str
    created_at: datetime = Field(alias="createdAt")
    author: CommentAuthor | None


class RawIssue(BaseModel):
    number: int
    title: str
    body: str
    state: str  # "OPEN" or "CLOSED"
    state_reason: str | None = Field(alias="stateReason")
    created_at: datetime = Field(alias="createdAt")
    closed_at: datetime | None = Field(alias="closedAt")
    author: Actor | None
    labels: list[Label]
    label_events: list[LabelEvent]  # oldest first
    label_events_total: int  # above 100 means label_events was cut short
    comments: list[Comment]  # the last 5

    @classmethod
    def from_graphql(cls, raw: dict) -> "RawIssue":
        """GraphQL wraps every list as {"nodes": [...]}. Unwrap those, then validate."""
        flat = dict(raw)
        flat["labels"] = raw["labels"]["nodes"]
        flat["label_events"] = raw["timelineItems"]["nodes"]
        flat["label_events_total"] = raw["timelineItems"]["totalCount"]
        flat["comments"] = raw["comments"]["nodes"]
        return cls.model_validate(flat)


class CleanIssue(BaseModel):
    number: int
    title: str
    prose: str  # body text with code blocks and markup removed
    code: str  # all fenced code blocks, joined
    num_code_blocks: int
    has_stack_trace: bool
    created_at: datetime
    closed_at: datetime | None
    state: str
    state_reason: str | None
    author: str | None
    team: str  # e.g. "team-engine"
    team_label_id: str  # the permanent label ID (ADR 0001)
    in_scope: bool  # one of the eight Teams the model predicts?
    confirmed: bool  # does it also carry triaged-<team>?
    routed: bool | None  # first Team label applied by someone other than the author; None if unknown
    team_label_events: int  # how many times a Team label was added (more than 1 = it bounced)
    duplicate_of: int | None  # the Original's number, if this Issue was closed as a Duplicate
