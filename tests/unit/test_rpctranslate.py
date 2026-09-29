"""Tests for the JSON-RPC translation layer."""

import pytest
from django.test import TestCase

from kernel_tracker.rpctranslate import (
    DataWrapper,
    MultipleReturn,
    RpcError,
    RpcWarning,
    Translator,
    ValidateError,
)


class TestDataWrapper(TestCase):
    """Test the DataWrapper class."""

    def test_basic_wrap(self):
        """DataWrapper should store data and extra kwargs."""
        obj = DataWrapper("test", extra_field=42)
        assert obj.data == "test"
        assert obj.extra == {"extra_field": 42}

    def test_empty_extra(self):
        """DataWrapper with no kwargs should have empty extra."""
        obj = DataWrapper("test")
        assert obj.extra == {}


class TestMultipleReturn(TestCase):
    """Test the MultipleReturn class."""

    def test_is_list(self):
        """MultipleReturn should be a list."""
        mr = MultipleReturn([1, 2, 3])
        assert isinstance(mr, list)
        assert len(mr) == 3


class TestTranslator(TestCase):
    """Test the Translator class."""

    def test_simple_function(self):
        """Translator should handle simple typed functions."""

        def my_func(name: str, count: int = 5):
            return name

        t = Translator(my_func)
        assert "name" in t.mandatory
        assert "count" not in t.mandatory

    def test_process_request_basic(self):
        """process_request should handle basic types."""

        def my_func(name: str, count: int):
            return name

        t = Translator(my_func)
        result, _config, warnings = t.process_request({"name": "test", "count": 5})
        assert result == {"name": "test", "count": 5}
        assert warnings == []

    def test_process_request_missing_param(self):
        """process_request should raise ValidateError for missing params."""

        def my_func(name: str, count: int):
            return name

        t = Translator(my_func)
        with pytest.raises(ValidateError, match="missing parameters"):
            t.process_request({"name": "test"})

    def test_process_request_unknown_param(self):
        """process_request should raise ValidateError for unknown params."""

        def my_func(name: str):
            return name

        t = Translator(my_func)
        with pytest.raises(ValidateError, match="unknown parameter"):
            t.process_request({"name": "test", "unknown": 42})

    def test_process_request_wrong_type(self):
        """process_request should raise ValidateError for wrong types."""

        def my_func(count: int):
            return count

        t = Translator(my_func)
        with pytest.raises(ValidateError, match="wrong type"):
            t.process_request({"count": "not_an_int"})

    def test_process_response_primitives(self):
        """process_response should pass through primitives."""

        def dummy():
            pass

        t = Translator(dummy)
        assert t.process_response(42, {}) == 42
        assert t.process_response("hello", {}) == "hello"
        assert t.process_response(True, {}) is True

    def test_process_response_list(self):
        """process_response should handle lists."""

        def dummy():
            pass

        t = Translator(dummy)
        assert t.process_response([1, 2, 3], {}) == [1, 2, 3]

    def test_process_response_dict(self):
        """process_response should handle dicts."""

        def dummy():
            pass

        t = Translator(dummy)
        assert t.process_response({"a": 1}, {}) == {"a": 1}


class TestErrorClasses(TestCase):
    """Test error class hierarchy."""

    def test_rpc_error_level(self):
        assert RpcError("test").level == "user"

    def test_validate_error_level(self):
        assert ValidateError("test").level == "system"

    def test_rpc_warning_with_result(self):
        w = RpcWarning("test", result=[1, 2])
        assert w.result == [1, 2]
