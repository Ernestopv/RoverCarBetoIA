"""Helpers to build the MediaMTX URLs.

The backend only needs the *ingress* URL (RTSP, to publish). The browser builds
its own *egress* URL from these values plus its own hostname.
"""

from __future__ import annotations


def normalize_path(path: str) -> str:
    """Return a clean stream path, without surrounding slashes."""
    return path.strip().strip("/")


def publish_url(host: str, port: int, path: str) -> str:
    """RTSP URL the camera publishes its stream to."""
    return f"rtsp://{host}:{port}/{normalize_path(path)}"


def whep_path(path: str) -> str:
    """Path appended to the MediaMTX WebRTC origin to receive the stream."""
    return f"/{normalize_path(path)}/whep"
