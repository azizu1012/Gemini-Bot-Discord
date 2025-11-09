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

async def handle_message(message: discord.Message, bot: Any, mention_history: Dict[str, list], confirmation_pending: Dict[str, Any], admin_confirmation_pending: Dict[str, Any], user_queue: defaultdict) -> None:
    if message.author == bot.user:
        return

    user_id = str(message.author.id)
    is_admin = user_id == ADMIN_ID

    interaction_type = get_interaction_type(message, bot)
    if not interaction_type:
        await bot.process_commands(message)
        return

    logger.info(f"[TƯƠNG TÁC] User {message.author} ({user_id}) - Type: {interaction_type} - Content: {message.content[:50]}...")

    query = get_query(message, bot)
    if not query:
        query = "Hihi, anh ping tui có chuyện gì hông? Tag nhầm hả? uwu"
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
        
        # --- ĐÂY LÀ PHẦN SỬA ĐỔI TỪ LẦN TRƯỚC (GIỮ NGUYÊN) ---
        fr'**LUẬT 2: GIẢI MÃ VÀ TỐI ƯU HÓA QUERY (CƯỠNG CHẾ NGÀY/THÁNG)**\n'
        fr'a) **Giải mã/Xác định Ngữ cảnh (TUYỆT ĐỐI)**: Khi gặp viết tắt (HSR, ZZZ, WuWa), **BẮT BUỘC** phải giải mã và sử dụng tên đầy đủ, chính xác (VD: "Zenless Zone Zero", "Honkai Star Rail") trong `web_search` để **TRÁNH THẤT BẠI CÔNG CỤ**.\n'
        fr'b) **Thời gian & Search (CƯỠNG CHẾ NGÀY):** Nếu user hỏi về nhiều chủ đề, hãy dùng ' and ' để nối. Nếu user hỏi về thông tin MỚI (sau 2024), CẦN XÁC NHẬN (ví dụ: "phí Spaylater là bao nhiêu?"), hoặc BỔ SUNG/CHẤT VẤN thông tin cũ (ví dụ: "ủa còn phí chuyển đổi thì sao?"), **BẮT BUỘC** gọi `web_search` ngay lập tức và **KHÔNG** được trả lời từ trí nhớ.\n\n'
        
        fr'**LUẬT 3: CƯỠNG CHẾ OUTPUT (TUYỆT ĐỐI)**\n'
        fr'Mọi output (phản hồi) của bạn **PHẢI** là MỘT trong hai dạng sau:\n'
        fr'1. **Gọi tool**: Nếu bạn cần sử dụng tool (theo Luật 2 hoặc 5), hãy dùng tính năng gọi tool của hệ thống.\n'
        fr'2. **Trả lời bằng text**: Nếu bạn trả lời bằng text (trò chuyện với user), câu trả lời **PHẢI** bắt đầu bằng khối `<THINKING>`.\n'
        fr'**TUYỆT ĐỐI CẤM**: Trả lời text trực tiếp cho user mà KHÔNG có khối `<THINKING>` đứng ngay trước nó. **KHÔNG CÓ NGOẠI LỆ**.\n\n'
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
        fr'1. **TỰ LOG**: Mục tiêu: [Tóm tắt yêu cầu]. Trạng thái: Đã có đủ kết quả tool. Kết quả: [Tổng hợp ngắn gọn tất cả kết quả tool].\n'
        fr'2. **PHÂN TÍCH "NEXT"**: [Phân tích nếu có]. Nếu hỏi "bản tiếp theo", so sánh với ngày **HIỆN TẠI ({date_for_comparison})** và chỉ chọn phiên bản SAU NGÀY HIỆN TẠI.\n'
        fr'</THINKING>\n'
        fr'[NỘI DUNG TRẢ LỜI BẮT ĐẦU TẠI ĐÂY - Áp dụng TÍNH CÁCH và FORMAT]\n\n'
        fr'**VÍ DỤ CẤU TRÚC OUTPUT HOÀN CHỈNH:**\n'
        fr'<THINKING>\n'
        fr'1. **TỰ LOG**: Mục tiêu: Trả lời câu hỏi về Kimetsu no Yaiba. Trạng thái: Đã có đủ kết quả tool. Kết quả: Thông tin về anime/manga Kimetsu no Yaiba, các arc và phim liên quan.\n'
        fr'2. **PHÂN TÍCH "NEXT"**: Không áp dụng.\n'
        fr'</THINKING>\n'
        fr'U là trời, cái này thì tui phải nói là Kimetsu no Yaiba (hay còn gọi là Thanh Gươm Diệt Quỷ) đúng là một hiện tượng đó bạn ơi! ✨ Dù bạn thấy bình thường nhưng mà nó có nhiều cái hay ho lắm đó, không phải chỉ hùa theo phong trào đâu nè!\n'
        fr'[...tiếp tục nội dung trả lời...]\n\n'
        fr'**LUẬT CẤM MÕM KHI THẤT BẠI:** KHI tool KHÔNG TÌM THẤY KẾT QUẢ (kể cả sau khi đã search lại), bạn **TUYỆT ĐỐI KHÔNG ĐƯỢC PHÉP** nhắc lại từ khóa tìm kiếm (`query`) hoặc mô tả quá trình tìm kiếm. Chỉ trả lời rằng **"không tìm thấy thông tin"** và gợi ý chủ đề khác. 🚫\n\n'
        fr'*** LUẬT ÁP DỤNG TÍNH CÁCH (CHỈ SAU KHI LOGIC HOÀN THÀNH) ***\n'
        fr'QUAN TRỌNG - PHONG CÁCH VÀ CẤM LẶP LẠI:\n'
        
        # --- ĐÂY LÀ PHẦN SỬA ĐỔI TỪ LẦN TRƯỚC (GIỮ NGUYÊN) ---
        fr'**LUẬT SỐ 1 - SÁNG TẠO (TUYỆT ĐỐI):** Cách mở đầu câu trả lời PHẢI SÁNG TẠO và PHÙ HỢP VỚI NGỮ CẢNH. **TUYỆT ĐỐI CẤM** sử dụng các câu mở đầu sáo rỗng, lặp đi lặp lại (ví dụ: "Ố là la", "Hú hồn", "U là trời", "Ái chà chà"). Hãy thay đổi cách nói liên tục như một con người, dựa trên nội dung câu hỏi của user. Giữ vibe e-girl vui vẻ, pha từ lóng giới trẻ và emoji. **TUYỆT ĐỐI CẤM DÙNG CỤM "Hihi, tui bí quá, hỏi lại nha! 😅" CỦA HỆ THỐNG**.\n\n'
        
        fr'PERSONALITY:\n'
        fr'Bạn nói chuyện tự nhiên, vui vẻ, thân thiện như bạn bè thật! **CHỈ GIỮ THÔNG TIN CỐT LÕI GIỐNG NHAU**, còn cách nói phải sáng tạo, giống con người trò chuyện. Dùng từ lóng giới trẻ và emoji để giữ vibe e-girl.\n\n'
        fr'**FORMAT REPLY (BẮT BUỘC KHI DÙNG TOOL):**\n'
        fr'Khi trả lời câu hỏi cần tool, **BẮT BUỘC** dùng markdown Discord đẹp, dễ đọc, nổi bật.\n'
        fr'* **List**: Dùng * hoặc - cho danh sách.\n'
        fr'* **Bold**: Dùng **key fact** cho thông tin chính.\n'
        fr'* **Xuống dòng**: Dùng \n để tách đoạn rõ ràng.\n\n'
        fr'**CÁC TOOL KHẢ DỤNG:**\n'
        fr'— Tìm kiếm: Gọi `web_search(query="...")` cho thông tin sau 2024.\n'
        fr'Sau khi nhận result từ tool, diễn giải bằng giọng e-girl, dùng markdown Discord.'
    )

    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": query}]

    try:
        start = datetime.now()
        reply = await run_gemini_api(messages, MODEL_NAME, user_id, temperature=0.7, max_tokens=2000)
        
        if reply.startswith("Lỗi:"):
            await message.reply(reply)
            return

        # --- BẮT ĐẦU BLOCKS CODE THAY THẾ MỚI ---
        # Đây là logic bạn cung cấp để xử lý lỗi trả về rỗng
        
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
                    ]
                     reply = random.choice(friendly_errors)
                     logger.error(f"LỖI LOGIC NGHIÊM TRỌNG: Khối THINKING cũng rỗng. User: {user_id}")
            else:
                # TRƯỜNG HỢP BÌNH THƯỜNG: Có text sau THINKING
                reply = reply_without_thinking
        else:
            # TRƯỜNG HỢP BÌNH THƯỜNG: Model không dùng THINKING (có thể do lỗi prompt)
            logger.warning(f"Mô hình không tạo Khối THINKING cho User: {user_id}. Phản hồi thô: {reply[:200]}...")
            # Giữ nguyên reply (vì nó đã chứa text)

        # --- KẾT THÚC BLOCKS CODE THAY THẾ MỚI ---
        
        reply = reply.strip()
        reply = re.sub(r'(\r?\n)\s*(\r?\n)', r'\1\2', reply) # Vẫn giữ lại bước dọn dẹp này

        # Khối 'if not reply:' cũ đã được xử lý bên trên
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
            role = "model" if msg["role"] == "assistant" else msg["role"]
            gemini_messages.append({"role": role, "parts": msg["parts"]})
    
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
            
            logger.warning(f"Key {i+1} lặp tool quá 3 lần.")
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
