from services.login_rate_limit import LoginRateLimiter


def test_login_limiter_blocks_both_account_and_source_then_clears() -> None:
    limiter = LoginRateLimiter()
    limiter.max_failures = 2
    limiter.window_seconds = 60
    limiter.lock_seconds = 60
    keys = limiter.keys("203.0.113.10", "Owner@Example.com")

    assert limiter.retry_after(keys) == 0
    assert limiter.record_failure(keys) == 0
    assert limiter.record_failure(keys) > 0
    assert limiter.retry_after(keys) > 0

    limiter.clear(keys)
    assert limiter.retry_after(keys) == 0


def test_login_limiter_normalizes_account_without_retaining_email() -> None:
    limiter = LoginRateLimiter()
    assert limiter.account_key(" Owner@Example.com ") == limiter.account_key("owner@example.com")
    assert "owner@example.com" not in limiter.account_key("owner@example.com")
