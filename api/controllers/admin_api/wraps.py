"""Authentication decorators for the admin API."""

from collections.abc import Callable
from functools import wraps

from flask import abort, request

from configs import dify_config


def admin_api_only[**P, R](view: Callable[P, R]) -> Callable[P, R]:
    """Require a valid ``X-Admin-Api-Key`` header.

    Aborts with 404 if ``ADMIN_API_KEY`` is not configured, and 401 if the
    supplied key does not match.
    """

    @wraps(view)
    def decorated(*args: P.args, **kwargs: P.kwargs) -> R:
        if not dify_config.ADMIN_API_KEY:
            abort(404)

        admin_api_key = request.headers.get("X-Admin-Api-Key")
        if not admin_api_key or admin_api_key != dify_config.ADMIN_API_KEY:
            abort(401)

        return view(*args, **kwargs)

    return decorated
