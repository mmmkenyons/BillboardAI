"""BillboardAI uploader module."""

import os
from typing import Optional

import cloudinary
import cloudinary.uploader

import config


def _configure_cloudinary() -> None:
    if not config.CLOUDINARY_CLOUD_NAME or not config.CLOUDINARY_API_KEY or not config.CLOUDINARY_API_SECRET:
        raise RuntimeError("Cloudinary credentials are required in environment variables.")

    cloudinary.config(
        cloud_name=config.CLOUDINARY_CLOUD_NAME,
        api_key=config.CLOUDINARY_API_KEY,
        api_secret=config.CLOUDINARY_API_SECRET,
        secure=True,
    )


def upload_asset(path: str, folder: str = "billboardai") -> Optional[str]:
    if not os.path.exists(path):
        return None

    _configure_cloudinary()
    result = cloudinary.uploader.upload(path, folder=folder)
    return result.get("secure_url")


def upload_assets(paths: list[str], folder: str = "billboardai") -> dict[str, Optional[str]]:
    uploaded = {}
    for path in paths:
        uploaded[path] = upload_asset(path, folder=folder)
    return uploaded


def upload():
    raise RuntimeError("Use upload_asset or upload_assets with explicit paths.")
