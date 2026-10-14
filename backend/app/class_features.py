"""Independent rollout gates. Existing evidence remains readable on rollback."""
import os
from fastapi import HTTPException

FLAGS={
    'phonePairing':'OPENLEARN_CLASS_PHONE_PAIRING_ENABLED',
    'buddy':'OPENLEARN_CLASS_BUDDY_ENABLED',
    'topicNotes':'OPENLEARN_CLASS_TOPIC_NOTES_ENABLED',
    'visualNotes':'OPENLEARN_CLASS_VISUAL_NOTES_ENABLED',
    'autoVisuals':'OPENLEARN_CLASS_AUTO_VISUALS_ENABLED',
}


def status():
    return {key:os.getenv(name,'false').lower()=='true' for key,name in FLAGS.items()}


def require(feature):
    if not status()[feature]:
        raise HTTPException(503,{'code':'class_feature_disabled','message':'This class feature is not enabled on this server.'})
