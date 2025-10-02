from django.test import Client, TestCase

from .models import DeepfakeQuestion


class QuestionFeedAPITests(TestCase):
    def setUp(self) -> None:
        self.client = Client()

    def create_question(self, idx: int) -> DeepfakeQuestion:
        return DeepfakeQuestion.objects.create(
            prompt=f"场景 {idx}",
            real_image_path=f"/static/images/{idx}_real.jpg",
            fake_image_path=f"/static/images/{idx}_fake.jpg",
            key_flaw="观察眼睛反光的细节。",
            technique_tip="先看光影，再看边缘。",
        )

    def test_returns_requested_number_of_questions(self) -> None:
        for i in range(5):
            self.create_question(i)

        response = self.client.get("/deepfake/questions/", {"count": 2})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 2)
        self.assertEqual(len(payload["questions"]), 2)
        for question in payload["questions"]:
            self.assertIn("prompt", question)
            self.assertIn("technique_tip", question)
            self.assertEqual(len(question["images"]), 2)

    def test_defaults_to_available_questions_when_count_exceeds(self) -> None:
        self.create_question(1)

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
