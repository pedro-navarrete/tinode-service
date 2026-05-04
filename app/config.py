from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    tinode_grpc_host: str = "tinode:16060"   # dentro de docker-compose
    tinode_api_key: str = "AQEAAAABAAD_rAp4DJh05a1HAwFT3A6K"
    admin_user: str = "pnavarret"
    admin_password: str = "tu_password"
    app_name: str = "TinodeAdminAPI/1.0"

    class Config:
        env_file = ".env"

settings = Settings()