import random

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
        images = [
            {"path": question.real_image_path, "label": "real"},
            {"path": question.fake_image_path, "label": "fake"},
        ]
        random.shuffle(images)

        payload.append(
            {
                "id": question.id,
                "prompt": question.prompt,
                "images": images,
                "key_flaw": question.key_flaw,
                "technique_tip": question.technique_tip,
            }
        )

    return JsonResponse(
        {"count": len(payload), "questions": payload},
        json_dumps_params={"ensure_ascii": False},
    )
