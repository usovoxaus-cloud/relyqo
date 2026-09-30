"""Organization-scoped read-only business statistics. Never changes ratings."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .categories import BUILTINS
from .config import settings
from .models import Branch, Organization, Rating, ScoreHistory, ServiceCategory, Visit

# Same dimensions as the consumer form; the persisted food field means quality.
METRIC_LABELS = {'FOOD': ['Общее впечатление',
          'Качество еды / продукта',
          'Обслуживание',
          'Чистота',
          'Цена и ценность'],
 'HOTEL': ['Общее впечатление',
           'Комфорт и состояние номера',
           'Обслуживание',
           'Чистота',
           'Цена и ценность'],
 'BEAUTY': ['Результат',
            'Качество процедуры',
            'Мастер и обслуживание',
            'Гигиена',
            'Цена и ценность'],
 'HEALTH': ['Общее впечатление',
            'Качество помощи',
            'Внимание персонала',
            'Гигиена и безопасность',
            'Цена и прозрачность'],
 'ENTERTAINMENT': ['Впечатление',
                   'Качество программы / развлечения',
                   'Обслуживание',
                   'Состояние места',
                   'Цена и ценность'],
 'RETAIL': ['Общее впечатление',
            'Ассортимент и качество товаров',
            'Обслуживание',
            'Порядок и удобство',
            'Цена и ценность'],
 'AUTO_SERVICE': ['Общее впечатление',
                  'Качество работы',
                  'Сроки и обслуживание',
                  'Аккуратность',
                  'Цена и прозрачность'],
 'PROFESSIONAL_SERVICE': ['Общее впечатление',
                          'Качество результата',
                          'Коммуникация и сервис',
                          'Надёжность и порядок',
                          'Цена и ценность'],
 'EDUCATION': ['Общее впечатление',
               'Качество обучения',
               'Преподаватели и поддержка',
               'Инфраструктура и условия',
               'Стоимость и результат'],
 'OTHER': ['Общее впечатление',
           'Качество результата',
           'Удобство и сервис',
           'Состояние и порядок',
           'Цена и ценность']}


def metric_labels(category: str, db: Session) -> dict:
    group = BUILTINS.get(category, (None, category))[1]
    custom = db.get(ServiceCategory, category) if category not in BUILTINS else None
    if custom:
        group = custom.group_code
    return dict(zip(
        ("overall", "food", "service", "cleanliness", "value"),
        METRIC_LABELS.get(group, METRIC_LABELS["OTHER"]),
    ))


def business_dashboard(org: Organization, db: Session) -> dict:
    branch = db.scalar(select(Branch).where(Branch.organization_id == org.id).limit(1))
    averages = db.execute(
        select(
            func.avg(Rating.overall),
            func.avg(Rating.food),
            func.avg(Rating.service),
            func.avg(Rating.cleanliness),
            func.avg(Rating.value),
        ).where(Rating.organization_id == org.id, Rating.included.is_(True))
    ).one()
    verified_visits = db.scalar(
        select(func.count(Visit.id))
        .join(Branch, Visit.branch_id == Branch.id)
        .where(Branch.organization_id == org.id)
    )
    submitted_ratings = db.scalar(
        select(func.count(Rating.id)).where(Rating.organization_id == org.id)
    )
    pending_review = db.scalar(
        select(func.count(Rating.id)).where(
            Rating.organization_id == org.id,
            Rating.status == "PENDING_REVIEW",
        )
    )
    history = db.scalars(
        select(ScoreHistory)
        .where(ScoreHistory.organization_id == org.id)
        .order_by(ScoreHistory.calculated_at.desc())
        .limit(12)
    ).all()

    def metric(value):
        return round(float(value) * 10, 1) if value is not None else 0.0

    metrics = {
        "overall": metric(averages[0]),
        "food": metric(averages[1]),
        "service": metric(averages[2]),
        "cleanliness": metric(averages[3]),
        "value": metric(averages[4]),
    }
    labels = metric_labels(org.category, db)
    category_labels = {key: labels[key] for key in ("food", "service", "cleanliness", "value")}
    category_metrics = {key: metrics[key] for key in category_labels}
    strongest = max(category_metrics, key=category_metrics.get)
    weakest = min(category_metrics, key=category_metrics.get)
    visit_count = verified_visits or 0
    submitted_count = submitted_ratings or 0
    sample_target = 20

    return {
        "organization": {
            "id": org.id,
            "name": org.name,
            "city": org.city,
            "category": org.category,
            "branch": branch.name if branch else None,
        },
        "relyqo_score": org.score,
        "rating_count": org.rating_count,
        "verified_visits": visit_count,
        "metrics": metrics,
        "metric_labels": labels,
        "pilot": {
            "sample_status": "EARLY" if org.rating_count < sample_target else "READY",
            "sample_target": sample_target,
            "remaining_to_target": max(0, sample_target - org.rating_count),
            "submitted_ratings": submitted_count,
            "completion_rate": (
                round(submitted_count / visit_count * 100, 1) if visit_count else 0.0
            ),
            "incomplete_visits": max(0, visit_count - submitted_count),
            "pending_review": pending_review or 0,
            "strongest_category": {
                "key": strongest,
                "label": category_labels[strongest],
                "score": category_metrics[strongest],
            },
            "weakest_category": {
                "key": weakest,
                "label": category_labels[weakest],
                "score": category_metrics[weakest],
            },
        },
        "history": [
            {"score": item.score, "calculated_at": item.calculated_at.isoformat() + "Z"}
            for item in reversed(history)
        ],
        "permissions": {
            "ratings_create": False,
            "ratings_update": False,
            "ratings_delete": False,
            "score_update": False,
        },
        "ai": {
            "configured": bool(settings.openai_api_key),
            "model": settings.openai_model if settings.openai_api_key else None,
            "affects_score": False,
            "can_change_ratings": False,
            "can_decide_reviews": False,
        },
        "calculation": "deterministic_weighted_ces_v1",
    }
