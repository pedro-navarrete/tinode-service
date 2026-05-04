import base64
import json
import threading
import queue
import uuid
import grpc
from typing import Optional, Dict, Any

from tinode_grpc import pb, pbx

from .config import settings


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

    def _stream_loop(self):
        def gen():
            # Inserta API key en metadata
            while self.running:
                msg = self.send_queue.get()
                if msg is None:
                    break
                yield msg

        metadata = (("x-tinode-apikey", settings.tinode_api_key),)
        try:
            for srv_msg in self.stub.MessageLoop(gen(), metadata=metadata):
                self._handle(srv_msg)
        except grpc.RpcError as e:
            print(f"gRPC error: {e}")
            self.running = False

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
                self.responses[ctrl.id] = {
                    "code": ctrl.code,
                    "text": ctrl.text,
                    "topic": ctrl.topic,
                    "params": params,
                }
                self.cv.notify_all()

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
            raise RuntimeError(f"Tinode error {resp['code']}: {resp['text']}")
        return resp

    def _send_wait(self, msg: pb.ClientMsg, msg_id: str) -> Dict[str, Any]:
        self._send(msg)
        return self._wait(msg_id)

    # ---------- operaciones ----------

    def create_user(self, login: str, password: str, fn: str,
                    email: Optional[str] = None, tags=None) -> str:
        secret = base64.b64encode(f"{login}:{password}".encode())
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
        # Solo el propio usuario puede cambiar su password.
        # Para admin reset: borrar y recrear, o usar utilidad tinode-db.
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
        self._send_wait(pb.ClientMsg(set=pb.ClientSet(
            id=msg_id,
            topic=group_id,
            query=pb.SetQuery(
                sub=pb.SetSub(user_id=user_id, mode=mode)
            ),
        )), msg_id)

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
        self._send_wait(pb.ClientMsg(set=pb.ClientSet(
            id=msg_id,
            topic=group_id,
            query=pb.SetQuery(desc=pb.SetDesc(public=public, private=private)),
        )), msg_id)


# Singleton
client = TinodeClient()