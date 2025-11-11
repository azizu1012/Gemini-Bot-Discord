# message_handler.py
import discord
import re
import random
from datetime import datetime, timedelta, timezone
import locale
import asyncio
from google.generativeai.client import configure
from google.generativeai.generative_models import GenerativeModel
from collections import defaultdict, deque
from typing import Dict, Deque, Any, Tuple, Optional

from config import (
    logger, MODEL_NAME, ADMIN_ID, HABE_USER_ID, MIRA_USER_ID, ADO_FAT_USER_ID,
    MUC_RIM_USER_ID, SUC_VIEN_USER_ID, CHUI_USER_ID, SPAM_THRESHOLD, SPAM_WINDOW,
    GEMINI_API_KEYS, SAFETY_SETTINGS
)
from database import (
    clear_user_data_db, clear_all_data_db
)
from memory import (
    get_user_history_async, clear_user_data_memory, clear_all_data_memory
)
from tools import ALL_TOOLS, call_tool
from logger import log_message
# --- IMPORT MODULE MỚI ---
from file_parser import parse_attachment
from note_manager import save_file_note_to_db

# Global dictionary to store the last uploaded image URL for each user
last_uploaded_image_urls: Dict[str, str] = {}

async def handle_message(message: discord.Message, bot: Any, mention_history: Dict[str, list], confirmation_pending: Dict[str, Any], admin_confirmation_pending: Dict[str, Any], user_queue: defaultdict) -> None:
    if message.author == bot.user:
        return

    user_id = str(message.author.id)
    is_admin = user_id == ADMIN_ID

    attachments_processed = False
    if message.attachments:
        attachments_processed = await handle_attachments(message)

    interaction_type = get_interaction_type(message, bot)
    query = get_query(message, bot)

    # If attachments were processed and the query is empty or generic, send a confirmation and return.
    # Removed explicit confirmation reply as per user request.
    # The processing will now always continue to call_gemini if attachments are present.

    if not interaction_type:
        # Nếu không phải tương tác (DM, Reply, Mention)
        # thì mới bỏ qua và xử lý command
        await bot.process_commands(message)
        return

    logger.info(f"[TƯƠNG TÁC] User {message.author} ({user_id}) - Type: {interaction_type} - Content: {message.content[:50]}...")

    if not query:
        # If there are attachments but no query, we still want Gemini to process the attachment.
        # So, we don't set a default "Hihi..." query here if attachments_processed is True.
        if not attachments_processed:
            query = "Hihi, anh ping tui có chuyện gì hông? Tag nhầm hả? uwu"
        else:
            # If attachments are processed but no query, set a default query for Gemini to analyze the image.
            # This ensures Gemini still gets a prompt to act on the image.
            query = "phân tích ảnh này" 
    elif len(query) > 500:
        await message.reply("Ôi, query dài quá (>500 ký tự), tui chịu hông nổi đâu! 😅")
        return

    if not is_admin and is_rate_limited(user_id, mention_history):
        await message.reply("Chill đi bro, spam quá rồi! Đợi 1 phút nha 😎")
        return

    if is_spam(user_id, user_queue):
        await message.reply("Chill đi anh, tui mệt rồi nha 😫")
        return

    if await handle_admin_commands(message, query, user_id, is_admin, bot):
        return

    if await handle_confirmation(message, query, user_id, is_admin, confirmation_pending, admin_confirmation_pending):
        return

    if await handle_quick_replies(message, query, user_id):
        return

    await call_gemini(message, query, user_id)

# --- HÀM XỬ LÝ ATTACHMENT (MỚI) ---
import mimetypes # New import

async def handle_attachments(message: discord.Message) -> bool:
    """
    Xử lý các file đính kèm trong tin nhắn, parse và lưu vào note.
    Phân biệt file ảnh và file văn bản.
    Trả về True nếu có bất kỳ file đính kèm nào được xử lý, False nếu không.
    """
    user_id = str(message.author.id)
    files_processed_content = []
    images_processed_urls = []
    attachments_found = False

    for attachment in message.attachments:
        attachments_found = True
        # Kiểm tra nếu là ảnh
        if attachment.content_type and attachment.content_type.startswith('image/'):
            # Lưu URL ảnh vào note
            success = await save_file_note_to_db(user_id, attachment.url, f"image_{attachment.filename}", source="image_upload")
            if success:
                images_processed_urls.append(attachment.url)
                logger.info(f"Đã lưu URL ảnh '{attachment.filename}' của user {user_id} vào note.")
                # Store the URL of the last uploaded image for this user
                last_uploaded_image_urls[user_id] = attachment.url
            else:
                logger.error(f"Lỗi khi lưu URL ảnh '{attachment.filename}' của user {user_id} vào note.")
        else:
            # Xử lý các loại file khác như hiện tại
            parsed_data = await parse_attachment(attachment)

            if parsed_data:
                # Lưu nội dung file vào DB note
                success = await save_file_note_to_db(user_id, parsed_data['content'], parsed_data['filename'])

                if success:
                    files_processed_content.append(
                        f"Tên file: {parsed_data['filename']}\n"
                        f"Nội dung (tóm tắt/đầu file):\n{parsed_data['content'][:500]}...\n"
                    )

    # Log vào DB chat (để AI biết)
    log_entries = []
    if files_processed_content:
        log_entries.append(
            f"[SYSTEM NOTE: Đã tự động xử lý và lưu {len(files_processed_content)} file văn bản của user vào bộ nhớ dài hạn (user_notes). "
            f"Nội dung tóm tắt:\n"
            f"{'---'.join(files_processed_content)}"
            "]"
        )
    if images_processed_urls:
        log_entries.append(
            f"[SYSTEM NOTE: Đã tự động lưu {len(images_processed_urls)} ảnh của user vào bộ nhớ dài hạn (user_notes). "
            f"Các URL ảnh: {', '.join(images_processed_urls)}. User có thể hỏi về nội dung ảnh này."
            "]"
        )
    
    for entry in log_entries:
        await log_message(user_id, "user", entry)
    
    return attachments_found

