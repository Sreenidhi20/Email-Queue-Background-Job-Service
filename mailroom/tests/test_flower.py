import unittest
from unittest.mock import patch

from src.infrastructure.celery_app import celery_app
from src.infrastructure.flower_launcher import FlowerLauncher


class FlowerLauncherTests(unittest.TestCase):
    def test_builds_secured_persistent_command(self) -> None:
        launcher = FlowerLauncher("admin", "longpassword", port=5600, db_path="x.db")

        args = launcher.build_args()

        self.assertEqual(args[0], "flower")
        self.assertIn("--port=5600", args)
        self.assertIn("--basic-auth=admin:longpassword", args)
        self.assertIn("--persistent=True", args)
        self.assertIn("--db=x.db", args)

    def test_password_may_contain_a_colon(self) -> None:
        launcher = FlowerLauncher("admin", "pass:word:12")

        self.assertIn("--basic-auth=admin:pass:word:12", launcher.build_args())

    def test_refuses_to_start_without_credentials(self) -> None:
        with self.assertRaises(ValueError):
            FlowerLauncher("", "longpassword")
        with self.assertRaises(ValueError):
            FlowerLauncher("admin", "")

    def test_refuses_short_password(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 8"):
            FlowerLauncher("admin", "short")

    def test_refuses_characters_that_break_basic_auth_parsing(self) -> None:
        with self.assertRaises(ValueError):
            FlowerLauncher("ad:min", "longpassword")
        with self.assertRaises(ValueError):
            FlowerLauncher("admin", "long,password")

    def test_from_settings_reads_user_password_and_port(self) -> None:
        with patch("src.infrastructure.flower_launcher.settings") as fake:
            fake.FLOWER_USER = "ops"
            fake.FLOWER_PASSWORD = "supersecret"
            fake.FLOWER_PORT = 5999

            launcher = FlowerLauncher.from_settings()

        self.assertEqual(launcher.port, 5999)
        self.assertIn("--basic-auth=ops:supersecret", launcher.build_args())

    def test_start_hands_arguments_to_celery(self) -> None:
        launcher = FlowerLauncher("admin", "longpassword")
        with patch.object(celery_app, "start") as start:
            launcher.start()

        start.assert_called_once_with(launcher.build_args())


class CeleryEventConfigTests(unittest.TestCase):
    def test_events_are_enabled_so_flower_sees_workers_and_queued_tasks(self) -> None:
        self.assertTrue(celery_app.conf.worker_send_task_events)
        self.assertTrue(celery_app.conf.task_send_sent_event)


if __name__ == "__main__":
    unittest.main()
