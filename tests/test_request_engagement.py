from datetime import datetime, timedelta
import json
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from app.backups import create_snapshot, restore_snapshot
from app.models import (CommunityRating, ManualPlace, Organization, RepresentationClaim, ServiceMessage,
                        ServiceRepresentative, ServiceRequest, ServiceRequestRead, User)
from test_service_requests import conversations, create, action


def claim(c, key, version=None):
    return c.post('/v1/representation/claims',json={'object_key':key,'contact':'office@example.test',
        'evidence':'Manager; confirm using the independently published office number','consent':True,'version':version})


def decision(c, row, action='approve', verified=True):
    return c.post('/v1/representation/claims/'+row['id']+'/decision',json={'version':row['version'],'action':action,
        'verified':verified,'note':'Verified role via official publicly listed office contact'})


def manual_key(factory, ids):
    with factory() as db:return db.get(CommunityRating,ids['community']).object_key


def test_read_receipts_do_not_lose_newer_answers_and_get_is_read_only(conversations):
    c,f,ids,_=conversations;item=create(c('consumer'),ids['rating']);url='/v1/service-requests/'+item['id']
    assert c('consumer').get('/v1/engagement/inbox').json()['unread']==0
    assert c('owner').get('/v1/engagement/inbox').json()['unread']==1
    assert c('owner').get(url).json()['unread'] is True
    assert c('owner').get('/v1/engagement/inbox').json()['unread']==1
    assert c('owner').post(url+'/read',json={'version':1}).status_code==200
    assert c('owner').get('/v1/engagement/inbox').json()['unread']==0
    updated=action(c('owner'),item,'reply','Please check our response').json()
    assert c('consumer').get('/v1/engagement/inbox').json()['unread']==1
    assert c('consumer').post(url+'/read',json={'version':1}).status_code==200
    assert c('consumer').get('/v1/engagement/inbox').json()['unread']==1
    assert c('consumer').post(url+'/read',json={'version':99}).status_code==409
    assert c('other').post(url+'/read',json={'version':2}).status_code==404
    assert c('consumer').post(url+'/read',json={'version':updated['version']}).status_code==200
    assert c('consumer').get('/v1/engagement/inbox').json()['unread']==0
    assert c('consumer').get('/v1/service-requests?filter=UNREAD').json()['items']==[]


def test_read_receipts_are_per_user_even_inside_one_business(conversations):
    c,f,ids,_=conversations;item=create(c('consumer'),ids['rating'])
    with f() as db:
        db.scalar(select(User).where(User.username=='private-owner2')).organization_id=ids['org'];db.commit()
    c('owner').post('/v1/service-requests/'+item['id']+'/read',json={'version':1})
    assert c('owner2').get('/v1/engagement/inbox').json()['unread']==1
    assert c('other').get('/v1/engagement/inbox').json()['unread']==0
    assert c('staff').get('/v1/engagement/inbox').status_code==403
    assert c('consumer').get('/v1/service-requests?view=admin').status_code==403


def test_overdue_uses_latest_consumer_message_and_owner_start_does_not_reset_it(conversations):
    c,f,ids,_=conversations;item=create(c('consumer'),ids['rating'])
    with f() as db:
        row=db.scalar(select(ServiceMessage));row.created_at=datetime.utcnow()-timedelta(hours=50);db.commit()
    started=action(c('owner'),item,'start').json()
    inbox=c('owner').get('/v1/service-requests?filter=OVERDUE').json()
    assert len(inbox['items'])==1 and inbox['items'][0]['waiting_hours']>=50
    assert inbox['summary']['overdue']==1
    assert c('owner').get('/v1/engagement/inbox').json()['overdue']==1
    answered=action(c('owner'),started,'reply','Here is a solution').json()
    assert c('owner').get('/v1/service-requests?filter=OVERDUE').json()['items']==[]
    action(c('consumer'),answered,'reply','One more question')
    assert c('owner').get('/v1/engagement/inbox').json()['overdue']==0
    assert c('owner').get('/v1/service-requests?filter=NEEDS_REPLY').json()['summary']['needs_reply']==1


