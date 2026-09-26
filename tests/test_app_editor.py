import copy
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db import Base, get_db
from app.models import User, AppContent, AuditLog
from app.security import password_hash
from app import app_editor as editor
from app.ai import AIServiceError


@pytest.fixture
def setup(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'editor.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    monkeypatch.setattr(editor.settings, "openai_api_key", "test-not-a-real-key")
    editor._requests.clear()
    with factory() as db:
        db.add_all(
            [
                User(
                    username=name,
                    role=role,
                    password_hash=password_hash("editor-test-password"),
                )
                for name, role in [
                    ("editor-admin", "RELYQO_ADMIN"),
                    ("editor-consumer", "CONSUMER"),
                ]
            ]
        )
        db.commit()
    client = TestClient(app)

    def login(name="editor-admin"):
        r = client.post(
            "/v1/auth/login",
            json={"username": name, "password": "editor-test-password"},
        )
        assert r.status_code == 200, r.text

    yield client, login, factory
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def test_private_controls_and_public_copy_only(setup):
    client, login, _ = setup
    for method, path, body in [
        ("GET", "/v1/admin/app-editor", None),
        (
            "POST",
            "/v1/admin/app-editor/draft",
            {"target": "home", "instruction": "Сделай проще"},
        ),
        (
            "PUT",
            "/v1/admin/app-content",
            {"content": editor.DEFAULT, "expected_version": 0},
        ),
    ]:
        assert client.request(method, path, json=body).status_code in [401, 403]
    login("editor-consumer")
    assert client.get("/v1/admin/app-editor").status_code == 403
    assert (
        client.post(
            "/v1/admin/app-editor/draft",
            json={"target": "home", "instruction": "Сделай проще"},
        ).status_code
        == 403
    )
    assert (
        client.put(
            "/v1/admin/app-content",
            json={"content": editor.DEFAULT, "expected_version": 0},
        ).status_code
        == 403
    )
    public = client.get("/v1/public/app-content")
    assert set(public.json()) == {"content", "version"}
    assert public.headers["cache-control"] == "no-store"


def test_publish_conflict_plain_text_and_rollback(setup):
    client, login, factory = setup
    login()
    content = copy.deepcopy(editor.DEFAULT)
    content["ru"]["title"] = "Найдите нужную услугу"
    saved = client.put(
        "/v1/admin/app-content", json={"content": content, "expected_version": 0}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["previous"] == editor.DEFAULT
    assert client.get("/v1/public/app-content").json()["content"] == content
    assert (
        client.put(
            "/v1/admin/app-content",
            json={"content": editor.DEFAULT, "expected_version": 0},
        ).status_code
        == 409
    )
    bad = copy.deepcopy(content)
    bad["ru"]["title"] = "<script>alert(1)</script>"
    assert (
        client.put(
            "/v1/admin/app-content", json={"content": bad, "expected_version": 1}
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/v1/admin/app-content",
            json={"content": saved.json()["previous"], "expected_version": 1},
        ).status_code
        == 200
    )
    assert client.get("/v1/public/app-content").json()["content"] == editor.DEFAULT
    with factory() as db:
        assert (
            len(
                db.scalars(
                    select(AuditLog).where(AuditLog.action == "APP_CONTENT_UPDATED")
                ).all()
            )
            == 2
        )
        assert db.get(AppContent, "home").updated_by


def test_ai_proposal_never_publishes_and_invalid_provider_output_is_rejected(
    setup, monkeypatch
):
    client, login, factory = setup
    login()
    contexts = []

    def generate(ctx):
        contexts.append(ctx)
        return {
            "title_ru": "Найдите услугу",
            "hint_ru": "Введите запрос",
            "title_uz": "Xizmat toping",
            "hint_uz": "So‘rovni kiriting",
            "summary": "Короче",
        }

    monkeypatch.setattr(editor, "generate_editor_draft", generate)
    r = client.post(
        "/v1/admin/app-editor/draft",
        json={"target": "home", "instruction": "Сделай проще"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["applied"] is False
    assert client.get("/v1/public/app-content").json()["version"] == 0
    assert set(contexts[0]) == {"target", "instruction", "current", "groups"}
    with factory() as db:
        assert db.get(AppContent, "home") is None
    assert (
        client.post(
            "/v1/admin/app-editor/draft",
            json={"target": "home", "instruction": "Сделай проще"},
        ).status_code
        == 429
    )
    editor._requests.clear()
    monkeypatch.setattr(
        editor, "generate_editor_draft", lambda ctx: {"title_ru": "<script>"}
    )
    assert (
        client.post(
            "/v1/admin/app-editor/draft",
            json={"target": "home", "instruction": "Сделай проще"},
        ).status_code
        == 502
    )
    assert client.get("/v1/public/app-content").json()["version"] == 0


def test_category_create_edit_conflict_and_builtin_guard(setup, monkeypatch):
    client, login, _ = setup
    login()
    made = client.post(
        "/v1/admin/service-categories",
        json={"label": "Ремонт велосипедов", "group": "OTHER"},
    )
    assert made.status_code == 201, made.text
    row = made.json()
    body = {
        "label": "Веломастерские",
        "group": "OTHER",
        "expected_label": row["label"],
        "expected_group": row["group"],
    }
    path = "/v1/admin/service-categories/" + row["code"]
    assert client.put(path, json=body).status_code == 200
    assert client.put(path, json=body).status_code == 409
    assert (
        client.put("/v1/admin/service-categories/RESTAURANT", json=body).status_code
        == 404
    )
    assert any(
        r["label"] == "Веломастерские"
        for r in client.get("/v1/public/service-categories").json()["items"]
    )
    login("editor-consumer")
    assert client.put(path, json=body).status_code == 403


def test_ai_failure_does_not_expose_errors_or_mutate(setup, monkeypatch):
    client, login, _ = setup
    login()

    def broken(ctx):
        raise AIServiceError("secret-test-key")

    monkeypatch.setattr(editor, "generate_editor_draft", broken)
    r = client.post(
        "/v1/admin/app-editor/draft",
        json={"target": "home", "instruction": "Сделай проще"},
    )
    assert r.status_code == 502 and "secret-test-key" not in r.text
    assert client.get("/v1/public/app-content").json()["version"] == 0
