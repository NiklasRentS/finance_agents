"""Errors shared by all provider adapters."""

from __future__ import annotations


class ProviderError(RuntimeError):
    """Base class for adapter failures."""

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(f"[{provider}] {message}")
        self.provider = provider


class ProviderUnavailableError(ProviderError):
    """The upstream service could not be reached or refused the request."""


class DataNotAvailableError(ProviderError):
    """The provider responded, but does not carry the requested data.

    Callers must translate this into an explicit N/A fact instead of
    substituting a value of their own.
    """


class CompanyNotFoundError(ProviderError):
    """The identifier could not be resolved to a company."""
