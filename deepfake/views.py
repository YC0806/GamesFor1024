from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .models import DeepfakeQuestion


@require_GET
def question_feed(request):
    """Return a random selection of deepfake challenges as JSON."""

    try:
        requested_count = int(request.GET.get("count", 3))
    except (TypeError, ValueError):
        return JsonResponse({"error": "count must be an integer"}, status=400)

    if requested_count < 1:
        return JsonResponse(
            {"error": "count must be a positive integer"}, status=400
        )

    queryset = DeepfakeQuestion.objects.all()
    available = queryset.count()
    if available == 0:
        return JsonResponse({"error": "no questions available"}, status=404)

    selected_questions = list(queryset.order_by("?")[: min(requested_count, available)])

    payload = []
    for question in selected_questions:
        payload.append(
            {
                "id": question.id,
                "real_img": question.real_img,
                "ai_img": question.ai_img,
                "analysis": question.analysis or "",
            }
        )

    return JsonResponse(
        {"count": len(payload), "questions": payload},
        json_dumps_params={"ensure_ascii": False},
    )
