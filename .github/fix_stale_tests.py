from pathlib import Path

p = Path("tests/test_api_flow.py")
text = p.read_text(encoding="utf-8")
text = text.replace(
    'assert "[\'EDUCATION\',\'Образование и образовательные учреждения\']" in owner_page.text',
    'assert "[\'EDUCATION\',\'Образование\']" in owner_page.text',
)
text = text.replace(
    'assert "Добавьте свою организацию" in page.text',
    'assert "Управляйте профилем. Не рейтингом." in page.text',
)
p.write_text(text, encoding="utf-8")
