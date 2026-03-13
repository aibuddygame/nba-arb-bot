"""
Configuration loading and validation module for NBA Arbitrage Bot.

This module provides:
- Pydantic models for type-safe configuration
- YAML config file loading
- Validation with helpful error messages
- Timezone-aware time handling

Usage:
    from nba_arb_bot.config import load_config, Config

    config = load_config()  # Loads from default config.yaml
    config = load_config("path/to/custom_config.yaml")  # Custom path

    # Access config values
    print(config.trade_size_usdc)
    print(config.scan_start_time)
    print(config.is_dry_run)
"""

from __future__ import annotations

import os
from datetime import time
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class LoggingConfig(BaseModel):
    """Configuration for logging behavior."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    file_enabled: bool = False
    file_path: str = "logs/nba_arb_bot.log"


class EmailConfig(BaseModel):
    """Configuration for email notifications."""

    enabled: bool = False
    sender_email: str = ""
    sender_password: str = ""  # App password, not regular password
    recipient_email: str = ""  # If empty, sends to sender_email


class Config(BaseModel):
    """
    Main configuration model for NBA Arbitrage Bot.

    All fields are validated on load. Invalid configurations will raise
    descriptive errors to help identify issues quickly.
    """

    # Scheduling
    scan_start_time: str = Field(
        default="00:00",
        description="Time of day (HH:MM in 24h format) to start scanning, in configured timezone",
    )
    scan_interval: int = Field(
        default=1,
        ge=1,
        le=24,
        description="Hours between scans (1-24)",
    )

    # Timezone
    timezone: str = Field(
        default="America/New_York",
        description="IANA timezone name for all time operations",
    )

    # Trading
    trade_size_usdc: float = Field(
        default=100.0,
        gt=0,
        description="Trade size in USDC (must be positive)",
    )
    opener_edge_threshold: float = Field(
        default=0.03,
        gt=0,
        lt=1,
        description="Minimum edge threshold as decimal (0.03 = 3%)",
    )

    # Operation mode
    dry_run: bool = Field(
        default=True,
        description="If true, simulate trades without execution",
    )

    # Logging
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    # Email notifications
    email: EmailConfig = Field(default_factory=EmailConfig)

    @field_validator("scan_start_time")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        """Validate that scan_start_time is in HH:MM format."""
        try:
            parts = v.split(":")
            if len(parts) != 2:
                raise ValueError
            hour, minute = int(parts[0]), int(parts[1])
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
            # Normalize format
            return f"{hour:02d}:{minute:02d}"
        except (ValueError, AttributeError):
            raise ValueError(
                f"scan_start_time must be in HH:MM format (24-hour), got: {v}"
            )

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        """Validate that timezone is a valid IANA timezone name."""
        try:
            import zoneinfo

            zoneinfo.ZoneInfo(v)
            return v
        except (KeyError, zoneinfo.ZoneInfoNotFoundError):
            raise ValueError(
                f"Invalid timezone: {v}. Use IANA timezone names like 'America/New_York' or 'UTC'"
            )

    @property
    def scan_start_time_parsed(self) -> time:
        """Return scan_start_time as a datetime.time object."""
        parts = self.scan_start_time.split(":")
        return time(hour=int(parts[0]), minute=int(parts[1]))

    @property
    def opener_edge_threshold_percent(self) -> float:
        """Return opener_edge_threshold as a percentage (e.g., 3.0 for 3%)."""
        return self.opener_edge_threshold * 100

    @property
    def is_dry_run(self) -> bool:
        """Alias for dry_run for more readable code."""
        return self.dry_run


def find_config_file() -> Path:
    """
    Find the config file, checking multiple locations.

    Search order:
    1. config.local.yaml (gitignored, for local overrides)
    2. config.yaml (default configuration)

    Returns:
        Path to the config file

    Raises:
        FileNotFoundError: If no config file is found
    """
    # Start from the module location and go up to find project root
    current = Path(__file__).resolve().parent

    # Go up to project root (from src/nba_arb_bot/ to project root)
    project_root = current.parent.parent

    # Check for config files in order of priority
    config_files = [
        project_root / "config.local.yaml",  # Local overrides (gitignored)
        project_root / "config.yaml",  # Default config
    ]

    for config_path in config_files:
        if config_path.exists():
            return config_path

    raise FileNotFoundError(
        f"No config file found. Searched in: {project_root}\n"
        f"Expected one of: config.yaml, config.local.yaml"
    )


def load_config(config_path: str | Path | None = None) -> Config:
    """
    Load and validate configuration from a YAML file.

    Args:
        config_path: Optional path to config file. If not provided,
                     searches for config.yaml in the project root.

    Returns:
        Validated Config object

    Raises:
        FileNotFoundError: If config file doesn't exist
        yaml.YAMLError: If config file has invalid YAML syntax
        pydantic.ValidationError: If config values fail validation

    Example:
        >>> config = load_config()
        >>> print(f"Trade size: ${config.trade_size_usdc}")
        Trade size: $100.0

        >>> print(f"Dry run: {config.is_dry_run}")
        Dry run: True
    """
    if config_path is None:
        config_path = find_config_file()
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r") as f:
        raw_config = yaml.safe_load(f)

    # Handle empty config file
    if raw_config is None:
        raw_config = {}

    return Config(**raw_config)


def get_config() -> Config:
    """
    Get the configuration, using a cached singleton pattern.

    This is useful when you need to access config from multiple places
    without passing it around or reloading from disk.

    Returns:
        Validated Config object (cached after first load)
    """
    if not hasattr(get_config, "_instance"):
        get_config._instance = load_config()
    return get_config._instance


# Allow running this module directly to validate config
if __name__ == "__main__":
    print("Loading and validating configuration...")
    try:
        config = load_config()
        print("\n✓ Configuration loaded successfully!\n")
        print(f"  Scan start time: {config.scan_start_time} ({config.timezone})")
        print(f"  Scan interval:   {config.scan_interval} hour(s)")
        print(f"  Trade size:      ${config.trade_size_usdc} USDC")
        print(f"  Edge threshold:  {config.opener_edge_threshold_percent}%")
        print(f"  Dry run:         {config.is_dry_run}")
        print(f"  Log level:       {config.logging.level}")
    except Exception as e:
        print(f"\n✗ Configuration error: {e}")
        exit(1)
