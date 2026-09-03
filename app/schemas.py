from typing import Literal
from pydantic import BaseModel, Field


class VerifyVisit(BaseModel):
    token: str = Field(min_length=20)


class RatingCreate(BaseModel):
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
    radius_km: float = Field(default=15, gt=0, le=50)
    limit: int = Field(default=200, ge=1, le=200)


class ManualPlaceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    category: Literal[
        "RESTAURANT",
        "CAFE",
        "COFFEE_SHOP",
        "BAKERY",
        "BAR",
        "FOOD_COURT",
        "HOTEL",
        "BEAUTY",
        "HEALTH",
        "ENTERTAINMENT",
        "RETAIL",
        "AUTO_SERVICE",
        "PROFESSIONAL_SERVICE",
        "OTHER",
    ]
    description: str = Field(min_length=10, max_length=500)
    address: str = Field(min_length=3, max_length=255)
    city: str = Field(min_length=2, max_length=80)
    country_code: str = Field(min_length=2, max_length=2)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class CommunityRatingCreate(BaseModel):
    object_key: str = Field(min_length=8, max_length=320)
    source: Literal["RELYQO_PARTNER", "MANUAL"]
    category: Literal[
        "FOOD",
        "RESTAURANT",
        "CAFE",
        "COFFEE_SHOP",
        "BAKERY",
        "BAR",
        "FOOD_COURT",
        "HOTEL",
        "BEAUTY",
        "HEALTH",
        "ENTERTAINMENT",
        "RETAIL",
        "AUTO_SERVICE",
        "PROFESSIONAL_SERVICE",
        "OTHER",
    ] = "OTHER"
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
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=200)


class ConsumerRegister(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=10, max_length=200)


class ConsumerFavoriteChange(BaseModel):
    object_key: str = Field(min_length=8, max_length=320)
    source: Literal["RELYQO_PARTNER", "MANUAL"]
    saved: bool = True


class ConsumerAssistantRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class BusinessOwnerRegister(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=10, max_length=200)
    organization_name: str = Field(min_length=2, max_length=160)
    category: Literal[
        "RESTAURANT", "CAFE", "COFFEE_SHOP", "BAKERY", "BAR", "FOOD_COURT",
        "HOTEL", "BEAUTY", "HEALTH", "ENTERTAINMENT", "RETAIL", "AUTO_SERVICE",
        "PROFESSIONAL_SERVICE", "OTHER",
    ]
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
    category: Literal[
        "RESTAURANT", "CAFE", "COFFEE_SHOP", "BAKERY", "BAR", "FOOD_COURT",
        "HOTEL", "BEAUTY", "HEALTH", "ENTERTAINMENT", "RETAIL", "AUTO_SERVICE",
        "PROFESSIONAL_SERVICE", "OTHER",
    ]
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