def test_response_statistics_use_first_reply_and_exclude_withdrawn_denominator(conversations):
    c,f,ids,_=conversations;item=create(c('consumer'),ids['rating']);waiting=create(c('consumer'),ids['community'])
    with f() as db:db.get(ServiceRequest,item['id']).created_at=datetime.utcnow()-timedelta(hours=4);db.commit()
    answer=action(c('owner'),item,'reply','Initial response').json()
    answer=action(c('owner'),answer,'reply','Additional response').json()
    action(c('consumer'),answer,'resolve')
    summary=c('owner').get('/v1/service-requests').json()['summary']
    assert (summary['total'],summary['resolved'],summary['resolution_percent'],summary['response_sample'])==(1,1,100,1)
    assert summary['first_response_hours']==pytest.approx(4,abs=.1)
    assert c('owner2').get('/v1/service-requests').json()['summary']['first_response_hours'] is None
    action(c('consumer'),waiting,'withdraw')
    summary=c('admin').get('/v1/service-requests').json()['summary']
    assert summary['total']==2 and summary['resolution_percent']==100


def test_claim_submission_never_grants_access_or_duplicates_cards(conversations):
    c,f,ids,_=conversations;key=manual_key(f,ids);item=create(c('consumer'),ids['community'])
    result=claim(c('other'),key);assert result.status_code==200,result.text
    row=result.json();assert row['status']=='PENDING'
    assert claim(c('other'),key).json()['id']==row['id']
    assert c('other').get('/v1/service-requests?view=business').status_code==403
    assert decision(c('other'),row).status_code==403
    assert c('consumer').get('/v1/representation/claims').json()['items']==[]
    assert c('admin').get('/v1/engagement/inbox').json()['pending_claims']==1
    with f() as db:
        assert db.scalar(select(func.count()).select_from(RepresentationClaim))==1
        assert db.scalar(select(func.count()).select_from(ServiceRepresentative))==0
        assert db.scalar(select(func.count()).select_from(ManualPlace))==1
        assert db.scalar(select(func.count()).select_from(Organization))==3


def test_verified_representative_can_reply_only_in_business_view_and_keeps_consumer_role(conversations):
    c,f,ids,_=conversations;key=manual_key(f,ids);item=create(c('consumer'),ids['community']);row=claim(c('other'),key).json()
    assert decision(c('admin'),row,verified=False).status_code==422
    approved=decision(c('admin'),row);assert approved.status_code==200,approved.text
    assert c('other').get('/v1/engagement/inbox').json()['unread']==2
    entries=c('other').get('/v1/engagement/inbox').json()['items'];assert any(e['status']=='CLAIM_APPROVED' for e in entries)
    c('other').post('/v1/representation/read',json={'items':[{'id':row['id'],'version':approved.json()['version']}]})
    assert c('other').get('/v1/engagement/inbox').json()['unread']==1
    listing=c('other').get('/v1/service-requests?view=business').json();assert listing['role']=='REPRESENTATIVE'
    assert len(listing['items'])==1 and 'rating_id' not in listing['items'][0]
    visible=c('other').get('/v1/service-requests/'+item['id']+'?view=business').json()
    assert visible['status']=='OPEN' and 'rating_id' not in visible and 'PRIVATE MAP COMMENT' not in json.dumps(visible)
    assert c('other').get('/v1/service-requests/'+item['id']).status_code==404
    response=c('other').post('/v1/service-requests/'+item['id']+'/actions?view=business',json={'version':visible['version'],'action':'reply','message':'A verified representative response'})
    assert response.status_code==200 and response.json()['status']=='ANSWERED'
    assert c('other').post('/v1/service-requests/'+item['id']+'/actions?view=business',json={'version':response.json()['version'],'action':'resolve'}).status_code==409
    with f() as db:
        assert db.scalar(select(User).where(User.username=='private-other')).role=='CONSUMER'
        assert db.scalar(select(func.count()).select_from(Organization))==3
        assert db.get(CommunityRating,ids['community']).community_score==30


