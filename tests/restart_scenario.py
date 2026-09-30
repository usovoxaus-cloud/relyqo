"""Subprocess-only fixture journey. Never runs against the deployed database."""
import json
import sys
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.db import SessionLocal
from app.models import Branch, Organization, User
from app.security import password_hash

PASSWORD='disposable-journey-password-2026'

def login(name):
    client=TestClient(app)
    result=client.post('/v1/auth/login',json={'username':name,'password':PASSWORD})
    assert result.status_code==200, result.text
    return client

if sys.argv[1]=='write':
    with SessionLocal() as db:
        org=Organization(name='Fregat journey fixture',city='Tashkent')
        db.add(org);db.flush()
        branch=Branch(organization_id=org.id,name='Journey branch',address='Test 1',city='Tashkent',country_code='UZ')
        db.add(branch);db.flush()
        db.add_all([User(username='journey-admin',role='RELYQO_ADMIN',password_hash=password_hash(PASSWORD)),
                    User(username='journey-owner',role='BUSINESS_OWNER',organization_id=org.id,password_hash=password_hash(PASSWORD))])
        db.commit(); branch_id=branch.id
    consumer=TestClient(app)
    assert consumer.post('/v1/consumer/register',json={'username':'journey-consumer','password':PASSWORD}).status_code==200
    search=consumer.get('/v1/public/rated-organizations',params={'q':'Фрегат','include_unrated':True}).json()
    assert any(row['branch_id']==branch_id for row in search['items'])
    owner=login('journey-owner')
    issued=owner.post('/v1/owner/visit-token',json={'transaction_reference':'journey-001'})
    assert issued.status_code==200,issued.text
    token=parse_qs(urlparse(issued.json()['visit_url']).query)['token'][0]
    visit=consumer.post('/v1/visits/verify-token',json={'token':token}).json()['visit_id']
    result=consumer.post('/v1/ratings',json=dict(visit_id=visit,overall=8,food=8,service=8,cleanliness=8,value=8,comment='Persistent journey fixture'))
    assert result.status_code==200,result.text
    assert result.json()['saved_to_consumer_history']
    admin=login('journey-admin')
    feedback=admin.get('/v1/admin/control/feedback?source=VERIFIED').json()['items']
    assert any(row['id']==result.json()['rating_id'] for row in feedback)
    print(json.dumps({'rating_id':result.json()['rating_id'],'branch_id':branch_id,'token':token}))
else:
    state=json.loads(sys.stdin.read())
    consumer=login('journey-consumer')
    detail=consumer.get('/v1/consumer/ratings/'+state['rating_id'])
    assert detail.status_code==200 and 'Persistent journey fixture' in detail.text
    card=consumer.get('/v1/public/place',params={'object_key':'relyqo:'+state['branch_id']}).json()
    assert card['relyqo_score']==80 and card['verified_rating_count']==1 and card['verified_visit_count']==1
    assert consumer.post('/v1/visits/verify-token',json={'token':state['token']}).status_code==409
    admin=login('journey-admin')
    assert any(row['id']==state['rating_id'] for row in admin.get('/v1/admin/control/feedback?source=VERIFIED').json()['items'])
    assert admin.get('/v1/admin/control/cases').json()['items']==[]
    # On CI this also exercises real PostgreSQL row locks, not SQLite emulation.
    from concurrent.futures import ThreadPoolExecutor
    issued=login('journey-owner').post('/v1/owner/visit-token',json={'transaction_reference':'journey-concurrent'})
    token=parse_qs(urlparse(issued.json()['visit_url']).query)['token'][0]
    def redeem(_):
        return TestClient(app).post('/v1/visits/verify-token',json={'token':token}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(redeem,range(2)))==[200,409]
    print('journey persists after process restart')
