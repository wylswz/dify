from datetime import datetime
from pydantic import BaseModel
from libs.uuid_utils import uuidv7
from extensions.ext_redis import redis_client

DATA_KEY_ACCESS_TOKEN = "access_token"
DATA_KEY_REFRESH_TOKEN = "refresh_token"
TTL = 5 * 60 * 1000_000_000 # 5 minutes in nanoseconds

class Session(BaseModel):
    id: str
    data: dict[str, str]
    created_at: datetime
    ttl: int # in nanoseconds
    user_id: str

    def is_valid(self) -> bool:
        return self.created_at.microsecond + self.ttl / 1000 > datetime.now().microsecond

    def get_access_token(self) -> str:
        return self.data.get(DATA_KEY_ACCESS_TOKEN, "")
    
    def get_refresh_token(self) -> str:
        return self.data.get(DATA_KEY_REFRESH_TOKEN, "")

class SessionManager:


    @classmethod
    def _cache_key(cls, session_id: str) -> str:
        return f"dify.ai/auth/session/{session_id}"

    @classmethod
    def get_session(cls, session_id: str) -> Session | None:
        data = redis_client.get(cls._cache_key(session_id))
        if not data:
            return None
        sess: Session = Session.model_validate_json(data)
        if not sess.is_valid():
            return None
        return sess

    @classmethod
    def create_session(cls, user_id: str, data: dict[str, str]) -> Session:
        session_id = str(uuidv7())
        sess = Session(id=session_id, data=data, created_at=datetime.now(), ttl=TTL, user_id=user_id)
        redis_client.set(cls._cache_key(session_id), sess.model_dump_json())
        return sess

    @classmethod
    def create_session_from_token(cls, user_id: str, access_token: str, refresh_token: str) -> Session:
        data = {
            DATA_KEY_ACCESS_TOKEN: access_token,
            DATA_KEY_REFRESH_TOKEN: refresh_token,
        }
        return cls.create_session(user_id, data)
    
    @classmethod
    def delete_session(cls, session_id: str):
        redis_client.delete(cls._cache_key(session_id))
