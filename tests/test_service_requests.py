"""Opt-in conversations: tenant isolation, transitions, consent, durable audit/backup."""
from datetime import datetime, timedelta
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.main import app
from app.models import (AuditLog, AuthSession, Branch, CommunityRating, ManualPlace,
                        Organization, Rating, ServiceMessage, ServiceRequest, User, Visit)
from app.security import token_hash
from app.backups import create_snapshot, restore_snapshot


@pytest.fixture
def conversations(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'requests.db'}", connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    def database():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    with factory() as db:
        org = Organization(name="Verified fixture", score=81, rating_count=7)
        other = Organization(name="Other fixture")
        unverified = Organization(name="Unverified fixture", profile_status="SELF_REGISTERED")
        db.add_all([org,other,unverified]); db.flush()
        users = {}
        for name,role,org_id in [("consumer","CONSUMER",None),("other","CONSUMER",None),
            ("owner","BUSINESS_OWNER",org.id),("owner2","BUSINESS_OWNER",other.id),
            ("unverified","BUSINESS_OWNER",unverified.id),("staff","BUSINESS_STAFF",org.id),
            ("admin","RELYQO_ADMIN",None)]:
            user=User(username="private-"+name,password_hash="not-a-login",role=role,organization_id=org_id)
            db.add(user);db.flush();users[name]=user
            db.add(AuthSession(user_id=user.id,token_hash=token_hash(name),expires_at=datetime.utcnow()+timedelta(hours=1)))
        branch=Branch(organization_id=org.id,name="Exact branch",address="Fixture street 1")
        wrong=Branch(organization_id=other.id,name="Wrong branch")
        db.add_all([branch,wrong]);db.flush()
        visit=Visit(branch_id=branch.id);db.add(visit);db.flush()
        rating=Rating(visit_id=visit.id,organization_id=org.id,consumer_user_id=users['consumer'].id,
                      overall=4,food=4,service=3,cleanliness=6,value=4,ces=42,trust_weight=1,
                      comment="SECRET ORIGINAL COMMENT",reasons_json='["LONG_WAIT"]')
        place=ManualPlace(identity_hash="fixture",name="Imported fixture",category="OTHER",description="fixture",address="Map street",city="Tashkent",country_code="UZ",created_by_hash="private")
        db.add_all([rating,place]);db.flush()
        community=CommunityRating(object_key="manual:"+place.id,source="MANUAL",rater_hash="private-device",consumer_user_id=users['consumer'].id,
                                  overall=3,quality=3,service=3,cleanliness=3,value=3,community_score=30,comment="PRIVATE MAP COMMENT")
        db.add(community);db.commit()
        ids={"rating":rating.id,"community":community.id,"org":org.id,"branch":branch.id,"wrong":wrong.id,"owner":users['owner'].id}
    clients={}
    def client(name):
        if name not in clients:
            clients[name]=TestClient(app);clients[name].cookies.set('relyqo_session',name)
        return clients[name]
    yield client,factory,ids,engine
    for c in clients.values():c.close()
    app.dependency_overrides.clear();engine.dispose()


def create(c, rating):
    response=c.post('/v1/service-requests',json={"rating_id":rating,"message":"Please fix the service","consent":True})
    assert response.status_code==201,response.text
    return response.json()


def action(c,item,action,message=""):
    return c.post('/v1/service-requests/'+item['id']+'/actions',json={"version":item['version'],"action":action,"message":message})


def test_consent_ownership_and_duplicate_creation(conversations):
    c,f,ids,_=conversations
    body={"rating_id":ids['rating'],"message":"Please help with this situation","consent":False}
    for consent in [False,'true',1]:
        assert c('consumer').post('/v1/service-requests',json={**body,"consent":consent}).status_code==422
    assert c('consumer').post('/v1/service-requests',json={**body,"consent":True,"message":" "*12}).status_code==422
    assert c('other').post('/v1/service-requests',json={**body,"consent":True}).status_code==404
    assert c('staff').post('/v1/service-requests',json={**body,"consent":True}).status_code==403
    assert c('absent').get('/v1/service-requests').status_code==401
    item=create(c('consumer'),ids['rating'])
    retry=c('consumer').post('/v1/service-requests',json={**body,"consent":True})
    assert retry.status_code==200 and retry.json()['id']==item['id']
    assert c('consumer').get('/v1/service-requests/context',params={'rating_id':ids['rating']}).json()['existing_id']==item['id']
    with f() as db:
        assert db.scalar(select(func.count()).select_from(ServiceRequest))==1
        assert db.scalar(select(func.count()).select_from(ServiceMessage))==1
        assert db.get(ServiceRequest,item['id']).consent_version=='2026-10-05'


def test_private_feedback_and_other_tenants_never_exposed(conversations):
    c,f,ids,_=conversations; item=create(c('consumer'),ids['rating']);url='/v1/service-requests/'+item['id']
    for who,code in [('other',404),('owner2',404),('staff',403),('unverified',403)]:
        assert c(who).get(url).status_code==code
        assert action(c(who),item,'reply','Secret attempt').status_code==code
    payload=c('owner').get(url).json()
    raw=json.dumps(payload)
    for secret in ['SECRET','private-','LONG_WAIT','consumer_user_id','rating_id','photo','ces','trust_weight']:
        assert secret not in raw
    assert payload['messages'][0]['body']=='Please fix the service'
    assert c('owner2').get('/v1/service-requests').json()['items']==[]
    with f() as db:
        db.get(Organization,ids['org']).profile_status='SELF_REGISTERED';db.commit()
    assert c('owner').get(url).status_code==403