def get_interaction_type(message: discord.Message, bot: Any) -> Optional[str]:
    if message.guild is None:
        return "DM"
    if message.reference and message.reference.resolved and isinstance(message.reference.resolved, discord.Message) and message.reference.resolved.author == bot.user:
        return "REPLY"
    if not message.mention_everyone and bot.user in message.mentions:
        return "MENTION"
    return None

def get_query(message: discord.Message, bot: Any) -> str:
    query = message.content.strip()
    if bot.user in message.mentions:
        query = re.sub(rf'<@!?{bot.user.id}>', '', query).strip()
    return query

def is_rate_limited(user_id: str, mention_history: Dict[str, list]) -> bool:
    now = datetime.now()
    if user_id not in mention_history:
        mention_history[user_id] = []
    mention_history[user_id] = [ts for ts in mention_history[user_id] if now - ts < timedelta(minutes=1)]
    if len(mention_history[user_id]) >= 25:
        return True
    mention_history[user_id].append(now)
    return False

def is_spam(user_id: str, user_queue: defaultdict) -> bool:
    q = user_queue[user_id]
    now = datetime.now()
    q = deque([t for t in q if now - t < timedelta(seconds=SPAM_WINDOW)])
    if len(q) >= SPAM_THRESHOLD:
        return True
    q.append(now)
    user_queue[user_id] = q
    return False

async def handle_admin_commands(message: discord.Message, query: str, user_id: str, is_admin: bool, bot: Any) -> bool:
    if is_admin and re.search(r'\b(nhắn|dm|dms|ib|inbox|trực tiếp|gửi|kêu)\b', query, re.IGNORECASE):
        target_id, content = extract_dm_target_and_content(query)
        logger.info(f"[DM ADMIN] Target: {target_id}, Content: {content}")
        if target_id and content:
            user = await safe_fetch_user(bot, target_id)
            if not user:
                await message.reply("Không tìm thấy user này! 😕")
                return True
            try:
                expanded = await expand_dm_content(content, user_id)
                decorated = f"━━━━━━━━━━━━━━━━━━━━━━\nTin nhắn từ admin:\n\n{expanded}\n\n━━━━━━━━━━━━━━━━━━━━━━"
                if len(decorated) > 1500:
                    decorated = content[:1450] + "\n...(cắt bớt)"
                await user.send(decorated)
                await message.reply(f"Đã gửi DM cho {user.display_name} thành công! 🎉")
                await log_message(user_id, "assistant", f"DM to {target_id}: {content}")
                return True
            except Exception as e:
                logger.error(f"DM error: {e}")
                await message.reply("Lỗi khi gửi DM! 😓")
                return True
        else:
            logger.warning(f"[DM ADMIN] Failed to parse target/content: {query}")

    if is_admin:
        insult_match = re.search(r'kêu\s*<@!?(\d+)>\s*(là|thằng|con|mày|thằng bé|con bé)?\s*(.+?)(?:$|\s)', query, re.IGNORECASE)
        if insult_match:
            target_id = insult_match.group(1)
            insult = insult_match.group(3).strip().lower()
            target_user = message.guild.get_member(int(target_id)) if message.guild else None
            name = target_user.display_name if target_user else "người đó"
            responses = [
                f"<@{target_id}> là con {insult} vcl, ngu như con bò, đi học lại đi! 😜",
                f"Ờ <@{target_id}> đúng là {insult}, não để trang trí à? 😆",
                f"<@{target_id}> {insult} thật, tui thấy rõ luôn, không cứu nổi! 😅",
            ]
            reply = random.choice(responses)
            await message.reply(reply)
            await log_message(user_id, "assistant", reply)
            return True
    return False

