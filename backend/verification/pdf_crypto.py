"""Password-protected-PDF handling — detect encryption and validate the unlock password.

Government and bank documents ship password-locked by default: the Aadhaar PDF from myAadhaar, CAMS/
Karvy CAS, and most bank e-statements. The honest way to read them is to take the password from the
applicant **in-app** and decrypt **in memory** at each consumer (signature reader, page renderer,
structure parser) — never re-saving the file. A 3rd-party "remove password" tool rewrites the file,
which changes the bytes the digital signature covers and **destroys the signature** (verified in
tests/test_pdf_password.py). These helpers are the cheap, pure detection/validation used at the intake
boundary so the API can ask for a password instead of failing closed on a perfectly legitimate doc.

The password is held only for the request and is never logged or persisted (CLAUDE.md §10).
"""

from __future__ import annotations

import io

import pikepdf


def is_pdf_encrypted(file_bytes: bytes | None) -> bool:
    """True iff the bytes are a PDF that needs a password to read its content.

    Fail-safe: anything that is not a parseable, password-protected PDF returns ``False`` so the normal
    pipeline (and its own error handling) takes over — we only divert to the password prompt for a
    genuinely encrypted PDF.
    """
    if not file_bytes:
        return False
    try:
        with pikepdf.open(io.BytesIO(file_bytes)):
            return False
    except pikepdf.PasswordError:
        return True
    except Exception:  # noqa: BLE001 — not a parseable PDF; let the normal path report it
        return False


def password_unlocks(file_bytes: bytes, password: str | None) -> bool:
    """True iff ``password`` opens the encrypted PDF. Used to reject a wrong password at the boundary
    before any analyzer runs (so the applicant gets a clear retry, not a confusing downstream error)."""
    if not file_bytes:
        return False
    try:
        with pikepdf.open(io.BytesIO(file_bytes), password=password or ""):
            return True
    except pikepdf.PasswordError:
        return False
    except Exception:  # noqa: BLE001 — unparseable for some other reason → not a usable unlock
        return False
