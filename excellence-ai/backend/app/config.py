import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the backend directory, override existing env vars
_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=_env_path, override=True)


class Settings:
    def __init__(self):
        self.groq_api_key: str   = os.getenv("GROQ_API_KEY", "").strip()
        self.groq_model: str     = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
        self.ai_temperature: float = float(os.getenv("AI_TEMPERATURE", "0.2"))

        self.app_secret_key: str = os.getenv("APP_SECRET_KEY", "dev-secret-key-change-in-production")

        self.workbook_dir: Path  = Path(os.getenv("WORKBOOK_DIR", "./data/workbooks"))
        self.upload_dir: Path    = Path(os.getenv("UPLOAD_DIR",   "./data/uploads"))

        self.enable_web_scraping: bool = os.getenv("ENABLE_WEB_SCRAPING", "true").lower() == "true"
        self.enable_ocr: bool          = os.getenv("ENABLE_OCR", "false").lower() == "true"

        self.host:  str = os.getenv("HOST",  "127.0.0.1")
        self.port:  int = int(os.getenv("PORT", "8000"))
        self.debug: bool = os.getenv("DEBUG", "true").lower() == "true"

    @property
    def backup_dir(self) -> Path:
        return self.workbook_dir / ".backups"

    def ensure_dirs(self):
        self.workbook_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    @property
    def groq_configured(self) -> bool:
        return bool(self.groq_api_key and self.groq_api_key != "your_groq_api_key_here")

    @property
    def storage_writable(self) -> bool:
        try:
            test = self.workbook_dir / ".write_test"
            test.touch()
            test.unlink()
            return True
        except Exception:
            return False


settings = Settings()
