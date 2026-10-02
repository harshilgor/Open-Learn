"""Explicit offline identity guard; never a hosted authentication mechanism."""
import os
from fastapi import HTTPException


def local_identity_enabled():
    return (os.getenv("AI_TUTOR_ENV", "development").lower() in {"development", "local", "test"}
            and os.getenv("AI_TUTOR_DEV_IDENTITY", "true").lower() in {"1", "true", "yes"})


def authorize_local(learner_id, claimed):
    if not local_identity_enabled():
        raise HTTPException(503, detail={"code": "authentication_required", "message": "Verified account authentication is required."})
    if (claimed or "local") != learner_id:
        raise HTTPException(403, detail={"code": "learner_scope_mismatch", "message": "The local profile does not match this request."})
