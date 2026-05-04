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

class MessageSend(BaseModel):
    topic: str                 # userXXX o grpXXX
    content: str

class TopicOut(BaseModel):
    topic: str
    name: Optional[str] = None
    last_seen: Optional[str] = None