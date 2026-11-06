"""Named reviewer accounts with scrypt password hashes and explicit clinic scopes."""
import base64
import binascii
from functools import lru_cache
import hashlib
import hmac
import json
import os
import re
import secrets


class AuthConfigError(ValueError):
    pass


def hash_password(password):
    if len(password) < 16:
        raise ValueError('Use a reviewer password with at least 16 characters.')
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return 'scrypt$' + salt + '$' + digest


def verify_password(password, encoded):
    try:
        algorithm, salt, expected = encoded.split('$')
        if algorithm != 'scrypt' or not re.fullmatch(r'[0-9a-f]{32}', salt) or not re.fullmatch(r'[0-9a-f]{128}', expected):
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


@lru_cache(maxsize=4)
def parse_accounts(raw):
    try:
        accounts = json.loads(raw)
        if not isinstance(accounts, dict) or not accounts:
            raise ValueError()
        for username, settings in accounts.items():
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', username) or not isinstance(settings, dict):
                raise ValueError()
            encoded = settings.get('password_hash', '')
            if not re.fullmatch(r'scrypt\$[0-9a-f]{32}\$[0-9a-f]{128}', encoded):
                raise ValueError()
            clinics = settings.get('clinic_ids')
            if not isinstance(clinics, list) or not clinics or any(not isinstance(c, str) or not re.fullmatch(r'\d+', c) for c in clinics):
                raise ValueError()
        return accounts
    except (ValueError, TypeError):
        raise AuthConfigError('REVIEW_ACCOUNTS_JSON must contain named users, scrypt password hashes and explicit numeric clinic_ids. Wildcard clinic access is not allowed.') from None


def credentials(header):
    try:
        scheme, token = header.split(' ', 1)
        if scheme.lower() != 'basic':
            return None
        return base64.b64decode(token, validate=True).decode('utf-8').split(':', 1)
    except (ValueError, UnicodeError, binascii.Error):
        return None


def authenticate_account(header, accounts):
    supplied = credentials(header)
    if not supplied:
        return None
    username, password = supplied
    settings = accounts.get(username)
    # Perform the same password-hash computation for an unknown username.
    encoded = settings['password_hash'] if settings else 'scrypt$' + '00' * 16 + '$' + '00' * 64
    valid = verify_password(password, encoded)
    return tuple(settings['clinic_ids']) if settings and valid else None
