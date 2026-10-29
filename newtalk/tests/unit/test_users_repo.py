"""Per-user data model: users, profiles, call slots, tokens, segments, deletion, migration."""

import datetime
import sqlite3

import pytest

from newtalk.db.models import OWNER_USER_ID
from newtalk.db.repository import NewTalkRepository


@pytest.fixture
def repo():
    r = NewTalkRepository("sqlite:///:memory:")
    r.create_tables()
    return r


def _new_user(repo, name="Sagar", **profile):
    user = repo.create_user(auth_provider="invite")
    repo.upsert_profile(user.id, call_name=name, interests=["tech"], **profile)
    return user


def test_owner_user_exists_after_create_tables(repo):
    owner = repo.get_user(OWNER_USER_ID)
    assert owner is not None
    assert owner.auth_provider == "owner"


def test_profile_defaults(repo):
    user = _new_user(repo)
    profile = repo.get_profile(user.id)
    assert profile.language == "en"
    assert profile.timezone == "Asia/Kolkata"
    assert profile.paused == 0
    assert profile.consented_at is None
    assert profile.call_time is None


def test_profile_interests_roundtrip_and_update(repo):
    user = _new_user(repo)
    repo.upsert_profile(
        user.id,
        interests=["tech", "markets"],
        free_text="Indian startups",
        call_time="21:30",
        language="hinglish",
        normalized={"categories": ["tech"], "keywords": ["startups"]},
    )
    profile = repo.get_profile(user.id)
    assert profile.interests_json == '["tech", "markets"]'
    assert profile.call_time == "21:30"
    assert profile.language == "hinglish"
    assert profile.call_name == "Sagar"


def test_consent_and_pause(repo):
    user = _new_user(repo)
    repo.set_consent(user.id, True)
    assert repo.get_profile(user.id).consented_at is not None
    repo.set_consent(user.id, False)
    assert repo.get_profile(user.id).consented_at is None
    repo.set_paused(user.id, True)
    assert repo.get_profile(user.id).paused == 1


def test_invite_code_claim_then_login(repo):
    invite = repo.create_invite_code()
    kind, user_id = repo.claim_invite(invite.code)
    assert kind == "new" and user_id is not None
    assert repo.claim_invite(invite.code) == ("existing", user_id)
    assert repo.claim_invite("nope") == ("invalid", None)


def test_deleting_user_frees_their_invite_code(repo):
    invite = repo.create_invite_code()
    _, user_id = repo.claim_invite(invite.code)
    repo.delete_user(user_id)
    kind, new_id = repo.claim_invite(invite.code)
    assert kind == "new" and new_id != user_id


def test_scheduled_slot_is_idempotent(repo):
    user = _new_user(repo)
    today = datetime.date(2026, 10, 15)
    first = repo.claim_call_slot(user.id, today, "scheduled")
    second = repo.claim_call_slot(user.id, today, "scheduled")
    assert first is not None
    assert second is None
    assert repo.claim_call_slot(
        user.id, today + datetime.timedelta(days=1), "scheduled"
    )


def test_test_calls_limited_to_three_per_day(repo):
    user = _new_user(repo)
    today = datetime.date(2026, 10, 15)
    claimed = [repo.claim_test_slot(user.id, today) for _ in range(4)]
    assert [c is not None for c in claimed] == [True, True, True, False]


def test_call_attempt_update(repo):
    user = _new_user(repo)
    attempt = repo.claim_call_slot(user.id, datetime.date(2026, 10, 15), "scheduled")
    repo.update_call_attempt(attempt.id, status="missed")
    assert repo.list_call_attempts(user.id)[0].status == "missed"


def test_call_token_single_use(repo):
    user = _new_user(repo)
    now = datetime.datetime(2026, 10, 15, 21, 30)
    repo.create_call_token("jti-1", user.id, None, now + datetime.timedelta(minutes=10))
    assert repo.consume_call_token("jti-1", now=now) is not None
    assert repo.consume_call_token("jti-1", now=now) is None


def test_call_token_expired_and_unknown(repo):
    user = _new_user(repo)
    now = datetime.datetime(2026, 10, 15, 21, 30)
    repo.create_call_token("jti-2", user.id, None, now + datetime.timedelta(minutes=10))
    late = now + datetime.timedelta(minutes=11)
    assert repo.consume_call_token("jti-2", now=late) is None
    assert repo.consume_call_token("missing", now=now) is None


def test_segment_cache_by_version(repo):
    cluster = repo.create_cluster(representative_title="Story")
    repo.upsert_segment(cluster.id, "en", 0, "v0 text")
    repo.upsert_segment(cluster.id, "en", 1, "v1 text")
    assert repo.get_segment(cluster.id, "en", 0).text == "v0 text"
    assert repo.get_segment(cluster.id, "en", 1).text == "v1 text"
    assert repo.get_segment(cluster.id, "hinglish", 0) is None
    repo.upsert_segment(cluster.id, "en", 0, "edited")
    assert repo.get_segment(cluster.id, "en", 0).text == "edited"