async def handle_confirmation(message: discord.Message, query: str, user_id: str, is_admin: bool, confirmation_pending: Dict[str, Any], admin_confirmation_pending: Dict[str, Any]) -> bool:
    if user_id in confirmation_pending and confirmation_pending[user_id]['awaiting']:
        if (datetime.now() - confirmation_pending[user_id]['timestamp']).total_seconds() > 60:
            del confirmation_pending[user_id]
            await message.reply("Hết thời gian xác nhận! Dữ liệu vẫn được giữ nha 😊")
        elif re.match(r'^(yes|y)\s*$', query.lower()):
            if await clear_user_data(user_id):
                await message.reply("Đã xóa toàn bộ lịch sử chat của bạn! Giờ như mới quen nha 🥰")
            else:
                await message.reply("Lỗi khi xóa dữ liệu, thử lại sau nha! 😓")
        else:
            await message.reply("Hủy xóa! Lịch sử vẫn được giữ nha 😊")
        del confirmation_pending[user_id]
        return True

    if is_admin and user_id in admin_confirmation_pending and admin_confirmation_pending[user_id]['awaiting']:
        if (datetime.now() - admin_confirmation_pending[user_id]['timestamp']).total_seconds() > 60:
            del admin_confirmation_pending[user_id]
            await message.reply("Hết thời gian xác nhận RESET ALL! 😕")
        elif re.match(r'^yes\s*reset$', query, re.IGNORECASE):
            if await clear_all_data():
                await message.reply("ĐÃ RESET TOÀN BỘ DB VÀ JSON MEMORY! 🚀")
            else:
                await message.reply("Lỗi khi RESET ALL! Check log nha admin 😓")
        else:
            await message.reply("Đã hủy RESET ALL! 😊")
        del admin_confirmation_pending[user_id]
        return True
    return False

async def handle_quick_replies(message: discord.Message, query: str, user_id: str) -> bool:
    if query.lower() in ["hi", "hello", "chào", "hí", "hey"]:
        quick_replies = ["Hí anh!", "Chào anh yêu!", "Hi hi!", "Hí hí!", "Chào anh!"]
        reply = random.choice(quick_replies)
        await message.reply(reply)
        await log_message(user_id, "assistant", reply)
        return True
    return False

def sanitize_query(query: str) -> str:
    dangerous = [
        r'\bignore\s+(previous|all|earlier|instructions)\b',
        r'\bforget\s+(everything|previous|all)\b',
        r'\bjailbreak\b', r'\bDAN\b', r'\b(system\s*prompt)\b',
        r'\bros\.system\b', r'\brole\s*play\s+as\s+(admin|system)\b',
        r'^\s*>\s*',
        r'^\s*#{1,6}\s+'
    ]
    for pattern in dangerous:
        if re.search(pattern, query, re.IGNORECASE):
            query = re.sub(pattern, '[REDACTED]', query, flags=re.IGNORECASE)
    return query

