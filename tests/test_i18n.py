import ast
from pathlib import Path
import re

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.i18n import register_i18n, translate


def test_error_language_uses_valid_query_cookie_and_header():
    app = FastAPI()
    register_i18n(app, lambda *_: None)

    @app.get('/error')
    def error():
        raise HTTPException(400, 'Выберите область Узбекистана')

    with TestClient(app) as client:
        client.cookies.set('relyqo_language', 'uz')
        result = client.get('/error?lang=invalid')
        assert result.headers['content-language'] == 'uz'
        assert result.json()['detail'] == 'O‘zbekiston hududini tanlang'
        assert client.get('/error?lang=ru').json()['detail'] == 'Выберите область Узбекистана'
        client.cookies.clear()
        assert client.get('/error', headers={'Accept-Language': 'uz-UZ,ru;q=0.8'}).json()['detail'] == 'O‘zbekiston hududini tanlang'


def test_all_literal_http_errors_have_uzbek_copy():
    missing = []
    for path in (Path(__file__).parents[1] / 'app').glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf8'))):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != 'HTTPException':
                continue
            detail = next((kw.value for kw in node.keywords if kw.arg == 'detail'), node.args[1] if len(node.args) > 1 else None)
            if isinstance(detail, ast.Constant) and isinstance(detail.value, str) and re.search('[А-Яа-яЁё]', translate(detail.value, 'uz')):
                missing.append((path.name, node.lineno, detail.value))
    assert not missing


def test_translation_does_not_change_russian_or_non_text_values():
    assert translate('Название организации', 'ru') == 'Название организации'
    assert translate({'name': 'Название организации'}, 'uz') == {'name': 'Название организации'}
    assert translate(300, 'uz') == 300
