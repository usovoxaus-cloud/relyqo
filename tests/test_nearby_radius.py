"""Real database checks for read-only, 300 metre public discovery."""
import math

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.main import app, haversine_km
from app.models import Branch, ManualPlace, Organization


@pytest.fixture
def catalog(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'nearby.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    def database():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    with factory() as db:
        org = Organization(name='Radius fixture', city='Tashkent')
        db.add(org); db.flush()
        for bearing in (0, 90, 180, 270):
            for meters in (10, 80, 150, 200, 250, 299.99, 300.01, 400):
                # Spherical destination from a synthetic fixture point in Tashkent.
                lat, lng, direction = map(math.radians, (41.3, 69.2, bearing))
                angle = meters / 6371008.8
                dest_lat = math.asin(math.sin(lat)*math.cos(angle)+math.cos(lat)*math.sin(angle)*math.cos(direction))
                dest_lng = lng + math.atan2(math.sin(direction)*math.sin(angle)*math.cos(lat), math.cos(angle)-math.sin(lat)*math.sin(dest_lat))
                coordinates = dict(latitude=math.degrees(dest_lat), longitude=math.degrees(dest_lng))
                key = f'{bearing}-{meters}'
                details = dict(name=key, city='Tashkent', country_code='UZ', address='Synthetic fixture', **coordinates)
                db.add(Branch(organization_id=org.id, **details))
                db.add(ManualPlace(identity_hash=key, category='CAFE', description='Fixture', created_by_hash='test-only', **details))
        db.commit()
    try:
        yield factory
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


@pytest.mark.parametrize('endpoint', ['branches', 'manual-places'])
def test_300m_nearby_includes_edge_in_each_direction_without_creating_places(catalog, endpoint):
    with catalog() as db:
        before = [db.scalar(select(func.count()).select_from(model)) for model in (Organization, Branch, ManualPlace)]
    response = TestClient(app).post(f'/v1/public/{endpoint}/nearby', json={
        'latitude':41.3, 'longitude':69.2, 'radius_km':0.3, 'limit':200,
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['radius_km'] == .3 and data['location_stored'] is False
    rows = data['items']
    assert len(rows) == 24  # All six distances in all four directions; more than five.
    field = 'branch' if endpoint == 'branches' else 'name'
    assert {row[field] for row in rows} == {f'{bearing}-{meters}' for bearing in (0,90,180,270) for meters in (10,80,150,200,250,299.99)}
    assert all(haversine_km(41.3,69.2,row['latitude'],row['longitude']) <= .3 for row in rows)
    with catalog() as db:
        assert [db.scalar(select(func.count()).select_from(model)) for model in (Organization, Branch, ManualPlace)] == before


@pytest.mark.parametrize('endpoint', ['branches', 'manual-places'])
def test_exact_300m_is_inclusive_before_rounding(catalog, endpoint):
    # At the equator these coordinates yield exactly 0.3 with the production metric.
    boundary = math.degrees(.3 / 6371.0088)
    assert haversine_km(0, 0, boundary, 0) == .3
    with catalog() as db:
        org = db.scalar(select(Organization))
        for key, latitude in [('edge', boundary), ('outside', math.degrees(.30001 / 6371.0088))]:
            details = dict(name=key, city='Fixture', country_code='UZ', address='Synthetic point', latitude=latitude, longitude=0)
            db.add(Branch(organization_id=org.id, **details))
            db.add(ManualPlace(identity_hash=key, category='CAFE', description='Fixture', created_by_hash='test-only', **details))
        db.commit()
    response = TestClient(app).post(f'/v1/public/{endpoint}/nearby', json={'latitude':0, 'longitude':0, 'radius_km':.3})
    assert response.status_code == 200, response.text
    rows = response.json()['items']
    assert len(rows) == 1 and rows[0]['distance_km'] == .3
    assert rows[0]['branch' if endpoint == 'branches' else 'name'] == 'edge'
