import io
import json
import unittest
import urllib.error
from scripts.sarashina_copy_review import review, ReviewError


class CopyReviewTests(unittest.TestCase):
    def setUp(self):
        self.items = [{"id": "a", "context": "保存失敗", "original": "再試行してください", "facts": ["未保存"]}]

    def response(self, candidates=None):
        rows = candidates or [{"title": "保存できませんでした", "body": "もう一度お試しください", "button": "保存する"}] * 3
        return io.StringIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(
            {"items": [{"id": "a", "candidates": rows}]})}}]}))

    def test_fixed_endpoint_and_redacted_key(self):
        def opener(request, timeout):
            self.assertEqual(request.full_url, "https://api.sarashina.ai/v1/chat/completions")
            self.assertEqual(timeout, 60)
            return self.response([{"title": "secret-value", "body": "候補", "button": "保存する"}] * 3)
        result = review(self.items, key="secret-value", opener=opener)
        self.assertNotIn("secret-value", json.dumps(result))
        self.assertTrue(result["requires_meaning_review"])

    def test_http_error_does_not_expose_response_or_key(self):
        def opener(*args, **kwargs):
            raise urllib.error.HTTPError("https://example.test/secret-value", 403, "secret-value", {}, None)
        with self.assertRaisesRegex(ReviewError, "^http_403$"):
            review(self.items, key="secret-value", opener=opener)

    def test_missing_facts_does_not_make_request(self):
        self.items[0]["facts"] = []
        with self.assertRaisesRegex(ReviewError, "facts_required"):
            review(self.items, key="secret-value", opener=lambda *a, **k: self.fail("must not call API"))

    def test_missing_candidate_is_rejected(self):
        with self.assertRaisesRegex(ReviewError, "invalid_output_shape"):
            review(self.items, key="secret-value", opener=lambda *a, **k: self.response(
                [{"title": "候補", "body": "候補", "button": "保存する"}]))


if __name__ == '__main__':
    unittest.main()
