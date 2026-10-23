"""The Team Split detector, with fakes instead of GitHub."""

import json
from datetime import datetime, timezone

import pytest

from pointsman.events.detector import GitHubIssueNotifier, alert_for, handle
from pointsman.events.source import RulebookChanged, TeamLabelCreated
from pointsman.live.collect import run_once

NEW_LABEL = TeamLabelCreated(name="team-fluttergpu", label_id="LA_gpu",
                             created_at=datetime(2026, 10, 22, 11, tzinfo=timezone.utc))
RULEBOOK_EDIT = RulebookChanged(commit="200fdfbdce72acfff65d38b692cede474ff505e1",
                                committed_at=datetime(2026, 10, 14, 22, 30, tzinfo=timezone.utc),
                                summary="Move Material PRs to framework triage")


class FakeNotifier:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def notify(self, alert):
        if self.fail:
            raise ConnectionError("GitHub is down")
        self.sent.append(alert)


class FakeSource:
    def __init__(self, events):
        self.events = events
        self.committed = False

    def poll(self):
        return self.events

    def commit(self):
        self.committed = True


def test_every_taxonomy_event_is_recorded_and_sent(tmp_path):
    notifier = FakeNotifier()
    counts = handle([NEW_LABEL, RULEBOOK_EDIT], tmp_path, notifier)

    assert counts["alerts"] == 2
    assert [a.key for a in notifier.sent] == ["LA_gpu", "200fdfb"]
    kinds = [json.loads(line)["kind"] for line in (tmp_path / "alerts.jsonl").read_text().splitlines()]
    assert kinds == ["team_label_created", "rulebook_changed"]


def test_alert_title_carries_its_key():
    # The notifier finds earlier Issues for the same event by this "(key)" in the title.
    assert "(LA_gpu)" in alert_for(NEW_LABEL).title
    assert "(200fdfb)" in alert_for(RULEBOOK_EDIT).title


def test_failed_notification_means_progress_is_not_committed(tmp_path):
    source = FakeSource([NEW_LABEL])
    with pytest.raises(ConnectionError):
        run_once(source, FakeNotifier(fail=True), tmp_path)
    assert not source.committed  # the next poll delivers the event again, so the alert is not lost


# --- GitHubIssueNotifier -----------------------------------------------------

class FakeGitHub:
    """Our own repo: holds some Issues and records the ones we create."""

    def __init__(self, titles):
        self.titles = list(titles)

    def query(self, query, variables):
        if "createIssue" in query:
            self.titles.append(variables["title"])
            return {"createIssue": {"issue": {"url": "https://github.com/me/pointsman/issues/1"}}}
        return {"repository": {"id": "R_1", "issues": {"nodes": [{"title": t} for t in self.titles]}}}


def test_notifier_opens_an_issue_once_even_if_the_event_repeats():
    github = FakeGitHub(["Some unrelated Issue"])
    notifier = GitHubIssueNotifier(github, "me/pointsman", mention="me")

    notifier.notify(alert_for(NEW_LABEL))
    notifier.notify(alert_for(NEW_LABEL))  # at-least-once delivery sent it again

    assert len(github.titles) == 2  # the unrelated Issue plus exactly one alert
