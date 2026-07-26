from __future__ import annotations

import os

import jwt
from fastapi import Header, HTTPException

# Same shared secret already wired into workbench, api-gateway, and
# model-registry (docker-compose.yml's AUTH_SECRET_KEY) -- omnibioai-auth
# signs access tokens with this key (HS256) and embeds a "roles" claim
# (auth_service.generate_tokens(): roles=[r.name for r in user.roles]).
# Validating locally here (rather than calling back to omnibioai-auth)
# matches the model-registry precedent (omnibioai_model_registry/auth.py)
# for a consuming service that needs its own admin check independent of
# nginx's auth_request gate.
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me")


def require_admin(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: 401 on missing/invalid/expired token, 403 if the
    token is valid but lacks the "admin" role. Returns the decoded payload."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing or malformed Authorization header")

    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")

    if "admin" not in (payload.get("roles") or []):
        raise HTTPException(403, "Admin role required")

    return payload
