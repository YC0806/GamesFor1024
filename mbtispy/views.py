import json
import logging
import random
import string
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional
import xml.etree.ElementTree as ET

import redis
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from games_backend.llm_client import call_llm

from .models import PlayerMBTIRecord

logger = logging.getLogger(__name__)

SESSION_PREFIX = getattr(settings, "MBTISPY_SESSION_PREFIX", "mbtispy:session:")
SESSION_TTL = getattr(settings, "MBTISPY_SESSION_TTL", 2 * 60 * 60)
SESSION_LOCK_PREFIX = getattr(settings, "MBTISPY_SESSION_LOCK_PREFIX", "mbtispy:lock:")
SESSION_LOCK_TIMEOUT = getattr(settings, "MBTISPY_LOCK_TIMEOUT", 5)
SESSION_LOCK_WAIT = getattr(settings, "MBTISPY_LOCK_WAIT", 5)
MBTI_LETTERS = {"I", "E", "S", "N", "T", "F", "P", "J"}

class GameStateError(Exception):
    """Raised when the game state is invalid or violates game rules."""


def _redis_client() -> redis.Redis:
    redis_url = getattr(settings, "REDIS_URL", None)
    if not redis_url:
        raise ImproperlyConfigured("REDIS_URL is not configured in settings.")
    return redis.Redis.from_url(redis_url, decode_responses=True)


def _session_key(code: str) -> str:
    return f"{SESSION_PREFIX}{code}"


def _load_session(client: redis.Redis, code: str) -> Optional[Dict[str, Any]]:
    raw = client.get(_session_key(code))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GameStateError(f"Failed to decode session payload: {exc}") from exc


def _save_session(client: redis.Redis, session: Dict[str, Any]) -> None:
    client.set(
        _session_key(session["code"]),
        json.dumps(session, ensure_ascii=True),
        ex=SESSION_TTL,
    )


def _parse_body(request) -> Dict[str, Any]:
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise GameStateError(f"Request body is not valid JSON: {exc}")


def _strict_bool(value: Any) -> bool:
    """Return True only if value is the boolean True; everything else is False."""
    return value is True


def _json_error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"success": False, "error": message}, status=status)


def _json_pending(message: str, extra: Optional[Dict[str, Any]] = None) -> JsonResponse:
    payload = {"success": False, "message": message}
    if extra:
        payload.update(extra)
    return JsonResponse(payload, status=200)


def _normalize_mbti(value: str) -> str:
    if not value:
        raise GameStateError("MBTI must not be empty.")
    candidate = value.strip().upper()
    if len(candidate) != 4 or not all(letter in MBTI_LETTERS for letter in candidate):
        raise GameStateError("MBTI must be a four-letter code such as INFJ.")
    return candidate


