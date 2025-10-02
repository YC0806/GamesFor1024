from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .models import RiskScenario


@require_GET
def scenario_feed(request):
    """Return a random selection of risk review scenarios as JSON."""

    try:
        requested_count = int(request.GET.get("count", 5))
    except (TypeError, ValueError):
        return JsonResponse({"error": "count must be an integer"}, status=400)

    if requested_count < 1:
        return JsonResponse({"error": "count must be a positive integer"}, status=400)

    queryset = RiskScenario.objects.all()
    available = queryset.count()
    if available == 0:
        return JsonResponse({"error": "no scenarios available"}, status=404)

    selected = list(queryset.order_by("?")[: min(requested_count, available)])

    payload = [
        {
            "id": scenario.id,
            "title": scenario.title,
            "content": scenario.content,
            "risk_label": scenario.risk_label,
            "analysis": scenario.analysis,
            "technique_tip": scenario.technique_tip,
        }
        for scenario in selected
    ]

    return JsonResponse(
        {"count": len(payload), "scenarios": payload},
        json_dumps_params={"ensure_ascii": False},
    )
