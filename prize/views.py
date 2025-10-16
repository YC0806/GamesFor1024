from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .locks import PrizeLockError, prize_draw_lock
from .models import Prize
from .services import DrawResult, PrizeUnavailableError, draw_prize


def _json_error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"success": False, "error": message}, status=status)


@require_http_methods(["GET"])
def get_prize(request):
    try:
        with prize_draw_lock():
            result: DrawResult = draw_prize()
    except PrizeLockError as exc:
        return _json_error(str(exc), status=503)
    except PrizeUnavailableError as exc:
        return _json_error(str(exc), status=409)
    return JsonResponse({"success": True, "prize": result.prize.to_payload()})


@require_http_methods(["GET"])
def list_prizes(request):
    prizes = [
        prize.to_payload()
        for prize in Prize.objects.all().order_by("id")
    ]
    return JsonResponse({"success": True, "prizes": prizes})
