import logging
from hashlib import sha256

from fastapi import HTTPException, status
from redis import Redis
from redis.exceptions import RedisError

from app.config import settings


logger = logging.getLogger(__name__)


def _identity_key(value: str) -> str:
    return sha256(value.strip().lower().encode()).hexdigest()


def _connection() -> Redis:
    return Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=1,
        socket_timeout=2,
        decode_responses=True,
    )


def ensure_login_allowed(email: str, client_ip: str) -> None:
    if not settings.login_rate_limit_enabled:
        return
    connection = _connection()
    account_key = f"fluvius:login:account:{_identity_key(email)}"
    ip_key = f"fluvius:login:ip:{_identity_key(client_ip)}"
    try:
        account_attempts, ip_attempts = connection.mget(account_key, ip_key)
    except RedisError as exc:
        logger.error("Rate limit de login indisponível")
        if settings.environment == "production":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Login temporariamente indisponível",
            ) from exc
        return
    finally:
        connection.close()
    limit = settings.login_rate_limit_attempts
    if int(account_attempts or 0) >= limit or int(ip_attempts or 0) >= limit * 3:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitas tentativas de login. Aguarde alguns minutos.",
            headers={"Retry-After": str(settings.login_rate_limit_window_seconds)},
        )


def record_login_failure(email: str, client_ip: str) -> None:
    if not settings.login_rate_limit_enabled:
        return
    connection = _connection()
    window = settings.login_rate_limit_window_seconds
    keys = (
        f"fluvius:login:account:{_identity_key(email)}",
        f"fluvius:login:ip:{_identity_key(client_ip)}",
    )
    try:
        pipeline = connection.pipeline()
        for key in keys:
            pipeline.incr(key)
            pipeline.expire(key, window)
        pipeline.execute()
    except RedisError:
        logger.error("Não foi possível registrar falha no rate limit de login")
    finally:
        connection.close()


def clear_account_login_failures(email: str) -> None:
    if not settings.login_rate_limit_enabled:
        return
    connection = _connection()
    try:
        connection.delete(f"fluvius:login:account:{_identity_key(email)}")
    except RedisError:
        logger.warning("Não foi possível limpar o rate limit da conta")
    finally:
        connection.close()
