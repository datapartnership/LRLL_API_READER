"""DDPLRLL Dataset Reader – Python client for the Low Resource Language Library collections API."""

from ddplrll_reader.auth import login, login_oob
from ddplrll_reader.client import DdplrllDatasetClient, preview_jsonld
from ddplrll_reader.config import Settings
from ddplrll_reader.entra_auth import (
    EntraConfig,
    acquire_api_token,
    login_entra,
    print_token_user,
    save_token,
)
from ddplrll_reader.entra_spa_auth import acquire_api_token_spa, login_entra_spa

__all__ = [
    "DdplrllDatasetClient",
    "EntraConfig",
    "Settings",
    "acquire_api_token",
    "acquire_api_token_spa",
    "login",
    "login_entra",
    "login_entra_spa",
    "login_oob",
    "preview_jsonld",
    "print_token_user",
    "save_token",
]
