"""Segments (cached, checked) and per-user assembly (no per-user LLM cost)."""

import datetime
import re

import pytest

from newtalk.composer.segments import check_segment, ensure_segments
from newtalk.composer.user_briefing import assemble_user_briefing
from newtalk.config.jiya_i18n import PHRASES, REQUIRED_KEYS
from newtalk.db.repository import NewTalkRepository
from newtalk.tests.unit.helpers import FakeLLM, seed_cluster


@pytest.fixture
def repo():
    r = NewTalkRepository("sqlite:///:memory:")
    r.create_tables()
    return r


def _user(repo, name="Sagar", interests=("tech",), language="en", free_text=None):
    user = repo.create_user(auth_provider="invite")
    repo.upsert_profile(
        user.id,
        call_name=name,
        interests=list(interests),
        free_text=free_text,
        language=language,
    )
    return user


# ---- segments -------------------------------------------------------------------------------


def test_second_run_makes_zero_llm_calls(repo):
    clusters = [seed_cluster(repo, f"Chip startup {i} raises funding") for i in range(3)]
    llm = FakeLLM()
    ensure_segments(repo, repo.list_clusters(), ["en"], llm=llm)
    first = llm.calls
    assert first >= 1
    ensure_segments(repo, repo.list_clusters(), ["en"], llm=llm)
    assert llm.calls == first
    assert len(clusters) == 3


def test_new_development_version_regenerates_only_that_cluster(repo):
    a = seed_cluster(repo, "Sensex rallies on FII buying", source="Mint Markets")
    seed_cluster(repo, "ISRO launches new satellite", source="The Hindu Science")
    llm = FakeLLM()
    ensure_segments(repo, repo.list_clusters(), ["en"], llm=llm)
    base = llm.calls
    repo.update_cluster_event_fields(a.id, development_count=1, last_change_kind="major")
    ensure_segments(repo, repo.list_clusters(), ["en"], llm=llm)
    assert llm.calls == base + 1


def test_languages_are_generated_separately(repo):
    seed_cluster(repo, "India and EU close trade talks")
    llm = FakeLLM()
    out = ensure_segments(repo, repo.list_clusters(), ["en", "hinglish"], llm=llm)
    assert {lang for (_cid, lang) in out} == {"en", "hinglish"}
    assert llm.calls == 2


def test_check_flags_unattributed_motive_but_allows_attributed():
    bad = (
        "The farmers protest in Punjab is a foreign-funded conspiracy to destabilise the "
        "country and everyone involved is paid by outside groups to create chaos across the "
        "state during the harvest season this year."
    )
    ok = (
        "Police allege the protest was foreign-funded, a claim organisers deny and which has "
        "not been verified by any court or independent agency, so treat it as unconfirmed "
        "while the investigation by state officials continues this week."
    )
    assert any("attribution" in i or "attribute" in i for i in check_segment(bad))
    assert check_segment(ok) == []


def test_foreign_funded_claim_is_regenerated_with_attribution(repo):
    c = seed_cluster(repo, "Farmers protest in Punjab turns tense")
    bad = (
        "The farmers protest in Punjab is a foreign-funded conspiracy to destabilise the "
        "country and everyone involved is paid by outside groups to create chaos across the "
        "state during the harvest season this year."
    )
    good = (
        "Police allege the Punjab protest was foreign-funded, a claim organisers deny and "
        "which has not been verified, so it remains unconfirmed while officials investigate "
        "and farmer unions say their demand is only about crop prices and procurement."
    )
    llm = FakeLLM(override={(c.id, False): bad, (c.id, True): good})
    out = ensure_segments(repo, repo.list_clusters(), ["en"], llm=llm)
    assert out[(c.id, "en")] == good
    assert llm.seen_feedback, "retry must carry the validator's feedback"


def test_persistent_violation_falls_back_to_safe_line(repo):
    c = seed_cluster(repo, "Protest turns violent in city")
    bad = (
        "This is a foreign-funded conspiracy by traitors who are paid by outside forces to "
        "damage the country and the government must crush them without waiting for any "
        "investigation or court to look at the facts of the case at all."
    )
    llm = FakeLLM(override={(c.id, False): bad, (c.id, True): bad})
    out = ensure_segments(repo, repo.list_clusters(), ["en"], llm=llm)
    assert "conspiracy" not in out[(c.id, "en")]
    assert "still developing" in out[(c.id, "en")]
    assert repo.get_segment(c.id, "en", 0) is None, "a fallback must never be cached"


