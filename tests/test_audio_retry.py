"""Tests for TTS transient error detection and retry handling."""

import unittest

from audio_generator import TTS_RETRY_DELAYS_SECONDS, _is_transient_tts_error


class TransientTTSErrorTests(unittest.TestCase):
    """Verify that transient Edge TTS network and rate limit errors are caught."""

    def test_actual_edge_tts_429_format_is_transient(self):
        # 実際のエラーメッセージ形式:
        # "429, message='Invalid response status', url='wss://api.msedgeservices.com/...'"
        err = Exception(
            "429, message='Invalid response status', "
            "url='wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1'"
        )
        self.assertTrue(_is_transient_tts_error(err))

    def test_status_codes_are_recognized(self):
        cases = [
            "429 Too Many Requests",
            "HTTP 429",
            "status: 429",
            "500 Internal Server Error",
            "502 Bad Gateway",
            "503 Service Unavailable",
            "504 Gateway Timeout",
        ]
        for msg in cases:
            with self.subTest(msg=msg):
                self.assertTrue(_is_transient_tts_error(Exception(msg)))

    def test_network_keywords_are_recognized(self):
        cases = [
            "Connection reset by peer",
            "Cannot connect to host api.msedgeservices.com:443",
            "Server disconnected",
            "Operation timed out",
            "Request timeout",
            "Service temporarily unavailable",
            "Too Many Requests",
            "Invalid response status",
        ]
        for msg in cases:
            with self.subTest(msg=msg):
                self.assertTrue(_is_transient_tts_error(Exception(msg)))

    def test_timeout_error_instance_is_transient(self):
        self.assertTrue(_is_transient_tts_error(TimeoutError("Socket timeout")))

    def test_non_transient_errors_are_rejected(self):
        cases = [
            "400 Bad Request",
            "401 Unauthorized",
            "403 Forbidden",
            "404 Not Found",
            "ValueError: invalid rate format",
            "Generated 4290 bytes successfully",
            "Item 5000 is invalid",
        ]
        for msg in cases:
            with self.subTest(msg=msg):
                self.assertFalse(_is_transient_tts_error(Exception(msg)))

    def test_retry_delays_are_configured_for_resilience(self):
        self.assertGreaterEqual(len(TTS_RETRY_DELAYS_SECONDS), 2)
        self.assertTrue(all(isinstance(d, (int, float)) and d > 0 for d in TTS_RETRY_DELAYS_SECONDS))


if __name__ == "__main__":
    unittest.main()
