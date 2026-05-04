from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from .tinode_client import client
from .schemas import (
    UserCreate, UserOut, GroupCreate, GroupOut,
    MemberAdd, MessageSend
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    client.connect()
    yield
    client.running = False

app = FastAPI(
    title="Tinode Admin API",
    version="1.0",
    description="REST API para gestionar Tinode (usuarios, grupos, mensajes)",
    lifespan=lifespan,
)

# ---------- Health ----------
@app.get("/health")
def health():
    return {"status": "ok", "admin": client.admin_uid}

# ---------- USERS ----------
@app.post("/users", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate):
    try:
        uid = client.create_user(
            login=payload.login,
            password=payload.password,
            fn=payload.fn,
            email=payload.email,
            tags=payload.tags,
        )
        return UserOut(user_id=uid, login=payload.login, fn=payload.fn)
    except Exception as e:
        raise HTTPException(400, str(e))

@app.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: str):
    # NOTA: Tinode solo permite que cada usuario borre su propia cuenta.
    # Para borrado administrativo hace falta un script con privilegios o
    # acceso directo a la BD. Aquí se deja como ejemplo del patrón.
    raise HTTPException(501, "Borrado admin no soportado por protocolo. Usa tinode-db.")

# ---------- GROUPS ----------
@app.post("/groups", response_model=GroupOut, status_code=201)
def create_group(payload: GroupCreate):
    try:
        gid = client.create_group(
            name=payload.name,
            is_channel=payload.is_channel,
            description=payload.description or "",
            tags=payload.tags,
        )
        return GroupOut(group_id=gid, name=payload.name)
    except Exception as e:
        raise HTTPException(400, str(e))

@app.patch("/groups/{group_id}")
def update_group(group_id: str, payload: GroupCreate):
    try:
        client.update_group(group_id, name=payload.name, description=payload.description)
        return {"updated": True}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.delete("/groups/{group_id}", status_code=204)
def delete_group(group_id: str):
    try:
        client.delete_group(group_id)
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post("/groups/{group_id}/members", status_code=201)
def add_member(group_id: str, payload: MemberAdd):
    try:
        client.add_member(group_id, payload.user_id, payload.mode)
        return {"added": True}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.delete("/groups/{group_id}/members/{user_id}", status_code=204)
def remove_member(group_id: str, user_id: str):
    try:
        client.remove_member(group_id, user_id)
    except Exception as e:
        raise HTTPException(400, str(e))

# ---------- MESSAGES ----------
@app.post("/messages", status_code=202)
def send_message(payload: MessageSend):
    try:
        client.send_message(payload.topic, payload.content)
        return {"sent": True}
    except Exception as e:
        raise HTTPException(400, str(e))