# ---- assembly -------------------------------------------------------------------------------


def test_fifty_users_same_interests_cost_no_extra_llm_calls(repo):
    for i in range(4):
        seed_cluster(repo, f"New AI chip startup {i} unveils machine learning hardware")
    llm = FakeLLM()
    users = [_user(repo, name=f"User{i}") for i in range(50)]

    first = assemble_user_briefing(users[0].id, repo, llm=llm)
    calls_after_first = llm.calls
    assert calls_after_first >= 1

    scripts = [first["script_text"]]
    for u in users[1:]:
        scripts.append(assemble_user_briefing(u.id, repo, llm=llm)["script_text"])
    assert llm.calls == calls_after_first

    normalized = {re.sub(r"User\d+", "NAME", s) for s in scripts}
    assert len(normalized) == 1, "scripts must differ only by call name"
    assert "User7" in scripts[7]


def test_only_followed_interests_plus_one_must_know(repo):
    seed_cluster(repo, "AI chip startup raises funding", source="TechCrunch", score=6.0)
    seed_cluster(repo, "IPL final: Mumbai win title", source="ESPNcricinfo", score=7.5)
    seed_cluster(repo, "Bollywood star announces film", source="Pinkvilla", score=6.5)
    seed_cluster(repo, "Massive earthquake hits region, thousands affected", score=9.2)
    seed_cluster(repo, "Another huge national development", score=8.6)
    user = _user(repo, interests=("tech",))
    out = assemble_user_briefing(user.id, repo, llm=FakeLLM())
    titles = out["titles"]
    assert "AI chip startup raises funding" in titles
    assert "IPL final: Mumbai win title" not in titles
    assert "Bollywood star announces film" not in titles
    must_know = [t for t in titles if t != "AI chip startup raises funding"]
    assert len(must_know) == 1  # a single must-know slot, not both big stories


def test_followed_category_uses_threshold_relief(repo):
    seed_cluster(repo, "India beat Australia in thrilling T20", source="ESPNcricinfo", score=3.4)
    user = _user(repo, interests=("sports",))
    out = assemble_user_briefing(user.id, repo, llm=FakeLLM())
    assert out["story_count"] == 1


def test_free_text_keywords_match_stories(repo):
    seed_cluster(repo, "SEBI tightens rules for small SME IPOs", source="Mint Markets", score=6.2)
    seed_cluster(repo, "Monsoon deficit worries farmers in Bihar", score=6.2)
    user = _user(repo, interests=(), free_text="SEBI and IPO regulations")
    out = assemble_user_briefing(user.id, repo, llm=FakeLLM())
    assert out["titles"] == ["SEBI tightens rules for small SME IPOs"]


def test_nothing_qualifies_gives_quiet_day(repo):
    seed_cluster(repo, "Minor cricket club result", source="ESPNcricinfo", score=1.0)
    user = _user(repo, interests=("tech",))
    out = assemble_user_briefing(user.id, repo, llm=FakeLLM())
    assert out["story_count"] == 0
    assert repo.get_latest_briefing(user.id).is_quiet_day == 1


def test_repeat_suppressed_but_real_development_is_kept_as_update(repo):
    old = seed_cluster(repo, "AI chip export curbs tighten", source="TechCrunch", change_kind="repeat")
    dev = seed_cluster(repo, "New AI model launches from startup", source="TechCrunch", change_kind="major")
    user = _user(repo, interests=("tech",))
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    prev = repo.create_briefing("old", 60, date=yesterday, story_count=2, user_id=user.id)
    repo.add_cluster_to_briefing(prev.id, old.id, 1)
    repo.add_cluster_to_briefing(prev.id, dev.id, 2)

    out = assemble_user_briefing(user.id, repo, llm=FakeLLM())
    assert "AI chip export curbs tighten" not in out["titles"]
    assert "New AI model launches from startup" in out["titles"]
    assert "Quick update on one we covered earlier." in out["script_text"]


