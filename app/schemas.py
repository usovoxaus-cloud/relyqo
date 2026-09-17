from datetime import datetime
from typing import Literal
from pydantic import AnyHttpUrl, BaseModel, Field, field_validator


class FeedbackDetails(BaseModel):
    reasons: list[str] = Field(default_factory=list, max_length=5)
    comment: str | None = Field(default=None, max_length=600)

    @field_validator("reasons")
    @classmethod
    def valid_reasons(cls, value):
        from .feedback import REASONS

        if any(code not in REASONS for code in value):
            raise ValueError("Выберите причину из списка")
        return list(dict.fromkeys(value))

    @field_validator("comment")
    @classmethod
    def clean_comment(cls, value):
        if value is None:
            return None
        return " ".join(value.split()) or None


class RegistrationEmail(BaseModel):
    email: str | None = Field(default=None, max_length=254)
    language: Literal["ru", "uz"] = "ru"

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if not value or not value.strip():
            return None
        from .password_recovery import EmailRequest

        return EmailRequest.normalize_email(value)


class VerifyVisit(BaseModel):
    token: str = Field(min_length=20)


class RatingCreate(FeedbackDetails):
    visit_id: str
    overall: int = Field(ge=1, le=10)
    food: int = Field(ge=1, le=10)
    service: int = Field(ge=1, le=10)
    cleanliness: int = Field(ge=1, le=10)
    value: int = Field(ge=1, le=10)
    photo_data_url: str | None = Field(default=None, max_length=8_000_000)


class NearbySearch(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_km: float = Field(default=15, gt=0)
    limit: int = Field(default=200, ge=1, le=200)


class ManualPlaceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    category: str = Field(min_length=2, max_length=40, pattern=r"^[A-Z][A-Z0-9_]*$")
    description: str = Field(min_length=10, max_length=500)
    address: str = Field(min_length=3, max_length=255)
    city: str = Field(min_length=2, max_length=80)
    country_code: str = Field(min_length=2, max_length=2)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    google_place_id: str | None = Field(default=None, min_length=3, max_length=255)


class CommunityRatingCreate(FeedbackDetails):
    object_key: str = Field(min_length=8, max_length=320)
    source: Literal["RELYQO_PARTNER", "MANUAL"]
    category: str = Field(
        default="OTHER", min_length=2, max_length=40, pattern=r"^[A-Z][A-Z0-9_]*$"
    )
    overall: int = Field(ge=1, le=10)
    quality: int = Field(ge=1, le=10)
    service: int = Field(ge=1, le=10)
    cleanliness: int = Field(ge=1, le=10)
    value: int = Field(ge=1, le=10)
    photo_data_url: str | None = Field(default=None, max_length=8_000_000)


class OwnerTokenCreate(BaseModel):
    transaction_reference: str = Field(min_length=1, max_length=120)


class ReviewDecision(BaseModel):
    decision: Literal["APPROVE", "REJECT"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=200)


class ConsumerRegister(RegistrationEmail):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=10, max_length=200)


class ConsumerFavoriteChange(BaseModel):
    object_key: str = Field(min_length=8, max_length=320)
    source: Literal["RELYQO_PARTNER", "MANUAL"]
    saved: bool = True


class ConsumerAssistantRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class PublicAdvisorCandidate(BaseModel):
    object_key: str = Field(min_length=8, max_length=320)
    distance_km: float | None = Field(default=None, ge=0)


class PublicAdvisorRequest(BaseModel):
    question: str = Field(min_length=3, max_length=300)
    candidates: list[PublicAdvisorCandidate] = Field(min_length=1, max_length=40)


class BusinessOwnerRegister(RegistrationEmail):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=10, max_length=200)
    organization_name: str = Field(min_length=2, max_length=160)
    category: str = Field(min_length=2, max_length=40, pattern=r"^[A-Z][A-Z0-9_]*$")
    description: str = Field(min_length=10, max_length=1000)
    address: str = Field(min_length=3, max_length=255)
    city: str = Field(min_length=2, max_length=80)
    country_code: str = Field(min_length=2, max_length=2)
    phone: str | None = Field(default=None, max_length=40)
    website: str | None = Field(default=None, max_length=255)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class BusinessProfileUpdate(BaseModel):
    organization_name: str = Field(min_length=2, max_length=160)
    category: str = Field(min_length=2, max_length=40, pattern=r"^[A-Z][A-Z0-9_]*$")
    description: str = Field(min_length=10, max_length=1000)
    address: str = Field(min_length=3, max_length=255)
    city: str = Field(min_length=2, max_length=80)
    country_code: str = Field(min_length=2, max_length=2)
    phone: str | None = Field(default=None, max_length=40)
    website: str | None = Field(default=None, max_length=255)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class BusinessApplicationDecision(BaseModel):
    decision: Literal["PUBLISH", "REJECT", "ENABLE_QR"]


class AdvertisementCreate(BaseModel):
    campaign_name: str = Field(min_length=2, max_length=80)
    sponsor_name: str = Field(min_length=2, max_length=120)
    headline: str = Field(min_length=3, max_length=120)
    message: str = Field(min_length=5, max_length=280)
    cta_text: str = Field(default="Подробнее", min_length=2, max_length=32)
    target_url: AnyHttpUrl | None = None
    placement: Literal["TOP_BANNER", "CORNER"]
    page_scope: Literal["ALL", "HOME", "MAP", "RANKINGS", "PROFILE"] = "ALL"
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    max_impressions: int | None = Field(default=None, ge=100, le=100_000_000)
    active: bool = True


class AdvertisementStatus(BaseModel):
    active: bool


class StaffCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=10, max_length=200)


class StaffStatus(BaseModel):
    active: bool


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=8, max_length=200)
    new_password: str = Field(min_length=10, max_length=200)


class StaffPasswordReset(BaseModel):
    new_password: str = Field(min_length=10, max_length=200)


class AccountRecovery(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    recovery_code: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=10, max_length=200)


class RecoveryCodeCreate(BaseModel):
    current_password: str = Field(min_length=8, max_length=200)
