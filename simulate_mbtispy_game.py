#!/usr/bin/env python3
"""
Simulate MBTI守护挑战 gameplay flows against a running backend service.

Usage:
    python simulate_mbtispy_game.py --base-url http://localhost:8000

The script exercises two end-to-end flows:
1) Unique MBTI assignment leading to a detective victory.
2) Duplicate MBTI scenario producing a voting tie, followed by a restart and
   final resolution.

It communicates purely over HTTP, mimicking a front-end client.
"""

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple, Union

try:
    import requests
except ModuleNotFoundError as exc:  # pragma: no cover - runtime dependency notice
    raise SystemExit(
        "The simulate_mbtispy_game script requires the 'requests' package. "
        "Install it via `pip install requests` and rerun."
    ) from exc


TIMEOUT = 10  # seconds per request


@dataclass
class PlayerRegistration:
    name: str
    mbti: str


class MBTISpyClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _request(
        self,
        method: str,
        path: str,
        expected_status: Iterable[int],
        json_payload: Dict | None = None,
    ) -> Dict:
        url = f"{self.base_url}{path}"
        response = requests.request(
            method=method,
            url=url,
            json=json_payload,
            timeout=TIMEOUT,
        )
        if response.status_code not in expected_status:
            raise RuntimeError(
                f"{method} {path} returned {response.status_code}: {response.text}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(f"Response from {path} was not valid JSON.") from exc

    # Session management -------------------------------------------------

    def create_session(self) -> str:
        data = self._request("POST", "/mbtispy/session/", {200}, {})
        session_code = data["session_code"]
        print(f"[info] session created (code={session_code})")
        return session_code

    def register_players(
        self, session_code: str, players: List[PlayerRegistration]
    ) -> Dict:
        url = f"/mbtispy/session/{session_code}/register/"
        last_payload = {}
        for idx, player in enumerate(players, start=1):
            payload = {"player_name": player.name, "mbti": player.mbti}
            resp = self._request("POST", url, {200}, payload)
            assert resp["player_id"] == idx, f"player {player.name} registration order mismatch"
            print(
                f"[info] registered #{resp['player_id']}: {player.name} ({player.mbti}) "
                f"role={resp['role']} roles_assigned={resp['roles_assigned']}"
            )
            last_payload = resp
        return last_payload

    def get_player_role(self, session_code: str, player_id: int) -> Dict:
        data = self._request(
            "GET",
            f"/mbtispy/session/{session_code}/role/{player_id}/",
            {200},
        )
        print(
            f"[info] player #{player_id} role={data['role']}"
            + (f" spy_mbti={data['spy_mbti']}" if "spy_mbti" in data else "")
        )
        return data

    # Voting -------------------------------------------------------------

    def ensure_vote_not_open(self, session_code: str):
        """Verify that voting endpoints reject access before host starts voting."""
        players = self._request(
            "GET", f"/mbtispy/session/{session_code}/players/", {200}
        )["players"]
        if not players:
            raise RuntimeError("No players registered when checking vote status.")
        first_player_id = players[0]["id"]
        response = self._request(
            "GET",
            f"/mbtispy/session/{session_code}/vote/{first_player_id}/",
            {200},
        )
        status = response.get("status")
        if response.get("success") is False:
            print(f"[info] voting not open yet (status={status})")
            return
        raise RuntimeError("Voting unexpectedly available prior to start.")

    def start_vote(self, session_code: str):
        data = self._request(
            "POST", f"/mbtispy/session/{session_code}/vote/start/", {200}, {}
        )
        print(f"[info] vote started (status={data['status']})")

    def get_vote_roster(self, session_code: str) -> List[Dict]:
        players_payload = self._request(
            "GET", f"/mbtispy/session/{session_code}/players/", {200}
        )
        roster: List[Dict] = []
        for player in players_payload.get("players", []):
            data = self._request(
                "GET",
                f"/mbtispy/session/{session_code}/vote/{player['id']}/",
                {200},
            )
            if not data.get("success", True):
                raise RuntimeError(f"Unable to fetch vote options: {data.get('message')}")
            roster.append(data["player"])
        print(f"[info] vote roster retrieved ({len(roster)} players)")
        return roster

    def poll_registration(self, session_code: str, retries: int = 5, interval: float = 0.5) -> Dict:
        for attempt in range(1, retries + 1):
            data = self._request(
                "GET",
                f"/mbtispy/session/{session_code}/register/status/",
                {200},
            )
            if data.get("success"):
                print(
                    f"[info] registration complete (registered={data['registered_players']}/"
                    f"{data['expected_players']}, spy_mbti={data.get('spy_mbti')})"
                )
                return data
            print(
                f"[info] registration pending #{attempt}: "
                f"{data.get('registered_players', 0)}/{data.get('expected_players', '?')}"
            )
            time.sleep(interval)
        raise RuntimeError("Registration did not complete in time.")

    def submit_vote(self, session_code: str, voter: int, target: Union[int, str]):
        payload = {"vote_for": target}
        data = self._request(
            "POST",
            f"/mbtispy/session/{session_code}/vote/{voter}/",
            {200},
            payload,
        )
        if not data.get("success", True):
            raise RuntimeError(f"Vote rejected: {data.get('message')}")
        print(
            f"[info] vote submitted: player #{data['player_id']} -> #{data['vote_for']} "
        )

    def fetch_results(self, session_code: str) -> Dict:
        data = self._request(
            "GET",
            f"/mbtispy/session/{session_code}/results/",
            {200},
        )
        if not data.get("success", True):
            raise RuntimeError(f"Results unavailable: {data.get('message')}")
        print(f"[info] results message={data['results'].get('message', '')}")
        return data["results"]


def scenario_unique_mbtis(client: MBTISpyClient):
    print("\n=== Scenario 1: unique MBTI assignments ===")
    session_code = client.create_session()

    # Register three players with distinct MBTIs
    client.register_players(
        session_code,
        [
            PlayerRegistration("Alice", "INFJ"),
            PlayerRegistration("Bob", "ENTP"),
            PlayerRegistration("Charlie", "ISFP"),
        ],
    )
    registration = client.poll_registration(session_code)
    if not registration.get("spy_mbti"):
        raise RuntimeError("spy_mbti not determined after registration polling.")

    # Inspect each player's role
    for pid in (1, 2, 3):
        client.get_player_role(session_code, pid)

    # Voting must be unavailable before host starts it
    client.ensure_vote_not_open(session_code)

    # Host starts the vote
    client.start_vote(session_code)

    client.get_vote_roster(session_code)

    # Submit votes: two detectives target the suspected spy
    vote_plan: List[Tuple[int, int]] = [(1, 3), (2, 3), (3, 1)]
    for voter, target in vote_plan:
        client.submit_vote(session_code, voter, target)

    results = client.fetch_results(session_code)
    print(f"[info] winner={results['winner']}")
    if results["winner"] != "detective":
        raise RuntimeError("Unexpected winner in unique MBTI scenario.")


def scenario_tie_and_restart(client: MBTISpyClient):
    print("\n=== Scenario 2: tie leads to spy victory ===")
    session_code = client.create_session()

    client.register_players(
        session_code,
        [
            PlayerRegistration("Alice", "INTJ"),
            PlayerRegistration("Bob", "INTJ"),
            PlayerRegistration("Eve", "ENFP"),
        ],
    )

    client.poll_registration(session_code)

    # Host begins voting
    client.start_vote(session_code)
    client.get_vote_roster(session_code)

    # Round 1: create a three-way tie
    for voter, target in ((1, 2), (2, 3), (3, 1)):
        client.submit_vote(session_code, voter, target)

    round1 = client.fetch_results(session_code)
    if not round1["tie"] or round1["winner"] != "spy":
        raise RuntimeError("Expected tie to result in spy victory.")
    print("[info] tie detected; spy team declared winner.")


def scenario_all_spies(client: MBTISpyClient):
    print("\n=== Scenario 3: all players are spies ===")
    session_code = client.create_session()

    client.register_players(
        session_code,
        [
            PlayerRegistration("Alice", "INTJ"),
            PlayerRegistration("Bob", "INTJ"),
            PlayerRegistration("Eve", "INTJ"),
        ],
    )

    client.poll_registration(session_code)
    client.start_vote(session_code)
    client.get_vote_roster(session_code)

    client.submit_vote(session_code, 1, "all_spies")
    client.submit_vote(session_code, 2, "all_spies")
    client.submit_vote(session_code, 3, 1)  # refuses to pick special option

    results = client.fetch_results(session_code)
    if results["winner"] != "spy":
        raise RuntimeError("Expected spy victory in all-spy scenario.")
    winners = results.get("spy_winners", [])
    losers = results.get("spy_losers", [])
    print(f"[info] spy winners={winners}, losers={losers}")


def main():
    parser = argparse.ArgumentParser(
        description="Simulate MBTI守护挑战 game flows via HTTP requests."
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Root URL of the running Django service (default: http://localhost:8000)",
    )
    args = parser.parse_args()

    client = MBTISpyClient(args.base_url)
    try:
        scenario_unique_mbtis(client)
        scenario_tie_and_restart(client)
        scenario_all_spies(client)
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print("\n[info] All scenarios completed successfully.")


if __name__ == "__main__":
    main()
