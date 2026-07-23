"""
tests/test_gpu.py

Unit tests for:
  - control_center.checks.gpu.check_gpu_temperature
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from control_center.checks import gpu as gpu_module


class TestCheckGpuTemperature(unittest.TestCase):

    def test_nvidia_smi_not_found_returns_empty(self) -> None:
        with patch.object(gpu_module.subprocess, "run", side_effect=FileNotFoundError()):
            results = gpu_module.check_gpu_temperature()
        self.assertEqual(results, [])

    def test_nonzero_returncode_returns_empty(self) -> None:
        result = MagicMock(returncode=1, stdout="")
        with patch.object(gpu_module.subprocess, "run", return_value=result):
            results = gpu_module.check_gpu_temperature()
        self.assertEqual(results, [])

    def test_normal_temperature_reports_up(self) -> None:
        result = MagicMock(returncode=0, stdout="0, NVIDIA GB10, 55\n")
        with patch.object(gpu_module.subprocess, "run", return_value=result):
            results = gpu_module.check_gpu_temperature()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "UP")
        self.assertEqual(results[0]["name"], "gpu:0")
        self.assertEqual(results[0]["target"], "NVIDIA GB10")
        self.assertIn("55", results[0]["message"])

    def test_high_temperature_reports_warn_and_notifies(self) -> None:
        result = MagicMock(returncode=0, stdout="0, NVIDIA GB10, 90\n")
        with patch.object(gpu_module.subprocess, "run", return_value=result):
            with patch.object(gpu_module, "_discord_notify") as mock_notify:
                with patch.object(gpu_module, "_WEBHOOK", "https://discord.example/webhook"):
                    results = gpu_module.check_gpu_temperature()
        self.assertEqual(results[0]["status"], "WARN")
        self.assertIn("High temp", results[0]["message"])
        mock_notify.assert_called_once()
        args, kwargs = mock_notify.call_args
        self.assertIn("High Temperature Alert", args[1])

    def test_multiple_gpus_all_returned(self) -> None:
        stdout = "0, NVIDIA GB10, 50\n1, NVIDIA GB10, 60\n"
        result = MagicMock(returncode=0, stdout=stdout)
        with patch.object(gpu_module.subprocess, "run", return_value=result):
            results = gpu_module.check_gpu_temperature()
        self.assertEqual(len(results), 2)
        self.assertEqual({r["name"] for r in results}, {"gpu:0", "gpu:1"})

    def test_malformed_line_skipped(self) -> None:
        result = MagicMock(returncode=0, stdout="not,enough\n0, NVIDIA GB10, 50\n")
        with patch.object(gpu_module.subprocess, "run", return_value=result):
            results = gpu_module.check_gpu_temperature()
        self.assertEqual(len(results), 1)

    def test_non_integer_temperature_skipped(self) -> None:
        result = MagicMock(returncode=0, stdout="0, NVIDIA GB10, N/A\n")
        with patch.object(gpu_module.subprocess, "run", return_value=result):
            results = gpu_module.check_gpu_temperature()
        self.assertEqual(results, [])

    def test_empty_stdout_returns_empty(self) -> None:
        result = MagicMock(returncode=0, stdout="")
        with patch.object(gpu_module.subprocess, "run", return_value=result):
            results = gpu_module.check_gpu_temperature()
        self.assertEqual(results, [])

    def test_unexpected_exception_reports_warn(self) -> None:
        with patch.object(gpu_module.subprocess, "run", side_effect=RuntimeError("boom")):
            results = gpu_module.check_gpu_temperature()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "gpu:check")
        self.assertEqual(results[0]["status"], "WARN")
        self.assertIn("RuntimeError", results[0]["message"])


if __name__ == "__main__":
    unittest.main()
