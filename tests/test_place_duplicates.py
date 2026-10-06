from sqlalchemy import func, select
from app.models import CommunityRating, ManualPlace, Organization, Branch
from test_place_polish import client
from test_service_requests import conversations


def test_name_address_formatting_and_slight_gps_change_reuse_existing_card(client):
    data=dict(name='Fixture Cafe',category='CAFE',address='Street 15',city='Tashkent',latitude=41.3,longitude=69.2)
    first=client.post('/v1/public/manual-places',json=data).json()['item']
    for change in [dict(name='FIXTURE CAFE',address='Street, 15'),dict(latitude=41.3001),dict(latitude=None,longitude=None)]:
        response=client.post('/v1/public/manual-places',json={**data,**change})
        assert response.status_code==200,response.text
        assert response.json()['status']=='COMMUNITY_PLACE_EXISTS'
        assert response.json()['item']['id']==first['id']


def test_different_branches_are_not_merged(client):
    data=dict(name='Fixture Cafe',category='CAFE',address='Street 15',city='Tashkent',latitude=41.3,longitude=69.2)
    first=client.post('/v1/public/manual-places',json=data).json()['item']
    for change in [dict(address='Street 16'),dict(latitude=42.3)]:
        created=client.post('/v1/public/manual-places',json={**data,**change}).json()
        assert created['status']=='COMMUNITY_PLACE_CREATED' and created['item']['id']!=first['id']


def test_conflicting_provider_ids_cannot_attach_to_existing_card(client):
    data=dict(name='Fixture Cafe',category='CAFE',address='Street 15',city='Tashkent',google_place_id='fixture-one')
    assert client.post('/v1/public/manual-places',json=data).status_code==200
    response=client.post('/v1/public/manual-places',json={**data,'google_place_id':'fixture-two'})
    assert response.status_code==409
    assert 'Google Maps' in response.json()['detail']


def test_duplicate_review_is_admin_only_read_only_and_exposes_no_private_feedback(conversations):
    c,f,ids,_=conversations
    with f() as db:
        place=db.scalar(select(ManualPlace));org=db.get(Organization,ids['org']);branch=db.get(Branch,ids['branch'])
        org.name=place.name.upper();branch.address=place.address;branch.city=place.city;branch.country_code=place.country_code;db.commit()
    assert c('consumer').get('/v1/admin/duplicate-places').status_code==403
    response=c('admin').get('/v1/admin/duplicate-places')
    assert response.status_code==200 and response.headers['cache-control']=='private, no-store'
    groups=response.json()['groups'];assert len(groups)==1 and groups[0]['same_address'] is True
    assert len(groups[0]['items'])==2
    assert 'PRIVATE' not in response.text and 'private-consumer' not in response.text
    with f() as db:
        assert db.scalar(select(ManualPlace)).active is True
        assert db.scalar(select(func.count()).select_from(CommunityRating))==1
