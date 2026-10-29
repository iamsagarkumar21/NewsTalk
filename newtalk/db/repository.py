import datetime
import json
import secrets
from contextlib import contextmanager

from sqlalchemy import create_engine, desc, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, sessionmaker

from newtalk.db.migrations import migrate
from newtalk.db.models import (
    OWNER_USER_ID,
    Base,
    Briefing,
    BriefingStory,
    CallAttempt,
    CallToken,
    ImportanceScore,
    InviteCode,
    NotificationChannel,
    QALog,
    RawArticle,
    StoryCluster,
    StoryContext,
    StorySegment,
    User,
    UserMemory,
    UserProfile,
    cluster_members,
)


class _LostInviteRace(Exception):
    pass


class NewTalkRepository:
    def __init__(self, db_url: str):
        """Initialize repository with a database URL."""
        self.engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False} if "sqlite" in db_url else {},
        )
        # expire_on_commit=False keeps model instances readable after session commit/close
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def create_tables(self):
        """Create all tables and apply pending migrations."""
        Base.metadata.create_all(self.engine)
        migrate(self.engine)

    def drop_tables(self):
        """Drop all tables in the database."""
        Base.metadata.drop_all(self.engine)

    @contextmanager
    def session_scope(self):
        """Provide a transactional scope around a series of operations."""
        session = self.Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # --- RawArticle Methods ---

    def add_article(
        self,
        source: str,
        source_type: str,
        url: str,
        title: str,
        body: str,
        author: str = None,
        published_at: datetime.datetime = None,
        tier: int = 4,
        canonical_key: str = None,
    ) -> RawArticle:
        with self.session_scope() as session:
            # Dedup: canonical_key first, then URL
            if canonical_key:
                existing = (
                    session.query(RawArticle)
                    .filter_by(canonical_key=canonical_key)
                    .first()
                )
                if existing:
                    return existing
            existing = session.query(RawArticle).filter_by(url=url).first()
            if existing:
                return existing

            article = RawArticle(
                source=source,
                source_type=source_type,
                url=url,
                title=title,
                body=body,
                author=author,
                published_at=published_at,
                tier=tier,
                canonical_key=canonical_key,
            )
            session.add(article)
            return article

    def get_article(self, article_id: int) -> RawArticle:
        with self.session_scope() as session:
            return session.query(RawArticle).filter_by(id=article_id).first()

    def get_article_by_url(self, url: str) -> RawArticle:
        with self.session_scope() as session:
            return session.query(RawArticle).filter_by(url=url).first()

    def list_articles(self, limit: int | None = None) -> list[RawArticle]:
        with self.session_scope() as session:
            q = session.query(RawArticle).order_by(desc(RawArticle.fetched_at))
            if limit:
                q = q.limit(limit)
            return q.all()

    def count_articles(self) -> int:
        with self.session_scope() as session:
            return session.query(RawArticle).count()

    def clear_clusters(self):
        """Remove all clusters (members cascade). Articles are kept."""
        with self.session_scope() as session:
            session.query(StoryCluster).delete()

    def list_clusters(self) -> list[StoryCluster]:
        with self.session_scope() as session:
            return (
                session.query(StoryCluster)
                .options(joinedload(StoryCluster.articles))
                .options(joinedload(StoryCluster.importance_score))
                .options(joinedload(StoryCluster.context))
                .order_by(StoryCluster.id)
                .all()
            )

    def get_ranked_clusters(self, limit: int = 10) -> list[StoryCluster]:
        with self.session_scope() as session:
            return (
                session.query(StoryCluster)
                .join(ImportanceScore, StoryCluster.id == ImportanceScore.cluster_id)
                .options(joinedload(StoryCluster.articles))
                .options(joinedload(StoryCluster.importance_score))
                .options(joinedload(StoryCluster.context))
                .order_by(desc(ImportanceScore.score))
                .limit(limit)
                .all()
            )

    # --- StoryCluster Methods ---

    def create_cluster(
        self,
        representative_title: str,
        status: str = "developing",
        latest_article_at: datetime.datetime = None,
    ) -> StoryCluster:
        with self.session_scope() as session:
            cluster = StoryCluster(
                representative_title=representative_title,
                status=status,
                latest_article_at=latest_article_at,
            )
            session.add(cluster)
            return cluster

    def update_cluster_latest_at(self, cluster_id: int, latest_at: datetime.datetime):
        with self.session_scope() as session:
            cluster = session.query(StoryCluster).filter_by(id=cluster_id).first()
            if cluster:
                cluster.latest_article_at = latest_at

    def get_cluster(self, cluster_id: int) -> StoryCluster:
        with self.session_scope() as session:
            return (
                session.query(StoryCluster)
                .options(joinedload(StoryCluster.articles))
                .options(joinedload(StoryCluster.importance_score))
                .options(joinedload(StoryCluster.context))
                .filter_by(id=cluster_id)
                .first()
            )

    def add_article_to_cluster(self, cluster_id: int, article_id: int):
        with self.session_scope() as session:
            cluster = session.query(StoryCluster).filter_by(id=cluster_id).first()
            article = session.query(RawArticle).filter_by(id=article_id).first()
            if cluster and article:
                if article not in cluster.articles:
                    cluster.articles.append(article)

    # --- ImportanceScore Methods ---

    def set_importance_score(
        self, cluster_id: int, score: float, rationale: str, rubric_version: str
    ) -> ImportanceScore:
        with self.session_scope() as session:
            imp_score = (
                session.query(ImportanceScore).filter_by(cluster_id=cluster_id).first()
            )
            if imp_score:
                imp_score.score = score
                imp_score.rationale = rationale
                imp_score.rubric_version = rubric_version
                imp_score.scored_at = datetime.datetime.utcnow()
            else:
                imp_score = ImportanceScore(
                    cluster_id=cluster_id,
                    score=score,
                    rationale=rationale,
                    rubric_version=rubric_version,
                )
                session.add(imp_score)
            return imp_score

    def get_importance_score(self, cluster_id: int) -> ImportanceScore:
        with self.session_scope() as session:
            return (
                session.query(ImportanceScore).filter_by(cluster_id=cluster_id).first()
            )

    # --- StoryContext Methods ---

    def set_story_context(
        self,
        cluster_id: int,
        background: str,
        timeline_json: str,
        viewpoints_json: str,
        confidence_level: str,
        evidence_json: str,
    ) -> StoryContext:
        with self.session_scope() as session:
            context = (
                session.query(StoryContext).filter_by(cluster_id=cluster_id).first()
            )
            if context:
                context.background = background
                context.timeline_json = timeline_json
                context.viewpoints_json = viewpoints_json
                context.confidence_level = confidence_level
                context.evidence_json = evidence_json
            else:
                context = StoryContext(
                    cluster_id=cluster_id,
                    background=background,
                    timeline_json=timeline_json,
                    viewpoints_json=viewpoints_json,
                    confidence_level=confidence_level,
                    evidence_json=evidence_json,
                )
                session.add(context)
            return context

    def get_story_context(self, cluster_id: int) -> StoryContext:
        with self.session_scope() as session:
            return session.query(StoryContext).filter_by(cluster_id=cluster_id).first()

    # --- Briefing Methods ---

    def create_briefing(
        self,
        script_text: str,
        duration_estimate_sec: int,
        date: datetime.date = None,
        story_count: int = None,
        is_quiet_day: bool = False,
        user_id: int | None = None,
    ) -> Briefing:
        with self.session_scope() as session:
            if date is None:
                date = datetime.date.today()
            briefing = Briefing(
                script_text=script_text,
                duration_estimate_sec=duration_estimate_sec,
                date=date,
                story_count=story_count,
                is_quiet_day=1 if is_quiet_day else 0,
                user_id=user_id if user_id is not None else OWNER_USER_ID,
            )
            session.add(briefing)
            return briefing

    def get_briefing(self, briefing_id: int) -> Briefing:
        with self.session_scope() as session:
            return (
                session.query(Briefing)
                .options(
                    joinedload(Briefing.stories)
                    .joinedload(BriefingStory.cluster)
                    .joinedload(StoryCluster.context)
                )
                .options(joinedload(Briefing.qa_logs))
                .filter_by(id=briefing_id)
                .first()
            )

    def add_cluster_to_briefing(
        self, briefing_id: int, cluster_id: int, position: int
    ) -> BriefingStory:
        with self.session_scope() as session:
            briefing_story = (
                session.query(BriefingStory)
                .filter_by(briefing_id=briefing_id, cluster_id=cluster_id)
                .first()
            )
            if briefing_story:
                briefing_story.position = position
            else:
                briefing_story = BriefingStory(
                    briefing_id=briefing_id, cluster_id=cluster_id, position=position
                )
                session.add(briefing_story)
            return briefing_story

    def get_latest_briefing(self, user_id: int | None = None) -> Briefing:
        with self.session_scope() as session:
            query = session.query(Briefing).options(
                joinedload(Briefing.stories).joinedload(BriefingStory.cluster)
            )
            if user_id is not None:
                query = query.filter(Briefing.user_id == user_id)
            return query.order_by(desc(Briefing.id)).first()

    # --- UserMemory Methods ---

    def get_user_memory(self, topic: str, user_id: int = OWNER_USER_ID) -> UserMemory:
        with self.session_scope() as session:
            return (
                session.query(UserMemory)
                .filter_by(topic=topic, user_id=user_id)
                .first()
            )

    def set_user_memory(
        self,
        topic: str,
        familiarity_level: float,
        notes: str = None,
        user_id: int = OWNER_USER_ID,
    ) -> UserMemory:
        with self.session_scope() as session:
            mem = (
                session.query(UserMemory)
                .filter_by(topic=topic, user_id=user_id)
                .first()
            )
            if mem:
                mem.familiarity_level = familiarity_level
                if notes is not None:
                    mem.notes = notes
                mem.last_covered_at = datetime.datetime.utcnow()
            else:
                mem = UserMemory(
                    user_id=user_id,
                    topic=topic,
                    familiarity_level=familiarity_level,
                    notes=notes,
                )
                session.add(mem)
            return mem

    # --- V2 Event-Tracking Methods ---

    def get_unclustered_articles(self, window_hours: int) -> list[RawArticle]:
        """Articles fetched within window that are not yet in any cluster."""
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=window_hours)
        with self.session_scope() as session:
            subq = session.query(cluster_members.c.article_id).subquery()
            return (
                session.query(RawArticle)
                .filter(RawArticle.fetched_at >= cutoff)
                .filter(RawArticle.id.notin_(session.query(subq.c.article_id)))
                .order_by(RawArticle.fetched_at)
                .all()
            )

    def set_article_embedding(self, article_id: int, embedding_bytes: bytes):
        with self.session_scope() as session:
            article = session.query(RawArticle).filter_by(id=article_id).first()
            if article:
                import base64

                article.embedding = base64.b64encode(embedding_bytes).decode("ascii")

    def update_cluster_event_fields(self, cluster_id: int, **kwargs):
        """Update event-tracking columns on a cluster. Field names match model attrs."""
        allowed = {
            "latest_article_at",
            "latest_development_at",
            "development_count",
            "last_change_kind",
            "india_relevance",
            "source_tiers_json",
            "conflicts_json",
            "event_started_at",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        with self.session_scope() as session:
            cluster = session.query(StoryCluster).filter_by(id=cluster_id).first()
            if cluster:
                for k, v in updates.items():
                    setattr(cluster, k, v)

    def prune_old_articles(self, retention_days: int = 30):
        """Delete raw_articles older than retention_days that are not in any cluster."""
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=retention_days)
        with self.session_scope() as session:
            subq = session.query(cluster_members.c.article_id).subquery()
            session.query(RawArticle).filter(
                RawArticle.fetched_at < cutoff,
                RawArticle.id.notin_(session.query(subq.c.article_id)),
            ).delete()

    def get_clusters_with_latest_development(
        self, since: datetime.datetime
    ) -> list[StoryCluster]:
        """Clusters that had a meaningful development since the given time."""
        with self.session_scope() as session:
            return (
                session.query(StoryCluster)
                .options(joinedload(StoryCluster.articles))
                .options(joinedload(StoryCluster.importance_score))
                .options(joinedload(StoryCluster.context))
                .filter(StoryCluster.latest_development_at >= since)
                .all()
            )

    def get_yesterdays_briefing_cluster_ids(
        self, user_id: int | None = None
    ) -> set[int]:
        """Cluster IDs that appeared in the most recent previous briefing (not today)."""
        today = datetime.date.today()
        with self.session_scope() as session:
            query = session.query(Briefing).filter(Briefing.date < today)
            if user_id is not None:
                query = query.filter(Briefing.user_id == user_id)
            prev = query.order_by(desc(Briefing.id)).first()
            if not prev:
                return set()
            cluster_ids = {bs.cluster_id for bs in prev.stories}
            return cluster_ids

    def get_cluster_centroids(self) -> dict[int, list[float]]:
        """Compute centroids for all existing clusters using stored article embeddings."""
        centroids = {}
        with self.session_scope() as session:
            clusters = session.query(StoryCluster).all()
            for cluster in clusters:
                if not cluster.articles:
                    continue
                vectors = []
                for article in cluster.articles:
                    if article.embedding:
                        import base64

                        import numpy as np

                        emb = np.frombuffer(
                            base64.b64decode(article.embedding), dtype=np.float32
                        )
                        vectors.append(emb)
                if vectors:
                    centroid = np.mean(np.stack(vectors), axis=0)
                    norm = np.linalg.norm(centroid)
                    if norm > 0:
                        centroid = centroid / norm
                    centroids[cluster.id] = centroid.tolist()
        return centroids

    # --- QALog Methods ---

    def log_qa(
        self, briefing_id: int, question: str, answer: str, user_id: int | None = None
    ) -> QALog:
        with self.session_scope() as session:
            if user_id is None:
                briefing = session.get(Briefing, briefing_id) if briefing_id else None
                user_id = (
                    briefing.user_id if briefing and briefing.user_id else OWNER_USER_ID
                )
            log_entry = QALog(
                briefing_id=briefing_id,
                question=question,
                answer=answer,
                user_id=user_id,
            )
            session.add(log_entry)
            return log_entry

    # --- Invite codes ---

    def create_invite_code(
        self, code: str | None = None, max_uses: int = 1, note: str | None = None
    ) -> InviteCode:
        with self.session_scope() as session:
            invite = InviteCode(
                code=code or secrets.token_urlsafe(6),
                max_uses=max_uses,
                note=note,
            )
            session.add(invite)
            return invite

    def claim_invite(self, code: str) -> tuple[str, int | None]:
        """Sign up or log in with a personal invite code.

        Returns ("new", user_id) the first time a code is used (a user is created and bound to
        it), ("existing", user_id) on later uses, or ("invalid", None) for unknown codes.
        """
        for _ in range(2):
            try:
                with self.session_scope() as session:
                    invite = session.get(InviteCode, code)
                    if invite is None:
                        return ("invalid", None)
                    if invite.user_id is not None:
                        return ("existing", invite.user_id)
                    user = User(auth_provider="invite")
                    session.add(user)
                    session.flush()
                    session.add(NotificationChannel(user_id=user.id))
                    bound = session.execute(
                        update(InviteCode)
                        .where(InviteCode.code == code, InviteCode.user_id.is_(None))
                        .values(user_id=user.id, used_count=InviteCode.used_count + 1)
                    )
                    if bound.rowcount != 1:
                        raise _LostInviteRace()
                    return ("new", user.id)
            except _LostInviteRace:
                continue  # someone else claimed it first; the retry reports "existing"
        return ("invalid", None)

    # --- Users and profiles ---

    def create_user(
        self, email: str | None = None, auth_provider: str = "invite"
    ) -> User:
        with self.session_scope() as session:
            user = User(email=email, auth_provider=auth_provider)
            session.add(user)
            session.flush()
            session.add(NotificationChannel(user_id=user.id))
            return user

    def get_user(self, user_id: int) -> User | None:
        with self.session_scope() as session:
            return session.get(User, user_id)

    def get_user_by_email(self, email: str) -> User | None:
        with self.session_scope() as session:
            return session.query(User).filter_by(email=email).first()

    def get_profile(self, user_id: int) -> UserProfile | None:
        with self.session_scope() as session:
            return session.get(UserProfile, user_id)

    def upsert_profile(self, user_id: int, **fields) -> UserProfile:
        """Create or update a profile. `interests` (list) is stored as interests_json,
        `normalized` (dict) as normalized_json. Validation is the API layer's job."""
        if "interests" in fields:
            fields["interests_json"] = json.dumps(fields.pop("interests"))
        if "normalized" in fields:
            fields["normalized_json"] = json.dumps(fields.pop("normalized"))
        with self.session_scope() as session:
            profile = session.get(UserProfile, user_id)
            if profile is None:
                profile = UserProfile(user_id=user_id, **fields)
                session.add(profile)
            else:
                for key, value in fields.items():
                    setattr(profile, key, value)
            profile.updated_at = datetime.datetime.utcnow()
            return profile

    def list_active_profiles(self) -> list[UserProfile]:
        """Profiles that should receive calls: consented and not paused."""
        with self.session_scope() as session:
            return (
                session.query(UserProfile)
                .filter(UserProfile.consented_at.isnot(None))
                .filter(UserProfile.paused == 0)
                .all()
            )

    def update_normalized_json(self, user_id: int, normalized_json: str) -> None:
        with self.session_scope() as session:
            profile = session.get(UserProfile, user_id)
            if profile is not None:
                profile.normalized_json = normalized_json
                profile.updated_at = datetime.datetime.utcnow()

    def set_consent(self, user_id: int, granted: bool) -> None:
        with self.session_scope() as session:
            profile = session.get(UserProfile, user_id)
            if profile is None:
                raise ValueError(f"user {user_id} has no profile")
            profile.consented_at = datetime.datetime.utcnow() if granted else None

    def set_paused(self, user_id: int, paused: bool) -> None:
        with self.session_scope() as session:
            profile = session.get(UserProfile, user_id)
            if profile is None:
                raise ValueError(f"user {user_id} has no profile")
            profile.paused = 1 if paused else 0

    def get_channel(self, user_id: int) -> NotificationChannel | None:
        with self.session_scope() as session:
            return session.get(NotificationChannel, user_id)

    def update_channel(self, user_id: int, **fields) -> NotificationChannel:
        with self.session_scope() as session:
            channel = session.get(NotificationChannel, user_id)
            if channel is None:
                channel = NotificationChannel(user_id=user_id)
                session.add(channel)
            for key, value in fields.items():
                setattr(channel, key, value)
            return channel

    def delete_user(self, user_id: int) -> None:
        """Erase a user and everything tied to them. The owner user cannot be deleted."""
        if user_id == OWNER_USER_ID:
            raise ValueError("the owner user cannot be deleted")
        with self.session_scope() as session:
            session.query(CallToken).filter_by(user_id=user_id).delete()
            session.query(CallAttempt).filter_by(user_id=user_id).delete()
            session.query(QALog).filter_by(user_id=user_id).delete()
            session.query(UserMemory).filter_by(user_id=user_id).delete()
            for briefing in session.query(Briefing).filter_by(user_id=user_id).all():
                session.delete(briefing)
            session.query(UserProfile).filter_by(user_id=user_id).delete()
            session.query(NotificationChannel).filter_by(user_id=user_id).delete()
            session.query(InviteCode).filter_by(user_id=user_id).update(
                {InviteCode.user_id: None, InviteCode.used_count: 0}
            )
            session.query(User).filter_by(id=user_id).delete()

    # --- Call attempts ---

    def claim_call_slot(
        self,
        user_id: int,
        local_date: datetime.date,
        slot: str,
        briefing_id: int | None = None,
    ) -> CallAttempt | None:
        """Insert a pending attempt for (user, local date, slot). None if it already exists."""
        try:
            with self.session_scope() as session:
                attempt = CallAttempt(
                    user_id=user_id,
                    local_date=local_date,
                    slot=slot,
                    status="pending",
                    briefing_id=briefing_id,
                )
                session.add(attempt)
                session.flush()
                return attempt
        except IntegrityError:
            return None

    def claim_test_slot(
        self, user_id: int, local_date: datetime.date, max_per_day: int = 3
    ) -> CallAttempt | None:
        """Claim the next free test-call slot of the day; None once the daily limit is used."""
        for n in range(1, max_per_day + 1):
            attempt = self.claim_call_slot(user_id, local_date, f"test-{n}")
            if attempt is not None:
                return attempt
        return None

    def update_call_attempt(self, attempt_id: int, **fields) -> CallAttempt:
        with self.session_scope() as session:
            attempt = session.get(CallAttempt, attempt_id)
            if attempt is None:
                raise ValueError(f"call attempt {attempt_id} not found")
            for key, value in fields.items():
                setattr(attempt, key, value)
            return attempt

    def list_call_attempts(self, user_id: int, limit: int = 20) -> list[CallAttempt]:
        with self.session_scope() as session:
            return (
                session.query(CallAttempt)
                .filter_by(user_id=user_id)
                .order_by(desc(CallAttempt.id))
                .limit(limit)
                .all()
            )

    def unlink_chat(self, chat_id: str) -> None:
        """A Telegram chat belongs to one user; clear any previous binding."""
        with self.session_scope() as session:
            for row in (
                session.query(NotificationChannel)
                .filter_by(telegram_chat_id=str(chat_id))
                .all()
            ):
                row.telegram_chat_id = None

    def get_user_id_by_chat(self, chat_id: str) -> int | None:
        with self.session_scope() as session:
            row = (
                session.query(NotificationChannel)
                .filter_by(telegram_chat_id=str(chat_id))
                .first()
            )
            return row.user_id if row else None

    def get_call_attempt(
        self, user_id: int, local_date: datetime.date, slot: str
    ) -> CallAttempt | None:
        with self.session_scope() as session:
            return (
                session.query(CallAttempt)
                .filter_by(user_id=user_id, local_date=local_date, slot=slot)
                .first()
            )

    def update_attempts_for_briefing(
        self, user_id: int, briefing_id: int, **fields
    ) -> int:
        """Update every attempt tied to a briefing (answered/completed bookkeeping)."""
        with self.session_scope() as session:
            rows = (
                session.query(CallAttempt)
                .filter_by(user_id=user_id, briefing_id=briefing_id)
                .all()
            )
            for row in rows:
                for key, value in fields.items():
                    setattr(row, key, value)
            return len(rows)

    def list_briefings(self, user_id: int, limit: int = 10) -> list[Briefing]:
        with self.session_scope() as session:
            return (
                session.query(Briefing)
                .filter_by(user_id=user_id)
                .options(joinedload(Briefing.qa_logs))
                .order_by(desc(Briefing.id))
                .limit(limit)
                .all()
            )

    def purge_user_history(
        self, older_than_days: int = 30, now: datetime.datetime | None = None
    ) -> dict:
        """Delete briefings (and their Q&A, stories), attempts and used tokens past retention.

        Text only is ever stored, so this is the whole retention story. The owner's legacy
        history is kept.
        """
        now = now or datetime.datetime.utcnow()
        cutoff = now - datetime.timedelta(days=older_than_days)
        with self.session_scope() as session:
            old = (
                session.query(Briefing)
                .filter(Briefing.date < cutoff.date(), Briefing.user_id != OWNER_USER_ID)
                .all()
            )
            n_briefings = len(old)
            for briefing in old:
                session.delete(briefing)
            n_attempts = (
                session.query(CallAttempt)
                .filter(CallAttempt.created_at < cutoff)
                .delete(synchronize_session=False)
            )
            n_tokens = (
                session.query(CallToken)
                .filter(CallToken.expires_at < cutoff)
                .delete(synchronize_session=False)
            )
        return {"briefings": n_briefings, "attempts": n_attempts, "tokens": n_tokens}

    # --- Story segments ---

    def get_segment(
        self, cluster_id: int, language: str, development_version: int = 0
    ) -> StorySegment | None:
        with self.session_scope() as session:
            return (
                session.query(StorySegment)
                .filter_by(
                    cluster_id=cluster_id,
                    language=language,
                    development_version=development_version,
                )
                .first()
            )

    def latest_segment_text(self, cluster_id: int, language: str) -> str | None:
        with self.session_scope() as session:
            row = (
                session.query(StorySegment)
                .filter_by(cluster_id=cluster_id, language=language)
                .order_by(desc(StorySegment.development_version), desc(StorySegment.id))
                .first()
            )
            return row.text if row else None

    def upsert_segment(
        self, cluster_id: int, language: str, development_version: int, text: str
    ) -> StorySegment:
        with self.session_scope() as session:
            segment = (
                session.query(StorySegment)
                .filter_by(
                    cluster_id=cluster_id,
                    language=language,
                    development_version=development_version,
                )
                .first()
            )
            if segment is None:
                segment = StorySegment(
                    cluster_id=cluster_id,
                    language=language,
                    development_version=development_version,
                    text=text,
                )
                session.add(segment)
            else:
                segment.text = text
            return segment

    # --- Call tokens ---

    def create_call_token(
        self,
        jti: str,
        user_id: int,
        briefing_id: int | None,
        expires_at: datetime.datetime,
    ) -> CallToken:
        with self.session_scope() as session:
            token = CallToken(
                jti=jti, user_id=user_id, briefing_id=briefing_id, expires_at=expires_at
            )
            session.add(token)
            return token

    def consume_call_token(
        self, jti: str, now: datetime.datetime | None = None
    ) -> CallToken | None:
        """Mark a token used exactly once. None if unknown, already used or expired."""
        now = now or datetime.datetime.utcnow()
        with self.session_scope() as session:
            result = session.execute(
                update(CallToken)
                .where(
                    CallToken.jti == jti,
                    CallToken.used_at.is_(None),
                    CallToken.expires_at > now,
                )
                .values(used_at=now)
            )
            if result.rowcount != 1:
                return None
            return session.get(CallToken, jti)
