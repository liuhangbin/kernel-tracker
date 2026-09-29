"""Tests for the OidField custom field."""

import pytest
from django.core.exceptions import ValidationError

from kernel_tracker.fields import validate_oid


class TestOidValidation:
    """Test OID format validation."""

    def test_valid_oid(self):
        """A 40-char lowercase hex string should pass."""
        validate_oid("a" * 40)

    def test_valid_oid_mixed_case_hex(self):
        """Lowercase hex should pass."""
        validate_oid("0123456789abcdef" * 2 + "0123456789abcdef"[:8])

    def test_invalid_oid_too_short(self):
        """A string shorter than 40 chars should fail."""
        with pytest.raises(ValidationError):
            validate_oid("a" * 39)

    def test_invalid_oid_too_long(self):
        """A string longer than 40 chars should fail."""
        with pytest.raises(ValidationError):
            validate_oid("a" * 41)

    def test_invalid_oid_uppercase(self):
        """Uppercase hex should fail."""
        with pytest.raises(ValidationError):
            validate_oid("A" * 40)

    def test_invalid_oid_non_hex(self):
        """Non-hex characters should fail."""
        with pytest.raises(ValidationError):
            validate_oid("g" * 40)
