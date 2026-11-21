"""Asynchronous invoke of the accountant package worker Lambda.

The API function calls ``Invoke`` with ``InvocationType="Event"`` and a payload
holding only the two lookup ids. The worker loads everything else from the job
item, so no user data travels in the event.
"""
from __future__ import annotations

import json
from typing import Any


class PackageInvoker:
    """Start the package worker for one job.

    Args:
        lambda_client: A boto3 Lambda client (injectable for tests).
        function_name: Name or ARN of the worker function.
    """

    def __init__(self, lambda_client: Any, function_name: str) -> None:
        self._client = lambda_client
        self._function_name = function_name

    def invoke(self, user_id: str, job_id: str) -> None:
        """Fire the worker asynchronously. Raises when the invoke is rejected."""
        self._client.invoke(
            FunctionName=self._function_name,
            InvocationType="Event",
            Payload=json.dumps({"user_id": user_id, "job_id": job_id}).encode("utf-8"),
        )
