import base64
import hashlib

from cryptography.fernet import Fernet
from django.conf import settings


def _fernet():
    if settings.TOKEN_ENCRYPTION_KEY:
        try:
            return Fernet(settings.TOKEN_ENCRYPTION_KEY.encode())
        except Exception:
            # اگر کلید نامعتبر بود، برای جلوگیری از crash در local dev
            # از derivation key استفاده می‌کنیم.
            pass

    derived_key = base64.urlsafe_b64encode(
        hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    )
    return Fernet(derived_key)


def encrypt_secret(value: str) -> bytes:
    return _fernet().encrypt(value.encode())


def decrypt_secret(value) -> str:
    if not value:
        return ""

    try:
        return _fernet().decrypt(bytes(value)).decode()
    except Exception:
        return ""