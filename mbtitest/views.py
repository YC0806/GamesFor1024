import json
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional

import redis
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from games_backend.llm_client import call_llm

logger = logging.getLogger(__name__)

DEFAULT_RESULT = {
    "mbti": "INFP",
    "intro": "理想主义者，善于共情，富有创造力。",
}

DIMENSION_CHOICES = {"E/I", "I/E", "S/N", "N/S", "T/F", "F/T", "J/P", "P/J"}

QUESTION_COUNT = getattr(settings, "MBTITEST_QUESTION_COUNT", 8)
SESSION_PREFIX = getattr(settings, "MBTITEST_SESSION_PREFIX", "mbtitest:session:")
SESSION_TTL = getattr(settings, "MBTITEST_SESSION_TTL", 30 * 60)


def _redis_client() -> redis.Redis:
    redis_url = getattr(settings, "REDIS_URL", None)
    if not redis_url:
        raise ImproperlyConfigured("REDIS_URL is not configured in settings.")
    return redis.Redis.from_url(redis_url, decode_responses=True)


def _questions_key(session_id: str) -> str:
    return f"{SESSION_PREFIX}{session_id}"


def _store_questions(
    client: redis.Redis,
    session_id: str,
    questions: List[Dict[str, Any]],
    tags: Optional[List[str]] = None,
) -> None:
    payload: Dict[str, Any] = {"questions": questions, "created_at": int(time.time())}
    if tags:
        payload["tags"] = tags
    client.set(
        _questions_key(session_id),
        json.dumps(payload, ensure_ascii=True),
        ex=SESSION_TTL,
    )


def _load_questions(client: redis.Redis, session_id: str) -> Optional[List[Dict[str, Any]]]:
    raw = client.get(_questions_key(session_id))
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to decode questions payload for %s: %s", session_id, exc)
        return None
    questions = payload.get("questions")
    if not isinstance(questions, list):
        return None
    return questions


def _default_questions() -> List[Dict[str, Any]]:
    """Return the predefined fallback question set."""
    return [
        {
            "dimension": "E/I",
            "question": "在一个陌生的聚会上，你会怎么做？",
            "options": ["主动去和新朋友聊天", "只和熟悉的人待在一起", "静静地感受氛围"],
        },
        {
            "dimension": "E/I",
            "question": "周末时你更喜欢哪种活动？",
            "options": ["参加热闹的社交活动", "独自在家休息或读书", "和一两个亲密朋友小聚"],
        },
        {
            "dimension": "N/S",
            "question": "当你读一本小说时，你更注意？",
            "options": ["故事背后的象征和隐喻", "人物的行为和具体细节", "整体的氛围和感受"],
        },
        {
            "dimension": "N/S",
            "question": "遇到一个新问题时，你更倾向于？",
            "options": ["寻找创新的方法和可能性", "依赖过往经验和事实", "结合直觉和现实同时考虑"],
        },
        {
            "dimension": "F/T",
            "question": "朋友向你倾诉烦恼时，你通常会？",
            "options": ["给予安慰和共情", "提出逻辑性的建议", "耐心倾听但不过多干预"],
        },
        {
            "dimension": "F/T",
            "question": "团队讨论中，你更在意？",
            "options": ["让大家感到被尊重和理解", "找到最合理有效的方案", "平衡情感和效率的关系"],
        },
        {
            "dimension": "J/P",
            "question": "你计划一次旅行时更喜欢？",
            "options": ["提前制定详细行程", "随性走到哪算哪", "大概定个方向但保留灵活性"],
        },
        {
            "dimension": "J/P",
            "question": "面对一项工作任务，你通常会？",
            "options": ["按计划分步骤完成", "随心情决定什么时候做", "先有个大概框架再灵活调整"],
        },
    ]


