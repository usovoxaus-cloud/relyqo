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


class OwnerTokenCreate(BaseModel):
    transaction_reference: str = Field(min_length=1, max_length=120)


class ReviewDecision(BaseModel):
    decision: Literal["APPROVE", "REJECT"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=200)


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
