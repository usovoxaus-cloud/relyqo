"""Behavioral checks for launch safety, independent of seeded demo data."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.main import app
from app.models import (AuthSession, Branch, CommunityRating, ManualPlace, ModerationCase,
                        Organization, Rating, RatingCooldown, User, Visit, VisitToken)
from app.security import create_token, token_hash
from app.search_text import search_matches


@pytest.fixture
def fixture(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'launch.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    def database():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    with factory() as db:
        org = Organization(name="Fregat sinov", city="Tashkent")
        db.add(org); db.flush()
        branch = Branch(organization_id=org.id, name="Main", city="Tashkent", country_code="UZ", address="Street 1")
        db.add(branch); db.commit()
        ids = (org.id, branch.id)
    yield factory, ids
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def qr(fixture, *, expired=False):
    factory, (_, bid) = fixture
    token, _ = create_token(bid)
    with factory() as db:
        db.add(VisitToken(branch_id=bid, token_hash=token_hash(token), expires_at=datetime.utcnow()+timedelta(hours=-1 if expired else 3)))
        db.commit()
    return token


def claim(client, fixture):
    reply = client.post('/v1/visits/verify-token', json={'token':qr(fixture)})
    assert reply.status_code == 200, reply.text
    return reply.json()['visit_id']


def body(visit_id, score=8):
    return dict(visit_id=visit_id, overall=score, food=score, service=score, cleanliness=score, value=score)


def account(client, fixture, role='CONSUMER'):
    with fixture[0]() as db:
        user = User(username=uuid4().hex, role=role, password_hash='test-only')
        db.add(user); db.flush()
        raw=uuid4().hex
        db.add(AuthSession(user_id=user.id, token_hash=token_hash(raw), expires_at=datetime.utcnow()+timedelta(hours=1)))
        db.commit()
    client.cookies.set('relyqo_session', raw)
    return raw


def test_qr_one_winner_when_redeemed_concurrently(fixture):
    token = qr(fixture)
    def redeem(_):
        with TestClient(app) as client:
            return client.post('/v1/visits/verify-token', json={'token':token}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(redeem, range(2))) == [200,409]
    with fixture[0]() as db:
        assert db.scalar(select(func.count(Visit.id))) == 1


def test_expiry_disabled_branch_and_tampering_do_not_consume_valid_codes(fixture):
    client=TestClient(app)
    assert client.post('/v1/visits/verify-token',json={'token':qr(fixture,expired=True)}).status_code == 410
    token=qr(fixture)
    assert client.post('/v1/visits/verify-token',json={'token':'x'+token[1:]}).status_code == 400
    with fixture[0]() as db:
        db.get(Branch,fixture[1][1]).active=False; db.commit()
    assert client.post('/v1/visits/verify-token',json={'token':token}).status_code == 410
    with fixture[0]() as db:
        assert db.scalar(select(VisitToken).where(VisitToken.token_hash==token_hash(token))).used_at is None


def test_visit_is_bound_to_browser_and_rating_has_a_deadline(fixture):
    client=TestClient(app); visit=claim(client,fixture)
    assert TestClient(app).post('/v1/ratings',json=body(visit)).status_code == 403
    with fixture[0]() as db:
        db.get(Visit,visit).verified_at=datetime.utcnow()-timedelta(hours=25); db.commit()
    assert client.post('/v1/ratings',json=body(visit)).status_code == 410
    with fixture[0]() as db:
        assert db.scalar(select(func.count(Rating.id))) == 0


def test_rolling_limit_for_browser_and_account_and_duplicate_visit(fixture):
    client=TestClient(app); session=account(client,fixture)
    visit=claim(client,fixture)
    assert client.post('/v1/ratings',json=body(visit)).status_code == 200
    assert client.post('/v1/ratings',json=body(visit)).status_code == 409
    second=claim(client,fixture)
    assert client.post('/v1/ratings',json=body(second)).status_code == 429
    another=TestClient(app); another.cookies.set('relyqo_session',session)
    assert another.post('/v1/ratings',json=body(claim(another,fixture))).status_code == 429
    with fixture[0]() as db:
        assert db.scalar(select(func.count(Rating.id))) == 1
        for limit in db.scalars(select(RatingCooldown)):
            limit.expires_at=datetime.utcnow()-timedelta(seconds=1)
        db.commit()
    assert client.post('/v1/ratings',json=body(second)).status_code == 200


def test_ordinary_low_rating_stays_out_of_review_but_contradiction_has_reason_and_history(fixture):
    admin=TestClient(app); account(admin,fixture,'RELYQO_ADMIN')
    client=TestClient(app); account(client,fixture)
    ordinary=client.post('/v1/ratings',json=body(claim(client,fixture),2)).json()
    assert ordinary['included_in_rating'] is True
    assert admin.get('/v1/admin/control/cases').json()['items'] == []
    second=TestClient(app); account(second,fixture)
    disputed=body(claim(second,fixture),1); disputed['overall']=10
    rating=second.post('/v1/ratings',json=disputed).json()
    assert rating['included_in_rating'] is False
    cases=admin.get('/v1/admin/control/cases').json()
    assert len(cases['legacy']) == 1
    case=cases['legacy'][0]
    assert case['details']
    answer=admin.post('/v1/admin/control/cases/'+case['id']+'/decision',json={'decision':'APPROVE','note':'Проверена ошибка выбора критериев, оценка сохранена.'})
    assert answer.status_code == 200, answer.text
    with fixture[0]() as db:
        history=db.scalar(select(ModerationCase).where(ModerationCase.rating_id==rating['rating_id']))
        assert history.decided_by and history.decided_at and history.decision_note
        assert db.get(Rating,rating['rating_id']).included


def test_public_card_is_canonical_and_does_not_expose_private_feedback(fixture):
    client=TestClient(app); account(client,fixture)
    payload=body(claim(client,fixture)); payload['comment']='private customer text'
    assert client.post('/v1/ratings',json=payload).status_code==200
    with fixture[0]() as db:
        db.get(Branch,fixture[1][1]).google_place_id='fixture-google-id';db.commit()
    key='relyqo:'+fixture[1][1]
    response=client.get('/v1/public/place',params={'object_key':key,'verified_score':100,'name':'Fake','google_place_id':'wrong-place','google_rating':5})
    data=response.json()
    assert data['name']=='Fregat sinov' and data['relyqo_score']==80
    assert data['verified_rating_count']==data['verified_visit_count']==1
    assert data['verified_last_rating_at'].endswith('Z')
    assert data['google_reference']['google_place_id']=='fixture-google-id'
    assert data['google_reference']['name']=='Fregat sinov'
    assert data['google_reference']['city']=='Tashkent'
    assert 'google_rating' not in data and 'rating' not in data['google_reference']
    assert 'private customer text' not in response.text and 'consumer_user_id' not in response.text
    with fixture[0]() as db:
        db.get(Organization,fixture[1][0]).profile_status='REJECTED';db.commit()
    assert client.get('/v1/public/place',params={'object_key':key}).status_code==404


def test_confidence_sort_never_uses_community_count_to_qualify_verified(fixture):
    factory,(oid,bid)=fixture
    with factory() as db:
        existing=db.get(Organization,oid); existing.rating_count=2;existing.score=100
        large=Organization(name='Large sample',rating_count=120,score=85);db.add(large);db.flush()
        db.add(Branch(organization_id=large.id,name='Branch',country_code='UZ',city='Tashkent'))
        for i in range(20):
            db.add(CommunityRating(object_key='relyqo:'+bid,source='RELYQO_PARTNER',rater_hash=str(i),overall=10,quality=10,service=10,cleanliness=10,value=10,community_score=100))
        db.commit()
    reply=TestClient(app).get('/v1/public/rated-organizations').json()
    assert reply['items'][0]['name']=='Large sample'
    tiny=next(row for row in reply['items'] if row['organization_id']==oid)
    assert tiny['sample_status']=='EARLY' and 'top_rank' not in tiny


def test_manual_place_without_gps_is_searchable_in_both_alphabets(fixture):
    client=TestClient(app)
    data=dict(name='Afsona sinov',category='RESTAURANT',description='Проверка каталога',address='Test street 10',city='Tashkent',country_code='UZ')
    created=client.post('/v1/public/manual-places',json=data)
    assert created.status_code==200,created.text
    item=created.json()['item'];assert item['latitude'] is None and item['longitude'] is None
    for query in ['Афсона','afsona','restoran','ресторан']:
        result=client.get('/v1/public/rated-organizations',params={'q':query,'include_unrated':True}).json()
        assert any(row.get('id')==item['id'] for row in result['items'])
    result=client.post('/v1/public/manual-places/nearby',json={'latitude':41,'longitude':69}).json()
    assert result['items']==[]
    assert client.post('/v1/public/manual-places',json=data).json()['status']=='COMMUNITY_PLACE_EXISTS'
    assert search_matches('ўқув','o‘quv') and search_matches('Фрегат','Fregat')


def test_startup_retries_connection_but_does_not_expose_credentials():
    from contextlib import contextmanager
    from sqlalchemy.exc import OperationalError
    from app.startup import wait_for_database
    class Engine:
        attempts=0
        @contextmanager
        def connect(self):
            self.attempts+=1
            if self.attempts<3:
                raise OperationalError('secret-dsn',None,Exception('private'))
            class Connection:
                def execute(self,statement): pass
            yield Connection()
    engine=Engine(); pauses=[]
    wait_for_database(engine,attempts=3,pause=pauses.append)
    assert engine.attempts==3 and pauses==[5,5]
    with pytest.raises(RuntimeError,match='Database unavailable') as error:
        wait_for_database(Engine(),attempts=1,pause=pauses.append)
    assert 'private' not in str(error.value) and 'secret' not in str(error.value)


@pytest.mark.parametrize('backend',['sqlite','postgres'])
def test_full_journey_survives_a_new_application_process(tmp_path,backend):
    import os
    from pathlib import Path
    import subprocess
    import sys
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    dsn=f"sqlite:///{tmp_path/'restart.db'}"
    if backend=='postgres':
        original=os.environ.get('RELYQO_TEST_PG_DSN')
        if not original: pytest.skip('Requires disposable PostgreSQL CI service')
        url=make_url(original)
        assert url.host in ('localhost','127.0.0.1') and url.database=='relyqo_ci'
        setup_engine=create_engine(url.set(database='postgres'),isolation_level='AUTOCOMMIT')
        with setup_engine.connect() as connection:
            connection.execute(text('CREATE DATABASE relyqo_ci_journey'))
        setup_engine.dispose()
        dsn=url.set(database='relyqo_ci_journey').render_as_string(hide_password=False)
    root=Path(__file__).parents[1]
    environment={**os.environ,'DATABASE_URL':dsn,'PYTHONPATH':str(root),'RENDER':'',
                 'OPENAI_API_KEY':'','RESEND_API_KEY':'','DEMO_MODE':'false'}
    def run(*args,input=None):
        result=subprocess.run([sys.executable,*args],cwd=root,env=environment,input=input,
                              text=True,capture_output=True,timeout=90)
        assert result.returncode==0, result.stderr[-4000:]
        return result.stdout
    run('-m','alembic','upgrade','head')
    state=run('tests/restart_scenario.py','write')
    assert run('tests/restart_scenario.py','read',input=state).strip()=='journey persists after process restart'
    # A repeat migration must preserve ratings and avoid duplicate directory entries.
    run('-m','alembic','upgrade','head')
    check=create_engine(dsn)
    with check.connect() as connection:
        assert connection.scalar(text('SELECT count(*) FROM ratings'))==1
        assert connection.scalar(text('SELECT count(*) FROM manual_places WHERE source_url IS NOT NULL'))==8
    check.dispose()
