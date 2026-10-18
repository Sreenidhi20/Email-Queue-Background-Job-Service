import unittest
from unittest.mock import patch

from src.features.health.health_tasks import ping


class HealthTaskTests(unittest.TestCase):
    def test_ping_returns_pong_message(self) -> None:
        with patch("src.features.health.health_tasks.time.sleep") as sleep:
            self.assertEqual(ping("hello"), "pong: hello")
            sleep.assert_called_once_with(3)


if __name__ == "__main__":
    unittest.main()