def test_approved_representative_cannot_answer_own_rating(conversations):
    c,f,ids,_=conversations;key=manual_key(f,ids);row=claim(c('consumer'),key).json()
    assert decision(c('admin'),row).status_code==200
    item=create(c('consumer'),ids['community']);assert item['status']=='WAITING_ORGANIZATION'
    assert c('consumer').get('/v1/service-requests?view=business').json()['items']==[]
    assert c('consumer').get('/v1/service-requests/'+item['id']+'?view=business').status_code==404
    assert c('consumer').get('/v1/service-requests/'+item['id']).status_code==200


def test_revoke_blocks_access_and_requeues_unanswered_conversation(conversations):
    c,f,ids,_=conversations;key=manual_key(f,ids);item=create(c('consumer'),ids['community']);row=claim(c('other'),key).json()
    approved=decision(c('admin'),row).json();assert decision(c('admin'),row).status_code==409
    visible=c('other').get('/v1/service-requests/'+item['id']+'?view=business').json()
    assert decision(c('admin'),approved,'revoke').status_code==200
    assert c('other').get('/v1/service-requests/'+item['id']+'?view=business').status_code==403
    consumer=c('consumer').get('/v1/service-requests/'+item['id']).json()
    assert consumer['status']=='WAITING_ORGANIZATION' and consumer['version']>visible['version']
    assert c('other').post('/v1/service-requests/'+item['id']+'/actions?view=business',json={'version':visible['version'],'action':'reply','message':'stale representative'}).status_code==403


def test_conflicting_claims_rejection_and_resubmission_require_current_versions(conversations):
    c,f,ids,_=conversations;key=manual_key(f,ids);a=claim(c('other'),key).json();b=claim(c('owner'),key).json()
    assert decision(c('admin'),a).status_code==200
    assert decision(c('admin'),b).status_code==409
    rejected=decision(c('admin'),b,'reject').json();assert rejected['status']=='REJECTED'
    assert claim(c('owner'),key,version=1).status_code==409
    assert claim(c('owner'),key,version=rejected['version']).json()['status']=='PENDING'
    assert c('consumer').post('/v1/representation/read',json={'items':[{'id':a['id'],'version':1}]}).status_code==404
    with f() as db:assert db.scalar(select(func.count()).select_from(ServiceRepresentative))==1


def test_validation_active_applicant_and_private_claim_fields(conversations):
    c,f,ids,_=conversations;key=manual_key(f,ids)
    assert claim(c('other'),'manual:missing').status_code==404
    assert claim(c('staff'),key).status_code==403
    assert c('other').post('/v1/representation/claims',json={'object_key':key,'contact':'office@example.test','evidence':'a valid sufficiently long explanation','consent':'yes'}).status_code==422
    row=claim(c('other'),key).json()
    with f() as db:db.scalar(select(User).where(User.username=='private-other')).active=False;db.commit()
    assert decision(c('admin'),row).status_code==422
    inbox=json.dumps(c('admin').get('/v1/engagement/inbox').json())
    assert 'office@example.test' not in inbox and 'independently' not in inbox


def test_engagement_records_survive_encrypted_backup(conversations,tmp_path):
    c,f,ids,engine=conversations;key=manual_key(f,ids);item=create(c('consumer'),ids['community']);row=claim(c('other'),key).json()
    decision(c('admin'),row)
    archive=create_snapshot(engine,'fixture-only-engagement-passphrase')
    target=create_engine(f"sqlite:///{tmp_path/'engagement-restore.db'}")
    restore_snapshot(target,archive,'fixture-only-engagement-passphrase')
    with Session(target) as db:
        assert db.get(RepresentationClaim,row['id']).status=='APPROVED'
        assert db.get(ServiceRepresentative,key).claim_id==row['id']
        assert db.scalar(select(func.count()).select_from(ServiceRequestRead))==1
    target.dispose()
