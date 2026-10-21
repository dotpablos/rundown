from unittest.mock import Mock

import pytest
from slack_sdk.errors import SlackApiError
from slack_sdk.web.slack_response import SlackResponse

from rundown.slack import SlackFailure, SlackSource


def error(code, headers=None):
    return SlackApiError(code, SlackResponse(client=None, http_verb="GET", api_url="https://slack.com/api/test", req_args={}, data={"ok":False,"error":code}, headers=headers or {}, status_code=429 if code == "ratelimited" else 200))


def test_pagination_empty_pages_and_channel_filters(config):
    client = Mock()
    client.conversations_list.side_effect = [
        {"channels":[],"response_metadata":{"next_cursor":"next"}},
        {"channels":[{"id":"C1","is_member":True,"name":"public"},{"id":"C2","is_member":False},{"id":"G1","is_private":True,"is_member":True},{"id":"C3","is_member":True,"is_archived":True}]},
    ]
    source = SlackSource(config, client)
    assert [c["id"] for c in source.channels()] == ["C1","G1"]
    assert client.conversations_list.call_args.kwargs["cursor"] == "next"


def test_all_conversation_settings(config):
    client = Mock()
    client.users_info.return_value = {"user":{"profile":{"display_name":"Ana"}}}
    client.conversations_list.return_value = {"channels":[{"id":"D1","is_im":True,"user":"U1"},{"id":"M1","is_mpim":True},{"id":"C2","is_member":False}]}
    config.slack.direct_messages = config.slack.group_messages = config.slack.unjoined_public = True
    rows = SlackSource(config,client).channels()
    assert len(rows) == 3
    assert rows[0]["name"] == "DM · Ana"


def test_rate_limit_honors_retry_after_and_bounds(config):
    config.slack.retries = 1
    client, sleep = Mock(), Mock()
    client.auth_test.side_effect = [error("ratelimited", {"Retry-After":"7"}), {"team_id":"T1","user_id":"U1"}]
    source = SlackSource(config,client,sleep)
    assert source.check()["team_id"] == "T1"
    sleep.assert_called_once_with(7)
    client.auth_test.side_effect = error("ratelimited", {"Retry-After":"900"})
    with pytest.raises(SlackFailure, match="retry in 900"):
        source.check()


def test_replies_normalization_bot_events_boundaries(config):
    client = Mock()
    client.users_info.return_value = {"user":{"profile":{"display_name":"Ana"}}}
    client.conversations_history.return_value = {"messages":[
        {"ts":"10.000001","user":"U1","text":"Hi <@U1> in <#C1|team> &amp; <https://example.com|docs>","reply_count":1},
        {"ts":"11","subtype":"channel_join","text":"joined"},
        {"ts":"12","subtype":"bot_message","bot_profile":{"name":"Release Bot"},"text":"Build passed"},
        {"ts":"20","text":"at next boundary","user":"U1"},
    ]}
    client.conversations_replies.side_effect = [
        {"messages":[{"ts":"5","text":"old root","user":"U1"},{"ts":"15","thread_ts":"5","text":"late reply","user":"U1"}]},
        {"messages":[{"ts":"10.000001","text":"duplicate root","user":"U1"},{"ts":"13","thread_ts":"10.000001","text":"reply","user":"U1"}]},
    ]
    source = SlackSource(config,client)
    # Normalize independently because Slack replies also includes the root.
    assert source.normalize("<@U1> <#C1|team> &amp; <https://example.com|docs>") == "@Ana #team & docs (https://example.com)"
    messages, activity = source.fetch("C1","10.000001","20",["5"])
    assert [m.ts for m in messages] == ["10.000001","12","13","15"]
    assert messages[1].author == "Release Bot"
    assert activity["5"] == "15"
    assert "12" in activity  # zero-reply roots tracked for future replies


def test_access_denied_fails_channel(config):
    client=Mock()
    client.conversations_history.side_effect=error("not_in_channel")
    with pytest.raises(SlackFailure,match="not_in_channel"):
        SlackSource(config,client).fetch("C1","1","10",[])

