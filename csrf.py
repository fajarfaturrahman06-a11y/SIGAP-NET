"""CSRF protection decorator shared by legacy and SIGAP-NET routes."""
from functools import wraps

from flask import request, abort

from security import validate_csrf_token


def csrf_protect(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            token = (request.headers.get('X-CSRF-Token')
                     or request.form.get('csrf_token'))
            if not token:
                payload = request.get_json(silent=True)
                if isinstance(payload, dict):
                    token = payload.get('csrf_token')
            if not validate_csrf_token(token):
                abort(403, 'Invalid CSRF token')
        return view(*args, **kwargs)
    return wrapped