def _generate_code(client: redis.Redis, length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(10):
        code = "".join(random.choices(alphabet, k=length))
        if not client.exists(_session_key(code)):
            return code
    raise GameStateError("Failed to create a session. Please try again later.")


def _generate_spy_question(spy_mbti: str) -> Dict[str, str]:
    sys_prompt = r'''
    <example>
    [
        {
            "id": "ENTP_1",
            "title": "头脑风暴会议中的创意火花",
            "scene": "在一次产品创新会议上，团队正讨论如何改进一款老旧的软件，但大家意见分歧，进展缓慢。",
            "ask": "你会如何引导讨论，激发新的想法，并确保团队能快速找到可行的解决方案？",
            "axis": "EI"
        },
        {
            "id": "ENTP_2",
            "title": "面对模糊项目需求的策略",
            "scene": "你接手了一个新项目，客户只给了大致方向，没有具体细节，团队对下一步感到困惑。",
            "ask": "你打算用什么方法快速理清需求，并推动项目向前发展？",
            "axis": "SN"
        },
        {
            "id": "ENTP_3",
            "title": "团队决策中的逻辑与情感平衡",
            "scene": "在团队讨论中，有人提出一个基于个人情感的方案，而另一个基于数据的方案更高效但可能影响士气。",
            "ask": "你会如何权衡这两个方案，并说服团队采纳你的建议？",
            "axis": "TF"
        },
        {
            "id": "ENTP_4",
            "title": "应对突发机会的灵活计划",
            "scene": "你正在执行一个严格时间表的项目，突然出现一个意外机会，可能带来巨大收益但会打乱原计划。",
            "ask": "你如何评估这个机会，并调整你的计划来最大化整体收益？",
            "axis": "JP"
        }
    ]
    </example>
    你是一位心理博弈类游戏主持人，正在主持《MBTI守护大挑战》。
    游戏规则：
    - 本局共有3位玩家，每位玩家都有自己的MBTI类型。
    - 其中一位玩家的MBTI类型被隐藏，是“隐藏者”。
    - 你要根据三位玩家的MBTI，生成4个高区分度的开放式情境问题。
    - 问题必须能引导玩家自然展现各自MBTI的差异，使其他人有机会推理出隐藏者是谁。

    出题要求：
    1. 共生成4个问题，分别聚焦在 MBTI 的四个维度：
    - EI（外向 vs 内向）
    - SN（实感 vs 直觉）
    - TF（理性 vs 情感）
    - JP（计划 vs 随性）
    2. 每个问题都要是「生活化」「有代入感」的情境题。
    3. 问题不能直接提及“MBTI”、“人格”、“类型”或“性格”。
    4. 每个问题用自然中文表达，控制在1~2句话，20个字。
    5. 设计的问题应能让隐藏者在回答时“露出特征”，例如：
    - E/I 维度：在社交、聚会或发言场景下；
    - S/N 维度：在规划、创造或未知任务下；
    - T/F 维度：在团队冲突或情绪决策下；
    - J/P 维度：在突发变化或计划执行下。
    6. 输出时，请使用 JSON 数组格式，每题包含：
    - id（1~4）
    - title（简短主题）
    - scene（描述情境）
    - ask（玩家要回答的问题）
    - axis（维度代码）
'''
    user_prompt = '''
    隐藏者的MBTI类型：{{hidden_mbti}}
    请根据以上三位玩家的MBTI类型与隐藏MBTI，
    生成4个能在回答中暴露{{hidden_mbti}}特征的开放式生活情境问题。
    每个问题应聚焦在不同的MBTI维度（EI、SN、TF、JP）。

    - 若隐藏MBTI为E/I类型 → 优先让第1题区分明显。
    - 若隐藏MBTI为S/N类型 → 在第2题体现抽象思维差异。
    - 若隐藏MBTI为T/F类型 → 在第3题聚焦情绪反应。
    - 若隐藏MBTI为J/P类型 → 在第4题表现计划与即兴反应差异。
    请用中文回答
    '''.format(hidden_mbti=spy_mbti)

    llm_response = call_llm(
        [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )

    if llm_response.get("success"):
        return {"success": True, "question": llm_response.get("content", "")}

    return {
        "success": False,
        "message": llm_response.get("error") or "Language model service is unavailable. Please try again later.",
    }

def _parse_questions(answer: str) -> List[Dict[str, Any]]:
    try:
        questions = json.loads(answer)
        if not isinstance(questions, list):
            raise ValueError("Parsed questions is not a list.")
        for q in questions:
            if not all(key in q for key in ("id", "title", "scene", "ask", "axis")):
                raise ValueError("One or more questions are missing required keys.")
        return questions
    except (json.JSONDecodeError, ValueError) as exc:
        raise GameStateError(f"Failed to parse generated question: {exc}, {answer}")


def _assign_spies(players: List[Dict[str, Any]]) -> str:
    """Return spy_mbti while mutating players' roles based on MBTI distribution."""

    if len(players) != 3:
        raise GameStateError("MBTI Spy Challenge requires exactly three players.")

    mbtis = [p["mbti"] for p in players]
    unique_mbtis = list({mbti for mbti in mbtis})
    if len(unique_mbtis) == 1:
        spy_mbti = unique_mbtis[0]
    elif len(unique_mbtis) == 2:
        # Find singleton MBTI (the one appearing once)
        spy_mbti = None
        for mbti in unique_mbtis:
            if mbtis.count(mbti) == 1:
                spy_mbti = mbti
                break
        if spy_mbti is None:
            raise GameStateError("Unable to determine spy_mbti from the provided MBTI values.")
    else:
        spy_mbti = random.choice(mbtis)

    for player in players:
        player["role"] = "spy" if player["mbti"] == spy_mbti else "detective"
    return spy_mbti


@contextmanager
def _session_lock(client: redis.Redis, code: str):
    lock_name = f"{SESSION_LOCK_PREFIX}{code}"
    lock = client.lock(
        lock_name,
        timeout=SESSION_LOCK_TIMEOUT,
        blocking_timeout=SESSION_LOCK_WAIT,
    )
    try:
        acquired = lock.acquire(blocking=True)
    except redis.RedisError as exc:
        raise GameStateError(f"Failed to acquire session lock: {exc}")
    if not acquired:
        raise GameStateError("System is busy, please try again.")
    try:
        yield
    finally:
        try:
            lock.release()
        except redis.exceptions.LockError:
            pass


def _redis_guard(func):
    def _wrapped(request, *args, **kwargs):
        try:
            client = _redis_client()
        except (redis.RedisError, ImproperlyConfigured) as exc:
            return _json_error(f"Redis is not configured or unavailable: {exc}", status=503)
        try:
            return func(request, client, *args, **kwargs)
        except GameStateError as exc:
            return _json_error(str(exc), status=400)
        except redis.RedisError as exc:
            return _json_error(f"Redis access error: {exc}", status=503)

    return _wrapped


@csrf_exempt
@require_http_methods(["POST"])
@_redis_guard
def create_session(request, client: redis.Redis) -> JsonResponse:
    payload = _parse_body(request)
    expected_players = 3
    if "expected_players" in payload and payload["expected_players"] != 3:
        raise GameStateError("MBTI Spy Challenge always uses exactly 3 players.")

    code = _generate_code(client)
    session = {
        "code": code,
        "expected_players": expected_players,
        "status": "registering",
        "players": [],
        "spy_mbti": None,
        "votes": {},
        "created_ts": time.time(),
        "results": None,
    }
    _save_session(client, session)
    return JsonResponse({"success": True, "session_code": code, "expected_players": expected_players})


@csrf_exempt
@require_http_methods(["POST"])
@_redis_guard
def register_player(request, client: redis.Redis, code: str) -> JsonResponse:
    payload = _parse_body(request)

    session_code = code or payload.get("session_code")
    player_name = payload.get("player_name")
    mbti = payload.get("mbti")
    department_raw = payload.get("department")
    consent_flag = payload.get("save_mbti")

    if not session_code:
        raise GameStateError("session_code is required.")
    body_code = payload.get("session_code")
    if body_code and body_code != session_code:
        raise GameStateError("session_code in URL and body do not match.")
    if not player_name or not isinstance(player_name, str):
        raise GameStateError("Player name must not be empty.")
    if len(player_name.strip()) == 0:
        raise GameStateError("Player name must not be empty.")
    if department_raw is None:
        raise GameStateError("Department is required.")
    if not isinstance(department_raw, str):
        raise GameStateError("Department must be a string.")
    department_clean = department_raw.strip()
    if not department_clean:
        raise GameStateError("Department must not be empty.")
    mbti_value = _normalize_mbti(mbti)
    player_name_clean = player_name.strip()
    store_mbti = _strict_bool(consent_flag)
    player_id = None
    player_record: Dict[str, Any] = {}

    with _session_lock(client, session_code):
        session = _load_session(client, session_code)
        if not session:
            raise GameStateError("Session does not exist. Please verify the session_code.")
        if session.get("status") not in {"registering"}:
            raise GameStateError("Game already started; new players cannot join.")

        players: List[Dict[str, Any]] = session["players"]
        if any(p["name"] == player_name_clean for p in players):
            raise GameStateError("Player name already taken. Choose another nickname.")

        if len(players) >= session["expected_players"]:
            raise GameStateError("Session is full; cannot join.")

        player_id = len(players) + 1
        player = {
            "id": player_id,
            "name": player_name_clean,
            "mbti": mbti_value,
            "role": "unknown",
            "department": department_clean,
            "consent_save_mbti": store_mbti,
        }
        players.append(player)
        player_record = player
        _save_session(client, session)

    if store_mbti:
        try:
            PlayerMBTIRecord.objects.create(
                session_code=session_code,
                player_name=player_name_clean,
                department=department_clean,
                mbti=mbti_value,
                consent=True,
            )
        except DatabaseError as exc:
            logger.warning(
                "Failed to persist MBTI record for %s in session %s: %s",
                player_name_clean,
                session_code,
                exc,
            )

    return JsonResponse(
        {
            "success": True,
            "session_code": session_code,
            "player_id": player_id,
            "player_name": player_record["name"],
            "role": player_record["role"],
            "roles_assigned": bool(session.get("spy_mbti")),
            "spy_mbti": session.get("spy_mbti"),
            "expected_players": session["expected_players"],
            "department": department_clean,
            "consent_save_mbti": store_mbti,
        }
    )


@require_http_methods(["GET"])
@_redis_guard
def list_players(request, client: redis.Redis, code: str) -> JsonResponse:
    session = _load_session(client, code)
    if not session:
        return _json_error("Session does not exist.", status=404)
    players = [
        {
            "id": player["id"],
            "name": player["name"],
            "mbti": player["mbti"],
        }
        for player in session["players"]
    ]
    return JsonResponse(
        {
            "success": True,
            "session_code": code,
            "status": session["status"],
            "players": players,
            "expected_players": session["expected_players"],
        }
    )


@require_http_methods(["GET"])
@_redis_guard
def registration_status(request, client: redis.Redis, code: str) -> JsonResponse:
    with _session_lock(client, code):
        session = _load_session(client, code)
        if not session:
            return _json_error("Session does not exist.", status=404)

        players: List[Dict[str, Any]] = session.get("players", [])
        expected = session.get("expected_players", 0)

        if len(players) < expected:
            return _json_pending(
                "Waiting for all players to register.",
                {
                    "session_code": code,
                    "status": session.get("status"),
                    "registered_players": len(players),
                    "expected_players": expected,
                },
            )

        if len(players) > expected:
            raise GameStateError("Number of registered players exceeds expected count.")
        
        roles_assigned = bool(session.get("spy_mbti"))
        if not roles_assigned:
            spy_mbti = _assign_spies(players)
            session["spy_mbti"] = spy_mbti
            session["status"] = "started"
            session["votes"] = {}
            session["results"] = None
            session["vote_started_at"] = None
        else:
            # Ensure status reflects readiness once roles are assigned.
            if session.get("status") in {"registering", "confirming"}:
                session["status"] = "started"
            spy_mbti = session.get("spy_mbti")
        
        for player in players:
            if player["mbti"] == spy_mbti:
                player["role"] = "spy"
            else:
                player["role"] = "detective"
        _save_session(client, session)

    players_payload = [
        {
            "id": p["id"],
            "name": p["name"],
            "mbti": p["mbti"],
            "role": p.get("role", "unknown"),
        }
        for p in session["players"]
    ]

    return JsonResponse(
        {
            "success": True,
            "session_code": code,
            "status": session["status"],
            "registered_players": len(session["players"]),
            "expected_players": session["expected_players"],
            "spy_mbti": session.get("spy_mbti"),
            "players": players_payload,
        }
    )

@require_http_methods(["GET"])
@_redis_guard
def get_spy_mbti(request, client: redis.Redis, code: str) -> JsonResponse:
    session = _load_session(client, code)
    if not session:
        return _json_error("Session does not exist.", status=404)
    if not session.get("spy_mbti"):
        return _json_pending(
            "spy_mbti has not been determined yet.",
            {"session_code": code, "status": session.get("status")},
        )
    return JsonResponse(
        {
            "success": True,
            "session_code": code,
            "spy_mbti": session["spy_mbti"],
        }
    )

@require_http_methods(["GET"])
@_redis_guard
def get_player_role(request, client: redis.Redis, code: str, player_id: int) -> JsonResponse:
    session = _load_session(client, code)
    if not session:
        return _json_error("Session does not exist.", status=404)
    player = next((p for p in session["players"] if p["id"] == player_id), None)
    if not player:
        return _json_error("Player does not exist.", status=404)
    if session.get("status") == "registering" or not session.get("spy_mbti"):
        return _json_pending(
            "Roles have not been assigned yet.",
            {"session_code": code, "status": session.get("status", "registering")},
        )
    spy_mbti = session.get("spy_mbti")
    payload = {
        "success": True,
        "session_code": code,
        "player_id": player_id,
        "role": player["role"],
        "spy_mbti":spy_mbti
    }
    return JsonResponse(payload)


@csrf_exempt
@require_http_methods(["POST"])
@_redis_guard
def start_vote(request, client: redis.Redis, code: str) -> JsonResponse:
    with _session_lock(client, code):
        session = _load_session(client, code)
        if not session:
            return _json_error("Session does not exist.", status=404)
        if not session.get("spy_mbti"):
            return _json_pending(
                "Roles have not been assigned yet, voting cannot start.",
                {"session_code": code, "status": session.get("status", "registering")},
            )
        if session.get("status") != "started":
            return _json_pending(
                "Voting cannot be started from the current state.",
                {"session_code": code, "status": session.get("status")},
            )

        session["votes"] = {}
        session["results"] = None
        session["status"] = "voting"
        session["vote_started_at"] = time.time()
        _save_session(client, session)

    return JsonResponse(
        {
            "success": True,
            "session_code": code,
            "status": "voting",
        }
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
@_redis_guard
def vote_endpoint(
    request, client: redis.Redis, code: str, player_id: int
) -> JsonResponse:
    session = _load_session(client, code)
    if not session:
        return _json_error("Session does not exist.", status=404)

    if session.get("status") != "voting":
        return _json_pending(
            "Voting has not started yet.",
            {"session_code": code, "status": session.get("status", "registering")},
        )

    if request.method == "GET":
        all_spies_mode = all(p["role"] == "spy" for p in session["players"])
        players = session["players"]
        player = next((p for p in players if p["id"] == player_id), None)
        if not player:
            raise GameStateError("Requested player does not exist.")
        options = [
            {
                "id": candidate["id"],
                "name": candidate["name"],
            }
            for candidate in players
            if candidate["id"] != player["id"]
        ]
        # if player["role"] == "spy":
            # options.append({"id": "都是隐藏者", "name": "场上所有玩家都是隐藏者！"})
        options.append({"id": "都是隐藏者", "name": "场上所有玩家都是隐藏者！"})
        return JsonResponse(
            {
                "success": True,
                "session_code": code,
                "status": session["status"],
                "player": {
                    "id": player["id"],
                    "name": player["name"],
                    "role": player["role"],
                    "options": options,
                },
            }
        )

    payload = _parse_body(request)
    raw_target = payload.get("vote_for")

    if raw_target is None:
        raise GameStateError("vote_for must be provided.")
    if isinstance(raw_target, str) and raw_target.strip().lower() == "all_spies":
        target_id = "all_spies"
    else:
        try:
            target_id = int(raw_target)
        except (TypeError, ValueError):
            raise GameStateError("vote_for must be an integer player id or 'all_spies'.")
    
    players = session["players"]
    if not any(p["id"] == player_id for p in players):
        raise GameStateError("Voting player does not exist.")
    if target_id != "all_spies" and not any(p["id"] == target_id for p in players):
        raise GameStateError("Selected target player does not exist.")
    if player_id == target_id:
        raise GameStateError("Cannot vote for oneself.")

    with _session_lock(client, code):
        session = _load_session(client, code)
        if not session:
            return _json_error("Session does not exist.", status=404)
        if session.get("status") != "voting":
            return _json_pending(
                "Voting has not started yet.",
                {"session_code": code, "status": session.get("status")},
            )

        session.setdefault("votes", {})
        session["votes"][str(player_id)] = target_id
        session["results"] = None

        _save_session(client, session)

    return JsonResponse(
        {
            "success": True,
            "session_code": code,
            "player_id": player_id,
            "vote_for": target_id,
        }
    )


@require_http_methods(["GET"])
@_redis_guard
def get_results(request, client: redis.Redis, code: str) -> JsonResponse:
    with _session_lock(client, code):
        session = _load_session(client, code)
        if not session:
            return _json_error("Session does not exist.", status=404)
        if session.get("status") not in ["voting", "completed"]:
            return _json_pending(
                "Voting has not started yet.",
                {"session_code": code, "status": session.get("status")},
            )
        if len(session.get("votes")) != session.get("expected_players", 0):
            return _json_pending(
                "Not all players have voted yet.",
                {
                    "session_code": code,
                    "status": session.get("status"),
                    "votes_received": len(session.get("votes", {})),
                    "expected_votes": session.get("expected_players", 0),
                },
            )
        
        votes: Dict[str, int] = session.get("votes", {})
        total: Dict[int, int] = {}
        for vote_target in votes.values():
            total[vote_target] = total.get(vote_target, 0) + 1

        players = {p["id"]: p for p in session["players"]}
        players_with_votes = [
            {
                "player_id": pid,
                "name": players[pid]["name"],
                "role": players[pid]["role"],
                "votes": total.get(pid, 0),
            }
            for pid in sorted(players.keys())
        ]
        all_spies_mode = all(p["role"] == "spy" for p in session["players"])
        results: Dict[str, Any] = {
            "winners": None,
            "losers": None,
            "message": None,
        }
        if all_spies_mode:
            winners = [
                p["name"] for p in session["players"]
                if session["votes"].get(str(p["id"])) == "all_spies"
            ]
            losers = [
                p["name"] for p in session["players"]
                if session["votes"].get(str(p["id"])) != "all_spies"
            ]
            results["winners"] = winners
            results["losers"] = losers
        
        else:
            max_votes = max(total.values())
            top_candidates = [pid for pid, count in total.items() if count == max_votes]
            if len(top_candidates) > 1 and "all_spies" not in top_candidates:
                winners = [p["name"] for p in session["players"] if p["role"] == "spy"]
                losers = [p["name"] for p in session["players"] if p["role"] == "detective"]
                message = "Vote tied. Spy team wins."

            elif len(top_candidates) > 1 and "all_spies" in top_candidates:
                winners = []
                losers = [p["name"] for p in session["players"]]
                message = "Vote tied with 'all_spies'. No one wins."

            elif len(top_candidates) == 1:
                target = top_candidates[0]
                if target == "all_spies":
                    return _json_pending(
                        "There is some issue with the votes. Please verify.",
                        {"session_code": code, "status": session.get("status"), "votes": votes},
                    )
                elif players[target]["role"] == "spy":
                    winners = [p["name"] for p in session["players"] if p["role"] == "detective"]
                    losers = [p["name"] for p in session["players"] if p["role"] == "spy"]
                    message = "Spy eliminated. Detective team wins!"
                elif players[target]["role"] == "detective":
                    winners = [p["name"] for p in session["players"] if p["role"] == "spy"]
                    losers = [p["name"] for p in session["players"] if p["role"] == "detective"]
                    message = "Spy survives. Spy team wins!"
                else:
                    return _json_pending(
                        "There is some issue with the votes. Please verify.",
                        {"session_code": code, "status": session.get("status"), "votes": votes},
                    )
            else:
                return _json_pending(
                    "There is some issue with the votes. Please verify.",
                    {"session_code": code, "status": session.get("status"), "votes": votes},
                )
            
        results["winners"] = [player for player in players_with_votes if player["name"] in winners]
        results["losers"] = [player for player in players_with_votes if player["name"] in losers]
        session["status"] = "completed"
        session["message"] = message
        session["results"] = results
        _save_session(client, session)
    return JsonResponse({"success": True, "session_code": code, "results": results})


@csrf_exempt
@require_http_methods(["POST"])
@_redis_guard
def generate_spy_question(request, client: redis.Redis) -> JsonResponse:  # noqa: ARG001
    payload = _parse_body(request)
    spy_mbti_input = payload.get("spy_mbti")
    spy_mbti = _normalize_mbti(spy_mbti_input)
    generated = _generate_spy_question(spy_mbti)
    print(generated)

    if generated['success']:
        try:
            return JsonResponse(
                {
                    "success": True,
                    "spy_mbti": spy_mbti,
                    "question": _parse_questions(generated['question']),
                }
            )        
        except json.JSONDecodeError as exc:
            return _json_error(f"Failed to decode generated question: {exc}, {generated['question']}")
    else:
        return _json_error(f"Failed to generate question:, {generated['message']}")
