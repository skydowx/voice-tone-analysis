#!/usr/bin/env python3
"""Generate a PBKDF2 password hash suitable for EVALUATOR_PASSWORD_HASH."""

from __future__ import annotations

import base64
import getpass
import hashlib
import secrets


password = getpass.getpass("Evaluator password: ").encode()
salt = secrets.token_bytes(18)
rounds = 600_000
digest = hashlib.pbkdf2_hmac("sha256", password, salt, rounds)
print(
    "pbkdf2_sha256$"
    + str(rounds)
    + "$"
    + base64.urlsafe_b64encode(salt).decode()
    + "$"
    + base64.urlsafe_b64encode(digest).decode()
)
