import os
import asyncio
from datetime import datetime
import shutil
from core.config import config
from core.logger import logger

def get_disk_free_space_mb(path: str) -> int:
    """Kiểm tra dung lượng trống của ổ đĩa (MB)."""
    try:
        # Đảm bảo đường dẫn tồn tại để kiểm tra
        os.makedirs(path, exist_ok=True)
        total, used, free = shutil.disk_usage(path)
        return free // (1024 * 1024)
    except Exception as e:
        logger.error(f"Lỗi kiểm tra dung lượng ổ đĩa tại {path}: {e}")
        return 0

async def cleanup_local_files():
    """
    Dọn dẹp file trong thư mục config.FILE_STORAGE_PATH nếu dung lượng trống dưới ngưỡng.
    Ưu tiên xóa các file cũ nhất (dựa trên thời gian truy cập cuối).
    """
    try:
        current_free_space = get_disk_free_space_mb(config.FILE_STORAGE_PATH)
        
        if current_free_space > config.MIN_FREE_SPACE_MB:
            logger.info(f"Dung lượng trống: {current_free_space} MB. Không cần dọn dẹp file local.")
            return

        logger.warning(f"Dung lượng trống còn {current_free_space} MB (dưới ngưỡng {config.MIN_FREE_SPACE_MB} MB). Bắt đầu dọn dẹp file local...")
        
        files_to_delete = []
        
        # Lấy danh sách file và thời gian truy cập gần nhất (access time)
        for root, _, files in os.walk(config.FILE_STORAGE_PATH):
            for name in files:
                path = os.path.join(root, name)
                try:
                    # Lấy thời gian truy cập lần cuối (cũ nhất sẽ bị xóa trước)
                    last_access_time = os.path.getatime(path) 
                    files_to_delete.append((path, last_access_time))
                except OSError:
                    continue

        # Sắp xếp theo thời gian truy cập (cũ nhất lên trước)
        files_to_delete.sort(key=lambda x: x[1])

        total_deleted_size = 0
        deleted_count = 0
        
        # Xóa file cho đến khi đạt ngưỡng hoặc hết file
        for path, _ in files_to_delete:
            try:
                size_mb = os.path.getsize(path) / (1024 * 1024)
                os.remove(path)
                total_deleted_size += size_mb
                deleted_count += 1
                logger.info(f"Đã xóa file local cũ: {path} ({size_mb:.2f} MB)")
                
                # Kiểm tra lại dung lượng trống sau mỗi lần xóa để tránh làm quá nhiều
                current_free_space = get_disk_free_space_mb(config.FILE_STORAGE_PATH)
                if current_free_space > config.MIN_FREE_SPACE_MB + 50: # Thêm buffer 50MB
                    logger.info(f"Đã dọn dẹp đủ dung lượng.")
                    break
            except Exception as e:
                logger.error(f"Lỗi khi xóa file local: {path}: {e}")
                
        logger.info(f"Hoàn tất dọn dẹp file local. Đã xóa {deleted_count} file. Tổng dung lượng: {total_deleted_size:.2f} MB.")
        
    except Exception as e:
        logger.error(f"Lỗi nghiêm trọng trong quá trình dọn dẹp file local: {e}")