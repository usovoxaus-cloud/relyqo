import uuid
from datetime import datetime
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def uid():
    return str(uuid.uuid4())


def now():
    return datetime.utcnow()


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(160))
    city: Mapped[str] = mapped_column(String(80), default="Tashkent")
    category: Mapped[str] = mapped_column(String(40), default="RESTAURANT", index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    profile_status: Mapped[str] = mapped_column(
        String(30), default="VERIFIED_PARTNER", index=True
    )
    score: Mapped[float] = mapped_column(Float, default=0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ServiceCategory(Base):
    __tablename__ = "service_categories"
    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    label: Mapped[str] = mapped_column(String(80))
    label_key: Mapped[str] = mapped_column(String(80), unique=True)
    group_code: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Branch(Base):
    __tablename__ = "branches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(String(160))
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    google_place_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ManualPlace(Base):
    __tablename__ = "manual_places"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    identity_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text)
    address: Mapped[str] = mapped_column(String(255))
    city: Mapped[str] = mapped_column(String(80))
    country_code: Mapped[str] = mapped_column(String(2))
    latitude: Mapped[float] = mapped_column(Float, index=True)
    longitude: Mapped[float] = mapped_column(Float, index=True)
    google_place_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True
    )
    created_by_hash: Mapped[str] = mapped_column(String(64), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class GooglePlaceReference(Base):
    __tablename__ = "google_place_references"
    place_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class VisitToken(Base):
    __tablename__ = "visit_tokens"
    __table_args__ = (
        UniqueConstraint(
            "branch_id",
            "transaction_reference",
            name="uq_visit_tokens_branch_transaction_reference",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    transaction_reference: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    issued_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=now, nullable=True
    )


class Visit(Base):
    __tablename__ = "visits"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"))
    verified_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    verification_score: Mapped[float] = mapped_column(Float, default=0.95)


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (UniqueConstraint("visit_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    visit_id: Mapped[str] = mapped_column(ForeignKey("visits.id"))
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
    consumer_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    overall: Mapped[int] = mapped_column(Integer)
    food: Mapped[int] = mapped_column(Integer)
    service: Mapped[int] = mapped_column(Integer)
    cleanliness: Mapped[int] = mapped_column(Integer)
    value: Mapped[int] = mapped_column(Integer)
    ces: Mapped[float] = mapped_column(Float)
    trust_weight: Mapped[float] = mapped_column(Float)
    included: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(30), default="ACCEPTED")
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasons_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class CommunityRating(Base):
    __tablename__ = "community_ratings"
    __table_args__ = (
        UniqueConstraint("object_key", "rater_hash"),
        UniqueConstraint("object_key", "consumer_user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    object_key: Mapped[str] = mapped_column(String(320), index=True)
    source: Mapped[str] = mapped_column(String(30))
    category: Mapped[str] = mapped_column(String(40), default="OTHER")
    rater_hash: Mapped[str] = mapped_column(String(64), index=True)
    consumer_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    overall: Mapped[int] = mapped_column(Integer)
    quality: Mapped[int] = mapped_column(Integer)
    service: Mapped[int] = mapped_column(Integer)
    cleanliness: Mapped[int] = mapped_column(Integer)
    value: Mapped[int] = mapped_column(Integer)
    community_score: Mapped[float] = mapped_column(Float)
    included: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    status: Mapped[str] = mapped_column(
        String(30), default="ACCEPTED", server_default="ACCEPTED"
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasons_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class RatingPhoto(Base):
    __tablename__ = "rating_photos"
    __table_args__ = (
        UniqueConstraint("rating_id"),
        UniqueConstraint("community_rating_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    rating_id: Mapped[str | None] = mapped_column(
        ForeignKey("ratings.id"), nullable=True, index=True
    )
    community_rating_id: Mapped[str | None] = mapped_column(
        ForeignKey("community_ratings.id"), nullable=True, index=True
    )
    object_key: Mapped[str | None] = mapped_column(
        String(320), nullable=True, index=True
    )
    content_type: Mapped[str] = mapped_column(String(40), default="image/jpeg")
    image_data: Mapped[bytes] = mapped_column(LargeBinary)
    content_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    ai_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_status: Mapped[str] = mapped_column(String(30), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ScoreHistory(Base):
    __tablename__ = "score_history"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
    score: Mapped[float] = mapped_column(Float)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class OwnerReview(Base):
    __tablename__ = "owner_reviews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[str] = mapped_column(String(36))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    actor_type: Mapped[str] = mapped_column(String(30))
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Advertisement(Base):
    __tablename__ = "advertisements"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    campaign_name: Mapped[str] = mapped_column(String(80), default="")
    sponsor_name: Mapped[str] = mapped_column(String(120))
    headline: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(String(280))
    cta_text: Mapped[str] = mapped_column(String(32), default="Подробнее")
    target_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    placement: Mapped[str] = mapped_column(String(30), index=True)
    page_scope: Mapped[str] = mapped_column(String(30), default="ALL", index=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    max_impressions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    media_kind: Mapped[str | None] = mapped_column(String(30), nullable=True)
    media_content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    media_filename: Mapped[str | None] = mapped_column(String(180), nullable=True)
    media_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AdvertisementMedia(Base):
    __tablename__ = "advertisement_media"
    advertisement_id: Mapped[str] = mapped_column(
        ForeignKey("advertisements.id"), primary_key=True
    )
    media_data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(40), index=True)
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    language: Mapped[str] = mapped_column(String(2), default="ru", server_default="ru")
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recovery_code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recovery_code_created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ConsumerFavorite(Base):
    __tablename__ = "consumer_favorites"
    __table_args__ = (UniqueConstraint("user_id", "object_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    object_key: Mapped[str] = mapped_column(String(320), index=True)
    source: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ConsumerEmail(Base):
    __tablename__ = "consumer_emails"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class PasswordRecoveryToken(Base):
    __tablename__ = "password_recovery_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(20))
    email: Mapped[str] = mapped_column(String(254))
    password_fingerprint: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class RecoveryRateLimit(Base):
    __tablename__ = "recovery_rate_limits"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class FeedbackSignal(Base):
    __tablename__ = "feedback_signals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    rating_id: Mapped[str] = mapped_column(String(36), unique=True)
    rating_type: Mapped[str] = mapped_column(String(20))
    object_key: Mapped[str] = mapped_column(String(320), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    device_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class ModerationCase(Base):
    __tablename__ = "moderation_cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_key: Mapped[str] = mapped_column(String(100), unique=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    object_key: Mapped[str] = mapped_column(String(320), index=True)
    rating_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    rating_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reporter_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    details: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MailDelivery(Base):
    __tablename__ = "mail_deliveries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    purpose: Mapped[str] = mapped_column(String(20))
    provider_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class OperationsEvent(Base):
    __tablename__ = "operations_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(20))
    details: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class AdminNotificationRead(Base):
    __tablename__ = "admin_notification_reads"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    event_key: Mapped[str] = mapped_column(String(180), primary_key=True)
    read_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ImprovementAction(Base):
    __tablename__ = "improvement_actions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(160))
    recommendation: Mapped[str] = mapped_column(Text)
    filters_json: Mapped[str] = mapped_column(Text)
    baseline_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class ImprovementEvent(Base):
    __tablename__ = "improvement_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    action_id: Mapped[str] = mapped_column(
        ForeignKey("improvement_actions.id"), index=True
    )
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class BackupAgent(Base):
    __tablename__ = "backup_agents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    password_fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_export_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_saved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    latest_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