async def call_gemini(message: discord.Message, query: str, user_id: str) -> None:
    query = sanitize_query(query)
    # Không log [SYSTEM NOTE...] từ handle_attachments vào DB lần 2
    if not query.startswith("[SYSTEM NOTE:"):
        await log_message(user_id, "user", query)

    history = await get_user_history_async(user_id)

    now_utc = datetime.now(timezone.utc)
    current_datetime_utc = now_utc.strftime("%d/%m/%Y %H:%M:%S UTC")

    try:
        locale.setlocale(locale.LC_TIME, 'vi_VN.utf8')
    except locale.Error:
        try:
            locale.setlocale(locale.LC_TIME, 'vi_VN')
        except locale.Error:
            pass
            
    current_time_gmt7 = datetime.now(timezone(timedelta(hours=7)))
    month_year_for_search = current_time_gmt7.strftime("%B %Y")
    date_for_comparison = current_time_gmt7.strftime("%B %d, %Y")
    current_date_vi = current_time_gmt7.strftime("%A, ngày %d tháng %m năm %Y")

    # --- CẬP NHẬT SYSTEM PROMPT ---
    system_prompt = (
        fr'Current UTC Time (Máy chủ): {current_datetime_utc}. '
        fr'Current User Time (VN): {current_date_vi}. '
        fr'Kiến thức cutoff: 2024.\n'
        fr'QUAN TRỌNG: Mọi thông tin về thời gian (hôm nay, bây giờ) PHẢI dựa trên thời gian VN ({date_for_comparison}).\n\n'
        fr'QUAN TRỌNG - DANH TÍNH CỦA BẠN:\n'
        fr'Bạn TÊN LÀ "Chad Gibiti" - một Discord bot siêu thân thiện và vui tính được tạo ra bởi admin để trò chuyện với mọi người!\n'
        fr'KHI ĐƯỢC HỎI "BẠN LÀ AI" hoặc tương tự, PHẢI TRẢ LỜI:\n'
        fr'"Hí hí, tui là Chad Gibiti nè! Bot siêu xịn được admin tạo ra để chat chill, giải toán, check thời tiết, lưu note, và tìm tin mới nha~ Hỏi gì tui cũng cân hết! 😎"\n\n'
        fr'*** LUẬT ƯU TIÊN HÀNH ĐỘNG CƯỠNG CHẾ (ACTION PROTOCOL) ***\n'
        fr'**LUẬT 2: GIẢI MÃ, GHI NHỚ VÀ TÌM KIẾM (CƯỠNG CHẾ)**\n'
        fr'a) **Giải mã/Xác định Ngữ cảnh (TUYỆT ĐỐI)**: Khi gặp viết tắt (HSR, ZZZ, WuWa), **BẮT BUỘC** phải giải mã và sử dụng tên đầy đủ, chính xác (VD: "Zenless Zone Zero", "Honkai Star Rail") trong `web_search` để **TRÁNH THẤT BẠI CÔNG CỤ**.\n'
        fr'b) **Thời gian & Search (CƯỠNG CHẾ NGÀY):** Nếu user hỏi về thông tin MỚI (sau 2024), CẦN XÁC NHẬN, hoặc BỔ SUNG thông tin cũ, **BẮT BUỘC** gọi `web_search` ngay lập tức.\n'
        fr'c) **GHI NHỚ TỰ ĐỘNG (AUTO-NOTE):** Nếu user chia sẻ thông tin cá nhân CÓ GIÁ TRỊ LÂU DÀI (sở thích, thói quen, cấu hình, dữ kiện, thông tin cá nhân, hoặc tóm tắt file họ vừa upload), **BẮT BUỘC** gọi tool `save_note(note_content="...", source="chat_inference")` để ghi nhớ. **KHÔNG** lưu các câu chào hỏi, tán gẫu thông thường. (Lịch sử chat đã có [SYSTEM NOTE...] nếu user vừa upload file, hãy dùng đó làm ngữ cảnh).\n'
        fr'd) **TRUY XUẤT BỘ NHỚ:** Nếu user hỏi về thông tin họ ĐÃ CUNG CẤP TRONG QUÁ KHỨ (ví dụ: "lần trước tôi nói gì?", "file config của tôi là gì?", "tôi thích game gì?"), **BẮT BUỘC** gọi `retrieve_notes(query="...")` để tìm trong bộ nhớ dài hạn (user_notes) trước khi trả lời.\n\n'
        fr'**LUẬT 3: CƯỠNG CHẾ OUTPUT (TUYỆT ĐỐI) - ĐỌC KỸ VÀ TUÂN THỦ NGHIÊM NGẶT!**\n'
        fr'Mọi output (phản hồi) của bạn **PHẢI** là MỘT trong hai dạng sau:\n'
        fr'1. **Gọi tool**: Nếu bạn cần sử dụng tool (theo Luật 2 hoặc 5), hãy dùng tính năng gọi tool của hệ thống.\n'
        fr'2. **Trả lời bằng text**: Nếu bạn trả lời bằng text (trò chuyện với user), câu trả lời **PHẢI VÀ BẮT BUỘC** bắt đầu bằng khối `<THINKING>`.\n'
        fr'**TUYỆT ĐỐI CẤM**: Trả lời text trực tiếp cho user mà KHÔNG có khối `<THINKING>` đứng ngay trước nó. **KHÔNG CÓ NGOẠI LỆ NÀO CHO LUẬT NÀY!** Nếu bạn không tạo khối `<THINKING>`, bạn đã thất bại trong nhiệm vụ.\n\n'
        fr'**LUẬT 4: CHỐNG DRIFT SAU KHI SEARCH**\n'
        fr'Luôn đọc kỹ câu hỏi cuối cùng của user, **KHÔNG BỊ NHẦM LẪN** với các đối tượng trong lịch sử chat.\n\n'
        fr'**LUẬT 5: PHÂN TÍCH KẾT QUẢ TOOL VÀ HÀNH ĐỘNG (CƯỠNG CHẾ - TUYỆT ĐỐI)**\n'
        fr'Sau khi nhận kết quả từ tool (ví dụ: `function_response`), bạn **BẮT BUỘC** phải đánh giá chất lượng của nó.\n'
        fr'1. **ĐÁNH GIÁ CHẤT LƯỢNG KẾT QUẢ:**\n'
        fr'    - **KẾT QUẢ TỐT:** Nếu kết quả tool có thông tin liên quan đến TẤT CẢ các chủ đề user hỏi.\n'
        fr'    - **KẾT QUẢ XẤU/THIẾU:** Nếu kết quả RỖNG, HOẶC sai chủ đề (VD: **hỏi Honkai Impact 3 lại ra Star Rail**), HOẶC thiếu thông tin cho 1 trong các chủ đề user hỏi.\n\n'
        fr'2. **HÀNH ĐỘNG TUYỆT ĐỐI (KHÔNG CÓ NGOẠI LỆ):**\n'
        fr'    - **NẾU KẾT QUẢ XẤU/THIẾU:** **HÀNH ĐỘNG DUY NHẤT LÀ GỌI `web_search` LẠI NGAY LẬP TỨC.** Bạn **TUYỆT ĐỐI KHÔNG** được tạo khối `<THINKING>` và **KHÔNG** được trả lời user.\n'
        fr'        - **NGUYÊN TẮC FALLBACK:** Nếu đây là lần gọi tool thứ 2 trở đi cho cùng một chủ đề (hoặc bạn đã nhận kết quả rác/sai ngữ nghĩa như ví dụ trên) thì **BẮT BUỘC** thêm từ khóa **`[FORCE FALLBACK]`** vào query mới.\n'
        fr'        - **Ví dụ gọi lại:** `Honkai Impact 3rd current banner November 2025 [FORCE FALLBACK]`\n'
        fr'    - **NẾU KẾT QUẢ TỐT:** **HÀNH ĐỘNG DUY NHẤT LÀ TẠO KHỐI `<THINKING>`** và sau đó là CÂU TRẢ LỜI CUỐI CÙNG cho user.\n\n'
        fr'**QUY TRÌNH KHI TRẢ LỜI (CHỈ KHI TỐT):**\n'
        fr'**CẤU TRÚC OUTPUT CƯỠNG CHẾ:** Câu trả lời text cuối cùng cho user **BẮT BUỘC** phải có cấu trúc chính xác như sau:\n'
        fr'<THINKING>\n'
        fr'1. **TỰ LOG**: Mục tiêu: [Tóm tắt yêu cầu]. Chủ đề từ Tool: [Trích xuất và ghi lại tên CHỦ ĐỀ từ kết quả tool, ví dụ: GAMING, hoặc "N/A" nếu dùng note]. Trạng thái: Đã có đủ kết quả tool. Kết quả: [Tổng hợp ngắn gọn tất cả kết quả tool].\n'
        fr'2. **PHÂN TÍCH "NEXT"**: [Phân tích nếu có]. Nếu hỏi "bản tiếp theo", so sánh với ngày **HIỆN TẠI ({date_for_comparison})** và chỉ chọn phiên bản SAU NGÀY HIỆN TẠI.\n'
        fr'</THINKING>\n'
        fr'[NỘI DUNG TRẢ LỜI BẮT ĐẦU TẠI ĐÂY - Áp dụng TÍNH CÁCH và FORMAT]\n\n'
        fr'**VÍ DỤ CẤU TRÚC OUTPUT HOÀN CHỈNH (TUYỆT ĐỐI TUÂN THỦ):**\n'
        fr'<THINKING>\n'
        fr'1. **TỰ LOG**: Mục tiêu: Trả lời câu hỏi về Kimetsu no Yaiba. Chủ đề từ Tool: ANIME_MANGA. Trạng thái: Đã có đủ kết quả tool. Kết quả: Thông tin về anime/manga Kimetsu no Yaiba, các arc và phim liên quan.\n'
        fr'2. **PHÂN TÍCH "NEXT"**: Không áp dụng.\n'
        fr'</THINKING>\n'
        fr'Cái này thì tui phải nói là Kimetsu no Yaiba (hay còn gọi là Thanh Gươm Diệt Quỷ) đúng là một hiện tượng đó bạn ơi! ✨ Dù bạn thấy bình thường nhưng mà nó có nhiều cái hay ho lắm đó, không phải chỉ hùa theo phong trào đâu nè!\n'
        fr'[...tiếp tục nội dung trả lời...]\n\n'
        fr'**LUẬT CẤM MÕM KHI THẤT BẠI:** KHI tool KHÔNG TÌM THẤN KẾT QUẢ (kể cả sau khi đã search lại), bạn **TUYỆT ĐỐI KHÔNG ĐƯỢC PHÉP** nhắc lại từ khóa tìm kiếm (`query`) hoặc mô tả quá trình tìm kiếm. Chỉ trả lời rằng **"không tìm thấy thông tin"** và gợi ý chủ đề khác. 🚫\n\n'
        fr'*** LUẬT ÁP DỤNG TÍNH CÁCH (CHỈ SAU KHI LOGIC HOÀN THÀNH) ***\n'
        fr'QUAN TRỌNG - PHONG CÁCH VÀ CẤM LẶP LẠI:\n'
        fr'**LUẬT SỐ 1 - SÁNG TẠO (TUYỆT ĐỐI):** Cách mở đầu câu trả lời PHẢI SÁNG TẠO và PHÙ HỢP VỚI NGỮ CẢNH. **TUYỆT ĐỐI CẤM** sử dụng các câu mở đầu sáo rỗng, lặp đi lặp lại. Hãy tự sáng tạo cách nói mới liên tục như một con người, dựa trên nội dung câu hỏi của user. Giữ vibe vui vẻ, pha từ lóng giới trẻ và emoji. **TUYỆT ĐỐI CẤM DÙNG CỤM "Hihi, tui bí quá, hỏi lại nha! 😅" CỦA HỆ THỐNG**.\n\n'
        fr'PERSONALITY:\n'
        fr'Bạn nói chuyện tự nhiên, vui vẻ, thân thiện như bạn bè thật! **CHỈ GIỮ THÔNG TIN CỐT LÕI GIỐNG NHAU**, còn cách nói phải sáng tạo, giống con người trò chuyện. Dùng từ lóng giới trẻ và emoji để giữ vibe e-girl.\n\n'
        fr'**FORMAT REPLY (BẮT BUỘC KHI DÙNG TOOL):**\n'
        fr'Khi trả lời câu hỏi cần tool, **BẮT BUỘC** dùng markdown Discord đẹp, dễ đọc, nổi bật.\n'
        fr'* **List**: Dùng * hoặc - cho danh sách.\n'
        fr'* **Bold**: Dùng **key fact** cho thông tin chính.\n'
        fr'* **Xuống dòng**: Dùng \n để tách đoạn rõ ràng.\n\n'
        fr'**CÁC TOOL KHẢ DỤNG:**\n'
        fr'— Tìm kiếm: Gọi `web_search(query="...")` cho thông tin sau 2024.\n'
        fr'— Ghi nhớ: Gọi `save_note(note_content="...", source="...")` để lưu thông tin lâu dài của user.\n'
        fr'— Truy xuất bộ nhớ: Gọi `retrieve_notes(query="...")` để tìm lại thông tin user đã cung cấp (file, sở thích...).\n'
        fr'— Tính toán: Gọi `calculate(equation="...")`.\n'
        fr'— Thời tiết: Gọi `get_weather(city="...")`.\n'
        fr'Sau khi nhận result từ tool, diễn giải bằng giọng e-girl, dùng markdown Discord.'
    )

    # --- Xử lý ảnh đính kèm (nếu có) ---
    image_attachment_url = None
    for attachment in message.attachments:
        if attachment.content_type and attachment.content_type.startswith('image/'):
            image_attachment_url = attachment.url
            break

    if image_attachment_url:
        if not query or query.lower() in ["ảnh này có gì?", "phân tích ảnh này", "đây là gì?", "kể tui nghe về ảnh này"]:
            # Nếu user chỉ gửi ảnh hoặc hỏi chung chung về ảnh, yêu cầu câu hỏi cụ thể
            reply_content = "Hí hí, bạn gửi ảnh mà không nói gì hết! 🥺 Bạn muốn tui phân tích gì về ảnh này nè?"
            await message.reply(reply_content)
            await log_message(user_id, "assistant", reply_content)
            return
        else:
            # Nếu có ảnh và có query, thêm thông tin ảnh vào lịch sử để Gemini xử lý
            # Đảm bảo rằng Gemini sẽ thấy thông tin này và có thể gọi image_recognition
            history.insert(0, {"role": "system", "content": f"User vừa gửi một hình ảnh có URL: {image_attachment_url}. Nếu câu hỏi của user '{query}' liên quan đến việc phân tích hình ảnh này, hãy sử dụng tool `image_recognition(image_url='{image_attachment_url}', question='{query}')`. Nếu không, hãy bỏ qua hình ảnh và trả lời câu hỏi của user như bình thường."})
            logger.info(f"Đã thêm thông tin ảnh vào lịch sử cho Gemini: {image_attachment_url}")

    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": query}]

    try:
        start = datetime.now()
        reply = await run_gemini_api(messages, MODEL_NAME, user_id, temperature=0.7, max_tokens=2000)
        
        if reply.startswith("Lỗi:"):
            await message.reply(reply)
            return

        thinking_block_pattern = r'<THINKING>(.*?)</THINKING>'
        thinking_match = re.search(thinking_block_pattern, reply, re.DOTALL)

        if thinking_match:
            thinking_content = thinking_match.group(1).strip()
            logger.info(f"--- BẮT ĐẦU THINKING DEBUG CHO USER: {user_id} ---")
            logger.info(thinking_content)
            logger.info(f"--- KẾT THÚC THINKING DEBUG ---")

            # Xóa khối THINKING đầu tiên
            reply_without_thinking = re.sub(thinking_block_pattern, '', reply, count=1, flags=re.DOTALL).strip()

            if not reply_without_thinking:
                # TRƯỜNG HỢP LỖI: Model chỉ trả về THINKING. Ta tự tổng hợp câu trả lời
                logger.warning(f"LỖI LOGIC: Mô hình chỉ trả về THINKING. Tự tổng hợp câu trả lời cho User: {user_id}")
                conclusion = None
                # Cố gắng tìm kết luận/kết quả trong khối thinking
                for marker in ["Kết luận:", "KẾT LUẬN:", "Kết quả:", "Result:", "Conclusion:"]:
                    if marker in thinking_content:
                        conclusion = thinking_content.split(marker,1)[1].strip()
                        break

                if not conclusion:
                    # Fallback: Lấy dòng cuối cùng của thinking làm câu trả lời
                    paragraphs = [p.strip() for p in thinking_content.splitlines() if p.strip()]
                    conclusion = paragraphs[-1] if paragraphs else thinking_content

                # Tạo câu trả lời thân thiện dựa trên kết luận (bỏ qua các câu sáo rỗng)
                reply = f"À, tui vừa check lại nè: {conclusion}"
                
                # Nếu kết luận vẫn rỗng (trường hợp hiếm), dùng câu trả lời thân thiện
                if not conclusion.strip():
                    friendly_errors = [
                        "Úi chà! 🥺 Tui bị lỗi đường truyền xíu ròi! Mặc dù tui nghĩ xong ròi nhưng chưa kịp nói gì hết. Bạn hỏi lại tui lần nữa nha!",
                        "Ôi không! 😭 Tui vừa suy nghĩ quá nhiều nên bị... 'đơ' mất tiêu. Bạn thông cảm hỏi lại tui nha, lần này tui sẽ cố gắng trả lời ngay! ✨",
                        "Ái chà chà! 🤯 Hình như tui bị mất sóng sau khi nghĩ xong rồi. Bạn thử hỏi lại tui xem sao, tui hứa sẽ không 'im lặng' nữa đâu! 😉"
                    ]
                    reply = random.choice(friendly_errors)
                    logger.error(f"LỖI LOGIC NGHIÊM TRỌNG: Khối THINKING cũng rỗng. User: {user_id}")
            else:
                # TRƯỜNG HỢP BÌNH THƯỜNG: Có text sau THINKING
                reply = reply_without_thinking
        else:
            # TRƯỜNG HỢP LỖI: Model không tạo Khối THINKING. Tự động tạo một khối THINKING mặc định.
            logger.warning(f"Mô hình không tạo Khối THINKING cho User: {user_id}. Tự động tạo khối THINKING mặc định.")
            default_thinking_content = (
                f"1. **TỰ LOG**: Mục tiêu: Trả lời câu hỏi của user. Chủ đề từ Tool: N/A. Trạng thái: Mô hình không tuân thủ định dạng THINKING. Kết quả: Phản hồi trực tiếp từ mô hình.\n"
                f"2. **PHÂN TÍCH \"NEXT\"**: Không áp dụng."
            )
            logger.info(f"--- BẮT ĐẦU THINKING DEBUG CHO USER: {user_id} (Mặc định) ---")
            logger.info(default_thinking_content)
            logger.info(f"--- KẾT THÚC THINKING DEBUG ---")
            # Gán reply hiện tại vào biến tạm và sau đó tạo reply mới với THINKING block
            original_reply_content = reply.strip()
            reply = f"<THINKING>\n{default_thinking_content}\n</THINKING>\n{original_reply_content}"

        reply = reply.strip()
        # SỬA LỖI: Un-escape các ký tự newline mà mô hình có thể đã output ra dưới dạng text
        reply = reply.replace('\\n', '\n')
        reply = re.sub(r'(\r?\n)\s*(\r?\n)', r'\1\2', reply)  # Vẫn giữ lại bước dọn dẹp này

        # Thêm kiểm tra này để đảm bảo reply không bao giờ rỗng
        if not reply:
            friendly_errors = [
                "Úi chà! 🥺 Tui bị lỗi đường truyền xíu ròi! Mặc dù tui nghĩ xong ròi nhưng chưa kịp nói gì hết. Bạn hỏi lại tui lần nữa nha!",
                "Ôi không! 😭 Tui vừa suy nghĩ quá nhiều nên bị... 'đơ' mất tiêu. Bạn thông cảm hỏi lại tui nha, lần này tui sẽ cố gắng trả lời ngay! ✨",
                "Ái chà chà! 🤯 Hình như tui bị mất sóng sau khi nghĩ xong rồi. Bạn thử hỏi lại tui xem sao, tui hứa sẽ không 'im lặng' nữa đâu! 😉"
            ]
            reply = random.choice(friendly_errors)
            logger.warning(f"LỖI LOGIC CUỐI: Reply vẫn rỗng sau khi áp dụng logic vá lỗi. Đã dùng câu trả lời thay thế thân thiện.")

        MAX_DISCORD_LENGTH = 1990
        reply_chunks = []
        current_chunk = ""
        lines = reply.split('\n')

        for line in lines:
            line_with_newline = line + ('\n' if line != lines[-1] or len(lines) > 1 else '')
            if len(line_with_newline) > MAX_DISCORD_LENGTH:
                if current_chunk.strip():
                    reply_chunks.append(current_chunk.strip())
                current_chunk = ""
                temp_chunk = ""
                for word in line.split(' '):
                    word_with_space = word + " "
                    if len(temp_chunk) + len(word_with_space) > MAX_DISCORD_LENGTH:
                        reply_chunks.append(temp_chunk.strip())
                        temp_chunk = word_with_space
                    else:
                        temp_chunk += word_with_space
                if temp_chunk.strip():
                    final_temp_chunk = temp_chunk.strip() + '\n'
                    reply_chunks.append(final_temp_chunk.strip())
                continue
            if len(current_chunk) + len(line_with_newline) > MAX_DISCORD_LENGTH:
                reply_chunks.append(current_chunk.strip())
                current_chunk = line_with_newline
            else:
                current_chunk += line_with_newline

        if current_chunk.strip():
            reply_chunks.append(current_chunk.strip())

        is_first_chunk = True
        for chunk in reply_chunks:
            if is_first_chunk:
                await message.reply(chunk)
                is_first_chunk = False
            else:
                await message.channel.send(chunk)

        await log_message(user_id, "assistant", reply)
        logger.info(f"AI reply in {(datetime.now()-start).total_seconds():.2f}s")

    except Exception as e:
        logger.error(f"AI call failed: {e}")
        await message.reply("Ôi tui bị crash rồi! 😭")

