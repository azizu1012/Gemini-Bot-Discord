import asyncio
import os
import shutil
import time

from src.core.config import logger, FILE_STORAGE_PATH, FILE_CHUNK_DIR, MIN_FREE_SPACE_MB


class CleanupManager:
    """Manager for cleaning up old files and managing disk space."""

    def __init__(
        self,
        storage_path: str = FILE_STORAGE_PATH,
        min_free_mb: int = MIN_FREE_SPACE_MB,
        min_age_hours: int = 24,
    ):
        self.storage_path = storage_path
        self.min_free_mb = min_free_mb
        self.min_age_seconds = min_age_hours * 3600
        self.logger = logger

    def get_disk_free_space_mb(self) -> int:
        """Get free disk space in MB."""
        try:
            os.makedirs(self.storage_path, exist_ok=True)
            total, used, free = shutil.disk_usage(self.storage_path)
            return free // (1024 * 1024)
        except Exception as e:
            self.logger.error(f"Error checking disk free space at {self.storage_path}: {e}")
            return 0

    async def cleanup_local_files(self) -> None:
        """Clean up old local files if disk space is below threshold.

        Runs the heavy synchronous disk I/O off the event loop so we do not
        block other async tasks while walking/removing files.
        """
        try:
            await asyncio.to_thread(self._run_cleanup)
        except Exception as e:
            self.logger.error(f"Critical error during file cleanup: {e}")

    def _run_cleanup(self) -> None:
        """Synchronous cleanup body — intended to run inside a worker thread."""
        try:
            current_free_space = self.get_disk_free_space_mb()

            if current_free_space > self.min_free_mb:
                self.logger.info(f"Free space: {current_free_space} MB. No cleanup needed.")
                return

            self.logger.warning(
                f"Free space: {current_free_space} MB (below {self.min_free_mb} MB). Starting file cleanup..."
            )

            files_to_delete = []
            now = time.time()

            # Collect old files from both the uploaded-file storage and the
            # output chunk directory (e.g. data/file_chunks/**).
            for base_dir in (self.storage_path, FILE_CHUNK_DIR):
                if not os.path.isdir(base_dir):
                    continue
                for root, _, files in os.walk(base_dir):
                    for name in files:
                        path = os.path.join(root, name)
                        try:
                            # Skip fresh/active files (recently written or read).
                            last_activity = max(
                                os.path.getmtime(path),
                                os.path.getatime(path),
                            )
                            if now - last_activity < self.min_age_seconds:
                                continue
                            files_to_delete.append((path, last_activity))
                        except OSError:
                            continue

            # Sort by activity time (oldest first)
            files_to_delete.sort(key=lambda x: x[1])

            total_deleted_size = 0.0
            deleted_count = 0

            # Delete files until we reach threshold
            for path, _ in files_to_delete:
                try:
                    size_mb = os.path.getsize(path) / (1024 * 1024)
                    os.remove(path)
                    total_deleted_size += size_mb
                    deleted_count += 1
                    self.logger.info(f"Deleted old local file: {path} ({size_mb:.2f} MB)")

                    current_free_space = self.get_disk_free_space_mb()
                    if current_free_space > self.min_free_mb + 50:
                        self.logger.info(f"Cleanup complete. Free space: {current_free_space} MB")
                        break
                except Exception as e:
                    self.logger.error(f"Error deleting file {path}: {e}")

            self.logger.info(
                f"File cleanup completed. Deleted {deleted_count} files. Total size: {total_deleted_size:.2f} MB."
            )

        except Exception as e:
            self.logger.error(f"Critical error during file cleanup: {e}")
