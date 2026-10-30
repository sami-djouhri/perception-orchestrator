# Diese Felder werden manuell in app/config.py ergaenzt (siehe install-Notiz).
# Hier nur als Referenz, NICHT importieren.

class _PerceptionExtras:
    inbox_root: str = "/data/inbox"
    originals_root: str = "/data/originals/immutable"
    results_root: str = "/data/results"
    queue_db: str = "/data/state/perception.sqlite"
    nano_base_url: str = "http://192.0.2.10:8800"
    nano_token: str = ""  # via .env: NANO_TOKEN=...
    dispatch_poll_seconds: float = 2.0
