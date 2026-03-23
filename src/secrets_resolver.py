"""
Intel Sweep — Secrets Resolver

Resolves secrets from multiple backends. The config file contains
secret REFERENCES (env var names), never values. This module resolves
those references against the configured backend.

Backends:
  - env:       Environment variables (default, works everywhere)
  - dotenv:    .env file (local development)
  - gcp:       Google Cloud Secret Manager
  - aws:       AWS Secrets Manager
  - azure:     Azure Key Vault

Usage in config.yaml:
  secrets:
    backend: "env"    # or: dotenv, gcp, aws, azure

  # Backend-specific settings:
  # gcp:    project_id (from GCP_PROJECT_ID env var)
  # aws:    region (from AWS_REGION or defaults to us-east-1)
  # azure:  vault_url (from AZURE_VAULT_URL env var)
"""

import logging
import os
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("intel-sweep.secrets")


class SecretsResolver:
    """Resolves secret references to values using the configured backend."""

    def __init__(self, config: dict):
        backend_name = config.get("secrets", {}).get("backend", "env")
        self._backend = _build_backend(backend_name, config.get("secrets", {}))
        logger.info(f"Secrets backend: {backend_name}")

    def resolve(self, env_var_name: str) -> str:
        """
        Resolve a secret reference (env var name) to its actual value.
        Raises ValueError if the secret cannot be resolved.
        """
        value = self._backend.get(env_var_name)
        if not value:
            raise ValueError(
                f"Secret '{env_var_name}' could not be resolved. "
                f"Check your secrets backend configuration."
            )
        return value

    def resolve_optional(self, env_var_name: str) -> str | None:
        """Resolve a secret, returning None if not found."""
        try:
            return self._backend.get(env_var_name)
        except Exception:
            return None


class BaseSecretsBackend(ABC):
    @abstractmethod
    def get(self, key: str) -> str | None:
        """Retrieve a secret by key. Returns None if not found."""
        ...


class EnvBackend(BaseSecretsBackend):
    """Read secrets from environment variables. Zero dependencies."""

    def get(self, key: str) -> str | None:
        return os.environ.get(key)


class DotenvBackend(BaseSecretsBackend):
    """Read secrets from a .env file. For local development."""

    def __init__(self, config: dict):
        self.env_file = Path(config.get("dotenv_path", ".env"))
        self._vars: dict[str, str] = {}
        if self.env_file.exists():
            self._vars = self._parse_dotenv(self.env_file)
            logger.info(f"Loaded {len(self._vars)} secrets from {self.env_file}")
        else:
            logger.warning(f".env file not found: {self.env_file}")

    def get(self, key: str) -> str | None:
        # .env takes precedence, fall back to actual env
        return self._vars.get(key) or os.environ.get(key)

    @staticmethod
    def _parse_dotenv(path: Path) -> dict[str, str]:
        result = {}
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                # Strip optional quotes
                v = v.strip().strip("\"'")
                result[k.strip()] = v
        return result


class GCPSecretManagerBackend(BaseSecretsBackend):
    """Google Cloud Secret Manager. Requires google-cloud-secret-manager."""

    def __init__(self, config: dict):
        from google.cloud import secretmanager

        self.project_id = config.get("project_id") or os.environ.get("GCP_PROJECT_ID")
        if not self.project_id:
            raise ValueError("GCP Secret Manager requires project_id or GCP_PROJECT_ID env var")
        self.client = secretmanager.SecretManagerServiceClient()
        self._prefix = config.get("secret_prefix", "intel-sweep-")

    @lru_cache(maxsize=32)
    def get(self, key: str) -> str | None:
        secret_name = f"{self._prefix}{key.lower().replace('_', '-')}"
        name = f"projects/{self.project_id}/secrets/{secret_name}/versions/latest"
        try:
            response = self.client.access_secret_version(request={"name": name})
            return response.payload.data.decode("UTF-8")
        except Exception as e:
            logger.debug(f"GCP secret not found: {secret_name} ({e})")
            # Fall back to env var
            return os.environ.get(key)


class AWSSecretsManagerBackend(BaseSecretsBackend):
    """AWS Secrets Manager. Requires boto3."""

    def __init__(self, config: dict):
        import boto3

        region = config.get("region") or os.environ.get("AWS_REGION", "us-east-1")
        self.client = boto3.client("secretsmanager", region_name=region)
        self._prefix = config.get("secret_prefix", "intel-sweep/")

    @lru_cache(maxsize=32)
    def get(self, key: str) -> str | None:
        secret_name = f"{self._prefix}{key}"
        try:
            response = self.client.get_secret_value(SecretId=secret_name)
            return response["SecretString"]
        except Exception as e:
            logger.debug(f"AWS secret not found: {secret_name} ({e})")
            return os.environ.get(key)


class AzureKeyVaultBackend(BaseSecretsBackend):
    """Azure Key Vault. Requires azure-identity and azure-keyvault-secrets."""

    def __init__(self, config: dict):
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient

        vault_url = config.get("vault_url") or os.environ.get("AZURE_VAULT_URL")
        if not vault_url:
            raise ValueError("Azure Key Vault requires vault_url or AZURE_VAULT_URL env var")
        credential = DefaultAzureCredential()
        self.client = SecretClient(vault_url=vault_url, credential=credential)

    @lru_cache(maxsize=32)
    def get(self, key: str) -> str | None:
        # Azure Key Vault doesn't allow underscores — convert to hyphens
        secret_name = key.lower().replace("_", "-")
        try:
            secret = self.client.get_secret(secret_name)
            return secret.value
        except Exception as e:
            logger.debug(f"Azure secret not found: {secret_name} ({e})")
            return os.environ.get(key)


def _build_backend(name: str, config: dict) -> BaseSecretsBackend:
    backends = {
        "env": lambda c: EnvBackend(),
        "dotenv": DotenvBackend,
        "gcp": GCPSecretManagerBackend,
        "aws": AWSSecretsManagerBackend,
        "azure": AzureKeyVaultBackend,
    }
    if name not in backends:
        raise ValueError(f"Unknown secrets backend: {name}. Use: {list(backends)}")
    return backends[name](config)
