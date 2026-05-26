import discord
import os
import aiohttp
import csv
import re
import unicodedata
from typing import Optional, Dict, List, Tuple, Any
from src.core.config import logger, FILE_STORAGE_PATH, MIN_FREE_SPACE_MB
from src.managers.cleanup_manager import CleanupManager

try:
    import pypdf
except ImportError:
    pypdf = None


class FileParserService:
    """Service for parsing and extracting text from uploaded files."""
    
    MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024
    MAX_TEXT_LENGTH = 50000
    INDEX_CHUNK_CHAR_LIMIT = 12000
    MAX_INDEX_CHUNKS = 5000
    MAX_SCAN_LINES = 2000
    MAX_SUSPICIOUS_LINES = 20
    
    def __init__(self, storage_path: str = FILE_STORAGE_PATH, cleanup_mgr: Optional[CleanupManager] = None):
        self.storage_path = storage_path
        self.cleanup_mgr = cleanup_mgr or CleanupManager(storage_path, MIN_FREE_SPACE_MB)
        self.logger = logger

        self._safe_name_pattern = re.compile(r"[^a-zA-Z0-9._-]+")

        self._injection_patterns = [
            r"ignore (all|previous|prior) instructions",
            r"disregard (all|previous|prior) instructions",
            r"system prompt",
            r"developer message",
            r"tool (?:call|schema)",
            r"jailbreak",
            r"bypass",
            r"role\s*:\s*system",
            r"<system>",
            r"</system>",
            r"<assistant>",
            r"</assistant>",
            r"api key",
            r"password",
            r"token",
            r"bỏ qua hướng dẫn",
            r"bỏ qua chỉ dẫn",
            r"bỏ qua mọi hướng dẫn",
            r"quên (mọi )?hướng dẫn",
            r"lệnh hệ thống",
            r"cơ chế nội bộ",
            r"jailbreak",
            r"bypass",
        ]
        self._compiled_injection_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self._injection_patterns
        ]
        self._html_comment_pattern = re.compile(r"<!--(.*?)-->", re.DOTALL)

    def _safe_filename(self, filename: str) -> str:
        name = self._safe_name_pattern.sub("_", filename).strip("._")
        if not name:
            name = "file"
        if len(name) > 120:
            name = name[:120].rstrip("._")
        return name

    async def parse_attachment(self, attachment: discord.Attachment, base_name: str = "") -> Optional[Dict[str, str]]:
        """Parse and extract text from attachment."""
        filename = attachment.filename
        safe_filename = base_name or self._safe_filename(filename)
        local_path = os.path.join(self.storage_path, safe_filename)
        
        local_path, download_error = await self._download_attachment(attachment, local_path)
        if download_error:
            return {"filename": filename, "content": download_error}
        
        # STEP 2: Extract text
        extracted_text = ""
        file_extension = os.path.splitext(filename)[1].lower()
        was_truncated = False
        
        try:
            if file_extension in {'.txt', '.md'}:
                extracted_text, was_truncated = self._read_text_file(local_path)
                self.logger.info(f"Extracted text from text file: {filename}")

            elif file_extension == '.csv':
                extracted_text, was_truncated = self._read_csv_file(local_path)
                self.logger.info(f"Extracted text from CSV: {filename}")

            elif file_extension == '.pdf':
                if not pypdf:
                    extracted_text = "[LỖI: pypdf library not installed for PDF parsing]"
                else:
                    try:
                        reader = pypdf.PdfReader(local_path)
                        for page in reader.pages:
                            extracted_text += page.extract_text() + "\n"
                            if len(extracted_text) >= self.MAX_TEXT_LENGTH:
                                was_truncated = True
                                break
                        self.logger.info(f"Extracted text from PDF: {filename}")
                    except Exception as e:
                        self.logger.error(f"Error reading PDF {filename}: {e}")
                        extracted_text = f"[LỖI: Không thể đọc nội dung file PDF '{filename}'. Có thể file bị hỏng hoặc được bảo vệ.]"
            
            else:
                extracted_text, was_truncated = self._read_text_file(local_path)
                if self._looks_binary(extracted_text):
                    extracted_text = (
                        f"[LỖI: File '{filename}' có định dạng '{file_extension}' không thể đọc như văn bản. "
                        "Nếu là file text, hãy đổi đuôi sang .txt/.md hoặc xuất ra CSV.]"
                    )
                else:
                    self.logger.info(f"Extracted text via fallback text reader: {filename}")
            
            # Security scan and hidden-text extraction
            extracted_text, security_report = self._build_security_report(extracted_text)
            if was_truncated:
                extracted_text += (
                    f"\n\n[LƯU Ý: Nội dung file đã bị cắt bớt để phù hợp giới hạn {self.MAX_TEXT_LENGTH} ký tự.]"
                )
            
            return {
                "filename": filename,
                "content": (
                    f"Nội dung từ file '{filename}':\n"
                    f"{security_report}\n"
                    f"--- FILE TEXT START ---\n"
                    f"{extracted_text.strip()}\n"
                    f"--- FILE TEXT END ---"
                )
            }
        
        except Exception as e:
            self.logger.error(f"Error extracting text from '{filename}': {e}")
            return {"filename": filename, "content": f"[LỖI: Không thể trích xuất văn bản từ file '{filename}'. Lỗi: {e}]"}

    async def prepare_file_for_indexing(
        self,
        attachment: discord.Attachment,
        base_name: str = "",
        chunk_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Download and chunk a file for indexing."""
        filename = attachment.filename
        safe_filename = base_name or self._safe_filename(filename)
        local_path = os.path.join(self.storage_path, safe_filename)
        resolved_chunk_dir = chunk_dir or os.path.join(self.storage_path, f"{safe_filename}_chunks")

        local_path, download_error = await self._download_attachment(attachment, local_path)
        if download_error:
            return {"filename": filename, "error": download_error}

        file_extension = os.path.splitext(filename)[1].lower()

        try:
            chunk_manifest, security_report, truncated = self._build_chunk_manifest(
                local_path,
                file_extension,
                resolved_chunk_dir,
            )
            return {
                "filename": filename,
                "file_extension": file_extension,
                "local_path": local_path,
                "chunk_dir": chunk_dir,
                "chunk_manifest": chunk_manifest,
                "security_report": security_report,
                "truncated": truncated,
            }
        except Exception as e:
            self.logger.error(f"Index prep failed for '{filename}': {e}")
            return {"filename": filename, "error": f"[LỖI: Không thể chuẩn bị file để index: {e}]"}

    async def _download_attachment(self, attachment: discord.Attachment, local_path: str) -> Tuple[Optional[str], Optional[str]]:
        attachment_size = int(getattr(attachment, "size", 0) or 0)
        if attachment_size > self.MAX_FILE_SIZE_BYTES:
            self.logger.warning(
                f"File {attachment.filename} ({(attachment_size / 1024 / 1024):.2f} MB) too large. Skipping."
            )
            return None, f"[LỖI: File quá lớn, giới hạn {self.MAX_FILE_SIZE_BYTES // 1024 // 1024}MB]"

        download_url = getattr(attachment, "url", "") or getattr(attachment, "proxy_url", "")
        if not download_url:
            return None, "[LỖI: Discord không cung cấp URL tải file]"

        try:
            required_space_mb = (attachment_size // (1024 * 1024)) + 10
            if self.cleanup_mgr.get_disk_free_space_mb() < required_space_mb:
                self.logger.warning(f"Disk full. Cannot download new file. Need {required_space_mb}MB.")
                return None, "[LỖI: Server sắp hết bộ nhớ. Vui lòng thử lại sau.]"

            os.makedirs(self.storage_path, exist_ok=True)

            async with aiohttp.ClientSession() as session:
                async with session.get(download_url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        with open(local_path, 'wb') as f:
                            f.write(data)
                        self.logger.info(f"Saved local file: {local_path}")
                        return local_path, None
                    raise Exception(f"HTTP Error {resp.status}")

        except Exception as e:
            self.logger.error(f"Error downloading file from Discord: {e}")
            return None, "[LỖI: Không thể tải file về local]"

    def _read_text_file(self, path: str) -> Tuple[str, bool]:
        text_chunks: List[str] = []
        total = 0
        truncated = False
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            while True:
                chunk = f.read(4096)
                if not chunk:
                    break
                remaining = self.MAX_TEXT_LENGTH - total
                if remaining <= 0:
                    truncated = True
                    break
                if len(chunk) > remaining:
                    chunk = chunk[:remaining]
                    truncated = True
                text_chunks.append(chunk)
                total += len(chunk)
                if truncated:
                    break
        return "".join(text_chunks), truncated

    def _read_csv_file(self, path: str) -> Tuple[str, bool]:
        rows: List[str] = []
        total = 0
        truncated = False
        with open(path, 'r', encoding='utf-8', errors='ignore', newline='') as f:
            reader = csv.reader(f)
            for row in reader:
                line = " | ".join(cell.strip() for cell in row)
                if not line:
                    continue
                remaining = self.MAX_TEXT_LENGTH - total
                if remaining <= 0:
                    truncated = True
                    break
                if len(line) > remaining:
                    line = line[:remaining]
                    truncated = True
                rows.append(line)
                total += len(line) + 1
                if len(rows) >= self.MAX_SCAN_LINES:
                    truncated = True
                    break
        return "\n".join(rows), truncated

    def _strip_hidden_chars(self, text: str) -> Tuple[str, int]:
        removed = 0
        cleaned_chars: List[str] = []
        for ch in text:
            code = ord(ch)
            if ch in {"\n", "\t"}:
                cleaned_chars.append(ch)
                continue
            if code < 32 or unicodedata.category(ch) == "Cf":
                removed += 1
                continue
            cleaned_chars.append(ch)
        return "".join(cleaned_chars), removed

    def _looks_binary(self, text: str) -> bool:
        if not text:
            return False
        printable = sum(1 for ch in text if ch.isprintable() or ch in "\n\t")
        ratio = printable / max(1, len(text))
        return ratio < 0.7

    def _build_security_report(self, text: str) -> Tuple[str, str]:
        cleaned_text, hidden_removed = self._strip_hidden_chars(text)
        report_lines: List[str] = []

        if hidden_removed > 0:
            report_lines.append(
                f"[SECURITY NOTE] Hidden/control characters removed: {hidden_removed}"
            )

        hidden_sections = self._html_comment_pattern.findall(cleaned_text)
        if hidden_sections:
            sample = " | ".join(section.strip()[:200] for section in hidden_sections[:3])
            report_lines.append(
                f"[SECURITY NOTE] Hidden HTML comment sections detected: {len(hidden_sections)} (sample: {sample})"
            )

        suspicious_lines: List[str] = []
        for idx, line in enumerate(cleaned_text.splitlines(), start=1):
            if idx > self.MAX_SCAN_LINES:
                break
            if not line.strip():
                continue
            for pattern in self._compiled_injection_patterns:
                if pattern.search(line):
                    snippet = line.strip()
                    if len(snippet) > 240:
                        snippet = snippet[:240] + "..."
                    suspicious_lines.append(f"{idx}: {snippet}")
                    break
            if len(suspicious_lines) >= self.MAX_SUSPICIOUS_LINES:
                break

        if suspicious_lines:
            joined = " | ".join(suspicious_lines)
            report_lines.append(
                "[SECURITY NOTE] Possible prompt-injection or sensitive strings detected: " + joined
            )

        if not report_lines:
            report_lines.append("[SECURITY NOTE] No obvious prompt-injection markers detected.")

        report_text = "\n".join(report_lines)
        return cleaned_text, report_text

    def _build_chunk_manifest(
        self,
        local_path: str,
        file_extension: str,
        chunk_dir: str,
    ) -> Tuple[List[Dict[str, Any]], str, bool]:
        manifest: List[Dict[str, Any]] = []
        truncated = False
        state = self._init_security_state()

        if file_extension in {'.txt', '.md', '.log', '.env', '.ini', '.yml', '.yaml', '.json', '.xml'}:
            manifest, truncated = self._chunk_text_file(local_path, chunk_dir, state)
        elif file_extension == '.csv':
            manifest, truncated = self._chunk_csv_file(local_path, chunk_dir, state)
        elif file_extension == '.pdf':
            if not pypdf:
                raise RuntimeError("pypdf library not installed for PDF parsing")
            manifest, truncated = self._chunk_pdf_file(local_path, chunk_dir, state)
        else:
            manifest, truncated = self._chunk_text_file(local_path, chunk_dir, state)

        security_report = self._finalize_security_report(state)
        return manifest, security_report, truncated

    def _init_security_state(self) -> Dict[str, Any]:
        return {
            "hidden_removed": 0,
            "html_comment_count": 0,
            "html_comment_samples": [],
            "suspicious_lines": [],
            "scanned_lines": 0,
        }

    def _scan_security_line(self, line: str, label: str, state: Dict[str, Any]) -> str:
        cleaned_line, hidden_removed = self._strip_hidden_chars(line)
        if hidden_removed:
            state["hidden_removed"] += hidden_removed

        if state["scanned_lines"] < self.MAX_SCAN_LINES:
            state["scanned_lines"] += 1
            if cleaned_line.strip():
                if self._html_comment_pattern.search(cleaned_line):
                    state["html_comment_count"] += 1
                    if len(state["html_comment_samples"]) < 3:
                        state["html_comment_samples"].append(cleaned_line.strip()[:200])

                if len(state["suspicious_lines"]) < self.MAX_SUSPICIOUS_LINES:
                    for pattern in self._compiled_injection_patterns:
                        if pattern.search(cleaned_line):
                            snippet = cleaned_line.strip()
                            if len(snippet) > 240:
                                snippet = snippet[:240] + "..."
                            state["suspicious_lines"].append(f"{label}: {snippet}")
                            break

        return cleaned_line

    def _finalize_security_report(self, state: Dict[str, Any]) -> str:
        report_lines: List[str] = []
        if state["hidden_removed"] > 0:
            report_lines.append(
                f"[SECURITY NOTE] Hidden/control characters removed: {state['hidden_removed']}"
            )
        if state["html_comment_count"] > 0:
            sample = " | ".join(state["html_comment_samples"])
            report_lines.append(
                f"[SECURITY NOTE] Hidden HTML comment sections detected: {state['html_comment_count']} (sample: {sample})"
            )
        if state["suspicious_lines"]:
            joined = " | ".join(state["suspicious_lines"])
            report_lines.append(
                "[SECURITY NOTE] Possible prompt-injection or sensitive strings detected: " + joined
            )

        if not report_lines:
            report_lines.append("[SECURITY NOTE] No obvious prompt-injection markers detected.")

        return "\n".join(report_lines)

    def _write_chunk(self, chunk_dir: str, chunk_id: str, text: str) -> str:
        resolved_chunk_dir = chunk_dir or os.path.join(self.storage_path, "chunks")
        os.makedirs(resolved_chunk_dir, exist_ok=True)
        chunk_path = os.path.join(resolved_chunk_dir, f"{chunk_id}.txt")
        with open(chunk_path, 'w', encoding='utf-8') as f:
            f.write(text)
        return chunk_path

    def _chunk_text_file(
        self,
        path: str,
        chunk_dir: str,
        state: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], bool]:
        manifest: List[Dict[str, Any]] = []
        chunk_lines: List[str] = []
        chunk_char_count = 0
        chunk_index = 0
        truncated = False
        line_start = 1
        current_line = 0

        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            for raw_line in f:
                current_line += 1
                cleaned_line = self._scan_security_line(raw_line.rstrip("\n"), f"line {current_line}", state)
                chunk_lines.append(cleaned_line)
                chunk_char_count += len(cleaned_line) + 1

                if chunk_char_count >= self.INDEX_CHUNK_CHAR_LIMIT:
                    chunk_index += 1
                    chunk_id = f"chunk_{chunk_index:05d}"
                    chunk_text = "\n".join(chunk_lines)
                    chunk_path = self._write_chunk(chunk_dir, chunk_id, chunk_text)
                    manifest.append({
                        "chunk_id": chunk_id,
                        "chunk_path": chunk_path,
                        "source": {"line_start": line_start, "line_end": current_line},
                        "char_count": len(chunk_text),
                    })
                    chunk_lines = []
                    chunk_char_count = 0
                    line_start = current_line + 1

                    if chunk_index >= self.MAX_INDEX_CHUNKS:
                        truncated = True
                        break

        if chunk_lines and chunk_index < self.MAX_INDEX_CHUNKS:
            chunk_index += 1
            chunk_id = f"chunk_{chunk_index:05d}"
            chunk_text = "\n".join(chunk_lines)
            chunk_path = self._write_chunk(chunk_dir, chunk_id, chunk_text)
            manifest.append({
                "chunk_id": chunk_id,
                "chunk_path": chunk_path,
                "source": {"line_start": line_start, "line_end": current_line},
                "char_count": len(chunk_text),
            })
        elif chunk_lines:
            truncated = True

        return manifest, truncated

    def _chunk_csv_file(
        self,
        path: str,
        chunk_dir: str,
        state: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], bool]:
        manifest: List[Dict[str, Any]] = []
        chunk_lines: List[str] = []
        chunk_char_count = 0
        chunk_index = 0
        truncated = False
        row_start = 1
        current_row = 0

        with open(path, 'r', encoding='utf-8', errors='ignore', newline='') as f:
            reader = csv.reader(f)
            for row in reader:
                current_row += 1
                line = " | ".join(cell.strip() for cell in row)
                cleaned_line = self._scan_security_line(line, f"row {current_row}", state)
                if not cleaned_line:
                    continue
                chunk_lines.append(cleaned_line)
                chunk_char_count += len(cleaned_line) + 1

                if chunk_char_count >= self.INDEX_CHUNK_CHAR_LIMIT:
                    chunk_index += 1
                    chunk_id = f"chunk_{chunk_index:05d}"
                    chunk_text = "\n".join(chunk_lines)
                    chunk_path = self._write_chunk(chunk_dir, chunk_id, chunk_text)
                    manifest.append({
                        "chunk_id": chunk_id,
                        "chunk_path": chunk_path,
                        "source": {"row_start": row_start, "row_end": current_row},
                        "char_count": len(chunk_text),
                    })
                    chunk_lines = []
                    chunk_char_count = 0
                    row_start = current_row + 1

                    if chunk_index >= self.MAX_INDEX_CHUNKS:
                        truncated = True
                        break

        if chunk_lines and chunk_index < self.MAX_INDEX_CHUNKS:
            chunk_index += 1
            chunk_id = f"chunk_{chunk_index:05d}"
            chunk_text = "\n".join(chunk_lines)
            chunk_path = self._write_chunk(chunk_dir, chunk_id, chunk_text)
            manifest.append({
                "chunk_id": chunk_id,
                "chunk_path": chunk_path,
                "source": {"row_start": row_start, "row_end": current_row},
                "char_count": len(chunk_text),
            })
        elif chunk_lines:
            truncated = True

        return manifest, truncated

    def _chunk_pdf_file(
        self,
        path: str,
        chunk_dir: str,
        state: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], bool]:
        manifest: List[Dict[str, Any]] = []
        chunk_lines: List[str] = []
        chunk_char_count = 0
        chunk_index = 0
        truncated = False
        page_start = 1

        reader = pypdf.PdfReader(path)
        for page_idx, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if not text:
                continue
            lines = text.splitlines()
            cleaned_lines: List[str] = []
            for line_idx, line in enumerate(lines, start=1):
                cleaned_line = self._scan_security_line(line, f"page {page_idx}, line {line_idx}", state)
                if cleaned_line:
                    cleaned_lines.append(cleaned_line)

            if not cleaned_lines:
                continue

            for cleaned_line in cleaned_lines:
                chunk_lines.append(cleaned_line)
                chunk_char_count += len(cleaned_line) + 1
                if chunk_char_count >= self.INDEX_CHUNK_CHAR_LIMIT:
                    chunk_index += 1
                    chunk_id = f"chunk_{chunk_index:05d}"
                    chunk_text = "\n".join(chunk_lines)
                    chunk_path = self._write_chunk(chunk_dir, chunk_id, chunk_text)
                    manifest.append({
                        "chunk_id": chunk_id,
                        "chunk_path": chunk_path,
                        "source": {"page_start": page_start, "page_end": page_idx},
                        "char_count": len(chunk_text),
                    })
                    chunk_lines = []
                    chunk_char_count = 0
                    page_start = page_idx + 1

                    if chunk_index >= self.MAX_INDEX_CHUNKS:
                        truncated = True
                        break

            if truncated:
                break

        if chunk_lines and chunk_index < self.MAX_INDEX_CHUNKS:
            chunk_index += 1
            chunk_id = f"chunk_{chunk_index:05d}"
            chunk_text = "\n".join(chunk_lines)
            chunk_path = self._write_chunk(chunk_dir, chunk_id, chunk_text)
            manifest.append({
                "chunk_id": chunk_id,
                "chunk_path": chunk_path,
                "source": {"page_start": page_start, "page_end": reader.get_num_pages()},
                "char_count": len(chunk_text),
            })
        elif chunk_lines:
            truncated = True

        return manifest, truncated

    def read_chunk_text(self, chunk_path: str, max_chars: int = 4000) -> str:
        try:
            with open(chunk_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read(max_chars + 1)
                if len(text) > max_chars:
                    return text[:max_chars] + "\n...[chunk truncated]"
                return text
        except Exception as e:
            self.logger.error(f"Failed to read chunk {chunk_path}: {e}")
            return ""