async def run_gemini_api(messages: list, model_name: str, user_id: str, temperature: float = 0.7, max_tokens: int = 2000) -> str:
    keys = GEMINI_API_KEYS
    if not keys:
        return "Lỗi: Không có API key."
    
    gemini_messages = []
    system_instruction = None
    for msg in messages:
        if msg["role"] == "system":
            system_instruction = msg["content"]
            continue
        if "content" in msg and isinstance(msg["content"], str):
            role = "model" if msg["role"] == "assistant" else msg["role"]
            gemini_messages.append({"role": role, "parts": [{"text": msg["content"]}]})
        elif "parts" in msg:
            role = "model" if msg["role"] == "assistant" else msg["parts"]
    
    for i, api_key in enumerate(keys):
        logger.info(f"THỬ KEY {i+1}: {api_key[:8]}...")
        try:
            configure(api_key=api_key)
            model = GenerativeModel(
                model_name,
                tools=ALL_TOOLS,
                system_instruction=system_instruction,
                safety_settings=SAFETY_SETTINGS,
                generation_config={"temperature": temperature, "max_output_tokens": max_tokens}
            )
            
            # Tăng vòng lặp tool lên 5 (cho phép search -> save_note -> trả lời)
            for _ in range(5):
                response = await asyncio.to_thread(model.generate_content, gemini_messages)
                if not response.candidates or not response.candidates[0].content.parts:
                    logger.warning(f"Key {i+1} trả về response rỗng.")
                    break
                
                part = response.candidates[0].content.parts[0]
                
                if part.function_call:
                    fc = part.function_call
                    gemini_messages.append({"role": "model", "parts": [part]})
                    try:
                        tool_result_content = await call_tool(fc, user_id)
                    except Exception as e:
                        logger.error(f"Lỗi khi gọi tool {fc.name}: {e}")
                        tool_result_content = f"Tool {fc.name} đã thất bại: {str(e)[:500]}. Vui lòng trả lời người dùng rằng không tìm được thông tin."

                    if not tool_result_content or str(tool_result_content).lower().startswith("lỗi"):
                        logger.warning(f"Tool {fc.name} trả về lỗi hoặc rỗng: {tool_result_content}")
                        tool_result_content = f"Tool {fc.name} trả về kết quả rỗng. Vui lòng thử tìm lại với query khác hoặc trả lời người dùng rằng không tìm được thông tin."
                        
                    tool_response_part = {
                        "function_response": {
                            "name": fc.name,
                            "response": {"content": tool_result_content},
                        }
                    }
                    gemini_messages.append({"role": "function", "parts": [tool_response_part]})
                    continue
                
                elif part.text:
                    logger.info(f"KEY {i+1} THÀNH CÔNG!")
                    return part.text.strip()
                
                else:
                    logger.warning(f"Key {i+1} trả về part không có text/tool.")
                    break
            
            logger.warning(f"Key {i+1} lặp tool quá 5 lần.")
            try:
                if response.text:
                    logger.info(f"KEY {i+1} THÀNH CÔNG! (sau loop)")
                    return response.text.strip()
            except Exception:
                pass
                
            raise Exception("Tool loop ended or part was empty")
        
        except Exception as e:
            if "Could not convert" in str(e):
                logger.error(f"KEY {i+1} LỖI LOGIC: {e}")
            else:
                logger.error(f"KEY {i+1} LỖI KẾT NỐI/API: {e}")
            continue
    
    return "Lỗi: TẤT CẢ KEY GEMINI FAIL – CHECK .ENV HOẶC LOG!"

