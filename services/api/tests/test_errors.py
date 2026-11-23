import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.errors import http_error_handler, unexpected_error_handler, validation_error_handler


def make_request() -> Request:
    return Request({"type": "http", "headers": []})


@pytest.mark.asyncio
async def test_validation_error_hides_internal_details() -> None:
    response = await validation_error_handler(make_request(), ValueError("secret detail"))

    assert response.status_code == 422
    assert b"secret detail" not in response.body


@pytest.mark.asyncio
async def test_http_error_uses_a_generic_public_message() -> None:
    response = await http_error_handler(make_request(), HTTPException(403, "private detail"))

    assert response.status_code == 403
    assert b"private detail" not in response.body


@pytest.mark.asyncio
async def test_unexpected_error_hides_internal_details() -> None:
    response = await unexpected_error_handler(make_request(), RuntimeError("secret detail"))

    assert response.status_code == 500
    assert b"secret detail" not in response.body
