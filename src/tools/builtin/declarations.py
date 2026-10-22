"""Gemini Tool function declarations."""

from __future__ import annotations

from typing import List
from google.genai import types as genai_types


def get_gemini_tools(is_admin: bool = False) -> List[genai_types.Tool]:
    """Build the standard list of Gemini FunctionDeclarations."""
    tools_list = [
        genai_types.Tool(function_declarations=[
            genai_types.FunctionDeclaration(
                name="web_search",
                description=(
                    "Tìm kiếm thông tin cập nhật, sự kiện mới, tin tức, "
                    "dữ liệu thực tế không có trong kiến thức của AI, "
                    "hoặc để xác minh thông tin. KHÔNG DÙNG cho các tác vụ tính toán, "
                    "dịch thuật, tóm tắt, viết lại, hoặc các câu hỏi không cần dữ liệu mới.\n\n"
                    "QUAN TRỌNG: Nếu người dùng hỏi nhiều chủ đề, hãy gọi web_search "
                    "NHIỀU LẦN — mỗi lần một chủ đề riêng, KHÔNG gộp chung vào một query.\n"
                    "LUÔN dùng ngày đầy đủ từ `Current time:` (DD Month YYYY) trong query "
                    "cho tin tức hoặc thông tin thời gian thực."
                ),
                parameters={  # type: ignore[arg-type]
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Truy vấn tìm kiếm cụ thể, KHÔNG gộp nhiều chủ đề. "
                                "Dùng đúng ngày từ `Current time:` (DD Month YYYY) cho tin tức."
                        }
                    },
                    "required": ["query"]
                }
            )
        ]),
        genai_types.Tool(function_declarations=[
            genai_types.FunctionDeclaration(
                name="get_weather",
                description="Lấy thông tin thời tiết hiện tại cho một thành phố cụ thể.",
                parameters={  # type: ignore[arg-type]
                    "type": "object",
                    "properties": {"city": {"type": "string", "description": "Tên thành phố, ví dụ: 'Hanoi', 'Tokyo'."}},
                    "required": ["city"]
                }
            )
        ]),
        genai_types.Tool(function_declarations=[
            genai_types.FunctionDeclaration(
                name="calculate",
                description=(
                    "Giải các bài toán số học hoặc biểu thức phức tạp (đại số, lượng giác, logarit). "
                    "Hỗ trợ đạo hàm/tích phân/rút gọn bằng cú pháp SymPy (vd: diff(x**3*exp(sin(x)), x))."
                ),
                parameters={  # type: ignore[arg-type]
                    "type": "object",
                    "properties": {"equation": {"type": "string", "description": "Biểu thức toán học dưới dạng string, ví dụ: 'sin(pi/2) + 2*x'."}},
                    "required": ["equation"]
                }
            )
        ]),
        genai_types.Tool(function_declarations=[
            genai_types.FunctionDeclaration(
                name="save_note",
                description=(
                    "Lưu một mẩu thông tin, sở thích, sự thật, hoặc nội dung quan trọng về người dùng để bạn có thể truy cập lại sau. "
                    "Dùng khi user chia sẻ thông tin cá nhân có giá trị lâu dài (ví dụ: 'tôi thích chơi game X', 'cấu hình máy của tôi là Y')."
                ),
                parameters={  # type: ignore[arg-type]
                    "type": "object",
                    "properties": {
                        "note_content": {"type": "string", "description": "Nội dung thông tin cần ghi nhớ."},
                        "source": {"type": "string", "description": "Ngữ cảnh hoặc nguồn của thông tin, ví dụ: 'chat_inference', 'user_request'."}
                    },
                    "required": ["note_content", "source"]
                }
            )
        ]),
        genai_types.Tool(function_declarations=[
            genai_types.FunctionDeclaration(
                name="retrieve_notes",
                description=(
                    "Truy xuất thông tin đã lưu trữ về người dùng, kiến thức cá nhân, "
                    "dữ liệu lịch sử, hoặc các sự kiện/thông tin quan trọng mà AI đã được yêu cầu ghi nhớ. "
                    "PHẢI LUÔN GỌI HÀM NÀY nếu câu hỏi liên quan đến kiến thức cá nhân, note, hoặc thông tin đã được ghi nhớ trước đó."
                ),
                parameters={  # type: ignore[arg-type]
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Từ khóa hoặc chủ đề tìm kiếm trong bộ nhớ (ví dụ: 'config', 'sở thích'). Để trống nếu muốn lấy tất cả."}
                    },
                    "required": ["query"]
                }
            )
        ]),
        genai_types.Tool(function_declarations=[
            genai_types.FunctionDeclaration(
                name="delete_note",
                description=(
                    "Xóa một ghi chú/thông tin cụ thể đã lưu trữ của người dùng dựa vào note_id. "
                    "Thường sử dụng kết hợp sau khi gọi retrieve_notes để lấy chính xác note_id cần xóa."
                ),
                parameters={  # type: ignore[arg-type]
                    "type": "object",
                    "properties": {
                        "note_id": {"type": "string", "description": "ID của note cần xóa (UUID)."}
                    },
                    "required": ["note_id"]
                }
            )
        ]),
        genai_types.Tool(function_declarations=[
            genai_types.FunctionDeclaration(
                name="image_recognition",
                description=(
                    "Nhận diện đối tượng, người nổi tiếng, nhân vật game/anime, đếm vật thể, và trích xuất văn bản (OCR) từ một hình ảnh. "
                    "Sử dụng khi người dùng tải lên một hình ảnh và hỏi các câu hỏi liên quan đến nội dung của hình ảnh đó. "
                    "Ví dụ: 'có bao nhiêu quả táo trong ảnh?', 'người này là ai?', 'đây là nhân vật gì?', 'đọc chữ trong ảnh này'."
                ),
                parameters={  # type: ignore[arg-type]
                    "type": "object",
                    "properties": {
                        "image_url": {
                            "type": "string",
                            "description": (
                                "URL công khai của hình ảnh cần nhận diện. "
                                "QUAN TRỌNG: Nếu là link Discord CDN, phải giữ nguyên vẹn 100% URL đầy đủ "
                                "kèm các tham số xác thực ?ex=...&is=...&hm=..., tuyệt đối KHÔNG ĐƯỢC cắt bỏ đuôi query parameter."
                            ),
                        },
                        "question": {"type": "string", "description": "Câu hỏi cụ thể của người dùng về hình ảnh (ví dụ: 'đếm số lượng', 'người này là ai?', 'đây là gì?')."}
                    },
                    "required": ["image_url", "question"]
                }
            )
        ]),
    ]

    if is_admin:
        tools_list.append(
            genai_types.Tool(function_declarations=[
                genai_types.FunctionDeclaration(
                    name="manage_user_role",
                    description=(
                        "Quản lý vai trò (roles) của người dùng: Thăng chức làm Moderator, Premium hoặc Admin, "
                        "hoặc hạ chức người dùng về User thông thường. Lệnh này chỉ thực hiện được khi người gọi lệnh "
                        "(tham số user_id của chat context) là Admin thực tế của bot."
                    ),
                    parameters={  # type: ignore[arg-type]
                        "type": "object",
                        "properties": {
                            "target_user_id": {"type": "string", "description": "ID Discord số của người dùng cần thay đổi vai trò."},
                            "action": {"type": "string", "description": "Hành động: 'add' (thăng chức/thêm) hoặc 'remove' (hạ chức/xóa).", "enum": ["add", "remove"]},
                            "role": {"type": "string", "description": "Vai trò cần thiết lập: 'moderator', 'premium', hoặc 'admin'.", "enum": ["moderator", "premium", "admin"]}
                        },
                        "required": ["target_user_id", "action", "role"]
                    }
                )
            ])
        )

    return tools_list