def test_memory_is_per_user(repo):
    a, b = _new_user(repo, "A"), _new_user(repo, "B")
    repo.set_user_memory("AI", 4.0, user_id=a.id)
    repo.set_user_memory("AI", 1.0, user_id=b.id)
    assert repo.get_user_memory("AI", user_id=a.id).familiarity_level == 4.0
    assert repo.get_user_memory("AI", user_id=b.id).familiarity_level == 1.0
    assert repo.get_user_memory("AI") is None  # owner has none


def test_briefing_and_qa_scoped_to_user(repo):
    a, b = _new_user(repo, "A"), _new_user(repo, "B")
    brief_a = repo.create_briefing("script a", 60, user_id=a.id)
    repo.create_briefing("script b", 60, user_id=b.id)
    assert repo.get_latest_briefing(user_id=a.id).id == brief_a.id
    qa = repo.log_qa(brief_a.id, "q?", "a.")
    assert qa.user_id == a.id


def test_delete_user_erases_everything_and_keeps_others(repo):
    gone, kept = _new_user(repo, "Gone"), _new_user(repo, "Kept")
    for u in (gone, kept):
        briefing = repo.create_briefing("script", 60, user_id=u.id)
        repo.log_qa(briefing.id, "q", "a")
        repo.set_user_memory("AI", 2.0, user_id=u.id)
        repo.claim_call_slot(u.id, datetime.date(2026, 10, 15), "scheduled")
        repo.create_call_token(
            f"jti-{u.id}", u.id, briefing.id, datetime.datetime(2030, 1, 1)
        )
        repo.update_channel(u.id, telegram_chat_id="123")

    repo.delete_user(gone.id)

    assert repo.get_user(gone.id) is None
    assert repo.get_profile(gone.id) is None
    assert repo.get_channel(gone.id) is None
    assert repo.get_latest_briefing(user_id=gone.id) is None
    assert repo.get_user_memory("AI", user_id=gone.id) is None
    assert repo.list_call_attempts(gone.id) == []
    assert repo.consume_call_token(f"jti-{gone.id}") is None

    assert repo.get_user(kept.id) is not None
    assert repo.get_latest_briefing(user_id=kept.id) is not None
    assert repo.get_user_memory("AI", user_id=kept.id) is not None
    assert len(repo.list_call_attempts(kept.id)) == 1


def test_owner_cannot_be_deleted(repo):
    with pytest.raises(ValueError):
        repo.delete_user(OWNER_USER_ID)


def test_migration_moves_legacy_single_user_rows_to_owner(tmp_path):
    db_file = tmp_path / "legacy.db"
    con = sqlite3.connect(db_file)
    con.executescript(
        """
        CREATE TABLE briefings (
            id INTEGER PRIMARY KEY, date DATE, script_text TEXT NOT NULL,
            duration_estimate_sec INTEGER NOT NULL, delivered_at DATETIME,
            story_count INTEGER, is_quiet_day INTEGER DEFAULT 0);
        CREATE TABLE qa_log (
            id INTEGER PRIMARY KEY, briefing_id INTEGER, question TEXT NOT NULL,
            answer TEXT NOT NULL, asked_at DATETIME);
        CREATE TABLE user_memory (
            topic VARCHAR PRIMARY KEY, familiarity_level FLOAT NOT NULL,
            last_covered_at DATETIME, notes TEXT);
        INSERT INTO briefings (id, date, script_text, duration_estimate_sec)
            VALUES (7, '2026-10-14', 'old script', 300);
        INSERT INTO qa_log (id, briefing_id, question, answer)
            VALUES (1, 7, 'why?', 'because');
        INSERT INTO user_memory (topic, familiarity_level) VALUES ('Cloudflare', 3.5);
        """
    )
    con.commit()
    con.close()

    repo = NewTalkRepository(f"sqlite:///{db_file}")
    repo.create_tables()
    repo.create_tables()  # idempotent

    briefing = repo.get_briefing(7)
    assert briefing.user_id == OWNER_USER_ID
    assert repo.get_latest_briefing(user_id=OWNER_USER_ID).id == 7
    assert repo.get_user_memory("Cloudflare").familiarity_level == 3.5
    # composite key now allows the same topic for another user
    other = repo.create_user()
    repo.set_user_memory("Cloudflare", 0.5, user_id=other.id)
    assert repo.get_user_memory("Cloudflare").familiarity_level == 3.5
    assert repo.get_user_memory("Cloudflare", user_id=other.id).familiarity_level == 0.5
