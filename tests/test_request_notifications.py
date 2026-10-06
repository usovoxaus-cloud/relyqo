from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app import request_notifications as mail
from app.config import settings
from app.models import ConsumerEmail, MailDelivery, RequestEmailJob, RequestEmailPreference, ServiceRequest, ServiceRequestRead, User
from app.backups import create_snapshot, restore_snapshot
from test_service_requests import conversations, create, action


@pytest.fixture
def configured_mail(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://relyqo.example.test")
    monkeypatch.setattr(settings, "resend_api_key", "fixture-no-real-network")
    monkeypatch.setattr(settings, "recovery_email_from", "fixture@example.test")
    sent = []
    monkeypatch.setattr(mail, "send_email", lambda *args, **kwargs: (sent.append((args, kwargs)), "fixture-provider-id")[1])
    return sent


def verify(factory, name):
    with factory() as db:
        user = db.scalar(select(User).where(User.username == "private-" + name))
        db.add(ConsumerEmail(user_id=user.id, email=name + "@example.test"))
        db.commit()
        return user.id


def enable(client):
    response = client.post('/v1/notifications/preferences', json={'enabled': True, 'consent': True})
    assert response.status_code == 200, response.text
    assert response.json()['enabled'] is True


def test_notifications_require_verified_email_and_explicit_consent(conversations, configured_mail):
    c, f, ids, _ = conversations
    assert c('absent').get('/v1/notifications/preferences').status_code == 401
    assert c('staff').get('/v1/notifications/preferences').status_code == 403
    assert c('consumer').get('/v1/notifications/preferences').json()['enabled'] is False
    assert c('consumer').post('/v1/notifications/preferences', json={'enabled': True, 'consent': True}).status_code == 422
    verify(f, 'consumer')
    for body in [{'enabled': True}, {'enabled': 'true', 'consent': True}, {'enabled': True, 'consent': 'true'}]:
        assert c('consumer').post('/v1/notifications/preferences', json=body).status_code == 422
    enable(c('consumer'))
    assert c('other').get('/v1/notifications/preferences').json()['email'] is None
    assert configured_mail == []


def test_event_outbox_is_opt_in_and_sends_no_private_content_or_duplicate(conversations, configured_mail):
    c, f, ids, _ = conversations
    verify(f, 'owner'); verify(f, 'consumer')
    enable(c('owner')); enable(c('consumer'))
    item = create(c('consumer'), ids['rating'])
    mail.drain_notifications(f); mail.drain_notifications(f)
    assert len(configured_mail) == 1
    assert configured_mail[0][0][0] == 'owner@example.test'
    answered = action(c('owner'), item, 'reply', 'PRIVATE RESPONSE').json()
    with f() as db:
        mail.queue_request_notifications(db, db.get(ServiceRequest, item['id']), ids['owner']); db.commit()
    mail.drain_notifications(f)
    assert len(configured_mail) == 2
    args, headers = configured_mail[1]
    assert args[0] == 'consumer@example.test'
    assert '/me/requests?id=' + item['id'] in args[2] and '/notifications?lang=ru' in args[2]
    for secret in ['PRIVATE', 'SECRET', 'Please fix', 'private-consumer', 'Verified fixture']:
        assert secret not in args[2]
    assert headers['idempotency_key'].startswith('request-event/')
    with f() as db:
        assert db.scalar(select(func.count()).select_from(RequestEmailJob)) == 2
        assert db.scalar(select(func.count()).select_from(MailDelivery).where(MailDelivery.status == 'ACCEPTED')) == 2


@pytest.mark.parametrize('change', ['disable', 'address', 'inactive', 'withdraw', 'read', 'scope'])
def test_delivery_rechecks_consent_address_access_and_read_state(conversations, configured_mail, change):
    c, f, ids, _ = conversations
    user_id = verify(f, 'owner'); enable(c('owner'))
    item = create(c('consumer'), ids['rating'])
    if change == 'disable':
        assert c('owner').post('/v1/notifications/preferences', json={'enabled': False}).status_code == 200
    elif change == 'withdraw':
        assert action(c('consumer'), item, 'withdraw').status_code == 200
    else:
        with f() as db:
            if change == 'address': db.get(ConsumerEmail, user_id).email = 'new@example.test'
            if change == 'inactive': db.get(User, user_id).active = False
            if change == 'read': db.add(ServiceRequestRead(user_id=user_id, request_id=item['id'], version=1))
            if change == 'scope': db.get(User, user_id).organization_id = None
            db.commit()
    mail.drain_notifications(f)
    assert configured_mail == []
    with f() as db: assert db.scalar(select(RequestEmailJob)).status == 'CANCELLED'


def test_retry_keeps_key_and_payload_and_survives_restart(conversations, configured_mail, monkeypatch):
    c, f, ids, _ = conversations
    user_id = verify(f, 'owner'); enable(c('owner')); create(c('consumer'), ids['rating'])
    attempts = []
    def transient(*args, **kwargs):
        attempts.append((args, kwargs)); raise URLError('fixture network timeout')
    monkeypatch.setattr(mail, 'send_email', transient)
    mail.drain_notifications(f)
    with f() as db:
        job = db.scalar(select(RequestEmailJob)); assert job.status == 'PENDING' and job.attempts == 1
        job.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
        db.get(User, user_id).language = 'uz'; db.commit()
    monkeypatch.setattr(mail, 'send_email', lambda *args, **kwargs: (attempts.append((args, kwargs)), 'accepted')[1])
    mail.drain_notifications(f)
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    with f() as db: assert db.scalar(select(RequestEmailJob)).status == 'ACCEPTED'


def test_permanent_failure_and_expired_job_are_not_retried(conversations, configured_mail, monkeypatch):
    c, f, ids, _ = conversations
    verify(f, 'owner'); enable(c('owner')); create(c('consumer'), ids['rating'])
    attempts = []
    def forbidden(*args, **kwargs):
        attempts.append(1); raise HTTPError('https://api.resend.com/emails', 403, 'fixture', None, None)
    monkeypatch.setattr(mail, 'send_email', forbidden)
    mail.drain_notifications(f); mail.drain_notifications(f)
    assert len(attempts) == 1
    with f() as db:
        job = db.scalar(select(RequestEmailJob)); assert job.status == 'FAILED'
        job.status = 'PENDING'; job.first_attempt_at = datetime.utcnow() - timedelta(hours=23)
        job.next_attempt_at = datetime.utcnow() - timedelta(seconds=1); db.commit()
    mail.drain_notifications(f); assert len(attempts) == 1


def test_queued_during_downtime_and_abandoned_lease_are_recoverable(conversations, configured_mail):
    c, f, ids, _ = conversations
    verify(f, 'owner'); enable(c('owner')); create(c('consumer'), ids['rating'])
    with f() as db:
        job = db.scalar(select(RequestEmailJob)); job.created_at = datetime.utcnow() - timedelta(days=3)
        job.status = 'PROCESSING'; job.next_attempt_at = datetime.utcnow() + timedelta(minutes=1); db.commit()
    mail.drain_notifications(f); assert configured_mail == []
    with f() as db:
        job = db.scalar(select(RequestEmailJob)); job.next_attempt_at = datetime.utcnow() - timedelta(seconds=1); db.commit()
    mail.drain_notifications(f); mail.drain_notifications(f)
    assert len(configured_mail) == 1
    with f() as db: assert db.scalar(select(RequestEmailJob)).status == 'ACCEPTED'


def test_email_preferences_and_queue_survive_encrypted_backup(conversations, configured_mail, tmp_path):
    c, f, ids, engine = conversations
    user_id = verify(f, 'owner'); enable(c('owner')); create(c('consumer'), ids['rating'])
    raw = create_snapshot(engine, 'fixture-backup-passphrase')
    target = create_engine('sqlite:///' + str(tmp_path / 'restore-mail.db'))
    restore_snapshot(target, raw, 'fixture-backup-passphrase')
    with Session(target) as db:
        assert db.get(RequestEmailPreference, user_id).enabled is True
        assert db.scalar(select(RequestEmailJob)).status == 'PENDING'
    target.dispose()
