from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "perception-orchestrator"
    service_version: str = "0.1.0"
    env: str = "dev"

    mqtt_host: str = "mosquitto"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None

    auth_required: bool = True
    auth_header_user: str = "Remote-User"
    auth_header_groups: str = "Remote-Groups"
    auth_trusted_proxies: list[str] = ["127.0.0.1", "10.210.0.0/16", "172.16.0.0/12"]

    ha_discovery_prefix: str = "homeassistant"
    log_level: str = "INFO"

    # Optionaler Readiness-Check: ist HEALTH_DB_PATH gesetzt, prueft /health per
    # SQLite-Probe (SELECT 1), ob die DB erreichbar ist, sonst 503. Leer = Liveness.
    health_db_path: str | None = None
    health_check_timeout: float = 5.0

    # --- Perception-spezifisch ---
    inbox_root: str = "/data/inbox"
    originals_root: str = "/data/originals/immutable"
    results_root: str = "/data/results"
    queue_db: str = "/data/state/perception.sqlite"
    nano_base_url: str = "http://192.0.2.10:8800"
    nano_token: str = ""
    dispatch_poll_seconds: float = 2.0


settings = Settings()
