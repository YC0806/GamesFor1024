import json
import random
import string
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import redis
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods


SESSION_PREFIX = getattr(settings, "MBTISPY_SESSION_PREFIX", "mbtispy:session:")
SESSION_TTL = getattr(settings, "MBTISPY_SESSION_TTL", 2 * 60 * 60)
SESSION_LOCK_PREFIX = getattr(settings, "MBTISPY_SESSION_LOCK_PREFIX", "mbtispy:lock:")
SESSION_LOCK_TIMEOUT = getattr(settings, "MBTISPY_LOCK_TIMEOUT", 5)
SESSION_LOCK_WAIT = getattr(settings, "MBTISPY_LOCK_WAIT", 5)
MBTI_LETTERS = {"I", "E", "S", "N", "T", "F", "P", "J"}

DEEPSEEK_BASE_URL = getattr(settings, "DEEPSEEK_BASE_URL", None)
DEEPSEEK_API_KEY = getattr(settings, "DEEPSEEK_API_KEY", None)


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
    prompt = r'''
    你是游戏主持人题库助手。请根据输入，生成用于辨析 MBTI 的“情景化开放式问题”。
    要求：
    1) 每题围绕一个 MBTI 维度（axis in {EI,SN,TF,JP}），但不要直接出现“E/I/S/N/T/F/J/P”字样。
    2) 问题必须是“情境+任务”的开放式描述，让玩家讲述做法/理由/取舍过程，避免AB二选。
    3) 语言贴近口语，结合行业/场景口吻。
    4) 不得提到“MBTI”“维度”“轴”等词。
    5) 尽量与历史题去重，变化场景、人物、约束。
    6) 返回 JSON 数组，每项包含：
    id（string），title（string），scene（string），ask（string），axis（string）。
    只输出 JSON 数组，不要解释。
    '''

    if DEEPSEEK_BASE_URL and DEEPSEEK_API_KEY:
        try:
            from openai import OpenAI

            client = OpenAI(
                base_url=DEEPSEEK_BASE_URL,
                api_key=DEEPSEEK_API_KEY,
            )
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": '目标MBTI：'+ spy_mbti},
                ],
                stream=False
            )
            answer = response.choices[0].message.content
            return {"success": True, "question": answer}
        except Exception as exc:
            return {
                "success": False,
                "message": f"Failed to reach DeepSeek ({exc}). Please try again later.",
            }
    return {
        "success": False,
        "message": f"Could not find base url or api key of Deepseek.",
    }

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

    if not session_code:
        raise GameStateError("session_code is required.")
    body_code = payload.get("session_code")
    if body_code and body_code != session_code:
        raise GameStateError("session_code in URL and body do not match.")
    if not player_name or not isinstance(player_name, str):
        raise GameStateError("Player name must not be empty.")
    if len(player_name.strip()) == 0:
        raise GameStateError("Player name must not be empty.")
    mbti_value = _normalize_mbti(mbti)
    player_name_clean = player_name.strip()
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
        }
        players.append(player)
        player_record = player
        _save_session(client, session)

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
        if player["role"] == "spy":
            options.append({"id": "all_spies", "name": "All players are spies"})
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
        if session.get("status") != "voting":
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
        all_spies_mode = all(p["role"] == "spy" for p in session["players"])
        results: Dict[str, Any] = {
            "total": [
                {
                    "player_id": pid,
                    "name": players[pid]["name"],
                    "votes": total.get(pid, 0),
                }
                for pid in sorted(players.keys())
            ],
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

            if len(top_candidates) > 1 and "all_spies" in top_candidates:
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
            
        results["winners"] = winners
        results["losers"] = losers
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
    if generated['success']:
        return JsonResponse(
            {
                "success": True,
                "spy_mbti": spy_mbti,
                "question": generated["question"],
            }
        )
    else:
        return JsonResponse(
            {
                "success": False,
                "message": generated["message"],
            }
        )