def test_hinglish_user_gets_hinglish_script(repo):
    seed_cluster(repo, "AI chip startup raises funding", source="TechCrunch")
    user = _user(repo, name="Riya", language="hinglish")
    out = assemble_user_briefing(user.id, repo, llm=FakeLLM())
    assert re.search(r"[ऀ-ॿ]", out["script_text"])
    assert "Riya" in out["script_text"]


# ---- localisation -----------------------------------------------------------------------------


@pytest.mark.parametrize("lang", ["en", "hinglish", "hinglish_roman", "hi"])
def test_every_fixed_phrase_exists_for_every_language(lang):
    assert REQUIRED_KEYS <= set(PHRASES[lang])
    assert PHRASES[lang]["middle"], "needs transitions"
    assert PHRASES[lang]["goodbye_words"]


def test_stale_cluster_is_never_selected(repo):
    old = seed_cluster(repo, "AI chip startup raises funding from last week", source="TechCrunch", score=9.0)
    week_ago = datetime.datetime.utcnow() - datetime.timedelta(days=5)
    with repo.session_scope() as session:
        from newtalk.db.models import RawArticle, StoryCluster

        for art in session.query(RawArticle).all():
            art.published_at = week_ago
            art.fetched_at = week_ago
        session.get(StoryCluster, old.id).latest_article_at = week_ago
    user = _user(repo, interests=("tech",))
    out = assemble_user_briefing(user.id, repo, llm=FakeLLM())
    assert out["story_count"] == 0


def test_generic_keywords_do_not_make_everything_relevant(repo):
    from newtalk.composer.user_selection import clean_keywords, keyword_hits

    assert clean_keywords(["India", "SEBI", "news", "IPOs", "the", "x"]) == ["sebi", "ipos"]
    seed_cluster(repo, "Monsoon deficit worries farmers across India", score=6.5)
    cluster = repo.list_clusters()[0]
    assert keyword_hits(cluster, clean_keywords(["india", "indian"])) == 0
    seed_cluster(repo, "Tata Capital IPO opens for subscription", score=6.5)
    ipo = repo.list_clusters()[1]
    assert keyword_hits(ipo, ["ipos"]) == 1


def test_script_form_is_enforced_per_language():
    from newtalk.composer.segments import normalize_for_speech, script_issues

    roman = "Aaj Sensex lagbhag 600 points gir gaya aur Nifty bhi neeche raha, analysts ke mutabik."
    mixed = "आज Sensex करीब 600 points गिर गया और Nifty भी नीचे रहा, analysts के मुताबिक।"
    assert script_issues(mixed, "hinglish") == []
    assert script_issues(roman, "hinglish")  # wrong script for the voice
    assert script_issues(mixed, "en")
    assert script_issues("आज बाज़ार गिरा और निवेशकों ने बिकवाली की।", "hi") == []
    assert script_issues("Market fell today", "hi")
    assert normalize_for_speech("Sensex ६१२ points, free\u2011trade deal\u00a0today") == (
        "Sensex 612 points, free-trade deal today"
    )
    assert normalize_for_speech("FY 2024-25 growth") == "FY 2024-25 growth"


def test_wrong_script_output_is_retried_then_accepted(repo):
    c = seed_cluster(repo, "Sensex falls 600 points on FII selling", source="Mint Markets")
    roman = (
        "Aaj Sensex lagbhag 600 points gir gaya kyunki foreign investors ne bikwali ki, Mint "
        "Markets ke mutabik. Isse retail investors ke SIP aur retirement funds par asar pad "
        "sakta hai, aur analysts ab agle hafte ke RBI policy ka intezaar kar rahe hain."
    )
    llm = FakeLLM(override={(c.id, False): roman})
    out = ensure_segments(repo, repo.list_clusters(), ["hinglish"], llm=llm)
    assert any("\u0900" <= ch <= "\u097f" for ch in out[(c.id, "hinglish")])
    assert llm.seen_feedback and "Devanagari" in llm.seen_feedback[0][str(c.id)][0]
