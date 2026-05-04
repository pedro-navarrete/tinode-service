import json
import threading
import time
import queue
import uuid
import grpc
from typing import Optional, Dict, Any, List

from tinode_grpc import pb, pbx

from .config import settings


class TinodeError(RuntimeError):
    """Error devuelto por Tinode con código y texto."""

    def __init__(self, code: int, text: str):
        super().__init__(f"Tinode {code}: {text}")
        self.code = code
        self.text = text


class TinodeClient:
    """
    Cliente gRPC bidireccional con Tinode.
    Mantiene una sesión de admin permanente para operaciones administrativas.
    """

    def __init__(self):
        self.channel: Optional[grpc.Channel] = None
        self.stub: Optional[pbx.NodeStub] = None
        self.send_queue: "queue.Queue[pb.ClientMsg]" = queue.Queue()
        self.responses: Dict[str, Any] = {}
        self.pending_meta: Dict[str, Dict[str, List]] = {}
        self.cv = threading.Condition()
        self.running = False
        self.admin_uid: Optional[str] = None
        self.admin_token: Optional[str] = None

    # ---------- conexión ----------

    def connect(self):
        self.channel = grpc.insecure_channel(settings.tinode_grpc_host)
        self.stub = pbx.NodeStub(self.channel)
        self.running = True
        threading.Thread(target=self._stream_loop, daemon=True).start()
        self._send(pb.ClientMsg(hi=pb.ClientHi(
            id=self._next_id(), user_agent=settings.app_name,
            ver="0.22", lang="es"
        )))
        self._login_admin()

    def _login_admin(self):
        secret = f"{settings.admin_user}:{settings.admin_password}".encode()
        msg_id = self._next_id()
        self._send(pb.ClientMsg(login=pb.ClientLogin(
            id=msg_id, scheme="basic", secret=secret
        )))
        resp = self._wait(msg_id)
        self.admin_uid = resp["params"].get("user")
        self.admin_token = resp["params"].get("token")
        if not self.admin_uid:
            raise RuntimeError(f"Admin login failed: {resp}")

    def _open_stream_and_consume(self):
        def gen():
            while self.running:
                msg = self.send_queue.get()
                if msg is None:
                    break
                yield msg

        metadata = (("x-tinode-apikey", settings.tinode_api_key),)
        for srv_msg in self.stub.MessageLoop(gen(), metadata=metadata):
            self._handle(srv_msg)

    def _stream_loop(self):
        backoff = 1
        while self.running:
            try:
                self._open_stream_and_consume()
                backoff = 1
            except grpc.RpcError as e:
                print(f"gRPC stream lost: {e}. Reconnecting in {backoff}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
                try:
                    self._login_admin()
                except Exception as ee:
                    print(f"Re-login failed: {ee}")

    def _handle(self, srv_msg: pb.ServerMsg):
        if srv_msg.HasField("ctrl"):
            ctrl = srv_msg.ctrl
            params = {}
            for k, v in ctrl.params.items():
                try:
                    params[k] = json.loads(v)
                except Exception:
                    params[k] = v.decode() if isinstance(v, bytes) else v
            with self.cv:
                result = {
                    "code": ctrl.code,
                    "text": ctrl.text,
                    "topic": ctrl.topic,
                    "params": params,
                }
                # Si hay acumulador pending_meta, adjuntarlo al resultado
                if ctrl.id and ctrl.id in self.pending_meta:
                    result["meta"] = self.pending_meta.pop(ctrl.id)
                self.responses[ctrl.id] = result
                self.cv.notify_all()

        elif srv_msg.HasField("meta"):
            meta = srv_msg.meta
            msg_id = meta.id
            if not msg_id:
                return
            with self.cv:
                if msg_id not in self.pending_meta:
                    self.pending_meta[msg_id] = {"sub": [], "data": []}
                for sub in meta.sub:
                    entry = {
                        "user_id": sub.user_id,
                        "topic": sub.topic,
                        "mode": sub.mode,
                    }
                    self.pending_meta[msg_id]["sub"].append(entry)

        elif srv_msg.HasField("data"):
            data = srv_msg.data
            msg_id = data.id
            if not msg_id:
                return
            with self.cv:
                if msg_id not in self.pending_meta:
                    self.pending_meta[msg_id] = {"sub": [], "data": []}
                try:
                    content = json.loads(data.content)
                except Exception:
                    content = data.content.decode() if isinstance(data.content, bytes) else str(data.content)
                self.pending_meta[msg_id]["data"].append({
                    "seq": data.seq_id,
                    "from_user": data.from_user_id,
                    "ts": data.timestamp.ToJsonString() if data.HasField("timestamp") else None,
                    "content": content,
                })

    # ---------- helpers ----------

    def _next_id(self) -> str:
        return uuid.uuid4().hex[:8]

    def _send(self, msg: pb.ClientMsg):
        self.send_queue.put(msg)

    def _wait(self, msg_id: str, timeout: float = 10.0) -> Dict[str, Any]:
        with self.cv:
            ok = self.cv.wait_for(lambda: msg_id in self.responses, timeout)
            if not ok:
                raise TimeoutError(f"Timeout waiting for {msg_id}")
            resp = self.responses.pop(msg_id)
        if resp["code"] >= 400:
            raise TinodeError(resp["code"], resp["text"])
        return resp

    def _send_wait(self, msg: pb.ClientMsg, msg_id: str) -> Dict[str, Any]:
        self._send(msg)
        return self._wait(msg_id)

    # ---------- operaciones ----------

    def create_user(self, login: str, password: str, fn: str,
                    email: Optional[str] = None, tags=None) -> str:
        secret = f"{login}:{password}".encode()
        public = json.dumps({"fn": fn}).encode()
        all_tags = list(tags or []) + [f"basic:{login}"]
        if email:
            all_tags.append(f"email:{email}")

        msg_id = self._next_id()
        acc = pb.ClientAcc(
            id=msg_id,
            user_id="new",
            scheme="basic",
            secret=secret,
            login=False,
            tags=all_tags,
            desc=pb.SetDesc(public=public),
        )
        if email:
            acc.cred.append(pb.ClientCred(method="email", value=email))
        resp = self._send_wait(pb.ClientMsg(acc=acc), msg_id)
        return resp["params"]["user"]

    def change_password(self, user_id: str, new_password: str):
        raise NotImplementedError("Use el endpoint de auto-cambio del usuario")

    def delete_user(self, user_id: str):
        msg_id = self._next_id()
        self._send_wait(pb.ClientMsg(del_=pb.ClientDel(
            id=msg_id, topic="me", what=pb.ClientDel.USER, hard=True
        )), msg_id)

    def create_group(self, name: str, is_channel: bool = False,
                     description: str = "", tags=None) -> str:
        msg_id = self._next_id()
        public = json.dumps({"fn": name}).encode()
        private = json.dumps({"comment": description}).encode() if description else b""
        topic = "nch" if is_channel else "new"

        sub = pb.ClientSub(
            id=msg_id,
            topic=topic,
            set_query=pb.SetQuery(
                desc=pb.SetDesc(public=public, private=private),
                tags=list(tags or []),
            ),
        )
        resp = self._send_wait(pb.ClientMsg(sub=sub), msg_id)
        return resp["topic"]

    def add_member(self, group_id: str, user_id: str, mode: str = "JRWPS"):
        msg_id = self._next_id()
        msg = pb.ClientMsg()
        msg.set.CopyFrom(pb.ClientSet(
            id=msg_id,
            topic=group_id,
            query=pb.SetQuery(
                sub=pb.SetSub(user_id=user_id, mode=mode)
            ),
        ))
        self._send_wait(msg, msg_id)

    def remove_member(self, group_id: str, user_id: str):
        msg_id = self._next_id()
        self._send_wait(pb.ClientMsg(del_=pb.ClientDel(
            id=msg_id, topic=group_id, what=pb.ClientDel.SUB, user_id=user_id
        )), msg_id)

    def delete_group(self, group_id: str):
        msg_id = self._next_id()
        self._send_wait(pb.ClientMsg(del_=pb.ClientDel(
            id=msg_id, topic=group_id, what=pb.ClientDel.TOPIC, hard=True
        )), msg_id)

    def send_message(self, topic: str, content: str):
        msg_id = self._next_id()
        self._send_wait(pb.ClientMsg(pub=pb.ClientPub(
            id=msg_id, topic=topic, no_echo=True,
            content=json.dumps(content).encode()
        )), msg_id)

    def update_group(self, group_id: str, name: Optional[str] = None,
                     description: Optional[str] = None):
        msg_id = self._next_id()
        public = json.dumps({"fn": name}).encode() if name else b""
        private = json.dumps({"comment": description}).encode() if description else b""
        msg = pb.ClientMsg()
        msg.set.CopyFrom(pb.ClientSet(
            id=msg_id,
            topic=group_id,
            query=pb.SetQuery(desc=pb.SetDesc(public=public, private=private)),
        ))
        self._send_wait(msg, msg_id)

    def get_group_members(self, group_id: str) -> List[Dict[str, Any]]:
        msg_id = self._next_id()
        with self.cv:
            self.pending_meta[msg_id] = {"sub": [], "data": []}
        get_msg = pb.ClientGet(
            id=msg_id,
            topic=group_id,
            query=pb.GetQuery(what="sub"),
        )
        resp = self._send_wait(pb.ClientMsg(get=get_msg), msg_id)
        return resp.get("meta", {}).get("sub", [])

    def get_messages(self, topic: str, limit: int = 20) -> List[Dict[str, Any]]:
        msg_id = self._next_id()
        with self.cv:
            self.pending_meta[msg_id] = {"sub": [], "data": []}
        get_query = pb.GetQuery(what="data")
        get_query.data.limit = limit
        get_msg = pb.ClientGet(
            id=msg_id,
            topic=topic,
            query=get_query,
        )
        resp = self._send_wait(pb.ClientMsg(get=get_msg), msg_id)
        return resp.get("meta", {}).get("data", [])

    def search_users(self, query: str) -> List[Dict[str, Any]]:
        # Sub to fnd, set search query, get sub results
        sub_id = self._next_id()
        self._send_wait(pb.ClientMsg(sub=pb.ClientSub(
            id=sub_id, topic="fnd"
        )), sub_id)

        set_id = self._next_id()
        msg = pb.ClientMsg()
        msg.set.CopyFrom(pb.ClientSet(
            id=set_id,
            topic="fnd",
            query=pb.SetQuery(desc=pb.SetDesc(
                public=json.dumps(query).encode()
            )),
        ))
        self._send_wait(msg, set_id)

        get_id = self._next_id()
        with self.cv:
            self.pending_meta[get_id] = {"sub": [], "data": []}
        resp = self._send_wait(pb.ClientMsg(get=pb.ClientGet(
            id=get_id,
            topic="fnd",
            query=pb.GetQuery(what="sub"),
        )), get_id)
        return resp.get("meta", {}).get("sub", [])

    def get_me(self) -> Dict[str, Any]:
        msg_id = self._next_id()
        with self.cv:
            self.pending_meta[msg_id] = {"sub": [], "data": []}
        resp = self._send_wait(pb.ClientMsg(get=pb.ClientGet(
            id=msg_id,
            topic="me",
            query=pb.GetQuery(what="desc"),
        )), msg_id)
        return {
            "user_id": self.admin_uid,
            "params": resp.get("params", {}),
            "meta": resp.get("meta", {}),
        }


# Singleton
client = TinodeClient()
