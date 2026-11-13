"""
Configuration management for the durable dispatcher.
Loads environment variables from .env using pydantic-settings and parses fixtures.
"""
from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Guarantee .env is loaded
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(
        default="postgresql+psycopg://au:au_local_only@localhost:5432/au_assignment",
        alias="DATABASE_URL",
    )
    telephony_base_url: str = Field(
        default="http://127.0.0.1:8099",
        alias="TELEPHONY_BASE_URL",
    )
    webhook_host: str = Field(default="127.0.0.1", alias="WEBHOOK_HOST")
    webhook_port: int = Field(default=8200, alias="WEBHOOK_PORT")
    webhook_url: str = Field(
        default="http://127.0.0.1:8200/webhooks/telephony",
        alias="WEBHOOK_URL",
    )
    fixtures_path: str = Field(
        default="assignment-b-workflow/fixtures/campaigns.json",
        alias="FIXTURES_PATH",
    )
    output_csv_path: str = Field(default="final_state.csv", alias="OUTPUT_CSV_PATH")
    dispatcher_poll_interval: float = Field(
        default=0.05,
        alias="DISPATCHER_POLL_INTERVAL_SEC",
    )
    reconciler_poll_interval: float = Field(
        default=1.0,
        alias="RECONCILER_POLL_INTERVAL_SEC",
    )


settings = Settings()


@dataclass
class TenantConfig:
    tenant_id: str
    max_concurrent_calls: int


@dataclass
class CampaignWindow:
    start: str
    end: str
    days: List[str]


@dataclass
class CampaignConfig:
    campaign_id: str
    tenant_id: str
    leads_file: str
    window: CampaignWindow
    max_attempts: int


@dataclass
class RetryPolicy:
    no_answer_minutes: int
    busy_minutes: int
    failed_minutes: int


@dataclass
class FixturesData:
    sim_start: str
    timezone: str
    regulatory_window: Dict[str, str]
    window_grace_seconds: int
    retry_policy: RetryPolicy
    webhook_secret: str
    tenants: List[TenantConfig]
    campaigns: List[CampaignConfig]
    raw: Dict[str, Any] = field(default_factory=dict)


def load_fixtures(fixtures_path: Optional[str] = None) -> FixturesData:
    path = fixtures_path or settings.fixtures_path
    if not os.path.isabs(path):
        path = os.path.abspath(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    tenants = [
        TenantConfig(
            tenant_id=t["tenant_id"],
            max_concurrent_calls=t["max_concurrent_calls"],
        )
        for t in data["tenants"]
    ]

    campaigns = [
        CampaignConfig(
            campaign_id=c["campaign_id"],
            tenant_id=c["tenant_id"],
            leads_file=c["leads_file"],
            window=CampaignWindow(
                start=c["window"]["start"],
                end=c["window"]["end"],
                days=c["window"]["days"],
            ),
            max_attempts=c["max_attempts"],
        )
        for c in data["campaigns"]
    ]

    rp = RetryPolicy(
        no_answer_minutes=data["retry_policy"]["no_answer_minutes"],
        busy_minutes=data["retry_policy"]["busy_minutes"],
        failed_minutes=data["retry_policy"]["failed_minutes"],
    )

    return FixturesData(
        sim_start=data["sim_start"],
        timezone=data.get("timezone", "Asia/Kolkata"),
        regulatory_window=data["regulatory_window"],
        window_grace_seconds=data.get("window_grace_seconds", 120),
        retry_policy=rp,
        webhook_secret=data["webhook_secret"],
        tenants=tenants,
        campaigns=campaigns,
        raw=data,
    )


def load_campaign_leads(fixtures_path: str, leads_file: str) -> List[Dict[str, str]]:
    base_dir = os.path.dirname(os.path.abspath(fixtures_path))
    file_path = os.path.join(base_dir, leads_file)
    leads = []
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            leads.append(row)
    return leads
