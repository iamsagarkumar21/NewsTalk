# Configurable ingestion sources — India-focused (edit to add/remove)
# Tiers: 1 = official/primary, 2 = quality journalism, 3 = broad discovery, 4 = early signals
#
# Every feed below was probed live (HTTP 200, parseable, items published in the last 24h)
# when this file was written. Re-check with `python3 -m newtalk.ingestion.feed_health`.


def _feed(url: str, source: str, tier: int = 2, topic: str = "general") -> dict:
    return {"url": url, "source": source, "tier": tier, "topic": topic}


RSS_FEEDS = [
    # ── Tier 1 — Official / Primary ──────────────────────────────────────────────
    _feed("https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3", "PIB", 1, "policy"),
    _feed("https://www.rbi.org.in/pressreleases_rss.xml", "RBI", 1, "economy"),
    # ── National / politics ──────────────────────────────────────────────────────
    _feed(
        "https://www.thehindu.com/news/national/feeder/default.rss",
        "The Hindu National",
        2,
        "politics",
    ),
    _feed(
        "https://indianexpress.com/section/india/feed/",
        "Indian Express India",
        2,
        "politics",
    ),
    _feed(
        "https://indianexpress.com/section/political-pulse/feed/",
        "IE Political Pulse",
        2,
        "politics",
    ),
    _feed(
        "https://indianexpress.com/section/explained/feed/",
        "IE Explained",
        2,
        "general",
    ),
    _feed("https://indianexpress.com/section/cities/feed/", "IE Cities", 2, "politics"),
    _feed(
        "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml",
        "HT India",
        2,
        "politics",
    ),
    _feed(
        "https://feeds.feedburner.com/ndtvnews-top-stories", "NDTV Top", 2, "general"
    ),
    _feed(
        "https://feeds.feedburner.com/ndtvnews-india-news", "NDTV India", 2, "politics"
    ),
    _feed(
        "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
        "Times of India",
        2,
        "general",
    ),
    _feed(
        "https://www.news18.com/commonfeeds/v1/eng/rss/india.xml",
        "News18 India",
        3,
        "politics",
    ),
    _feed("https://feeds.feedburner.com/ScrollinArticles.rss", "Scroll", 2, "politics"),
    _feed(
        "https://www.thehindu.com/opinion/editorial/feeder/default.rss",
        "The Hindu Editorial",
        2,
        "politics",
    ),
    # ── Geopolitics / world ──────────────────────────────────────────────────────
    _feed(
        "https://www.thehindu.com/news/international/feeder/default.rss",
        "The Hindu International",
        2,
        "geopolitics",
    ),
    _feed("http://feeds.bbci.co.uk/news/world/rss.xml", "BBC World", 2, "geopolitics"),
    _feed(
        "http://feeds.bbci.co.uk/news/world/asia/india/rss.xml",
        "BBC India",
        2,
        "geopolitics",
    ),
    _feed("https://www.aljazeera.com/xml/rss/all.xml", "Al Jazeera", 2, "geopolitics"),
    _feed("https://thediplomat.com/feed/", "The Diplomat", 2, "geopolitics"),
    # ── Markets & finance ────────────────────────────────────────────────────────
    _feed(
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "ET Markets",
        2,
        "markets",
    ),
    _feed(
        "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
        "ET Stocks",
        2,
        "markets",
    ),
    _feed(
        "https://economictimes.indiatimes.com/markets/ipos/rssfeeds/1977021501.cms",
        "ET IPOs",
        2,
        "markets",
    ),
    _feed("https://www.livemint.com/rss/markets", "Mint Markets", 2, "markets"),
    _feed("https://www.livemint.com/rss/money", "Mint Money", 2, "markets"),
    _feed(
        "https://www.business-standard.com/rss/markets-106.rss",
        "BS Markets",
        2,
        "markets",
    ),
    _feed(
        "https://www.business-standard.com/rss/companies-101.rss",
        "BS Companies",
        2,
        "markets",
    ),
    _feed(
        "https://www.thehindubusinessline.com/markets/feeder/default.rss",
        "BusinessLine Markets",
        2,
        "markets",
    ),
    _feed(
        "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml",
        "CNBC-TV18 Markets",
        2,
        "markets",
    ),
    _feed(
        "https://feeds.feedburner.com/ndtvprofit-latest", "NDTV Profit", 2, "markets"
    ),
    _feed(
        "https://www.moneycontrol.com/rss/marketreports.xml",
        "Moneycontrol Markets",
        2,
        "markets",
    ),
    # ── Economy & business ───────────────────────────────────────────────────────
    _feed(
        "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms",
        "ET Economy",
        2,
        "economy",
    ),
    _feed(
        "https://economictimes.indiatimes.com/rssfeedstopstories.cms",
        "ET Top",
        2,
        "economy",
    ),
    _feed(
        "https://www.business-standard.com/rss/economy-102.rss",
        "BS Economy",
        2,
        "economy",
    ),
    _feed(
        "https://www.business-standard.com/rss/home_page_top_stories.rss",
        "Business Standard",
        2,
        "economy",
    ),
    _feed(
        "https://www.thehindubusinessline.com/economy/feeder/default.rss",
        "BusinessLine Economy",
        2,
        "economy",
    ),
    _feed("https://www.livemint.com/rss/news", "Mint News", 2, "economy"),
    _feed(
        "https://www.hindustantimes.com/feeds/rss/business/rssfeed.xml",
        "HT Business",
        2,
        "economy",
    ),
    _feed(
        "http://feeds.bbci.co.uk/news/business/rss.xml", "BBC Business", 2, "economy"
    ),
    # ── Tech & startups ──────────────────────────────────────────────────────────
    _feed(
        "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms",
        "ET Tech",
        2,
        "tech",
    ),
    _feed(
        "https://www.thehindu.com/sci-tech/technology/feeder/default.rss",
        "The Hindu Tech",
        2,
        "tech",
    ),
    _feed(
        "https://indianexpress.com/section/technology/feed/",
        "Indian Express Tech",
        2,
        "tech",
    ),
    _feed("https://www.livemint.com/rss/technology", "Mint Tech", 2, "tech"),
    _feed(
        "https://www.business-standard.com/rss/technology-108.rss", "BS Tech", 2, "tech"
    ),
    _feed("https://inc42.com/feed/", "Inc42", 2, "tech"),
    _feed("https://yourstory.com/feed", "YourStory", 3, "tech"),
    _feed("https://www.medianama.com/feed/", "MediaNama", 2, "tech"),
    _feed("https://techcrunch.com/feed/", "TechCrunch", 2, "tech"),
    _feed("https://www.theverge.com/rss/index.xml", "The Verge", 3, "tech"),
    _feed("https://feeds.arstechnica.com/arstechnica/index", "Ars Technica", 3, "tech"),
    _feed("https://hnrss.org/frontpage?points=150", "Hacker News", 3, "tech"),
    _feed("https://www.technologyreview.com/feed/", "MIT Technology Review", 2, "tech"),
    # ── Science ──────────────────────────────────────────────────────────────────
    _feed(
        "https://www.thehindu.com/sci-tech/science/feeder/default.rss",
        "The Hindu Science",
        2,
        "science",
    ),
    _feed(
        "https://www.sciencedaily.com/rss/top/science.xml", "ScienceDaily", 3, "science"
    ),
    # ── Health ───────────────────────────────────────────────────────────────────
    _feed(
        "https://www.thehindu.com/sci-tech/health/feeder/default.rss",
        "The Hindu Health",
        2,
        "health",
    ),
    _feed(
        "https://indianexpress.com/section/lifestyle/health/feed/",
        "IE Health",
        2,
        "health",
    ),
    _feed(
        "https://timesofindia.indiatimes.com/rssfeeds/3908999.cms",
        "TOI Health",
        2,
        "health",
    ),
    _feed("https://www.who.int/rss-feeds/news-english.xml", "WHO News", 1, "health"),
    # ── Sports ───────────────────────────────────────────────────────────────────
    _feed(
        "https://www.espncricinfo.com/rss/content/story/feeds/0.xml",
        "ESPNcricinfo",
        2,
        "sports",
    ),
    _feed("https://www.espn.in/espn/rss/news", "ESPN India", 2, "sports"),
    _feed(
        "https://www.thehindu.com/sport/feeder/default.rss",
        "The Hindu Sports",
        2,
        "sports",
    ),
    _feed("https://indianexpress.com/section/sports/feed/", "IE Sports", 2, "sports"),
    _feed(
        "https://timesofindia.indiatimes.com/rssfeeds/4719148.cms",
        "TOI Sports",
        2,
        "sports",
    ),
    # ── Entertainment ────────────────────────────────────────────────────────────
    _feed(
        "https://indianexpress.com/section/entertainment/feed/",
        "IE Entertainment",
        2,
        "entertainment",
    ),
    _feed(
        "https://www.thehindu.com/entertainment/movies/feeder/default.rss",
        "The Hindu Movies",
        2,
        "entertainment",
    ),
    _feed(
        "https://www.bollywoodhungama.com/rss/news.xml",
        "Bollywood Hungama",
        3,
        "entertainment",
    ),
    _feed("https://www.pinkvilla.com/rss.xml", "Pinkvilla", 3, "entertainment"),
    _feed(
        "https://timesofindia.indiatimes.com/rssfeeds/1081479906.cms",
        "TOI Entertainment",
        3,
        "entertainment",
    ),
    # ── State-level (The Hindu state desks; IE state feeds no longer exist) ──────
    _feed(
        "https://www.thehindu.com/news/national/uttar-pradesh/feeder/default.rss",
        "The Hindu Uttar Pradesh",
        2,
        "state",
    ),
    _feed(
        "https://www.thehindu.com/news/national/bihar/feeder/default.rss",
        "The Hindu Bihar",
        2,
        "state",
    ),
    _feed(
        "https://www.thehindu.com/news/national/maharashtra/feeder/default.rss",
        "The Hindu Maharashtra",
        2,
        "state",
    ),
    _feed(
        "https://www.thehindu.com/news/national/tamil-nadu/feeder/default.rss",
        "The Hindu Tamil Nadu",
        2,
        "state",
    ),
    _feed(
        "https://www.thehindu.com/news/national/karnataka/feeder/default.rss",
        "The Hindu Karnataka",
        2,
        "state",
    ),
    _feed(
        "https://www.thehindu.com/news/national/west-bengal/feeder/default.rss",
        "The Hindu West Bengal",
        2,
        "state",
    ),
    _feed(
        "https://www.thehindu.com/news/national/gujarat/feeder/default.rss",
        "The Hindu Gujarat",
        2,
        "state",
    ),
    _feed(
        "https://www.thehindu.com/news/national/rajasthan/feeder/default.rss",
        "The Hindu Rajasthan",
        2,
        "state",
    ),
    _feed(
        "https://www.thehindu.com/news/national/madhya-pradesh/feeder/default.rss",
        "The Hindu Madhya Pradesh",
        2,
        "state",
    ),
    _feed(
        "https://www.thehindu.com/news/national/kerala/feeder/default.rss",
        "The Hindu Kerala",
        2,
        "state",
    ),
    _feed(
        "https://www.thehindu.com/news/national/jharkhand/feeder/default.rss",
        "The Hindu Jharkhand",
        2,
        "state",
    ),
    # ── Tier 3 — Broad discovery (Google News topic searches) ────────────────────
    _feed(
        "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en", "Google News India", 3
    ),
    _feed(
        "https://news.google.com/rss/search?q=India+economy&hl=en-IN&gl=IN&ceid=IN:en",
        "Google News Economy",
        3,
        "economy",
    ),
    _feed(
        "https://news.google.com/rss/search?q=India+foreign+policy&hl=en-IN&gl=IN&ceid=IN:en",
        "Google News Foreign Policy",
        3,
        "geopolitics",
    ),
    _feed(
        "https://news.google.com/rss/search?q=Nifty+Sensex+stock+market&hl=en-IN&gl=IN&ceid=IN:en",
        "Google News Markets",
        3,
        "markets",
    ),
    _feed(
        "https://news.google.com/rss/search?q=cricket+India&hl=en-IN&gl=IN&ceid=IN:en",
        "Google News Cricket",
        3,
        "sports",
    ),
    _feed(
        "https://news.google.com/rss/search?q=Bollywood&hl=en-IN&gl=IN&ceid=IN:en",
        "Google News Bollywood",
        3,
        "entertainment",
    ),
    _feed(
        "https://news.google.com/rss/search?q=India+startup+funding&hl=en-IN&gl=IN&ceid=IN:en",
        "Google News Startups",
        3,
        "tech",
    ),
    _feed(
        "https://news.google.com/rss/search?q=AI+artificial+intelligence&hl=en-IN&gl=IN&ceid=IN:en",
        "Google News AI",
        3,
        "tech",
    ),
]

