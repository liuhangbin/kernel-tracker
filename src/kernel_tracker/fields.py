"""Custom Django field for storing git Object IDs (OIDs).

Git OIDs are 40-character hexadecimal strings (SHA-1 or SHA-256).
This field stores them as binary(20) in MariaDB for compact storage
and efficient indexing, and converts to/from hex strings in Python.
"""

import re

from django.core.exceptions import ValidationError
from django.db import models

_OID_PATTERN = re.compile(r"[a-f0-9]{40}")


def validate_oid(value):
    """Validate that the value is a 40-character lowercase hex string."""
    if not _OID_PATTERN.match(value) or len(value) != 40:
        raise ValidationError("Exactly 40 lowercase hexadecimal characters required.")


class OidField(models.Field):
    """A Django field that stores git OIDs as binary(20) in the database."""

    default_validators = [validate_oid]
    description = "Git object ID (40-hex, stored as binary(20))"

    def db_type(self, connection):
        engine = connection.settings_dict["ENGINE"]
        if engine == "django.db.backends.mysql":
            return "binary(20)"
        if engine == "django.db.backends.sqlite3":
            return "BLOB"
        raise TypeError(f"OidField unsupported for database backend: {engine}")

    def from_db_value(self, value, expression, connection, context=None):
        if value is None:
            return None
        if isinstance(value, bytes):
            if not value.lstrip(b"\x00"):
                # all zeroes -> blank
                return ""
            return value.hex()
        return value.lower()

    def get_db_prep_value(self, value, connection, prepared=False):
        value = super().get_db_prep_value(value, connection, prepared)
        if value is None:
            return None
        return connection.Database.Binary(bytes.fromhex(value))

    def get_prep_lookup(self, lookup_type, value):
        if lookup_type == "exact":
            return self.get_prep_value(value)
        if lookup_type == "in":
            return [self.get_prep_value(v) for v in value]
        raise TypeError(f"Lookup type {lookup_type} not supported.")
