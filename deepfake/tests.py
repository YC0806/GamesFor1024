from django.test import Client, TestCase

from .models import DeepfakePair, DeepfakeSelection


class QuestionFeedAPITests(TestCase):
    def setUp(self) -> None:
        self.client = Client()

    def create_pair(self, idx: int) -> DeepfakePair:
        return DeepfakePair.objects.create(
            real_img=f"/static/images/{idx}_real.jpg",
            ai_img=f"/static/images/{idx}_ai.jpg",
            analysis="",
        )

    def test_returns_requested_number_of_questions(self) -> None:
        for i in range(5):
            self.create_pair(i)

        response = self.client.get("/deepfake/questions/", {"count": 2})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 2)
        self.assertEqual(len(payload["questions"]), 2)
        for question in payload["questions"]:
            self.assertIn("real_img", question)
            self.assertIn("ai_img", question)

    def test_defaults_to_available_questions_when_count_exceeds(self) -> None:
        self.create_pair(1)

        response = self.client.get("/deepfake/questions/", {"count": 5})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)

    def test_returns_not_found_when_no_questions_available(self) -> None:
        response = self.client.get("/deepfake/questions/", {"count": 1})
        self.assertEqual(response.status_code, 404)

    def test_validates_count_parameter(self) -> None:
        response = self.client.get("/deepfake/questions/", {"count": "abc"})
        self.assertEqual(response.status_code, 400)

        response = self.client.get("/deepfake/questions/", {"count": 0})
        self.assertEqual(response.status_code, 400)


class SelectionChallengeAPITests(TestCase):
    def setUp(self) -> None:
        self.client = Client()

    def create_selection(
        self, *, idx: int, ai_generated: bool
    ) -> DeepfakeSelection:
        return DeepfakeSelection.objects.create(
            img_path=f"/static/images/{idx}.png",
            ai_generated=ai_generated,
            analysis="",
        )

    def test_returns_requested_number_of_groups(self) -> None:
        for idx in range(1, 4):
            self.create_selection(idx=idx, ai_generated=True)
        for idx in range(10, 16):
            self.create_selection(idx=idx, ai_generated=False)

        response = self.client.get("/deepfake/selection/", {"count": 3})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 3)
        self.assertEqual(len(payload["groups"]), 3)
        for group in payload["groups"]:
            self.assertEqual(len(group["images"]), 3)
            self.assertEqual(
                sum(1 for image in group["images"] if image["ai_generated"]), 1
            )

    def test_returns_not_found_when_data_insufficient(self) -> None:
        self.create_selection(idx=1, ai_generated=True)
        self.create_selection(idx=2, ai_generated=False)

        response = self.client.get("/deepfake/selection/")

        self.assertEqual(response.status_code, 404)
