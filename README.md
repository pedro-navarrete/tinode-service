# Tinode Service — API REST para Tinode

API REST en **FastAPI** que envuelve el protocolo gRPC de [Tinode](https://github.com/tinode/chat) para gestionar usuarios, grupos y mensajes desde cualquier frontend (Next.js, Android, etc.).

---

## 🏗️ Arquitectura

```
Cliente (Next.js / Android)
        │  HTTP REST
        ▼
  FastAPI (puerto 8000)
        │  gRPC (puerto 16060)
        ▼
  Tinode Server (puerto 6060 WebSocket / 16060 gRPC)
        │  MySQL DSN
        ▼
  MySQL 8.0 (puerto 3306)
```

---

## 🚀 Setup paso a paso

### 1. Clonar el repositorio

```bash
git clone https://github.com/pedro-navarrete/tinode-service.git
cd tinode-service
```

### 2. Configurar variables de entorno

```bash
cp .env.example .env
```

Edita `.env` con tus valores reales:

```dotenv
MYSQL_ROOT_PASSWORD=tu_password_seguro
AUTH_TOKEN_KEY=genera_con_openssl_rand_base64_32
TINODE_API_KEY=AQEAAAABAAD_rAp4DJh05a1HAwFT3A6K
ADMIN_USER=pnavarret
ADMIN_PASSWORD=tu_password_admin
```

Para generar `AUTH_TOKEN_KEY`:

```bash
openssl rand -base64 32
```

### 3. Arrancar todos los servicios

```bash
docker compose up -d --build
```

### 4. Verificar que todo funciona

```bash
# Health check de la API
curl http://localhost:8000/health

# Swagger / OpenAPI docs
open http://localhost:8000/docs
```

---

## 📋 Tabla de endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/health` | Estado del servicio |
| `GET` | `/me` | Info del admin conectado |
| `POST` | `/users` | Crear usuario nuevo |
| `DELETE` | `/users/{user_id}` | Borrar usuario (no soportado vía protocolo) |
| `POST` | `/users/search?q=texto` | Buscar usuarios por nombre/email |
| `POST` | `/groups` | Crear grupo o canal |
| `PATCH` | `/groups/{group_id}` | Actualizar nombre/descripción del grupo |
| `DELETE` | `/groups/{group_id}` | Eliminar grupo |
| `GET` | `/groups/{group_id}/members` | Listar miembros del grupo |
| `POST` | `/groups/{group_id}/members` | Añadir miembro al grupo |
| `DELETE` | `/groups/{group_id}/members/{user_id}` | Eliminar miembro del grupo |
| `POST` | `/messages` | Enviar mensaje a un topic |
| `GET` | `/messages/{topic}?limit=20` | Obtener histórico de mensajes |

---

## 👤 Crear el primer admin

La primera vez que arrancas, debes crear el usuario admin desde TinodeWeb:

1. Abre `http://localhost:6060` en el navegador.
2. Regístrate con el usuario definido en `ADMIN_USER` y el password en `ADMIN_PASSWORD`.
3. Reinicia la API: `docker compose restart tinode-api`.

La API hará login automático con esas credenciales al arrancar.

> ⚠️ Si `RESET_DB=true`, la base de datos se borra en cada reinicio. Úsalo **solo** la primera vez. Déjalo en `false` para no perder datos.

---

## 🔐 Permisos (mode)

Tinode usa un string de permisos para los miembros de un topic:

| Letra | Permiso |
|-------|---------|
| `J` | Join — puede suscribirse |
| `R` | Read — puede leer mensajes |
| `W` | Write — puede escribir mensajes |
| `P` | Presence — puede ver presencia |
| `S` | Share — puede invitar a otros |
| `A` | Admin — puede cambiar metadata |
| `D` | Delete — puede borrar mensajes |
| `O` | Owner — dueño del topic |

Ejemplo para miembro normal: `JRWPS`
Ejemplo para admin del grupo: `JRWPSAD`
Ejemplo para owner: `JRWPSADO`

---

## 🔧 Troubleshooting

### La API no arranca / error de conexión gRPC

```bash
docker compose logs tinode-api
docker compose logs tinode
```

Verifica que Tinode esté saludable antes que la API conecte:

```bash
docker compose ps
```

### Error 401 en login admin

- Comprueba que `ADMIN_USER` y `ADMIN_PASSWORD` en `.env` coinciden con el usuario creado en TinodeWeb.
- Si creaste el usuario después de arrancar la API, reinicia: `docker compose restart tinode-api`.

### Error `cannot import name 'pbx'`

Versión de `tinode-grpc` incorrecta. Verifica que `requirements.txt` tiene `tinode-grpc==0.22.6`.

### Tinode se reinicia y la API se queda colgada

La API tiene reconexión automática con backoff exponencial (1s → 2s → 4s → ... → 30s). Espera unos segundos y vuelve a intentar la llamada.

### `RESET_DB: "true"` borró mis datos

Los datos de MySQL están en el volumen `mysql_data`. Si `RESET_DB=true`, Tinode los borra. Cambia a `RESET_DB=false` inmediatamente tras la primera instalación.

---

## 📚 Recursos

- [Documentación oficial de Tinode](https://github.com/tinode/chat/blob/master/docs/API.md)
- [Tinode gRPC API](https://github.com/tinode/chat/blob/master/pbx/pbx.proto)
- [FastAPI docs](https://fastapi.tiangolo.com/)
