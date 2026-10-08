"""Exercise the admin endpoint on both SQLite and real PostgreSQL LIKE semantics."""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.admin_directory import register_admin_directory
from app.db import Base, get_db
from app.models import Organization


@pytest.fixture(params=['sqlite', 'postgres'])
def registry(request, tmp_path):
    admin = None
    if request.param == 'postgres':
        dsn = os.environ.get('RELYQO_TEST_PG_DSN')
        if not dsn:
            pytest.skip('Requires disposable PostgreSQL CI database')
        url = make_url(dsn)
        assert url.host in ('127.0.0.1', 'localhost') and url.database == 'relyqo_ci'
        admin = create_engine(url.set(database='postgres'), isolation_level='AUTOCOMMIT')
        with admin.connect() as connection:
            connection.execute(text('CREATE DATABASE relyqo_ci_directory'))
        engine = create_engine(url.set(database='relyqo_ci_directory'))
    else:
        engine = create_engine(f'sqlite:///{tmp_path / "directory.db"}', connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as db:
        db.add_all([
            Organization(name='Scopus Alpha', city='Tashkent', category='EDUCATION'),
            Organization(name='scopus Beta', city='tashkent', category='EDUCATION'),
            Organization(name='SCOPUS Gamma', city='TASHKENT', category='EDUCATION'),
            Organization(name='100%_School', city='Samarkand', category='EDUCATION'),
            Organization(name='100XXSchool', city='Bukhara', category='EDUCATION'),
        ])
        db.commit()
    app = FastAPI()
    def database():
        with factory() as db:
            yield db
    def authorized(cookie, db, role):
        assert role == 'RELYQO_ADMIN'
    app.dependency_overrides[get_db] = database
    register_admin_directory(app, authorized)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        engine.dispose()
        if admin:
            with admin.connect() as connection:
                connection.execute(text('DROP DATABASE relyqo_ci_directory'))
            admin.dispose()


def test_registry_search_ignores_case_and_keeps_wildcards_literal(registry):
    for query in ['Scopus', 'scopus', 'SCOPUS', '  sCoPuS  ', 'tAsHkEnT']:
        response = registry.get('/v1/admin/organizations', params={'q': query})
        assert response.status_code == 200
        assert response.json()['total'] == 3
        assert {row['name'] for row in response.json()['items']} == {'Scopus Alpha', 'scopus Beta', 'SCOPUS Gamma'}
        assert 'no-store' in response.headers['cache-control']
    for query in ['%', '_', '100%_']:
        result = registry.get('/v1/admin/organizations', params={'q': query}).json()
        assert result['total'] == 1
        assert result['items'][0]['name'] == '100%_School'
    assert registry.get('/v1/admin/organizations', params={'q': '  '}).json()['total'] == 5
    assert registry.get('/v1/admin/organizations', params={'q': 'Scopus', 'offset': 3}).json()['items'] == []
