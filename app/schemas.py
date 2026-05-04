from pydantic import BaseModel, EmailStr
from typing import Optional, List

class UserCreate(BaseModel):
    login: str
    password: str
    fn: str                    # nombre completo
    email: Optional[EmailStr] = None
    tags: List[str] = []

class UserOut(BaseModel):
    user_id: str
    login: str
    fn: str

class PasswordChange(BaseModel):
    user_id: str
    new_password: str

class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = None
    tags: List[str] = []
    is_channel: bool = False

class GroupOut(BaseModel):
    group_id: str
    name: str

class MemberAdd(BaseModel):
    user_id: str
    mode: str = "JRWPS"        # ver permisos Tinode

class MemberOut(BaseModel):
    user_id: str
    topic: Optional[str] = None
    mode: Optional[str] = None

class MessageSend(BaseModel):
    topic: str                 # userXXX o grpXXX
    content: str

class MessageOut(BaseModel):
    seq: Optional[int] = None
    from_user: Optional[str] = None
    ts: Optional[str] = None
    content: Optional[str] = None

    model_config = {"populate_by_name": True}

class UserSearchOut(BaseModel):
    user_id: Optional[str] = None
    topic: Optional[str] = None
    mode: Optional[str] = None

class MeOut(BaseModel):
    user_id: Optional[str] = None

class TopicOut(BaseModel):
    topic: str
    name: Optional[str] = None
    last_seen: Optional[str] = None
