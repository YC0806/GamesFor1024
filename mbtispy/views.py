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

        if len(players) == session["expected_players"]:
            session["status"] = "awaiting_confirmation"
        else:
            session["status"] = "registering"

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
                    "status": session.get("status", "registering"),
                    "registered_players": len(players),
                    "expected_players": expected,
                },
            )

        roles_assigned = bool(session.get("spy_mbti"))
        if not roles_assigned:
            spy_mbti = _assign_spies(players)
            session["spy_mbti"] = spy_mbti
            session["status"] = "ready"
            session["votes"] = {}
            session["results"] = None
            session["vote_started_at"] = None
            _save_session(client, session)
        else:
            # Ensure status reflects readiness once roles are assigned.
            if session.get("status") in {"registering", "awaiting_confirmation"}:
                session["status"] = "ready"
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
    roles_assigned_final = bool(session.get("spy_mbti"))

    return JsonResponse(
        {
            "success": True,
            "session_code": code,
            "status": session["status"],
            "registered_players": len(session["players"]),
            "expected_players": session["expected_players"],
            "spy_mbti": session.get("spy_mbti"),
            "roles_assigned": roles_assigned_final,
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
            {"session_code": code, "status": session.get("status", "registering")},
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
        if session.get("status") != "ready":
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
def vote_endpoint(request, client: redis.Redis, code: str) -> JsonResponse:
    session = _load_session(client, code)
    if not session:
        return _json_error("Session does not exist.", status=404)

    if session.get("status") != "voting":
        return _json_pending(
            "Voting has not started yet.",
            {"session_code": code, "status": session.get("status", "registering")},
        )

    if request.method == "GET":
        players = [
            {
                "id": player["id"],
                "name": player["name"],
            }
            for player in session["players"]
        ]
        return JsonResponse(
            {
                "success": True,
                "session_code": code,
                "status": session["status"],
                "players": players,
            }
        )

    payload = _parse_body(request)
    voter_id = payload.get("player_id")
    raw_target = payload.get("vote_for")

    if not isinstance(voter_id, int):
        raise GameStateError("player_id must be an integer.")
    if raw_target is None:
        raise GameStateError("vote_for must be provided.")
    if isinstance(raw_target, str) and raw_target.strip().lower() == "all_spies":
        target_id = "all_spies"
    else:
        try:
            target_id = int(raw_target)
        except (TypeError, ValueError):
            raise GameStateError("vote_for must be an integer player id or 'all_spies'.")

    total_votes = 0
    with _session_lock(client, code):
        session = _load_session(client, code)
        if not session:
            return _json_error("Session does not exist.", status=404)
        if session.get("status") != "voting":
            return _json_pending(
                "Voting has not started yet.",
                {"session_code": code, "status": session.get("status", "registering")},
            )

        players = session["players"]
        if not any(p["id"] == voter_id for p in players):
            raise GameStateError("Voting player does not exist.")
        all_spies_mode = all(p["role"] == "spy" for p in players)
        if target_id == "all_spies" and not all_spies_mode:
            raise GameStateError("The 'all_spies' option is only available when all players are spies.")
        if target_id != "all_spies" and not any(p["id"] == target_id for p in players):
            raise GameStateError("Selected target player does not exist.")

        session.setdefault("votes", {})
        session["votes"][str(voter_id)] = target_id
        session["results"] = None

        _save_session(client, session)
        total_votes = len(session["votes"])

    return JsonResponse(
        {
            "success": True,
            "session_code": code,
            "player_id": voter_id,
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
        if not session.get("spy_mbti"):
            return _json_pending(
                "spy_mbti has not been determined; results are unavailable.",
                {"session_code": code, "status": session.get("status", "registering")},
            )

        votes: Dict[str, int] = session.get("votes", {})
        tally: Dict[int, int] = {}
        for vote_target in votes.values():
            tally[vote_target] = tally.get(vote_target, 0) + 1

        players = {p["id"]: p for p in session["players"]}
        all_spies_mode = all(p["role"] == "spy" for p in session["players"])
        results: Dict[str, Any] = {
            "tally": [
                {
                    "player_id": pid,
                    "name": players[pid]["name"],
                    "votes": tally.get(pid, 0),
                }
                for pid in sorted(players.keys())
            ],
            "total_ballots": len(votes),
            "expected_ballots": session["expected_players"],
            "tie": False,
            "winner": None,
            "eliminated_player": None,
        }

        if not tally:
            results["message"] = "No votes recorded yet."
            session["status"] = "ready"
        else:
            max_votes = max(tally.values())
            top_candidates = [pid for pid, count in tally.items() if count == max_votes]
            if all_spies_mode:
                winners = [
                    p["name"]
                    for p in session["players"]
                    if session["votes"].get(str(p["id"])) == "all_spies"
                ]
                losers = [
                    p["name"]
                    for p in session["players"]
                    if session["votes"].get(str(p["id"])) != "all_spies"
                ]
                if winners:
                    results["winner"] = "spy"
                    results["message"] = "Spy players who selected 'all_spies' win."
                else:
                    results["winner"] = "spy"
                    results["message"] = "No spy selected the 'all_spies' option. Spy team wins by default."
                results["spy_winners"] = winners
                results["spy_losers"] = losers
                results["tie"] = len(top_candidates) > 1
                results["eliminated_player"] = None
                session["status"] = "completed"
                session["vote_started_at"] = None
            else:
                if len(top_candidates) > 1:
                    results["tie"] = True
                    results["winner"] = "spy"
                    results["message"] = "Vote tied. Spy team wins."
                    session["status"] = "completed"
                    session["vote_started_at"] = None
                else:
                    target = top_candidates[0]
                    eliminated_player = players.get(target)
                    if isinstance(target, str) and target == "all_spies":
                        results["eliminated_player"] = None
                        results["winner"] = "spy"
                        results["message"] = "Spy team wins."
                    else:
                        results["eliminated_player"] = {
                            "player_id": target,
                            "name": eliminated_player["name"],
                            "role": eliminated_player["role"],
                        }
                        if eliminated_player["role"] == "spy":
                            results["winner"] = "detective"
                            results["message"] = "Spy eliminated. Detective team wins!"
                        else:
                            results["winner"] = "spy"
                            results["message"] = "Spy survives. Spy team wins!"
                    session["status"] = "completed"
                    session["vote_started_at"] = None

        session["results"] = results
        _save_session(client, session)
    return JsonResponse({"success": True, "session_code": code, "results": results})
