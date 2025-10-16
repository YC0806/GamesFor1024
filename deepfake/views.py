import random

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .models import DeepfakePair, DeepfakeSelection


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

    queryset = DeepfakePair.objects.all()
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


@require_GET
def selection_challenge(request):
    """Return `count` selection challenges each with one AI-generated and two real images."""

    try:
        requested_count = int(request.GET.get("count", 1))
    except (TypeError, ValueError):
        return JsonResponse({"error": "count must be an integer"}, status=400)

    if requested_count < 1:
        return JsonResponse(
            {"error": "count must be a positive integer"}, status=400
        )

    ai_qs = DeepfakeSelection.objects.filter(ai_generated=True)
    real_qs = DeepfakeSelection.objects.filter(ai_generated=False)

    ai_required = requested_count
    real_required = requested_count * 2

    if ai_qs.count() < ai_required or real_qs.count() < real_required:
        return JsonResponse(
            {"error": "not enough data to assemble the challenge"}, status=404
        )

    ai_images = list(ai_qs.order_by("?")[:ai_required])
    real_images = list(real_qs.order_by("?")[:real_required])

    if len(ai_images) < ai_required or len(real_images) < real_required:
        return JsonResponse(
            {"error": "not enough data to assemble the challenge"}, status=404
        )

    groups = []
    real_iter = iter(real_images)
    for index, ai_image in enumerate(ai_images, start=1):
        group_images = [
            {
                "id": ai_image.id,
                "img_path": ai_image.img_path,
                "ai_generated": True,
                "analysis": ai_image.analysis or "",
            }
        ]

        selections = [next(real_iter, None), next(real_iter, None)]
        if None in selections:
            return JsonResponse(
                {"error": "not enough data to assemble the challenge"}, status=404
            )

        for image in selections:
            group_images.append(
                {
                    "id": image.id,
                    "img_path": image.img_path,
                    "ai_generated": False,
                    "analysis": image.analysis or "",
                }
            )

        random.shuffle(group_images)

        groups.append(
            {
                "index": index,
                "images": group_images,
            }
        )

    return JsonResponse(
        {"count": len(groups), "groups": groups},
        json_dumps_params={"ensure_ascii": False},
    )
