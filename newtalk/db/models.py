import datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

# Pre-existing single-user data (briefings, memory, Q&A) belongs to this user.
OWNER_USER_ID = 1

# Association table for cluster members
cluster_members = Table(
    "cluster_members",
    Base.metadata,
    Column(
        "cluster_id",
        Integer,
        ForeignKey("story_clusters.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "article_id",
        Integer,
        ForeignKey("raw_articles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class RawArticle(Base):
    __tablename__ = "raw_articles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String, nullable=False)
    source_type = Column(
        String, nullable=False
    )  # rss, reddit, youtube, arxiv, agentic_search, gdelt
    url = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    author = Column(String, nullable=True)
    published_at = Column(DateTime, nullable=True)
    fetched_at = Column(DateTime, default=datetime.datetime.utcnow)
    # v2 columns
    tier = Column(Integer, default=4)  # 1=official, 2=quality, 3=broad, 4=early-signal
    embedding = Column(String)  # base64-encoded float32 bytes for reuse
    canonical_key = Column(
        String
    )  # stable dedup key (sha1 of normalized url or title+source)

    # Relationships
    clusters = relationship(
        "StoryCluster", secondary=cluster_members, back_populates="articles"
    )

    def __repr__(self):
        return f"<RawArticle(id={self.id}, title='{self.title[:30]}', source='{self.source}')>"


class StoryCluster(Base):
    __tablename__ = "story_clusters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    representative_title = Column(String, nullable=False)
    first_seen_at = Column(DateTime, default=datetime.datetime.utcnow)
    latest_article_at = Column(DateTime, nullable=True)  # most recent member timestamp
    status = Column(String, default="developing")  # developing, settled
    # v2 event-tracking columns
    event_started_at = Column(DateTime, nullable=True)
    latest_development_at = Column(DateTime, nullable=True)
    development_count = Column(Integer, default=0)
    last_change_kind = Column(String, nullable=True)  # repeat, minor, major
    india_relevance = Column(Float, default=0.0)
    source_tiers_json = Column(Text, nullable=True)  # JSON list of tiers across sources
    conflicts_json = Column(Text, nullable=True)  # JSON list of conflict notes

    # Relationships
    articles = relationship(
        "RawArticle", secondary=cluster_members, back_populates="clusters"
    )
    importance_score = relationship(
        "ImportanceScore",
        back_populates="cluster",
        uselist=False,
        cascade="all, delete-orphan",
    )
    context = relationship(
        "StoryContext",
        back_populates="cluster",
        uselist=False,
        cascade="all, delete-orphan",
    )
    briefing_associations = relationship(
        "BriefingStory", back_populates="cluster", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<StoryCluster(id={self.id}, title='{self.representative_title[:30]}', status='{self.status}')>"


class ImportanceScore(Base):
    __tablename__ = "importance_scores"

    cluster_id = Column(
        Integer, ForeignKey("story_clusters.id", ondelete="CASCADE"), primary_key=True
    )
    score = Column(Float, nullable=False)
    rationale = Column(Text, nullable=False)
    scored_at = Column(DateTime, default=datetime.datetime.utcnow)
    rubric_version = Column(String, nullable=False)

    # Relationships
    cluster = relationship("StoryCluster", back_populates="importance_score")

    def __repr__(self):
        return f"<ImportanceScore(cluster_id={self.cluster_id}, score={self.score})>"


class StoryContext(Base):
    __tablename__ = "story_context"

    cluster_id = Column(
        Integer, ForeignKey("story_clusters.id", ondelete="CASCADE"), primary_key=True
    )
    background = Column(Text, nullable=False)
    timeline_json = Column(Text, nullable=False)  # JSON string
    viewpoints_json = Column(Text, nullable=False)  # JSON string
    confidence_level = Column(String, nullable=False)  # high, medium, developing
    evidence_json = Column(Text, nullable=False)  # JSON string

    # Relationships
    cluster = relationship("StoryCluster", back_populates="context")

    def __repr__(self):
        return f"<StoryContext(cluster_id={self.cluster_id}, confidence='{self.confidence_level}')>"


class Briefing(Base):
    __tablename__ = "briefings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, default=datetime.date.today)
    script_text = Column(Text, nullable=False)
    duration_estimate_sec = Column(Integer, nullable=False)
    delivered_at = Column(DateTime, nullable=True)
    # v2 dynamic briefing columns
    story_count = Column(Integer, nullable=True)
    is_quiet_day = Column(Integer, default=0)  # 0=False, 1=True
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Relationships
    stories = relationship(
        "BriefingStory",
        back_populates="briefing",
        order_by="BriefingStory.position",
        cascade="all, delete-orphan",
    )
    qa_logs = relationship(
        "QALog", back_populates="briefing", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Briefing(id={self.id}, date={self.date}, duration={self.duration_estimate_sec}s)>"


class BriefingStory(Base):
    __tablename__ = "briefing_stories"

    briefing_id = Column(
        Integer, ForeignKey("briefings.id", ondelete="CASCADE"), primary_key=True
    )
    cluster_id = Column(
        Integer, ForeignKey("story_clusters.id", ondelete="CASCADE"), primary_key=True
    )
    position = Column(Integer, nullable=False)

    # Relationships
    briefing = relationship("Briefing", back_populates="stories")
    cluster = relationship("StoryCluster", back_populates="briefing_associations")

    def __repr__(self):
        return f"<BriefingStory(briefing_id={self.briefing_id}, cluster_id={self.cluster_id}, position={self.position})>"


class UserMemory(Base):
    __tablename__ = "user_memory"

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        default=OWNER_USER_ID,
    )
    topic = Column(String, primary_key=True)
    familiarity_level = Column(
        Float, nullable=False, default=1.0
    )  # numeric scale, e.g., 0.0 to 5.0
    last_covered_at = Column(DateTime, default=datetime.datetime.utcnow)
    notes = Column(Text, nullable=True)

    def __repr__(self):
        return (
            f"<UserMemory(topic='{self.topic}', familiarity={self.familiarity_level})>"
        )


class QALog(Base):
    __tablename__ = "qa_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    briefing_id = Column(
        Integer, ForeignKey("briefings.id", ondelete="SET NULL"), nullable=True
    )
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    asked_at = Column(DateTime, default=datetime.datetime.utcnow)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Relationships
    briefing = relationship("Briefing", back_populates="qa_logs")

    def __repr__(self):
        return f"<QALog(id={self.id}, question='{self.question[:20]}')>"


class User(Base):
    __tablename__ = "users"
    # Never reuse ids: a deleted user's signed session cookie must not match a later user.
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=True)
    auth_provider = Column(
        String, nullable=False, default="invite"
    )  # owner, invite, google
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    profile = relationship(
        "UserProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    channel = relationship(
        "NotificationChannel",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<User(id={self.id}, provider='{self.auth_provider}')>"


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    call_name = Column(String, nullable=False)
    interests_json = Column(Text, nullable=False, default="[]")  # chosen topic slugs
    free_text = Column(Text, nullable=True)
    normalized_json = Column(
        Text, nullable=True
    )  # {"categories": [...], "keywords": [...]}
    call_time = Column(String, nullable=True)  # "HH:MM" in the user's timezone
    timezone = Column(String, nullable=False, default="Asia/Kolkata")
    language = Column(String, nullable=False, default="en")  # en, hinglish, hi
    paused = Column(Integer, nullable=False, default=0)
    consented_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="profile")


class NotificationChannel(Base):
    __tablename__ = "notification_channels"

    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    telegram_chat_id = Column(String, nullable=True)
    telegram_link_token = Column(String, nullable=True, unique=True)
    phone_e164 = Column(String, nullable=True)
    phone_verified_at = Column(DateTime, nullable=True)
    delivery_mode = Column(String, nullable=False, default="browser")  # browser, phone

    user = relationship("User", back_populates="channel")


class InviteCode(Base):
    __tablename__ = "invite_codes"

    code = Column(String, primary_key=True)
    note = Column(String, nullable=True)
    max_uses = Column(Integer, nullable=False, default=1)
    used_count = Column(Integer, nullable=False, default=0)
    # Personal access code: once claimed it is bound to one user and doubles as their login.
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class CallAttempt(Base):
    """One ring. `slot` is 'scheduled', 'reminder' or 'test-1'..'test-3'; the unique key makes
    scheduled calls idempotent across restarts and caps test calls at 3 per local day."""

    __tablename__ = "call_attempts"
    __table_args__ = (
        UniqueConstraint("user_id", "local_date", "slot", name="uq_call_attempt_slot"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    local_date = Column(Date, nullable=False)
    slot = Column(String, nullable=False)
    # pending, rung, answered, completed, missed, undeliverable, failed
    status = Column(String, nullable=False, default="pending")
    briefing_id = Column(
        Integer, ForeignKey("briefings.id", ondelete="SET NULL"), nullable=True
    )
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    rung_at = Column(DateTime, nullable=True)
    answered_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)


class StorySegment(Base):
    """Spoken text for one story in one language, reused for every user who gets that story."""

    __tablename__ = "story_segments"
    __table_args__ = (
        UniqueConstraint(
            "cluster_id", "language", "development_version", name="uq_segment_version"
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    cluster_id = Column(
        Integer,
        ForeignKey("story_clusters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    language = Column(String, nullable=False)
    development_version = Column(Integer, nullable=False, default=0)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class CallToken(Base):
    __tablename__ = "call_tokens"

    jti = Column(String, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    briefing_id = Column(
        Integer, ForeignKey("briefings.id", ondelete="CASCADE"), nullable=True
    )
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
