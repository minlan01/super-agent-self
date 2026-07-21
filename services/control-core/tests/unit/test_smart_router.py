"""Tests for SmartModelRouter."""

from __future__ import annotations

import pytest

from packages.llm_gateway.smart_router import SmartModelRouter


@pytest.fixture
def router():
    return SmartModelRouter()


# ── should_use_cheap_model ─────────────────────────────────────────────────


class TestShouldUseCheapModel:
    def test_simple_greeting(self, router):
        assert router.should_use_cheap_model("hello")

    def test_simple_thanks(self, router):
        assert router.should_use_cheap_model("thanks!")

    def test_short_question(self, router):
        assert router.should_use_cheap_model("how are you?")

    def test_long_message_rejected(self, router):
        msg = "x" * 200
        assert not router.should_use_cheap_model(msg)

    def test_many_words_rejected(self, router):
        msg = " ".join(["word"] * 30)
        assert not router.should_use_cheap_model(msg)

    def test_code_block_rejected(self, router):
        assert not router.should_use_cheap_model("```python\nprint('hi')\n```")

    def test_inline_code_rejected(self, router):
        assert not router.should_use_cheap_model("use `pip install`")

    def test_url_rejected(self, router):
        assert not router.should_use_cheap_model("check https://example.com")

    def test_www_rejected(self, router):
        assert not router.should_use_cheap_model("visit www.example.com")

    def test_debug_keyword_rejected(self, router):
        assert not router.should_use_cheap_model("debug this error")

    def test_implement_keyword_rejected(self, router):
        assert not router.should_use_cheap_model("implement feature")

    def test_fix_keyword_rejected(self, router):
        assert not router.should_use_cheap_model("fix the bug")


# ── route ───────────────────────────────────────────────────────────────────


class TestRoute:
    def test_routes_simple_to_cheap(self, router):
        result = router.route("hello", cheap_provider="llamacpp", main_provider="deepseek")
        assert result == "llamacpp"

    def test_routes_complex_to_main(self, router):
        result = router.route("debug this error", cheap_provider="llamacpp", main_provider="deepseek")
        assert result == "deepseek"