def _ensure_question_ids(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for index, question in enumerate(questions[:QUESTION_COUNT], start=1):
        options = question.get("options") or []
        if not isinstance(options, list):
            options = []
        cleaned_options = [str(option).strip() for option in options if str(option).strip()]
        enriched.append(
            {
                "qid": index,
                "dimension": (question.get("dimension") or "").strip().upper() or None,
                "question": str(question.get("question", "")).strip(),
                "options": cleaned_options,
            }
        )
    return enriched


def _safe_json_loads(content: str) -> Optional[Dict[str, Any]]:
    """Attempt to parse JSON and fall back to extracting the first JSON object."""
    if not content:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


def _normalise_questions(raw_questions: Any) -> Optional[List[Dict[str, Any]]]:
    """Coerce raw data into the question schema expected by the frontend."""
    if not isinstance(raw_questions, list):
        return None

    normalised: List[Dict[str, Any]] = []
    for item in raw_questions:
        if not isinstance(item, dict):
            continue
        dimension = str(item.get("dimension", "")).strip().upper()
        question_text = str(item.get("question", "")).strip()
        options = item.get("options")
        if dimension and dimension not in DIMENSION_CHOICES:
            dimension = dimension.replace(" ", "")
            if dimension not in DIMENSION_CHOICES:
                dimension = ""
        if not question_text:
            continue
        if not isinstance(options, list):
            options = []
        cleaned_options = []
        for option in options:
            text = str(option).strip()
            if text:
                cleaned_options.append(text)
        normalised.append(
            {
                "dimension": dimension or None,
                "question": question_text,
                "options": cleaned_options,
            }
        )

    return normalised or None


def _parse_request_body(request: HttpRequest) -> Dict[str, Any]:
    if request.content_type and "application/json" in request.content_type:
        try:
            return json.loads(request.body.decode("utf-8")) if request.body else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
    if request.method == "POST":
        return request.POST.dict()
    return {}


def _option_text_from_index(index_value: int, options: List[str]) -> str:
    if not options:
        return ""
    if 0 <= index_value < len(options):
        return options[index_value]
    if 1 <= index_value <= len(options):
        return options[index_value - 1]
    return ""


def _extract_player_tags(request: HttpRequest) -> List[str]:
    """Extract player-related tags from JSON payload."""
    payload = _parse_request_body(request)
    candidate = payload.get("tags")
    raw_values: List[Any] = []
    if isinstance(candidate, (list, tuple, set)):
        raw_values.extend(candidate)
    elif candidate is not None:
        raw_values.append(candidate)

    tags: List[str] = []
    seen: set[str] = set()
    for value in raw_values:
        if value is None:
            continue
        parts: List[str]
        if isinstance(value, str):
            parts = re.split(r"[,，/|\\;\s]+", value)
        else:
            parts = [str(value)]
        for part in parts:
            text = part.strip()
            if not text:
                continue
            lowered = text.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            tags.append(text)
    return tags


def _resolve_answer(raw_answer: Any, question: Optional[Dict[str, Any]] = None) -> str:
    if raw_answer is None:
        return ""
    if isinstance(raw_answer, dict):
        for key in (
            "answer",
            "value",
            "text",
            "selected_option",
            "selected",
            "selectedOption",
            "selectedText",
        ):
            if key in raw_answer:
                resolved = _resolve_answer(raw_answer[key], question)
                if resolved:
                    return resolved
        if "option_index" in raw_answer:
            resolved = _resolve_answer(raw_answer["option_index"], question)
            if resolved:
                return resolved
        return ""
    if isinstance(raw_answer, (list, tuple)):
        parts = [str(item).strip() for item in raw_answer if str(item).strip()]
        return ", ".join(parts)
    if isinstance(raw_answer, str):
        text = raw_answer.strip()
        if not text:
            return ""
        if question and text.isdigit():
            option_text = _option_text_from_index(int(text), question.get("options", []))
            if option_text:
                return option_text
        return text
    if isinstance(raw_answer, (int, float)):
        options = question.get("options", []) if question else []
        option_text = _option_text_from_index(int(raw_answer), options)
        if option_text:
            return option_text
        return str(int(raw_answer))
    return str(raw_answer).strip()


def _build_responses(payload: Dict[str, Any], questions: Optional[List[Dict[str, Any]]] = None) -> Optional[List[Dict[str, Any]]]:
    """Extract question-answer pairs from the incoming payload."""
    if questions:
        question_map: Dict[int, Dict[str, Any]] = {}
        for question in questions:
            try:
                qid = int(question.get("qid"))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            question_map[qid] = question

        resolved: List[Dict[str, Any]] = []
        responses_payload = payload.get("responses")
        if isinstance(responses_payload, list):
            for item in responses_payload:
                if not isinstance(item, dict):
                    continue
                raw_qid = item.get("qid") or item.get("question_id")
                question = None
                if raw_qid is not None:
                    try:
                        question = question_map.get(int(raw_qid))
                    except (TypeError, ValueError):
                        question = None
                if question is None:
                    question_text = str(item.get("question", "")).strip()
                    if question_text:
                        question = next(
                            (candidate for candidate in questions if candidate.get("question") == question_text),
                            None,
                        )
                if question is None:
                    continue
                answer_value = (
                    item.get("answer")
                    or item.get("selected_option")
                    or item.get("selected")
                    or item.get("value")
                    or item.get("text")
                )
                if answer_value is None and "option_index" in item:
                    answer_value = item["option_index"]
                answer_text = _resolve_answer(answer_value, question)
                if not answer_text:
                    continue
                resolved.append(
                    {
                        "qid": question.get("qid"),
                        "dimension": (question.get("dimension") or "").strip().upper() or None,
                        "question": question.get("question"),
                        "answer": answer_text,
                    }
                )
        if not resolved and isinstance(payload.get("answers"), list):
            answers_list = payload["answers"]
            for index, raw_answer in enumerate(answers_list):
                if index >= len(questions):
                    break
                question = questions[index]
                answer_text = _resolve_answer(raw_answer, question)
                if not answer_text:
                    continue
                resolved.append(
                    {
                        "qid": question.get("qid"),
                        "dimension": (question.get("dimension") or "").strip().upper() or None,
                        "question": question.get("question"),
                        "answer": answer_text,
                    }
                )
        if resolved:
            return resolved

    # Fallback to legacy parsing when question metadata is unavailable.
    responses_payload = payload.get("responses")
    if isinstance(responses_payload, list):
        extracted: List[Dict[str, Any]] = []
        for item in responses_payload:
            if not isinstance(item, dict):
                continue
            question_text = str(item.get("question", "")).strip()
            answer_text = str(item.get("answer", "")).strip()
            if not (question_text and answer_text):
                continue
            extracted.append(
                {
                    "dimension": str(item.get("dimension", "")).strip().upper() or None,
                    "question": question_text,
                    "answer": answer_text,
                }
            )
        if extracted:
            return extracted

    questions_payload = payload.get("questions")
    answers_payload = payload.get("answers")
    if (
        isinstance(questions_payload, list)
        and isinstance(answers_payload, list)
        and len(questions_payload) == len(answers_payload)
    ):
        extracted = []
        for question, answer in zip(questions_payload, answers_payload):
            question_text = ""
            dimension = ""
            if isinstance(question, dict):
                question_text = str(question.get("question", "")).strip()
                dimension = str(question.get("dimension", "")).strip().upper() or None
            else:
                question_text = str(question).strip()
            answer_text = str(answer).strip()
            if not (question_text and answer_text):
                continue
            extracted.append(
                {
                    "dimension": dimension,
                    "question": question_text,
                    "answer": answer_text,
                }
            )
        if extracted:
            return extracted

    return None


@csrf_exempt
@require_http_methods(["POST"])
def llm_questions(request: HttpRequest) -> JsonResponse:
    """Generate MBTI questions via LLM, store them in Redis, and return the session."""
    try:
        client = _redis_client()
    except (redis.RedisError, ImproperlyConfigured) as exc:
        logger.exception("Failed to create Redis client: %s", exc)
        return JsonResponse(
            {"success": False, "error": "题目存储服务暂不可用，请稍后再试。"},
            status=503,
        )

    session_id = uuid.uuid4().hex
    player_tags = _extract_player_tags(request)

    tag_instructions = ""
    if player_tags:
        tag_list_str = "、".join(player_tags)
        tag_instructions = (
            f"\n玩家标签：{tag_list_str}。\n"
            "请确保生成的题目场景、语气或兴趣点尽量贴合这些标签所代表的特征。\n"
        )

    prompt = (
        f"请你作为心理学测验设计师，严格生成 {QUESTION_COUNT} 个简短有趣的选择题，\n"
        "用于区分 MBTI 的四个维度：\n"
        "- 2 个问题测试 E/I\n"
        "- 2 个问题测试 N/S\n"
        "- 2 个问题测试 F/T\n"
        "- 2 个问题测试 J/P\n"
        f"{tag_instructions}"
        "要求：\n"
        "1. 每个问题必须提供 3 个选项：\n"
        "   - 一个对应维度的第一个极端\n"
        "   - 一个对应维度的第二个极端\n"
        "   - 一个中性选项\n"
        "2. 选项里不要带括号或维度解释，只保留自然的表达。\n"
        "3. 题目需覆盖不同的日常生活场景，语言简洁。\n"
        "4. 输出格式严格为 JSON 对象：\n"
        "   {\n"
        '     "questions": [\n'
        "       {\n"
        '         "dimension": "E/I",\n'
        '         "question": "...",\n'
        '         "options": ["...", "...", "..."]\n'
        "       }\n"
        "     ]\n"
        "   }\n"
    )

    llm_response = call_llm(
        [{"role": "user", "content": prompt}],
        temperature=0.4,
        response_format={"type": "json_object"},
    )

    error = None
    source = "llm"
    questions: Optional[List[Dict[str, Any]]] = None

    if llm_response.get("success"):
        payload = _safe_json_loads(llm_response.get("content", ""))
        if isinstance(payload, dict):
            questions = _normalise_questions(payload.get("questions"))
        elif isinstance(payload, list):
            questions = _normalise_questions(payload)
    else:
        error = llm_response.get("error")

    if not questions or len(questions) < QUESTION_COUNT:
        if questions:
            questions = questions[:QUESTION_COUNT]
        source = "fallback"
        if not error:
            error = "LLM 未返回足够题目，已使用兜底题库。"
        questions = _default_questions()

    questions = questions[:QUESTION_COUNT]
    questions_with_ids = _ensure_question_ids(questions)

    try:
        _store_questions(client, session_id, questions_with_ids, player_tags)
    except redis.RedisError as exc:
        logger.exception("Failed to store questions for session %s: %s", session_id, exc)
        return JsonResponse(
            {"success": False, "error": "题目暂时无法保存，请稍后再试。"},
            status=500,
        )

    response_payload: Dict[str, Any] = {
        "success": True,
        "session_id": session_id,
        "question_count": len(questions_with_ids),
        "questions": questions_with_ids,
        "source": source,
        "tags": player_tags,
        "expires_in": SESSION_TTL,
    }
    if error:
        response_payload["warning"] = error

    return JsonResponse(response_payload)


@csrf_exempt
@require_http_methods(["POST"])
def evaluate_answers(request: HttpRequest) -> JsonResponse:
    """Combine stored questions with user answers and request MBTI evaluation."""
    payload = _parse_request_body(request)
    session_id = str(payload.get("session_id", "")).strip()
    if not session_id:
        return JsonResponse({"success": False, "error": "缺少 session_id。"}, status=400)

    try:
        client = _redis_client()
    except (redis.RedisError, ImproperlyConfigured) as exc:
        logger.exception("Failed to create Redis client: %s", exc)
        return JsonResponse(
            {"success": False, "error": "评估服务暂不可用，请稍后再试。"},
            status=503,
        )

    try:
        questions = _load_questions(client, session_id)
    except redis.RedisError as exc:
        logger.exception("Failed to load questions for session %s: %s", session_id, exc)
        return JsonResponse({"success": False, "error": "无法读取题目，请稍后再试。"}, status=500)

    if not questions:
        return JsonResponse({"success": False, "error": "session_id 无效或已过期。"}, status=404)

    responses = _build_responses(payload, questions)
    if not responses:
        return JsonResponse({"success": False, "error": "缺少有效的答题数据。"}, status=400)

    question_lookup = {entry.get("qid"): entry for entry in questions}
    summary_lines = []
    for index, response in enumerate(responses, start=1):
        question_info = question_lookup.get(response.get("qid"))
        options_text = ""
        if question_info and question_info.get("options"):
            options_text = " | 选项: " + " / ".join(question_info["options"])
        dimension_label = response.get("dimension") or "未知维度"
        summary_lines.append(
            f"{index}. 维度: {dimension_label} | 题目: {response['question']}{options_text} | 用户回答: {response['answer']}"
        )

    prompt = (
        "根据以下 MBTI 测试题与用户回答，判断用户的 MBTI 类型，并返回 JSON 结果：\n"
        + "\n".join(summary_lines)
        + "\n\n"
        "输出格式：\n"
        "{\n"
        '  \"mbti\": \"XXXX\",\n'
        '  \"intro\": \"一句话简介\"\n'
        "}\n"
        "请只返回 JSON，不要附加其它内容。"
    )

    llm_response = call_llm(
        [{"role": "user", "content": prompt}],
        temperature=0.3,
        response_format={"type": "json_object"},
    )

    result = _safe_json_loads(llm_response.get("content", "")) if llm_response.get("success") else None
    if not isinstance(result, dict):
        result = DEFAULT_RESULT

    mbti_code = result.get("mbti") if isinstance(result, dict) else None
    if not isinstance(mbti_code, str) or len(mbti_code) != 4:
        mbti_code = DEFAULT_RESULT["mbti"]
    result["mbti"] = mbti_code.upper()

    response_payload: Dict[str, Any] = {
        "success": True,
        "result": result,
        "session_id": session_id,
        "responses": responses,
        "questions": questions,
    }
    if not llm_response.get("success"):
        response_payload["warning"] = llm_response.get("error")

    return JsonResponse(response_payload)
