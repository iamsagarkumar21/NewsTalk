"""
YouTube transcript ingestion source.
Fetches video transcripts for a configured list of channel IDs using
youtube-transcript-api and the YouTube Data API v3.

Requires in .env:
    YOUTUBE_API_KEY   (needed to list channel videos)

youtube-transcript-api needs no key — it fetches public CC transcripts.
"""
import logging
import datetime
from pathlib import Path
from dotenv import load_dotenv

# Ensure .env is loaded before anything else
for _p in [Path(__file__).resolve().parent.parent / ".env",
           Path(__file__).resolve().parent.parent.parent / ".env"]:
    if _p.exists():
        load_dotenv(dotenv_path=_p, override=True)
        break

from newtalk.ingestion.sources_config import YOUTUBE_CHANNELS, YOUTUBE_MAX_RESULTS
from newtalk.db.repository import NewTalkRepository
from newtalk.config.settings import DATABASE_URL, YOUTUBE_API_KEY
from newtalk.processing.freshness import get_freshness_window_hours, is_within_freshness_window
from newtalk.ingestion.canonical import make_canonical_key

logger = logging.getLogger(__name__)


def _list_channel_videos(channel_id: str, max_results: int) -> list[dict]:
    """Use YouTube Data API to list recent video IDs + metadata for a channel."""
    if not YOUTUBE_API_KEY:
        raise EnvironmentError(
            "YOUTUBE_API_KEY is not set. "
            "Create one at https://console.cloud.google.com/ → APIs → YouTube Data API v3."
        )
    from googleapiclient.discovery import build

    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    request = youtube.search().list(
        part="snippet",
        channelId=channel_id,
        maxResults=max_results,
        order="date",
        type="video",
    )
    response = request.execute()
    videos = []
    for item in response.get("items", []):
        vid_id  = item["id"]["videoId"]
        snippet = item["snippet"]
        videos.append({
            "video_id":     vid_id,
            "title":        snippet.get("title", "").strip(),
            "channel":      snippet.get("channelTitle", "").strip(),
            "published_at": snippet.get("publishedAt"),
        })
    return videos


def _get_transcript(video_id: str) -> str:
    """Return the full transcript text for a YouTube video (or empty string)."""
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound
    try:
        fetched = YouTubeTranscriptApi().fetch(video_id)
        return " ".join(snippet.text for snippet in fetched)
    except (TranscriptsDisabled, NoTranscriptFound):
        logger.info("No transcript available for video %s", video_id)
        return ""
    except Exception as exc:
        logger.warning("Transcript fetch error for %s: %s", video_id, exc)
        return ""


def fetch_youtube_transcripts(repo: NewTalkRepository | None = None) -> list[dict]:
    """
    Fetch transcripts for videos in all configured YouTube channels.

    Args:
        repo: Optional repository. Writes to DB when provided.

    Returns:
        List of article dicts that were fetched.
    """
    if not YOUTUBE_CHANNELS:
        logger.info("No YouTube channels configured. Add channel IDs to sources_config.py.")
        return []

    if not YOUTUBE_API_KEY:
        logger.warning(
            "YOUTUBE_API_KEY is not set — skipping YouTube ingestion. "
            "Add the key to .env to enable."
        )
        return []

    if repo is None:
        repo = NewTalkRepository(DATABASE_URL)
        repo.create_tables()

    fetched = []
    for channel_id in YOUTUBE_CHANNELS:
        logger.info("Fetching YouTube channel %s …", channel_id)
        try:
            videos = _list_channel_videos(channel_id, YOUTUBE_MAX_RESULTS)
        except EnvironmentError as exc:
            logger.error("%s", exc)
            return []
        except Exception as exc:
            logger.warning("Failed to list videos for channel %s: %s", channel_id, exc)
            continue

        # Sort by upload date descending (newest first)
        def _video_dt(v):
            if not v.get("published_at"):
                return datetime.datetime.min
            try:
                return datetime.datetime.fromisoformat(v["published_at"].rstrip("Z"))
            except ValueError:
                return datetime.datetime.min

        videos.sort(key=_video_dt, reverse=True)
        window_hours = get_freshness_window_hours()
        skipped_stale = 0

        for video in videos:
            published_at = None
            if video["published_at"]:
                try:
                    published_at = datetime.datetime.fromisoformat(
                        video["published_at"].rstrip("Z")
                    )
                except ValueError:
                    pass

            if published_at and not is_within_freshness_window(published_at, window_hours):
                skipped_stale += 1
                continue

            transcript = _get_transcript(video["video_id"])
            if not transcript:
                continue   # Skip videos with no public transcript

            video_url = f"https://www.youtube.com/watch?v={video['video_id']}"

            repo.add_article(
                source=video["channel"] or f"YouTube:{channel_id}",
                source_type="youtube",
                url=video_url,
                title=video["title"],
                body=transcript,
                author=video["channel"],
                published_at=published_at,
                tier=2,  # quality journalism
                canonical_key=make_canonical_key(video_url),
            )
            fetched.append({
                "source": video["channel"],
                "title": video["title"],
                "url": video_url,
            })

        if skipped_stale:
            logger.info(
                "YouTube channel %s: skipped %d videos outside %dh window",
                channel_id, skipped_stale, window_hours,
            )

    return fetched


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = fetch_youtube_transcripts()
    print(f"\nYouTube ingestion complete — {len(results)} transcripts fetched.")
    for r in results[:5]:
        print(f"  [{r['source']}] {r['title'][:80]}")