def test_consumer_alone_confirms_resolution_and_ratings_are_immutable(conversations):
    c,f,ids,_=conversations;item=create(c('consumer'),ids['rating'])
    assert action(c('owner'),item,'resolve').status_code==409
    assert action(c('consumer'),item,'resolve').status_code==409
    assert action(c('admin'),item,'reply','Admin cannot impersonate').status_code==403
    item=action(c('owner'),item,'start').json(); assert item['status']=='IN_PROGRESS'
    item=action(c('owner'),item,'reply','We have corrected the issue').json(); assert item['status']=='ANSWERED'
    item=action(c('consumer'),item,'resolve').json(); assert item['status']=='RESOLVED'
    assert action(c('owner'),item,'reply','Cannot reopen for consumer').status_code==409
    item=action(c('consumer'),item,'reopen','The issue still happens').json();assert item['status']=='IN_PROGRESS'
    item=action(c('owner'),item,'reply','Please try again now').json()
    item=action(c('consumer'),item,'resolve').json();assert item['status']=='RESOLVED'
    with f() as db:
        rating=db.get(Rating,ids['rating']);org=db.get(Organization,ids['org'])
        assert (rating.ces,rating.included,rating.status,rating.comment,rating.reasons_json)==(42,True,'ACCEPTED','SECRET ORIGINAL COMMENT','["LONG_WAIT"]')
        assert (org.score,org.rating_count)==(81,7)
        assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.entity_id==item['id']))==7


def test_stale_version_and_withdrawal_cannot_be_overwritten(conversations):
    c,f,ids,_=conversations;item=create(c('consumer'),ids['rating'])
    answer=action(c('owner'),item,'reply','Here is our answer').json()
    assert action(c('owner'),item,'reply','Duplicate send').status_code==409
    assert action(c('consumer'),item,'withdraw').status_code==409
    withdrawn=action(c('consumer'),answer,'withdraw').json(); assert withdrawn['status']=='WITHDRAWN'
    assert action(c('owner'),answer,'reply','Racing reply').status_code==404
    assert c('owner').get('/v1/service-requests/'+item['id']).status_code==404
    assert c('owner').get('/v1/service-requests').json()['items']==[]
    assert action(c('consumer'),withdrawn,'reply','No further sharing').status_code==409
    with f() as db:
        assert db.scalar(select(func.count()).select_from(ServiceMessage))==2


def test_manual_organization_requires_admin_verification(conversations):
    c,f,ids,_=conversations;item=create(c('consumer'),ids['community']);url='/v1/service-requests/'+item['id']+'/assign'
    assert item['status']=='WAITING_ORGANIZATION'
    assert c('owner').get('/v1/service-requests').json()['items']==[]
    payload={'version':item['version'],'branch_id':ids['branch'],'confirmed':True,'note':'Verified exact name, address and owner'}
    assert c('owner').post(url,json=payload).status_code==403
    assert c('admin').post(url,json={**payload,'confirmed':False}).status_code==422
    assert c('admin').get('/v1/service-requests/branches',params={'q':'Verified'}).json()['items'][0]['id']==ids['branch']
    assigned=c('admin').post(url,json=payload);assert assigned.status_code==200,assigned.text
    assert assigned.json()['status']=='OPEN'
    assert c('admin').post(url,json=payload).status_code==409
    visible=c('owner').get('/v1/service-requests/'+item['id']).json()
    assert 'PRIVATE MAP COMMENT' not in json.dumps(visible) and 'assignment_note' not in visible
    assert len(visible['messages'])==1
    with f() as db:
        assert db.get(ServiceRequest,item['id']).assigned_by is not None


def test_awaiting_verified_branch_cannot_be_reassigned_to_wrong_business(conversations):
    c,f,ids,_=conversations
    with f() as db:
        db.get(User,ids['owner']).active=False;db.commit()
    item=create(c('consumer'),ids['rating']);assert item['status']=='WAITING_ORGANIZATION'
    payload={'version':1,'branch_id':ids['wrong'],'confirmed':True,'note':'Wrong recipient must be blocked'}
    assert c('admin').post('/v1/service-requests/'+item['id']+'/assign',json=payload).status_code==422


def test_message_length_rate_limit_and_pagination(conversations):
    c,f,ids,_=conversations;item=create(c('consumer'),ids['rating'])
    create(c('consumer'),ids['community'])
    page=c('consumer').get('/v1/service-requests?limit=1').json()
    assert page['has_more'] and len(page['items'])==1
    second=c('consumer').get('/v1/service-requests?limit=1&offset=1').json()
    assert not second['has_more'] and second['items'][0]['id']!=page['items'][0]['id']
    assert action(c('owner'),item,'reply',' '*10).status_code==422
    assert action(c('owner'),item,'reply','x'*2001).status_code==422
    for i in range(29):
        reply=action(c('owner'),item,'reply','A valid response '+str(i))
        assert reply.status_code==200,reply.text
        item=reply.json()
    assert action(c('owner'),item,'reply','Exceeds hourly limit').status_code==429


def test_backup_preserves_consent_messages_and_owner_access(conversations,tmp_path):
    c,f,ids,engine=conversations;item=create(c('consumer'),ids['rating'])
    action(c('owner'),item,'reply','A durable organization reply')
    phrase='fixture-only-long-passphrase'
    archive=create_snapshot(engine,phrase)
    target=create_engine(f"sqlite:///{tmp_path/'restore.db'}")
    restore_snapshot(target,archive,phrase)
    with sessionmaker(target)() as db:
        saved=db.get(ServiceRequest,item['id']);assert saved.status=='ANSWERED' and saved.consent_at is not None
        assert saved.organization_id==ids['org']
        assert db.scalar(select(func.count()).select_from(ServiceMessage))==2
    target.dispose()
