"""Short manual form, nearby discovery and category-specific feedback."""
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base, get_db
from app.main import app
from app.models import ServiceCategory
from app.schemas import FeedbackDetails


@pytest.fixture
def client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'polish.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add(ServiceCategory(code='CUSTOM_TEST', label='Fixture learning', label_key='fixture learning', group_code='EDUCATION'))
        db.commit()
    def database():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


@pytest.mark.parametrize('category,group,reason', [
    ('UNRECOGNIZED','OTHER','FAST_SERVICE'), ('RESTAURANT','FOOD','TASTY_FOOD'),
    ('CAFE','FOOD','TASTY_FOOD'), ('HOTEL','HOTEL','COMFORTABLE_ROOM'),
    ('BEAUTY','BEAUTY','BEAUTY_GOOD_RESULT'), ('CLINIC','HEALTH','HEALTH_ATTENTION'),
    ('SHOPPING_MALL','RETAIL','RETAIL_SELECTION'), ('CAR_WASH','AUTO_SERVICE','AUTO_QUALITY'),
    ('LEGAL_SERVICE','PROFESSIONAL_SERVICE','PRO_GOOD_RESULT'),
    ('ENTERTAINMENT','ENTERTAINMENT','FUN_PROGRAM'),
    ('EDUCATION','EDUCATION','GOOD_TEACHING'), ('LEARNING_CENTER','EDUCATION','GOOD_TEACHING'),
    ('CUSTOM_TEST','EDUCATION','GOOD_TEACHING'),
])
def test_reasons_follow_category_and_custom_group(client,category,group,reason):
    result = client.get('/v1/public/feedback-reasons',params={'category':category})
    assert result.status_code == 200
    data = result.json()
    assert data['group'] == group
    codes = [row['code'] for row in data['items']]
    assert reason in codes and 'OTHER' in codes
    assert len(codes) == len(set(codes))
    assert all(row['label'] and row['label_uz'] and row['label'] != row['label_uz'] for row in data['items'])
    if group == 'EDUCATION':
        assert 'TASTY_FOOD' not in codes and 'FAST_SERVICE' not in codes
        assert 'HELPFUL_ADMINISTRATION' in codes


def test_historical_and_new_reasons_remain_readable_and_valid(client):
    items = {row['code']:row for row in client.get('/v1/public/feedback-reasons').json()['items']}
    assert items['FAST_SERVICE']['label'] == 'Быстрое обслуживание'
    assert items['GOOD_TEACHING']['label'] == 'Понятное и качественное обучение'
    assert FeedbackDetails(reasons=['GOOD_TEACHING','GOOD_TEACHING','LONG_WAIT']).reasons == ['GOOD_TEACHING','LONG_WAIT']
    with pytest.raises(ValidationError):
        FeedbackDetails(reasons=['UNKNOWN_REASON'])


def test_short_form_needs_no_description_or_country_and_confirmed_point_is_nearby(client):
    place = dict(name='Fixture school',category='EDUCATION',address='Fixture street 15',city='Tashkent',latitude=41.3,longitude=69.2)
    response = client.post('/v1/public/manual-places',json=place)
    assert response.status_code == 200, response.text
    item = response.json()['item']
    assert item['description'] == '' and item['country_code'] == 'UZ'
    nearby = client.post('/v1/public/manual-places/nearby',json={'latitude':41.3,'longitude':69.2,'radius_km':0.3}).json()['items']
    assert any(row['id'] == item['id'] for row in nearby)
    duplicate = client.post('/v1/public/manual-places',json=place).json()
    assert duplicate['status'] == 'COMMUNITY_PLACE_EXISTS' and duplicate['item']['id'] == item['id']
    without_point = {**place,'name':'Fixture without point','latitude':None,'longitude':None,'description':'OK'}
    result = client.post('/v1/public/manual-places',json=without_point)
    assert result.status_code == 200
    assert result.json()['item']['description'] == 'OK'


def test_short_form_still_rejects_invalid_address_and_partial_coordinates(client):
    place = dict(name='Fixture',category='CAFE',address='Test street',city='Tashkent')
    for changes in [{'address':'   '},{'latitude':41.3},{'latitude':91,'longitude':69},{'country_code':'12'}]:
        assert client.post('/v1/public/manual-places',json={**place,**changes}).status_code == 422
