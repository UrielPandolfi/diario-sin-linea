from sqlalchemy.orm import Session

from app.models.app_setting import AUTO_POLL_ENABLED_KEY, AppSetting


class AppSettingsService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def is_auto_poll_enabled(self) -> bool:
        row = self.session.get(AppSetting, AUTO_POLL_ENABLED_KEY)
        if row is None:
            return True
        return bool(row.enabled)

    def set_auto_poll_enabled(self, enabled: bool) -> bool:
        row = self.session.get(AppSetting, AUTO_POLL_ENABLED_KEY)
        if row is None:
            row = AppSetting(key=AUTO_POLL_ENABLED_KEY, enabled=enabled)
            self.session.add(row)
        else:
            row.enabled = enabled
        self.session.flush()
        return bool(row.enabled)

    def ingestion_payload(self) -> dict:
        return {"auto_poll_enabled": self.is_auto_poll_enabled()}
