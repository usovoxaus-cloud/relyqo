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


CONSUMER_AI_INSTRUCTIONS = """
Ты — AI-помощник потребителя RELYQO. Отвечай по-русски, ясно и кратко. Помогай
выбирать организации и услуги только по переданным агрегированным данным.

Обязательные правила:
- не рассчитывай и не изменяй Verified RELYQO Score;
- не смешивай Verified RELYQO Score, Community Score и Google Rating;
- явно называй источник каждого показателя;
- не считай рекламу доказательством качества;
- не утверждай, что организация хорошая, если данных мало;
- не запрашивай пароль, точную историю перемещений или другие секретные данные;
- не принимай решения Owner Review и не обещай гарантированный результат услуги;
- если данных недостаточно, честно скажи это и предложи, что проверить.

Сначала дай прямой ответ, затем 2–4 коротких практических рекомендации.
""".strip()


def generate_consumer_assistance(context: dict) -> str:
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
            instructions=CONSUMER_AI_INSTRUCTIONS,
            input=json.dumps(context, ensure_ascii=False, sort_keys=True),
            max_output_tokens=600,
            reasoning={"effort": "low"},
            store=False,
            text={"verbosity": "low"},
        )
    except Exception as exc:
        raise AIServiceError("OpenAI request failed") from exc
    answer = (response.output_text or "").strip()
    if not answer:
        raise AIServiceError("OpenAI returned an empty response")
    return answer
