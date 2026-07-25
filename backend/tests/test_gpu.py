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


class TestParseNvidiaValue(unittest.TestCase):

    def test_parses_float(self) -> None:
        self.assertEqual(gpu_module._parse_nvidia_value(" 55.5 "), 55.5)

    def test_empty_string_returns_none(self) -> None:
        self.assertIsNone(gpu_module._parse_nvidia_value(""))

    def test_bracketed_na_returns_none(self) -> None:
        self.assertIsNone(gpu_module._parse_nvidia_value("[N/A]"))

    def test_plain_na_returns_none(self) -> None:
        self.assertIsNone(gpu_module._parse_nvidia_value("N/A"))

    def test_non_numeric_returns_none(self) -> None:
        self.assertIsNone(gpu_module._parse_nvidia_value("nope"))


class TestIsUnsupportedField(unittest.TestCase):

    def test_bracketed_not_supported(self) -> None:
        self.assertTrue(gpu_module._is_unsupported_field("[Not Supported]"))

    def test_plain_na(self) -> None:
        self.assertTrue(gpu_module._is_unsupported_field("n/a"))

    def test_real_value_is_not_unsupported(self) -> None:
        self.assertFalse(gpu_module._is_unsupported_field("55"))


class TestGetGpuStatus(unittest.TestCase):

    def test_nvidia_smi_not_installed(self) -> None:
        with patch.object(gpu_module.shutil, "which", return_value=None):
            result = gpu_module.get_gpu_status()
        self.assertFalse(result["reachable"])
        self.assertIn("nvidia-smi not found", result["error"])

    def test_subprocess_exception_reports_unreachable(self) -> None:
        with patch.object(gpu_module.shutil, "which", return_value="/usr/bin/nvidia-smi"):
            with patch.object(gpu_module.subprocess, "run", side_effect=RuntimeError("boom")):
                result = gpu_module.get_gpu_status()
        self.assertFalse(result["reachable"])
        self.assertIn("RuntimeError", result["error"])

    def test_nonzero_returncode_reports_stderr(self) -> None:
        result = MagicMock(returncode=1, stdout="", stderr="driver error\n")
        with patch.object(gpu_module.shutil, "which", return_value="/usr/bin/nvidia-smi"):
            with patch.object(gpu_module.subprocess, "run", return_value=result):
                status = gpu_module.get_gpu_status()
        self.assertFalse(status["reachable"])
        self.assertEqual(status["error"], "driver error")

    def test_empty_stdout_reports_default_error(self) -> None:
        result = MagicMock(returncode=0, stdout="   ", stderr="")
        with patch.object(gpu_module.shutil, "which", return_value="/usr/bin/nvidia-smi"):
            with patch.object(gpu_module.subprocess, "run", return_value=result):
                status = gpu_module.get_gpu_status()
        self.assertFalse(status["reachable"])
        self.assertEqual(status["error"], "nvidia-smi returned no output")

    def _query_result(self, stdout: str) -> MagicMock:
        return MagicMock(returncode=0, stdout=stdout, stderr="")

    def test_full_success_parses_all_fields(self) -> None:
        main_result = self._query_result("NVIDIA GB10, 16384, 8192, 45, 60, 120.5\n")
        procs_result = MagicMock(returncode=0, stdout="1234, python, 2048\n")

        with patch.object(gpu_module.shutil, "which", return_value="/usr/bin/nvidia-smi"):
            with patch.object(gpu_module.subprocess, "run", side_effect=[main_result, procs_result]):
                with patch.object(gpu_module.httpx, "Client", side_effect=RuntimeError("no ollama")):
                    status = gpu_module.get_gpu_status()

        self.assertTrue(status["reachable"])
        self.assertEqual(status["gpu_name"], "NVIDIA GB10")
        self.assertEqual(status["memory_total_mb"], 16384)
        self.assertEqual(status["memory_used_mb"], 8192)
        self.assertEqual(status["utilization_pct"], 45)
        self.assertEqual(status["temperature_c"], 60)
        self.assertEqual(status["power_draw_w"], 120.5)
        self.assertFalse(status["memory_unsupported"])
        self.assertIsNone(status["error"])
        self.assertEqual(status["processes"], [{"pid": 1234, "name": "python", "memory_mb": 2048}])
        self.assertEqual(status["ollama_loaded_models"], [])

    def test_memory_na_on_unified_memory_hardware_not_flagged_as_error(self) -> None:
        main_result = self._query_result("NVIDIA GB10, [N/A], [N/A], 45, 60, 120.5\n")
        procs_result = MagicMock(returncode=0, stdout="")

        with patch.object(gpu_module.shutil, "which", return_value="/usr/bin/nvidia-smi"):
            with patch.object(gpu_module.subprocess, "run", side_effect=[main_result, procs_result]):
                with patch.object(gpu_module.httpx, "Client", side_effect=RuntimeError("no ollama")):
                    status = gpu_module.get_gpu_status()

        self.assertTrue(status["memory_unsupported"])
        self.assertIsNone(status["error"])
        self.assertIsNone(status["memory_used_mb"])

    def test_memory_missing_for_other_reason_reports_error(self) -> None:
        main_result = self._query_result("NVIDIA GB10, 16384, garbled, 45, 60, 120.5\n")
        procs_result = MagicMock(returncode=0, stdout="")

        with patch.object(gpu_module.shutil, "which", return_value="/usr/bin/nvidia-smi"):
            with patch.object(gpu_module.subprocess, "run", side_effect=[main_result, procs_result]):
                with patch.object(gpu_module.httpx, "Client", side_effect=RuntimeError("no ollama")):
                    status = gpu_module.get_gpu_status()

        self.assertIsNone(status["memory_used_mb"])
        self.assertIn("driver may be in a bad state", status["error"])

    def test_process_query_exception_leaves_processes_empty(self) -> None:
        main_result = self._query_result("NVIDIA GB10, 16384, 8192, 45, 60, 120.5\n")

        with patch.object(gpu_module.shutil, "which", return_value="/usr/bin/nvidia-smi"):
            with patch.object(gpu_module.subprocess, "run", side_effect=[main_result, RuntimeError("boom")]):
                with patch.object(gpu_module.httpx, "Client", side_effect=RuntimeError("no ollama")):
                    status = gpu_module.get_gpu_status()

        self.assertEqual(status["processes"], [])

    def test_malformed_process_lines_skipped(self) -> None:
        main_result = self._query_result("NVIDIA GB10, 16384, 8192, 45, 60, 120.5\n")
        procs_result = MagicMock(returncode=0, stdout="not,enough\n\n5678, ok, 100\n")

        with patch.object(gpu_module.shutil, "which", return_value="/usr/bin/nvidia-smi"):
            with patch.object(gpu_module.subprocess, "run", side_effect=[main_result, procs_result]):
                with patch.object(gpu_module.httpx, "Client", side_effect=RuntimeError("no ollama")):
                    status = gpu_module.get_gpu_status()

        self.assertEqual(status["processes"], [{"pid": 5678, "name": "ok", "memory_mb": 100.0}])

    def test_ollama_models_included_when_reachable(self) -> None:
        main_result = self._query_result("NVIDIA GB10, 16384, 8192, 45, 60, 120.5\n")
        procs_result = MagicMock(returncode=0, stdout="")

        ollama_resp = MagicMock()
        ollama_resp.status_code = 200
        ollama_resp.json.return_value = {
            "models": [{"name": "llama3", "size": 4_000_000_000, "expires_at": "2026-01-01T00:00:00Z"}],
        }
        mock_client = MagicMock()
        mock_client.get.return_value = ollama_resp
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_client)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch.object(gpu_module.shutil, "which", return_value="/usr/bin/nvidia-smi"):
            with patch.object(gpu_module.subprocess, "run", side_effect=[main_result, procs_result]):
                with patch.object(gpu_module.httpx, "Client", return_value=mock_ctx):
                    status = gpu_module.get_gpu_status()

        self.assertEqual(status["ollama_loaded_models"], [
            {"name": "llama3", "size_gb": 4.0, "until": "2026-01-01T00:00:00Z"},
        ])

    def test_ollama_non_200_gives_empty_models(self) -> None:
        main_result = self._query_result("NVIDIA GB10, 16384, 8192, 45, 60, 120.5\n")
        procs_result = MagicMock(returncode=0, stdout="")

        ollama_resp = MagicMock()
        ollama_resp.status_code = 500
        mock_client = MagicMock()
        mock_client.get.return_value = ollama_resp
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_client)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch.object(gpu_module.shutil, "which", return_value="/usr/bin/nvidia-smi"):
            with patch.object(gpu_module.subprocess, "run", side_effect=[main_result, procs_result]):
                with patch.object(gpu_module.httpx, "Client", return_value=mock_ctx):
                    status = gpu_module.get_gpu_status()

        self.assertEqual(status["ollama_loaded_models"], [])


if __name__ == "__main__":
    unittest.main()
