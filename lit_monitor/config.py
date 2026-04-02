"""Load and validate the YAML configuration."""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class JournalConfig:
    id: str
    name: str


@dataclass
class SearchConfig:
    name: str
    keywords: list[str]


@dataclass
class EmailConfig:
    smtp_host: str
    smtp_port: int
    use_tls: bool
    sender: str
    password: str
    recipients: list[str]


@dataclass
class AppConfig:
    searches: list[SearchConfig]
    journals: list[JournalConfig]
    email: EmailConfig
    initial_lookback_days: int


def load_config(config_path: str | Path) -> AppConfig:
    """Load configuration from a YAML file."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    # Parse searches
    searches = []
    for s in raw.get("searches", []):
        searches.append(SearchConfig(
            name=s["name"],
            keywords=s["keywords"],
        ))

    if not searches:
        raise ValueError("At least one search must be configured in config.yaml")

    # Parse journals
    journals = []
    for j in raw.get("journals", []):
        journals.append(JournalConfig(id=j["id"], name=j["name"]))

    # Parse email config
    email_raw = raw.get("email", {})
    email_password = os.environ.get(email_raw.get("password_env", ""), "")

    email_config = EmailConfig(
        smtp_host=email_raw.get("smtp_host", ""),
        smtp_port=email_raw.get("smtp_port", 587),
        use_tls=email_raw.get("use_tls", True),
        sender=email_raw.get("sender", ""),
        password=email_password,
        recipients=email_raw.get("recipients", []),
    )

    return AppConfig(
        searches=searches,
        journals=journals,
        email=email_config,
        initial_lookback_days=raw.get("initial_lookback_days", 30),
    )
