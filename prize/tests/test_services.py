from unittest import mock

from django.test import TestCase

from prize.models import Prize
from prize.services import PrizeUnavailableError, draw_prize


class DrawPrizeTests(TestCase):
    def setUp(self):
        self.prize = Prize.objects.create(name="Desk Mat", stock=2)

    def test_draw_prize_decrements_stock(self):
        with mock.patch("prize.services.random.randint", return_value=0):
            result = draw_prize()

        self.assertEqual(result.prize.id, self.prize.id)
        self.prize.refresh_from_db()
        self.assertEqual(self.prize.stock, 1)

    def test_no_prize_available_raises_error(self):
        self.prize.stock = 0
        self.prize.save(update_fields=["stock"])

        with self.assertRaises(PrizeUnavailableError):
            draw_prize()
