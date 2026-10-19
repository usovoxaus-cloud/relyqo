"""Real login and request lifecycle against a disposable local fixture database."""
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import app
from app.models import CommunityRating, Organization, RequestDraft, ServiceMessage, User
from app.security import password_hash
from tests.test_service_requests import conversations  # noqa: F401


def test_professional_services_pilot_without_gps_uses_real_login_and_private_drafts(conversations):
    _, factory, ids, _ = conversations
    password = 'local-pilot-fixture-password'
    with factory() as db:
        db.get(User, ids['owner']).password_hash = password_hash(password)
        db.get(Organization, ids['org']).category = 'PROFESSIONAL_SERVICE'
        db.commit()

    with TestClient(app) as owner, TestClient(app) as consumer, TestClient(app) as reopened:
        assert owner.get('/v1/business-owner/profile').status_code == 401
        signed_in = owner.post('/v1/auth/login', json={'username': 'private-owner', 'password': password})
        assert signed_in.status_code == 200, signed_in.text
        profile = owner.get('/v1/business-owner/profile').json()
        assert profile['branch_id'] == ids['branch']
        assert profile['profile_status'] == 'VERIFIED_PARTNER'
        assert profile['latitude'] is None and profile['longitude'] is None
        assert consumer.post('/v1/consumer/register', json={'username': 'pilot-consumer', 'password': password}).status_code == 200

        object_key = 'relyqo:' + ids['branch']
        card = consumer.get('/v1/public/place', params={'object_key': object_key}).json()
        assert card['category'] == 'PROFESSIONAL_SERVICE'
        assert card['object_key'] == object_key
        rated = consumer.post('/v1/community-ratings', json={
            'object_key': object_key, 'source': 'RELYQO_PARTNER', 'category': 'PROFESSIONAL_SERVICE',
            'overall': 6, 'quality': 6, 'service': 6, 'cleanliness': 6, 'value': 6,
            'comment': 'Private local fixture feedback',
        })
        assert rated.status_code == 200, rated.text
        rating_id = rated.json()['rating_id']
        draft_url = '/v1/request-drafts/new/' + rating_id
        message = 'Please clarify the delivery date for the local fixture order.'
        assert consumer.post(draft_url, json={'message': message, 'version': 0}).status_code == 200
        assert owner.get('/v1/service-requests?view=business').json()['items'] == []

        assert reopened.post('/v1/auth/login', json={'username': 'pilot-consumer', 'password': password}).status_code == 200
        assert reopened.get(draft_url).json()['draft']['message'] == message
        sent = reopened.post('/v1/service-requests', json={'rating_id': rating_id, 'message': message, 'consent': True})
        assert sent.status_code == 201, sent.text
        item = sent.json()
        assert item['status'] == 'OPEN'
        assert reopened.get(draft_url).status_code == 409
        request_url = '/v1/service-requests/' + item['id']
        inbox = owner.get('/v1/service-requests?view=business').json()['items']
        assert [row['id'] for row in inbox] == [item['id']]
        owner_detail = owner.get(request_url + '?view=business')
        assert 'Private local fixture feedback' not in owner_detail.text
        assert owner_detail.json()['messages'][0]['body'] == message

        reply_url = '/v1/request-drafts/reply/' + item['id']
        answer = 'The local fixture order will be ready tomorrow.'
        assert owner.post(reply_url + '?view=business', json={'message': answer, 'version': 0}).status_code == 200
        assert reopened.get(reply_url).json() == {'draft': None}
        assert answer not in reopened.get(request_url).text
        replied = owner.post(request_url + '/actions?view=business', json={'version': item['version'], 'action': 'reply', 'message': answer})
        assert replied.status_code == 200, replied.text
        item = replied.json()
        assert item['status'] == 'ANSWERED'
        assert owner.get(reply_url + '?view=business').json() == {'draft': None}
        assert owner.post(request_url + '/actions?view=business', json={'version': item['version'], 'action': 'resolve'}).status_code == 409
        assert reopened.get(request_url).json()['messages'][-1]['body'] == answer
        resolved = reopened.post(request_url + '/actions', json={'version': item['version'], 'action': 'resolve'})
        assert resolved.status_code == 200 and resolved.json()['status'] == 'RESOLVED'
        assert owner.get(request_url + '?view=business').json()['status'] == 'RESOLVED'

    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ServiceMessage)) == 2
        assert db.scalar(select(func.count()).select_from(RequestDraft)) == 0
        rating = db.get(CommunityRating, rating_id)
        assert rating.comment == 'Private local fixture feedback' and rating.community_score == 60
        org = db.get(Organization, ids['org'])
        assert (org.score, org.rating_count) == (81, 7)
