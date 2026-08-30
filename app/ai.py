import json

from .config import settings


class AIUnavailableError(RuntimeError):
    pass


class AIServiceError(RuntimeError):
    pass


AI_INSTRUCTIONS = """
Ты — AI-аналитик RELYQO для ресторана Fregat. Используй только переданные
агрегированные показатели. Отвечай по-русски, кратко и конкретно.

Обязательные правила:
- не рассчитывай и не изменяй RELYQO Score;
- не предлагай удалить, исправить или скрыть оценки;
- не принимай решения Owner Review;
- не делай выводов о конкретных сотрудниках или гостях;
- при выборке менее 20 учтённых оценок явно называй выводы ранним сигналом;
- предложи только безопасные операционные эксперименты, которые можно проверить
  новыми подтверждёнными оценками.

Структура ответа:
1. Краткий вывод.
2. Что уже работает.
3. Что проверить в первую очередь.
4. Три действия на ближайшие 7 дней.
""".strip()


def generate_business_insight(metrics: dict) -> str:
    if not settings.openai_api_key:
        raise AIUnavailableError("OPENAI_API_KEY is not configured")
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.openai_api_key,
            timeout=30.0,
            max_retries=1,
        )
        response = client.responses.create(
            model=settings.openai_model,
            instructions=AI_INSTRUCTIONS,
            input=json.dumps(metrics, ensure_ascii=False, sort_keys=True),
            max_output_tokens=700,
            reasoning={"effort": "low"},
            store=False,
            text={"verbosity": "low"},
        )
    except Exception as exc:
        raise AIServiceError("OpenAI request failed") from exc
    text = (response.output_text or "").strip()
    if not text:
        raise AIServiceError("OpenAI returned an empty response")
    return text