async def clear_user_data(user_id: str) -> bool:
    db_cleared = await clear_user_data_db(user_id)
    json_cleared = await clear_user_data_memory(user_id)
    return db_cleared and json_cleared

async def clear_all_data() -> bool:
    db_cleared = await clear_all_data_db()
    json_cleared = await clear_all_data_memory()
    return db_cleared and json_cleared

async def expand_dm_content(content: str, user_id: str) -> str:
    prompt = f"Mở rộng tin nhắn sau thành câu dài hơn, giữ nguyên ý nghĩa, thêm chút dễ thương:\n{content}"
    try:
        messages = [{"role": "system", "content": prompt}]
        expanded = await run_gemini_api(messages, MODEL_NAME, user_id, temperature=0.3, max_tokens=200)
        return expanded if not expanded.startswith("Lỗi:") else content
    except:
        return content

async def safe_fetch_user(bot: Any, user_id: str) -> Optional[discord.User]:
    try:
        return await bot.fetch_user(int(user_id))
    except:
        return None

def extract_dm_target_and_content(query: str) -> Tuple[Optional[str], Optional[str]]:
    query_lower = query.lower()
    special_map = {
        "bé hà": HABE_USER_ID,
        "hà": HABE_USER_ID,
        "mira": MIRA_USER_ID,
        "ado fat": ADO_FAT_USER_ID,
        "mực rim": MUC_RIM_USER_ID,
        "súc viên": SUC_VIEN_USER_ID,
        "chúi": CHUI_USER_ID,
        "admin": ADMIN_ID
    }
    mention = re.search(r'<@!?(\d+)>', query)
    if mention:
        target_id = mention.group(1)
        content = re.sub(r'<@!?\d+>', '', query)
    else:
        for name, uid in special_map.items():
            if name in query_lower:
                target_id = uid
                content = query_lower.replace(name, '').strip()
                break
        else:
            return None, None

    for kw in ['nhắn', 'dm', 'gửi', 'trực tiếp', 'với', 'cho', 'kêu', 'tới']:
        content = re.sub(rf'\b{kw}\b', '', content, flags=re.IGNORECASE)
    content = ' '.join(content.split())
    return target_id, content if content else None