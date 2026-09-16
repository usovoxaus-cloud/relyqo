"""Shared built-in and administrator-created service categories."""

import secrets

from fastapi import Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import get_db
from .models import AuditLog, ServiceCategory

BUILTINS = {
    "RESTAURANT": ("Ресторан", "FOOD"),
    "CAFE": ("Кафе", "FOOD"),
    "COFFEE_SHOP": ("Кофейня", "FOOD"),
    "BAKERY": ("Пекарня", "FOOD"),
    "BAR": ("Бар", "FOOD"),
    "FOOD_COURT": ("Фуд-корт", "FOOD"),
    "HOTEL": ("Гостиницы", "HOTEL"),
    "BEAUTY": ("Красота и уход", "BEAUTY"),
    "HEALTH": ("Здоровье", "HEALTH"),
    "ENTERTAINMENT": ("Развлечения", "ENTERTAINMENT"),
    "RETAIL": ("Магазины", "RETAIL"),
    "AUTO_SERVICE": ("Автоуслуги", "AUTO_SERVICE"),
    "PROFESSIONAL_SERVICE": ("Профессиональные услуги", "PROFESSIONAL_SERVICE"),
    "EDUCATION": ("Образование", "EDUCATION"),
    "OTHER": ("Другие услуги", "OTHER"),
}
GROUPS = {
    "FOOD": "Рестораны и кафе",
    **{code: label for code, (label, group) in BUILTINS.items() if code == group},
}


def category_catalog(db):
    items = [
        {"code": code, "label": label, "group": group, "custom": False}
        for code, (label, group) in BUILTINS.items()
    ]
    items.extend(
        {"code": row.code, "label": row.label, "group": row.group_code, "custom": True}
        for row in db.scalars(select(ServiceCategory).order_by(ServiceCategory.label))
    )
    return items


def require_category(db, code, *, allow_food=False):
    if (
        code not in BUILTINS
        and not (allow_food and code == "FOOD")
        and not db.get(ServiceCategory, code)
    ):
        raise HTTPException(
            422, "Неизвестная сфера услуг. Выберите категорию из списка."
        )


class CategoryCreate(BaseModel):
    label: str = Field(min_length=2, max_length=80)
    group: str = "OTHER"

    @field_validator("label")
    @classmethod
    def clean_label(cls, value):
        value = " ".join(value.split())
        if len(value) < 2 or any(char in value for char in "<>"):
            raise ValueError("Введите название категории без HTML")
        if len(value.casefold()) > 80:
            raise ValueError("Сократите название категории")
        return value


def register_category_routes(app, session_user):
    @app.get("/v1/public/service-categories")
    def public_categories(response: Response, db: Session = Depends(get_db)):
        response.headers["Cache-Control"] = "no-store"
        return {"items": category_catalog(db), "groups": GROUPS}

    @app.post("/v1/admin/service-categories", status_code=201)
    def create_category(
        body: CategoryCreate,
        response: Response,
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        session_user(relyqo_session, db, "RELYQO_ADMIN")
        if body.group not in GROUPS:
            raise HTTPException(422, "Выберите группу услуг из списка")
        key = body.label.casefold()
        if any(key == item["label"].casefold() for item in category_catalog(db)):
            raise HTTPException(409, "Категория с таким названием уже существует")
        category = ServiceCategory(
            code="CUSTOM_" + secrets.token_hex(6).upper(),
            label=body.label,
            label_key=key,
            group_code=body.group,
        )
        db.add(category)
        try:
            db.flush()
            db.add(
                AuditLog(
                    actor_type="RELYQO_ADMIN",
                    action="SERVICE_CATEGORY_CREATED",
                    entity_type="SERVICE_CATEGORY",
                    entity_id=category.code,
                )
            )
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Категория уже существует. Обновите список.")
        response.headers["Cache-Control"] = "no-store"
        return {
            "code": category.code,
            "label": category.label,
            "group": category.group_code,
            "custom": True,
        }
