"""Eight source-attributed Tashkent entries. No ratings, claims of partnership or GPS."""
from datetime import datetime
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

# Addresses checked against the operators' own pages on 2026-09-30.
# Afsona Shevchenko and Caravan omitted because retrieved sources disagree on address.
GROUP = "https://www.abnmbgroup.com/restaurants-boulangerie"
PLACES = [
    ("Afsona Tashkent City", "RESTAURANT", "Ташкент, улица Укчи, 4", GROUP),
    ("Bella Napoli", "RESTAURANT", "Ташкент, улица Шота Руставели, 63", GROUP),
    ("Bon! — Амира Темура", "COFFEE_SHOP", "Ташкент, проспект Амира Темура, 72А", GROUP),
    ("Bon! — Беруни", "COFFEE_SHOP", "Ташкент, проспект Беруни, 12", GROUP),
    ("Bon! — Истикбол", "COFFEE_SHOP", "Ташкент, улица Истикбол, 18", GROUP),
    ("Fretta! — Амира Темура", "COFFEE_SHOP", "Ташкент, проспект Амира Темура, 40", GROUP),
    ("Fretta! — Мирзо Улугбека", "COFFEE_SHOP", "Ташкент, улица Мирзо Улугбека, 62", GROUP),
    ("Novikov Café", "RESTAURANT", "Ташкент, Шайхантахурский район, улица Укчи, 1А", "https://novikov-cafe.uz/"),
]


def upgrade():
    connection = op.get_bind()
    table = sa.Table("manual_places", sa.MetaData(), autoload_with=connection)
    for name, category, address, source in PLACES:
        identity = f"tashkent-directory-20260930:{name}:{address}"
        key = str(uuid5(NAMESPACE_URL, identity))
        existing = connection.execute(sa.select(table.c.id).where(sa.or_(table.c.id == key,
            sa.and_(sa.func.lower(table.c.name) == name.lower(), table.c.address == address)))).first()
        if existing:
            continue
        connection.execute(table.insert().values(id=key, identity_hash=sha256(identity.encode()).hexdigest(),
            name=name, category=category, address=address, city="Tashkent", country_code="UZ",
            description="Ресторан в Ташкенте." if category == "RESTAURANT" else "Кофейня в Ташкенте.",
            latitude=None, longitude=None, google_place_id=None,
            created_by_hash=sha256(b"RELYQO_SOURCE_REVIEW_20260930").hexdigest(),
            source_url=source, source_checked_at=datetime(2026, 9, 30),
            active=True, created_at=datetime(2026, 9, 30)))


def downgrade():
    # Keep catalog rows: real customer feedback may now reference them.
    pass