# GDELT DOC 2.0 API — global event database for broad discovery (Tier 3)
GDELT_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_QUERIES = [
    "India",
    "Indian economy",
    "India geopolitics",
    "Sensex Nifty",
    "India cricket",
    "Jharkhand",
    "Uttar Pradesh",
    "Bihar",
    "Maharashtra",
    "Tamil Nadu",
    "Karnataka",
    "West Bengal",
    "Gujarat",
    "Rajasthan",
    "Madhya Pradesh",
    "Kerala",
]
GDELT_MAX_RECORDS = 25

REDDIT_SUBREDDITS = [
    "india",
    "IndiaNews",
    "indianews",
    "worldnews",
    "geopolitics",
    "technology",
    "economics",
    "IndianStockMarket",
    "IndiaInvestments",
    "Cricket",
    "bollywood",
    # State/regional subreddits
    "jharkhand",
    "uttarpradesh",
    "bihar",
    "maharashtra",
    "kerala",
    "bangalore",
    "mumbai",
    "delhi",
    "chennai",
    "kolkata",
    "hyderabad",
    "gujarat",
    "rajasthan",
]

REDDIT_POST_LIMIT = 25

ARXIV_CATEGORIES = [
    "cs.AI",
    "cs.LG",
    "econ.GN",
]
ARXIV_MAX_RESULTS = 15

YOUTUBE_CHANNELS = [
    "UC8p1rJ8FUXI3YJqYy6XvJ9w",  # WION
    "UCXIJgqnII2ZOINSWNOGFThA",  # PBS NewsHour (global context)
    "UC16niRr50-MSBwiO3YDbhRA",  # BBC News
]
YOUTUBE_MAX_RESULTS = 8

# Must stay in sync with trend_scout_categories in config/freshness_config.yaml
TREND_SCOUT_CATEGORIES = [
    "policy",
    "economy",
    "markets",
    "tech",
    "science",
    "geopolitics",
    "health",
    "sports",
    "entertainment",
    "state_politics",
]

# India-specific search suffix for trend scout
TREND_SCOUT_REGION_SUFFIX = (
    "India impact OR India news OR state news OR Jharkhand OR Uttar Pradesh OR Bihar OR "
    "Maharashtra OR Tamil Nadu OR Karnataka OR West Bengal last 24 hours"
)
