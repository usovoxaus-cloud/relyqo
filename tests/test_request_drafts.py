"""Account isolation, explicit persistence, race handling and draft lifecycle."""
import json

from sqlalchemy import create_engine, select

from app.backups import create_snapshot, restore_snapshot
from app.models import RequestDraft, ServiceMessage, User
from tests.test_service_requests import conversations, create, action  # noqa: F401


def path(kind, context):
    return '/v1/request-drafts/' + kind + '/' + context


def test_new_draft_is_private_not_a_message_and_survives_new_session(conversations):
    c, factory, ids, _ = conversations
    url = path('new', ids['rating'])
    assert c('absent').get(url).status_code == 401
    assert c('other').get(url).status_code == 404
    assert c('owner').get(url).status_code == 403
    assert c('admin').get(url).status_code == 403
    saved = c('consumer').post(url, json={'message': 'Private unfinished text', 'version': 0})
    assert saved.status_code == 200, saved.text
    assert saved.json()['draft']['version'] == 1
    assert 'no-store' in saved.headers['cache-control']
    assert c('consumer').get(url).json()['draft']['message'] == 'Private unfinished text'
    with factory() as db:
        assert not list(db.scalars(select(ServiceMessage)))
    # A fresh HTTP client with the same valid session can restore the saved text.
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as another:
        another.cookies.set('relyqo_session', 'consumer')
        assert another.get(url).json() == saved.json()


def test_draft_page_uses_matching_versioned_scripts_without_caching_private_html(conversations):
    import re
    from app.static_assets import assets
    c, _, _, _ = conversations
    for role, page in [('consumer', '/me/requests'), ('owner', '/business/requests'), ('admin', '/admin/requests')]:
        response = c(role).get(page)
        assert response.status_code == 200
        assert 'no-store' in response.headers['cache-control']
        version = re.search(r'/static/service-requests.js\?v=([a-f0-9]{64})', response.text)
        assert version and version[1] == assets.digest('/static/service-requests.js')


def test_saved_draft_update_and_delete_reject_stale_versions(conversations):
    c, _, ids, _ = conversations
    url = path('new', ids['rating'])
    user = c('consumer')
    assert user.post(url, json={'message': 'First', 'version': 0}).status_code == 200
    assert user.post(url, json={'message': 'Overwrite', 'version': 0}).status_code == 409
    assert user.post(url, json={'message': 'Second', 'version': 1}).json()['draft']['version'] == 2
    assert user.post(url, json={'message': 'Lost edit', 'version': 1}).status_code == 409
    assert user.post(url + '/remove', json={'version': 1}).status_code == 409
    assert user.get(url).json()['draft']['message'] == 'Second'
    assert user.post(url + '/remove', json={'version': 2}).json() == {'draft': None}
    assert user.get(url).json() == {'draft': None}


def test_successful_send_removes_matching_draft_but_keeps_newer_other_device_text(conversations):
    c, factory, ids, _ = conversations
    user = c('consumer')
    new = path('new', ids['rating'])
    user.post(new, json={'message': 'Please fix the service', 'version': 0})
    item = create(user, ids['rating'])
    with factory() as db:
        assert db.scalar(select(RequestDraft)) is None
    reply = path('reply', item['id'])
    user.post(reply, json={'message': 'Second device unsent text', 'version': 0})
    item = action(user, item, 'reply', 'First device sends another text').json()
    assert user.get(reply).json()['draft']['message'] == 'Second device unsent text'
    result = action(user, item, 'reply', 'Second device unsent text')
    assert result.status_code == 200
    assert user.get(reply).json() == {'draft': None}


def test_business_draft_is_not_visible_to_consumer_admin_or_another_owner(conversations):
    c, factory, ids, _ = conversations
    item = create(c('consumer'), ids['rating'])
    url = path('reply', item['id'])
    saved = c('owner').post(url + '?view=business', json={'message': 'Unsent business response', 'version': 0})
    assert saved.status_code == 200, saved.text
    assert c('consumer').get(url).json() == {'draft': None}
    assert c('owner2').get(url).status_code == 404
    assert c('admin').get(url).status_code == 403
    assert 'Unsent business response' not in json.dumps(c('consumer').get('/v1/service-requests/'+item['id']).json())
    with factory() as db:
        db.get(User, ids['owner']).active = False
        db.commit()
    assert c('owner').get(url).status_code == 401


def test_newer_unsent_first_message_stays_reachable_after_another_device_sends(conversations):
    c, factory, ids, _ = conversations
    user = c('consumer')
    user.post(path('new', ids['rating']), json={'message': 'Newer private unsent text', 'version': 0})
    item = create(user, ids['rating'])
    reply = path('reply', item['id'])
    assert user.get(reply).json()['draft']['message'] == 'Newer private unsent text'
    assert 'Newer private unsent text' not in json.dumps(c('owner').get('/v1/service-requests/'+item['id']).json())
    assert user.post(reply+'/remove', json={'version': 1}).status_code == 200
    with factory() as db:
        assert db.scalar(select(RequestDraft)) is None


def test_draft_requires_valid_context_and_bounded_text(conversations):
    c, _, ids, _ = conversations
    url = path('new', ids['rating'])
    for message in ['', '   ', 'x' * 2001]:
        assert c('consumer').post(url, json={'message': message, 'version': 0}).status_code == 422
    assert c('consumer').post(path('new', 'not-owned'), json={'message': 'Text', 'version': 0}).status_code == 404
    assert c('consumer').get(path('invalid', ids['rating'])).status_code == 422
    item = create(c('consumer'), ids['rating'])
    assert c('consumer').get(url).status_code == 409
    withdrawn = action(c('consumer'), item, 'withdraw')
    assert withdrawn.status_code == 200
    assert c('consumer').post(path('reply', item['id']), json={'message': 'Not shared', 'version': 0}).status_code == 409


def test_draft_is_in_encrypted_backup_and_restores_with_its_owner(conversations, tmp_path):
    c, _, ids, engine = conversations
    c('consumer').post(path('new', ids['rating']), json={'message': 'Private saved draft', 'version': 0})
    phrase = 'test-backup-phrase-not-a-real-secret'
    snapshot = create_snapshot(engine, phrase)
    assert b'Private saved draft' not in snapshot
    target = create_engine('sqlite:///' + str(tmp_path/'restored.db'))
    try:
        restore_snapshot(target, snapshot, phrase)
        with target.connect() as db:
            assert db.execute(select(RequestDraft.body)).scalar() == 'Private saved draft'
    finally:
        target.dispose()
