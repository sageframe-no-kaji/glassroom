"""Tests for the pure (non-Playwright) helpers in src/classroom.py.

The browser-driving functions are covered via mocks elsewhere; here we lock in
the session/host-detection logic that caused a real login bug: the Google
sign-in redirect URL carries 'classroom.google.com' in its query string, so a
substring check mistakes the login page for a valid session.
"""

import pytest

from src.classroom import SessionExpiredError, _check_session, _is_classroom_url

# A representative sign-in redirect: note 'classroom.google.com' appears inside
# the continue=/followup= params even though the host is accounts.google.com.
SIGNIN_URL = (
    "https://accounts.google.com/v3/signin/confirmidentifier?authuser=0"
    "&continue=https%3A%2F%2Fclassroom.google.com%2F"
    "&followup=https%3A%2F%2Fclassroom.google.com%2F&service=classroom"
)


class TestIsClassroomUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://classroom.google.com",
            "https://classroom.google.com/",
            "https://classroom.google.com/h",
            "https://classroom.google.com/u/0/h",
            "https://classroom.google.com/w/abc/t/all",
        ],
    )
    def test_true_for_classroom_host(self, url: str) -> None:
        assert _is_classroom_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            SIGNIN_URL,
            "https://accounts.google.com/",
            "http://classroom.google.com/",  # wrong scheme, not the real host
            "",
        ],
    )
    def test_false_for_non_classroom_host(self, url: str) -> None:
        assert _is_classroom_url(url) is False


class _FakePage:
    def __init__(self, url: str) -> None:
        self.url = url


class TestCheckSession:
    def test_raises_on_signin_redirect(self) -> None:
        with pytest.raises(SessionExpiredError):
            _check_session(_FakePage(SIGNIN_URL))  # type: ignore[arg-type]

    def test_passes_on_classroom_homepage(self) -> None:
        # No exception == valid session.
        _check_session(_FakePage("https://classroom.google.com/h"))  # type: ignore[arg-type]
