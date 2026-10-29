from pointsman.pipeline.clean import (
    clean_issue,
    find_duplicate_of,
    find_routed,
    has_stack_trace,
    split_code,
    strip_markup,
)
from pointsman.pipeline.schemas import RawIssue


def raw(make_issue, **kwargs) -> RawIssue:
    return RawIssue.from_graphql(make_issue(**kwargs))


# --- Text cleaning -----------------------------------------------------------

def test_strip_markup_removes_formatting_but_keeps_content():
    body = "<!-- template hint -->Crash on start\n<details><summary>Logs</summary>trace</details>\n_No response_\n![shot](x.png)"
    text = strip_markup(body)
    assert "template hint" not in text
    assert "<details>" not in text and "<summary>" not in text
    assert "_No response_" not in text
    assert "[image]" in text
    assert "Crash on start" in text and "trace" in text


def test_split_code_separates_fenced_blocks_from_prose():
    prose, blocks = split_code("Steps:\n```dart\nvoid main() {}\n```\nThen it crashes.")
    assert blocks == ["```dart\nvoid main() {}\n```"]
    assert "void main" not in prose
    assert "Steps:" in prose and "Then it crashes." in prose


def test_strip_markup_removes_the_bug_form_checklist():
    body = (
        "### Is there an existing issue for this?\n\n"
        "- [X] I have searched the [existing issues](https://github.com/flutter/flutter/issues)\n"
        "- [x] I have read the [guide to filing a bug](https://flutter.dev/docs/resources/bug-reports)\n\n"
        "### Steps to reproduce\n\n"
        "- [x] The issue still persists on the master channel"
    )
    text = strip_markup(body)
    assert "existing issue" not in text and "I have" not in text
    assert "### Steps to reproduce" in text
    assert "still persists on the master channel" in text  # other checkboxes are real information


def test_split_code_finds_fences_indented_in_a_list():
    prose, blocks = split_code("1. Run:\n   ```sh\n   flutter run\n   ```\n2. Tap the button.")
    assert len(blocks) == 1 and "flutter run" in blocks[0]
    assert "flutter run" not in prose
    assert "Tap the button." in prose


def test_windows_line_endings_are_handled(make_issue):
    # GitHub's web form ends lines with \r\n. The code block must still be found.
    body = "Steps:\r\n```\r\nvoid main() {}\r\n```\r\nThen it crashes:\r\n    at com.example.Main.run(Main.java:10)\r\n"
    row, _ = clean_issue(raw(make_issue, body=body))
    assert row.num_code_blocks == 1
    assert "void main" in row.code and "void main" not in row.prose
    assert "\r" not in row.prose
    assert row.has_stack_trace


def test_has_stack_trace_spots_dart_frames():
    trace = "#0      State.setState (package:flutter/src/widgets/framework.dart:1219:9)"
    assert has_stack_trace(trace)
    assert not has_stack_trace("The button is the wrong colour.")


# --- Duplicates --------------------------------------------------------------

def test_duplicate_found_in_common_phrasings(make_issue):
    for comment, expected in [
        ("Closing this as a duplicate of #192976", 192976),
        ("Duping to https://github.com/flutter/flutter/issues/128713", 128713),
        ("dupe of #123", 123),
    ]:
        issue = raw(make_issue, state="CLOSED", state_reason="DUPLICATE", comments=[comment])
        assert find_duplicate_of(issue) == expected, comment


def test_duplicate_in_another_repo_is_not_mistaken_for_a_flutter_issue(make_issue):
    issue = raw(
        make_issue,
        state_reason="DUPLICATE",
        comments=["Duplicate of https://github.com/flutter/packages/issues/5 and #77"],
    )
    assert find_duplicate_of(issue) is None


def test_mentioning_an_issue_is_not_a_duplicate(make_issue):
    issue = raw(make_issue, state_reason="COMPLETED", comments=["This looks related to #192365"])
    assert find_duplicate_of(issue) is None


# --- Routed vs Self-labeled --------------------------------------------------

def test_routed_when_someone_else_applied_the_first_team_label(make_issue):
    issue = raw(make_issue, author="alice", events=[("LabeledEvent", "team-engine", "triager")])
    assert find_routed(issue) is True


def test_self_labeled_when_the_author_applied_it(make_issue):
    issue = raw(make_issue, author="alice", events=[("LabeledEvent", "team-engine", "alice")])
    assert find_routed(issue) is False


def test_only_the_first_team_label_counts(make_issue):
    issue = raw(
        make_issue,
        author="alice",
        events=[
            ("LabeledEvent", "P2", "alice"),  # not a Team label: ignored
            ("LabeledEvent", "team-framework", "triager"),  # first Team label: decides
            ("LabeledEvent", "team-engine", "alice"),  # later move: ignored
        ],
    )
    assert find_routed(issue) is True


def test_routed_unknown_without_evidence(make_issue):
    assert find_routed(raw(make_issue, events=[])) is None
    assert find_routed(raw(make_issue, events=[("LabeledEvent", "team-engine", None)])) is None


# --- Keep or drop ------------------------------------------------------------

def test_bot_issues_are_dropped(make_issue):
    row, reason = clean_issue(raw(make_issue, author="dependabot", author_type="Bot"))
    assert row is None and reason == "bot author"


def test_issues_need_exactly_one_known_team(make_issue):
    assert clean_issue(raw(make_issue, labels=["P2"]))[1] == "no known Team label now"
    assert clean_issue(raw(make_issue, labels=["team-infra"]))[1] == "no known Team label now"
    assert clean_issue(raw(make_issue, labels=["team-web", "team-ios"]))[1] == "more than one Team label"


def test_kept_issue_carries_team_facts(make_issue):
    row, reason = clean_issue(raw(make_issue, labels=["team-web", "triaged-web"]))
    assert reason is None
    assert row.team == "team-web" and row.team_label_id == "LA_team-web"
    assert row.in_scope is True and row.confirmed is True

    row, _ = clean_issue(raw(make_issue, labels=["team-windows"]))
    assert row.in_scope is False and row.confirmed is False


# --- Second fetch of label histories ------------------------------------------

def test_more_complete_label_history_wins(make_issue):
    bulk = make_issue(author="alice", events=[("LabeledEvent", "P2", "alice")])  # truncated: Team event missing
    second = make_issue(author="alice", events=[("LabeledEvent", "P2", "alice"), ("LabeledEvent", "team-web", "triager")])
    issue = RawIssue.from_graphql(bulk, second["timelineItems"])
    assert find_routed(issue) is True


def test_shorter_second_history_is_ignored(make_issue):
    bulk = make_issue(author="alice", events=[("LabeledEvent", "team-web", "alice"), ("LabeledEvent", "P2", "bob")])
    second = make_issue(author="alice", events=[("LabeledEvent", "P2", "bob")])
    issue = RawIssue.from_graphql(bulk, second["timelineItems"])
    assert find_routed(issue) is False
