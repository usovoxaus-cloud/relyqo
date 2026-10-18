"""Upgrade both the existing 0031 database and a portable restored database."""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base
from app.models import RequestDraft, User


@pytest.mark.parametrize('restored', [False, True])
def test_draft_upgrade_keeps_existing_data_and_accepts_portable_restore(tmp_path, monkeypatch, restored):
    dsn = 'sqlite:///' + str(tmp_path / 'migration.sqlite')
    engine = create_engine(dsn)
    Base.metadata.create_all(engine)
    if not restored:
        RequestDraft.__table__.drop(engine)
    with Session(engine) as db:
        user = User(username='migration-fixture', role='CONSUMER', password_hash='fixture-only')
        db.add(user)
        db.commit()
        user_id = user.id
    monkeypatch.setattr(settings, 'database_url', dsn)
    cfg = Config(str(Path(__file__).parents[1] / 'alembic.ini'))
    command.stamp(cfg, '0031')
    command.upgrade(cfg, 'head')
    assert 'request_drafts' in inspect(engine).get_table_names()
    with Session(engine) as db:
        assert db.get(User, user_id).username == 'migration-fixture'
        assert db.scalar(text('SELECT version_num FROM alembic_version')) == '0032_request_drafts'
        db.add(RequestDraft(user_id=user_id, kind='new', context_id='fixture-rating', body='Unsent'))
        db.commit()
        assert db.scalar(select(RequestDraft.body)) == 'Unsent'
    engine.dispose()
