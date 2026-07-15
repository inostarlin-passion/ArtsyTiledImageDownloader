from __future__ import annotations

import pytest

from artsy_tiled_image_downloader.validation import (
    is_http_url,
    parse_http_url,
    validate_http_url,
)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (42, "must be a string"),
        (" ", "must not be empty"),
        ("https://example.test:bad/", "not a valid URL"),
        ("ftp://example.test/file", "absolute HTTP"),
        ("https://user@example.test/file", "credentials"),
        ("https://example.test/file#fragment", "fragment"),
    ],
)
def test_parse_http_url_rejects_invalid_values(value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_http_url(value, field="test URL")


def test_validate_http_url_host_policy_and_predicate() -> None:
    assert (
        validate_http_url(
            " https://www.artsy.net/artwork/example ",
            field="artwork URL",
            allowed_hosts={"artsy.net"},
            allow_subdomains=True,
        )
        == "https://www.artsy.net/artwork/example"
    )
    with pytest.raises(ValueError, match="host must be"):
        validate_http_url(
            "https://example.test/artwork/example",
            field="artwork URL",
            allowed_hosts={"artsy.net"},
        )

    assert not is_http_url(42)
    assert not is_http_url("file:///tmp/image.png")
    assert is_http_url("https://example.test/image.png")
