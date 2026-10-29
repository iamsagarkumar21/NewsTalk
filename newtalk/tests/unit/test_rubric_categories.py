"""Category detection: keywords plus the source's declared topic."""

from types import SimpleNamespace

from newtalk.scoring.rubric import (
    _text_blob,
    cluster_category,
    detect_category,
    load_rubric_config,
)

CFG = load_rubric_config()


def _art(source, title, body=""):
    return SimpleNamespace(source=source, title=title, body=body, tier=2, published_at=None)


def test_sensex_headline_is_markets():
    text = "sensex nifty rally as fii buying lifts bse smallcap index"
    assert detect_category(text, CFG) == "markets"


def test_markets_source_beats_overlapping_economy_keywords():
    arts = [_art("Mint Markets", "RBI policy and inflation outlook weigh on investors", "rupee gdp")]
    text = _text_blob(arts)
    assert detect_category(text, CFG) == "economy"  # keywords alone
    assert detect_category(text, CFG, arts) == "markets"  # source prior wins


def test_sports_source_is_sports():
    arts = [_art("ESPNcricinfo", "India name unchanged squad for series")]
    cluster = SimpleNamespace(articles=arts)
    assert cluster_category(cluster, CFG) == "sports"


def test_unknown_sources_fall_back_to_keywords():
    arts = [_art("Some Blog", "new chip startup raises funding for machine learning")]
    assert detect_category(_text_blob(arts), CFG, arts) == "tech"
