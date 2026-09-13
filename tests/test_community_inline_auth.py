from fastapi.testclient import TestClient

from app.main import app


def test_community_rating_keeps_scores_on_page_and_authenticates_inline():
    page = TestClient(app).get("/community-rate")

    assert page.status_code == 200
    assert "Community Score" in page.text
    assert "Создать аккаунт и отправить" in page.text
    assert "Войти и отправить" in page.text
    assert "/v1/consumer/register" in page.text
    assert "/v1/auth/login" in page.text
    assert "pendingSubmission" in page.text
    assert "баллы уже сохранены на странице" in page.text
    assert "return_to=" in page.text
