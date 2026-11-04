"""Persistent cache of recently fetched Jellyfin posters for offline display."""

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Optional

from PIL import Image

from displays.base import PosterDisplayItem

logger = logging.getLogger(__name__)


class PosterCache:
    def __init__(self, max_items: int = 10, cache_dir: Optional[Path] = None) -> None:
        self.max_items = max(1, max_items)
        self.cache_dir = cache_dir or Path(__file__).resolve().parent.parent / "poster_cache"
        self.manifest_path = self.cache_dir / "manifest.json"
        self._fallback_item_id: Optional[str] = None

    def _entries(self) -> list[dict[str, str]]:
        try:
            entries = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(entries, list):
            return []
        return [
            entry
            for entry in entries
            if isinstance(entry, dict)
            and isinstance(entry.get("item_id"), str)
            and isinstance(entry.get("title"), str)
            and isinstance(entry.get("filename"), str)
        ][: self.max_items]

    def add(self, item: PosterDisplayItem) -> None:
        """Store or promote an item as the most recently fetched poster."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{hashlib.sha256(item.item_id.encode('utf-8')).hexdigest()}.jpg"
        image_path = self.cache_dir / filename
        entries = self._entries()
        if (
            entries
            and entries[0]["item_id"] == item.item_id
            and entries[0]["filename"] == filename
            and image_path.is_file()
        ):
            return
        cached_file_exists = any(
            entry["item_id"] == item.item_id and entry["filename"] == filename
            for entry in entries
        ) and image_path.is_file()
        if not cached_file_exists:
            temporary_path = image_path.with_suffix(".jpg.tmp")
            item.image.convert("RGB").save(temporary_path, format="JPEG", quality=92)
            os.replace(temporary_path, image_path)

        entries = [entry for entry in entries if entry["item_id"] != item.item_id]
        entries.insert(0, {"item_id": item.item_id, "title": item.title, "filename": filename})
        entries = entries[: self.max_items]

        temp_manifest = self.manifest_path.with_suffix(".json.tmp")
        temp_manifest.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        os.replace(temp_manifest, self.manifest_path)

        keep_files = {entry["filename"] for entry in entries}
        for path in self.cache_dir.glob("*.jpg"):
            if path.name not in keep_files:
                path.unlink(missing_ok=True)

    def get_fallback(self, *, advance: bool) -> Optional[PosterDisplayItem]:
        """Return a cached poster, advancing through the recent set when requested."""
        entries = [
            entry
            for entry in self._entries()
            if (self.cache_dir / entry["filename"]).is_file()
        ]
        if not entries:
            return None

        current_index = next(
            (
                index
                for index, entry in enumerate(entries)
                if entry["item_id"] == self._fallback_item_id
            ),
            None,
        )
        if current_index is None:
            selected_index = 0
        elif advance:
            selected_index = (current_index + 1) % len(entries)
        else:
            selected_index = current_index

        for offset in range(len(entries)):
            selected = entries[(selected_index + offset) % len(entries)]
            try:
                with Image.open(self.cache_dir / selected["filename"]) as cached_image:
                    image = cached_image.convert("RGB")
            except (OSError, ValueError) as exc:
                logger.warning("Could not read cached poster '%s': %s", selected["title"], exc)
                continue

            self._fallback_item_id = selected["item_id"]
            return PosterDisplayItem(
                item_id=selected["item_id"],
                title=selected["title"],
                image=image,
                connection_lost=True,
            )
        return None
