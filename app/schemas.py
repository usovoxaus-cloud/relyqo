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
