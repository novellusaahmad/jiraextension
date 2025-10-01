from __future__ import annotations

import os
from datetime import datetime
from typing import Dict

from flask import Flask, jsonify, redirect, render_template, request, url_for, flash
from requests import HTTPError

from jira_client import JiraClient, JiraConfigurationError


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "change-me")


def get_jira_client() -> JiraClient:
    if not hasattr(app, "_jira_client"):
        try:
            app._jira_client = JiraClient()
        except JiraConfigurationError as exc:  # type: ignore[attr-defined]
            app._jira_client = exc
    client = app._jira_client  # type: ignore[attr-defined]
    if isinstance(client, JiraConfigurationError):
        raise client
    return client


@app.route("/", methods=["GET"])
def index():
    error = None
    try:
        get_jira_client()
    except JiraConfigurationError as exc:
        error = str(exc)
    return render_template("index.html", config_error=error)


@app.route("/", methods=["POST"])
def create_ticket():
    summary = request.form.get("summary", "").strip()
    details = request.form.get("details", "").strip()
    start_date = request.form.get("start_date", "").strip()
    due_date = request.form.get("due_date", "").strip()

    missing = [label for label, value in (
        ("Summary", summary),
        ("Details", details),
        ("Start Date", start_date),
        ("Expected By Date", due_date),
    ) if not value]

    if missing:
        flash(f"Please fill in the mandatory fields: {', '.join(missing)}", "error")
        return redirect(url_for("index"))

    # Validate ISO format (YYYY-MM-DD)
    for label, value in (("Start Date", start_date), ("Expected By Date", due_date)):
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            flash(f"{label} must be in YYYY-MM-DD format.", "error")
            return redirect(url_for("index"))

    try:
        client = get_jira_client()
    except JiraConfigurationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("index"))

    description_lines = [
        "Details:",
        details,
        "",
        f"Start Date: {start_date}",
        f"Expected By: {due_date}",
    ]
    description = "\n".join(description_lines)

    try:
        response = client.create_issue(summary, description, start_date, due_date)
    except HTTPError as exc:
        message = str(exc)
        if exc.response is not None:
            try:
                body = exc.response.json()
            except ValueError:
                body = None
            if isinstance(body, dict):
                errors = body.get("errorMessages") or body.get("errors")
                if isinstance(errors, list):
                    message = "; ".join(errors)
                elif isinstance(errors, dict):
                    message = "; ".join(f"{field}: {error}" for field, error in errors.items())
                elif errors:
                    message = str(errors)
        flash(f"Failed to create issue: {message}", "error")
        return redirect(url_for("index"))

    issue_key = response.get("key")
    flash(f"Successfully created Jira issue {issue_key}.", "success")
    return redirect(url_for("index"))


@app.route("/api/issues/<issue_key>", methods=["GET", "PUT"])
def issue_endpoint(issue_key: str):
    try:
        client = get_jira_client()
    except JiraConfigurationError as exc:
        return jsonify({"error": str(exc)}), 500

    if request.method == "GET":
        try:
            issue = client.get_issue(issue_key)
        except HTTPError as exc:
            return jsonify({"error": str(exc), "details": exc.response.json() if exc.response else {}}), 400
        return jsonify(issue)

    payload: Dict[str, str] = request.json or {}
    try:
        result = client.update_issue(issue_key, payload.get("fields", payload))
    except HTTPError as exc:
        return (
            jsonify({"error": str(exc), "details": exc.response.json() if exc.response else {}}),
            exc.response.status_code if exc.response else 400,
        )
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8505, debug=False)
