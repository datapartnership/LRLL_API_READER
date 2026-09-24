"""DDPLRLL Dataset Reader – Python client for the Nation Newspaper Dataset API."""

from ddplrll_reader.auth import login, login_oob
from ddplrll_reader.client import DdplrllDatasetClient, preview_jsonld
from ddplrll_reader.config import Settings
from ddplrll_reader.entra_auth import EntraConfig, acquire_api_token, login_entra, save_token

__all__ = [
    "DdplrllDatasetClient",
    "EntraConfig",
    "Settings",
    "acquire_api_token",
    "login",
    "login_entra",
    "login_oob",
    "preview_jsonld",
    "save_token",
]
