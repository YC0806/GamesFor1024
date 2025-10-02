from django.test import Client, TestCase

from .models import RiskScenario


class ScenarioFeedAPITests(TestCase):
    def setUp(self) -> None:
        self.client = Client()

    def create_scenario(self, idx: int, label: str = RiskScenario.RiskLabel.NON_COMPLIANT) -> RiskScenario:
        return RiskScenario.objects.create(
            title=f"场景 {idx}",
            content="这是一段需要审核的AI生成内容。",
            risk_label=label,
            analysis="指出文本中潜在的风险点。",
            technique_tip="留意涉及资金和个人信息的措辞。",
        )

    def test_returns_requested_number_of_scenarios(self) -> None:
        for i in range(6):
            self.create_scenario(i)

        response = self.client.get("/riskhunter/scenarios/", {"count": 3})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 3)
        self.assertEqual(len(payload["scenarios"]), 3)
        for scenario in payload["scenarios"]:
            self.assertIn("content", scenario)
            self.assertIn("analysis", scenario)
            self.assertIn(scenario["risk_label"], dict(RiskScenario.RiskLabel.choices))

    def test_returns_available_when_count_exceeds(self) -> None:
        self.create_scenario(1)

        response = self.client.get("/riskhunter/scenarios/", {"count": 5})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)

    def test_returns_not_found_when_no_scenarios(self) -> None:
        response = self.client.get("/riskhunter/scenarios/", {"count": 1})
        self.assertEqual(response.status_code, 404)

    def test_validates_count_parameter(self) -> None:
        response = self.client.get("/riskhunter/scenarios/", {"count": "abc"})
        self.assertEqual(response.status_code, 400)

        response = self.client.get("/riskhunter/scenarios/", {"count": 0})
        self.assertEqual(response.status_code, 400)
