"""Utility client for interacting with Jira's REST API."""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

import requests
import yaml

logger = logging.getLogger(__name__)


class JiraConfigurationError(RuntimeError):
    """Raised when Jira configuration is missing required fields."""


@dataclass
class JiraSettings:
    base_url: str
    email: str
    api_token: str
    project_key: str
    issue_type: str
    start_date_field_id: Optional[str] = None

    @property
    def auth_header(self) -> str:
        token = f"{self.email}:{self.api_token}".encode("utf-8")
        return base64.b64encode(token).decode("utf-8")


def load_settings(path: str = "config/jira_config.yml") -> JiraSettings:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            content = yaml.safe_load(handle) or {}
    except FileNotFoundError as exc:
        raise JiraConfigurationError(
            "Jira configuration file not found. Expected at config/jira_config.yml"
        ) from exc

    jira_config = content.get("jira") or {}
    required = ["base_url", "email", "api_token", "project_key", "issue_type"]
    missing = [field for field in required if not jira_config.get(field)]
    if missing:
        raise JiraConfigurationError(
            f"Missing Jira configuration values: {', '.join(missing)}"
        )

    return JiraSettings(
        base_url=jira_config["base_url"].rstrip("/"),
        email=jira_config["email"],
        api_token=jira_config["api_token"],
        project_key=jira_config["project_key"],
        issue_type=jira_config["issue_type"],
        start_date_field_id=jira_config.get("start_date_field_id"),
    )


def _text_to_adf(text: str) -> Dict[str, Any]:
    """Convert plain-text content into a minimal Atlassian Document Format payload."""

    # Split into paragraphs on double newlines while preserving intentional blank lines
    blocks = text.split("\n\n") if text else [""]
    adf_paragraphs = []

    for block in blocks:
        lines = block.split("\n") if block else [""]
        content: List[Dict[str, Any]] = []
        for index, line in enumerate(lines):
            if line:
                content.append({"type": "text", "text": line})
            if index < len(lines) - 1:
                content.append({"type": "hardBreak"})
        paragraph: Dict[str, Any] = {"type": "paragraph"}
        if content:
            paragraph["content"] = content
        adf_paragraphs.append(paragraph)

    return {"type": "doc", "version": 1, "content": adf_paragraphs}


def _ensure_adf(description: Union[str, Dict[str, Any], None]) -> Dict[str, Any]:
    """Ensure the payload is valid ADF, converting raw strings when necessary."""

    if description is None:
        return _text_to_adf("")
    if isinstance(description, dict):
        return description
    return _text_to_adf(description)


class JiraClient:
    """Simple Jira client for creating and retrieving issues."""

    def __init__(self, settings: Optional[JiraSettings] = None) -> None:
        self.settings = settings or load_settings()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Basic {self.settings.auth_header}",
            }
        )

    def _url(self, path: str) -> str:
        return f"{self.settings.base_url}{path}"

    def create_issue(
        self,
        summary: str,
        description: Union[str, Dict[str, Any]],
        start_date: Optional[str],
        due_date: Optional[str],
    ) -> Dict[str, Any]:
        fields: Dict[str, Any] = {
            "project": {"key": self.settings.project_key},
            "summary": summary,
            "issuetype": {"name": self.settings.issue_type},
        }

        if due_date:
            fields["duedate"] = due_date

        if start_date and self.settings.start_date_field_id:
            fields[self.settings.start_date_field_id] = start_date

        fields["description"] = _ensure_adf(description)

        payload = {"fields": fields}
        response = self.session.post(self._url("/rest/api/3/issue"), json=payload, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_issue(self, issue_key: str) -> Dict[str, Any]:
        response = self.session.get(self._url(f"/rest/api/3/issue/{issue_key}"), timeout=30)
        response.raise_for_status()
        return response.json()

    def update_issue(self, issue_key: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        if "description" in fields:
            fields = dict(fields)
            fields["description"] = _ensure_adf(fields["description"])
        response = self.session.put(
            self._url(f"/rest/api/3/issue/{issue_key}"), json={"fields": fields}, timeout=30
        )
        response.raise_for_status()
        return response.json() if response.text else {"status": "success"}
