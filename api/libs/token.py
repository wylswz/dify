
from flask import Request

from constants import COOKIE_NAME_ACCESS_TOKEN


def _try_extract_from_header(request: Request) -> str | None:
    """
    Try to extract access token from header
    """
    auth_header = request.headers.get("Authorization")
    if auth_header:
        if " " not in auth_header:
            return None
        else:
            auth_scheme, auth_token = auth_header.split(None, 1)
            auth_scheme = auth_scheme.lower()
            if auth_scheme != "bearer":
                return None
            else:
                return auth_token


def _try_extract_from_cookie(request: Request) -> str | None:
    """
    Try to extract access token from cookie
    """
    return request.cookies.get(COOKIE_NAME_ACCESS_TOKEN)


def _try_extract_from_query(request: Request) -> str | None:
    """
    Try to extract access token from query parameter
    """
    return request.args.get("_token")


def extract_access_token(request: Request) -> str | None:
    """
    Try to extract access token from cookie, header or params.
    """
    ret = _try_extract_from_cookie(request) or _try_extract_from_header(request) or _try_extract_from_query(request)
    return ret
