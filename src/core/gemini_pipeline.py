class TextParsedFunctionCall:
    def __init__(self, name, args, id=None):
        self.name = name
        self.args = args
        self.id = id

import asyncio
import re
from datetime import datetime
from typing import Any, Optional, Dict, List, Tuple

from src.core.config import logger
from src.core.prompt_loader import (
    get_azuris_system_prompt,
    get_lite_reasoning_prompt,
    get_fallback_system_prompt,
    get_three_block_context_prompt,
    get_search_budget_prompt,
    get_extra_retrieval_prompt,
    get_partial_evidence_prompt,
    get_auto_retrieval_limit_prompt,
    get_final_synthesis_prompt,
)

from .gemini_api_manager import GeminiApiManager


def _prepare_user_input_block(user_input: str, max_chars: int = 2200) -> str:
    text = (user_input or "").strip()
    if len(text) > max_chars:
        remaining = len(text) - max_chars
        text = f"{text[:max_chars]}\n...[truncated {remaining} chars to fit context]"
    return f"<USER_INPUT>\n{text}\n</USER_INPUT>"


def _prepare_user_metadata_block(privacy_context: Dict[str, Any]) -> str:
    display_name = str(privacy_context.get("discord_display_name") or "").strip()
    if not display_name:
        display_name = "Unknown"
    display_name = re.sub(r"\s+", " ", display_name)
    if len(display_name) > 80:
        display_name = display_name[:80].rstrip()

    system_role = "Admin" if bool(privacy_context.get("is_admin")) else "Standard User"
    return (
        "<USER_METADATA>\n"
        f"Discord Display Name: {display_name}\n"
        f"System Role: {system_role}\n"
        "</USER_METADATA>"
    )


def _prepare_user_context_block(user_input: str, privacy_context: Dict[str, Any], max_chars: int = 2200) -> str:
    metadata_block = _prepare_user_metadata_block(privacy_context)
    user_input_block = _prepare_user_input_block(user_input, max_chars=max_chars)
    return f"{metadata_block}\n{user_input_block}"


def _extract_intent_blocks(tool_results: str) -> Dict[str, str]:
    if not tool_results:
        return {}
    pattern = re.compile(r"\[web_search\|intent=(.*?)\]\s*(.*?)(?=\n\[web_search\|intent=|\Z)", re.DOTALL | re.IGNORECASE)
    matches = pattern.findall(tool_results)
    blocks: Dict[str, str] = {}
    for intent, body in matches:
        key = (intent or "").strip() or "unknown"
        blocks[key] = (body or "").strip()
    return blocks


def _parse_quality_counts(text: str) -> Tuple[Optional[int], Optional[int]]:
    lower = (text or "").lower()
    req_matches = [
        int(v)
        for v in re.findall(r"required (?:quality|reputable) sources:\s*(\d+)", lower)
    ]
    found_matches = [
        int(v)
        for v in re.findall(r"(?:quality|reputable) sources found:\s*(\d+)", lower)
    ]
    required = req_matches[-1] if req_matches else None
    found = found_matches[-1] if found_matches else None
    return required, found


def _is_block_sufficient(tool_results: str) -> bool:
    if not tool_results:
        return False
    lower = tool_results.lower()
    marker_groups = [
        ["top ranked sources", "required quality sources", "quality sources found"],
        ["top trusted sources", "required reputable sources", "reputable sources found"],
    ]
    if not any(all(marker in lower for marker in group) for group in marker_groups):
        return False

    required, found = _parse_quality_counts(lower)
    if required is None or found is None:
        return False

    return found >= required and "chưa đủ nguồn chất lượng" not in lower and "chưa đủ nguồn uy tín" not in lower


def _has_minimum_evidence_block(tool_results: str) -> bool:
    if not tool_results:
        return False

    lower = tool_results.lower()
    _, found = _parse_quality_counts(lower)
    if found is not None and found >= 1:
        return True

    if "additional corroborating sources:" in lower and "(không có nguồn bổ sung)" not in lower:
        return True

    return False


def _is_tool_result_sufficient(tool_results: str) -> bool:
    if not tool_results:
        return False

    intent_blocks = _extract_intent_blocks(tool_results)
    if not intent_blocks:
        return _is_block_sufficient(tool_results)

    return all(_is_block_sufficient(block) for block in intent_blocks.values())


def _has_minimum_search_evidence(tool_results: str) -> bool:
    if not tool_results:
        return False

    intent_blocks = _extract_intent_blocks(tool_results)
    if not intent_blocks:
        return _has_minimum_evidence_block(tool_results)

    return any(_has_minimum_evidence_block(block) for block in intent_blocks.values())


def _looks_semantically_incomplete(text: str) -> bool:
    cleaned = (text or "").strip()
    if len(cleaned) < 120:
        return False

    if cleaned.count("```") % 2 == 1:
        return True

    if cleaned.endswith(("...", "…", "—", "-")):
        return True

    if cleaned.endswith(("(", "[", "{")):
        return True

    last_line = cleaned.splitlines()[-1].strip().lower()
    if re.search(r"\b(và|va|hoặc|or|and|with|to|of|for|là|la|của|cho|theo)\b$", last_line):
        return True

    if not re.search(r"[.!?…]$|[\"”'\)\]]$", cleaned):
        if re.search(r"[a-z0-9]$", cleaned.lower()):
            return True

    return False


def _build_fallback_system_prompt(user_input: str, reasoning_result: str, tool_results: str) -> str:
    prompt_template = get_fallback_system_prompt()
    prompt_text = prompt_template.replace("[USER_INPUT_HERE]", user_input.strip())
    prompt_text = prompt_text.replace("[REASONING_OUTPUT_HERE]", reasoning_result.strip())
    prompt_text = prompt_text.replace(
        "[TOOL_RESULTS_HERE]",
        tool_results.strip() if tool_results else "(Không có tool được gọi)",
    )
    return prompt_text


_ARTIFACT_PATTERNS = [
    (re.compile(r'<THINKING>.*?</THINKING>', re.IGNORECASE | re.DOTALL), ''),
    (re.compile(r'^THINKING\s*\n(.*?)(?=\n[A-Z]|\n\n|$)', re.MULTILINE | re.IGNORECASE | re.DOTALL), ''),
    (re.compile(r'^\[REASONING CONTEXT:.*?\]', re.MULTILINE | re.DOTALL), ''),
    (re.compile(r'<tool_code>.*?</tool_code>', re.IGNORECASE | re.DOTALL), ''),
    (re.compile(r'<tool_result>.*?</tool_result>', re.IGNORECASE | re.DOTALL), ''),
    (re.compile(
        r'```(python|javascript|js|py)?\s*(web_search|calculate|get_weather|image_recognition|save_note|retrieve_notes|delete_note|manage_user_role).*?```',
        re.IGNORECASE | re.DOTALL,
    ), ''),
]


def _clean_response_artifacts(text: str) -> str:
    for pattern, replacement in _ARTIFACT_PATTERNS:
        text = pattern.sub(replacement, text).strip()
    return text


def _candidate_text(candidate: Any) -> str:
    parts = getattr(getattr(candidate, "content", None), "parts", None) or []
    text_parts = []
    for part in parts:
        text = getattr(part, "text", None)
        if text:
            text_parts.append(str(text))
    return _clean_response_artifacts("".join(text_parts).strip())


def _finish_reason_text(candidate: Any) -> str:
    finish_reason = getattr(candidate, "finish_reason", "")
    name = getattr(finish_reason, "name", None)
    if name:
        return str(name).lower()
    return str(finish_reason or "").lower()


def _is_truncated_candidate(candidate: Any) -> bool:
    reason = _finish_reason_text(candidate)
    if not reason:
        return False
    return any(marker in reason for marker in ("max_token", "max_tokens", "max_output", "length"))


def _append_continuation_text(current_text: str, next_text: str) -> str:
    current = (current_text or "").rstrip()
    incoming = (next_text or "").lstrip()
    if not current:
        return incoming
    if not incoming:
        return current

    max_overlap = min(len(current), len(incoming), 1200)
    for overlap in range(max_overlap, 80, -1):
        if current[-overlap:] == incoming[:overlap]:
            return current + incoming[overlap:]
    return f"{current}\n\n{incoming}"


def _long_output_prompt(base_prompt: str) -> str:
    base = (base_prompt or "[SYSTEM NOTE: Please provide a final, well-structured response.]").strip()
    return (
        f"{base}\n\n"
        "[LONG OUTPUT MODE]\n"
        "Nếu câu trả lời là báo cáo dài, hãy viết đầy đủ nhất có thể trong giới hạn output của lượt này. "
        "Không tự rút gọn chỉ vì câu trả lời dài. Nếu chạm giới hạn token, hệ thống sẽ yêu cầu viết tiếp ở lượt sau."
    )


def _continuation_prompt(accumulated_text: str, part_index: int, max_parts: int) -> str:
    tail = (accumulated_text or "")[-5000:]
    return (
        "[CONTINUATION REQUEST]\n"
        f"Đây là phần tiếp theo {part_index}/{max_parts} của cùng một câu trả lời dài. "
        "Hãy viết tiếp ngay từ điểm dừng, không lặp lại phần đã viết, không mở đầu lại, giữ cùng ngôn ngữ và định dạng.\n\n"
        "<PREVIOUS_OUTPUT_TAIL>\n"
        f"{tail}\n"
        "</PREVIOUS_OUTPUT_TAIL>"
    )


class GeminiPipeline:
    """Two-tier Gemini pipeline: Flash-Lite reasoning -> Flash final output."""

    def __init__(
        self,
        *,
        config,
        api_mgr: GeminiApiManager,
        tools_mgr,
        identity_builder,
        reasoning_model_alias: str,
        final_model_alias: str,
        fallback_model_alias: str,
    ):
        self.config = config
        self.api_mgr = api_mgr
        self.tools_mgr = tools_mgr
        self._build_identity_capability_instruction = identity_builder
        self.reasoning_model_alias = reasoning_model_alias
        self.final_model_alias = final_model_alias
        self.fallback_model_alias = fallback_model_alias
        self.logger = logger

    async def _continue_final_output(
        self,
        *,
        accumulated_text: str,
        system_instruction: str,
        generation_config: Dict[str, Any],
        model_alias: str,
        user_id: str,
        stage: str,
    ) -> str:
        max_calls = int(getattr(self.config, "FINAL_CONTINUATION_MAX_CALLS", 5) or 5)
        current_text = accumulated_text
        per_part_retries = 2

        for part_index in range(2, max_calls + 1):
            continuation_messages = [{
                "role": "user",
                "parts": [{"text": _continuation_prompt(current_text, part_index, max_calls)}],
            }]

            for retry_index in range(1, per_part_retries + 1):
                quota_ok = await self.api_mgr._acquire_gemini_quota(
                    continuation_messages,
                    generation_config["max_output_tokens"],
                    model_alias,
                    extra_text=system_instruction,
                )
                if not quota_ok:
                    self.logger.warning(f"{stage} continuation quota blocked for {user_id}; returning accumulated output.")
                    return current_text

                api_key: Optional[str] = None
                model_name: Optional[str] = None
                used_model_alias: Optional[str] = None
                key_reservation: Optional[Dict[str, str]] = None

                try:
                    api_key, model_name, used_model_alias, key_reservation = await self.api_mgr._get_best_api_key(model_alias)
                    if not api_key or not model_name:
                        self.logger.warning(f"{stage} continuation has no available key for {user_id}; returning accumulated output.")
                        return current_text

                    await self.api_mgr._throttle_api_request(api_key)
                    self.logger.info(
                        f"{stage} continuation {part_index}/{max_calls} retry {retry_index}/{per_part_retries} for {user_id} ({model_name})"
                    )

                    response = await self.api_mgr._generate_gemini_content(
                        api_key=api_key,
                        model_name=model_name,
                        system_instruction=system_instruction,
                        generation_config=generation_config,
                        messages=continuation_messages,
                    )
                    self.api_mgr._commit_selected_key(key_reservation)

                    candidate = response.candidates[0] if response.candidates else None
                    if not (candidate and candidate.content and candidate.content.parts):
                        self.logger.warning(
                            f"{stage} continuation empty candidate on part {part_index}/{max_calls}; returning accumulated output."
                        )
                        return current_text

                    next_text = _candidate_text(candidate)
                    if not next_text:
                        self.logger.warning(
                            f"{stage} continuation empty text on part {part_index}/{max_calls}; returning accumulated output."
                        )
                        return current_text

                    current_text = _append_continuation_text(current_text, next_text)
                    if not _is_truncated_candidate(candidate):
                        return current_text
                    break

                except Exception as e:
                    error_str = str(e)
                    if self.api_mgr._is_invalid_key_error(error_str):
                        if api_key:
                            self.api_mgr._mark_key_as_failed(
                                api_key,
                                used_model_alias,
                                duration=86400,
                                reason="invalid_key",
                                permanently_exhaust=True,
                                reservation=key_reservation,
                            )
                        self.logger.warning(
                            f"{stage} continuation invalid key on part {part_index}/{max_calls} retry {retry_index}/{per_part_retries}; rotating."
                        )
                        continue

                    if self.api_mgr._is_rate_limit_error(error_str):
                        error_type = "unavailable" if self.api_mgr._is_unavailable_error(error_str) else "rate_limit"
                        if api_key:
                            self.api_mgr._mark_key_as_failed(
                                api_key,
                                used_model_alias,
                                duration=60,
                                reason=error_type,
                                reservation=key_reservation,
                            )
                        self.logger.warning(
                            f"{stage} continuation transient {error_type} on part {part_index}/{max_calls} retry {retry_index}/{per_part_retries}; rotating."
                        )
                        await asyncio.sleep(2)
                        continue

                    if self.api_mgr._is_connection_error(e):
                        if api_key:
                            self.api_mgr._mark_key_as_failed(
                                api_key,
                                used_model_alias,
                                duration=120,
                                reason="endpoint_down",
                                reservation=key_reservation,
                            )
                        self.logger.warning(
                            f"{stage} continuation endpoint unreachable on part {part_index}/{max_calls}; rotating."
                        )
                        continue

                    self.api_mgr._log_gemini_exception(
                        stage=f"{stage}_continuation",
                        error=e,
                        user_id=user_id,
                        model_alias=used_model_alias,
                        model_name=model_name,
                        api_key=api_key,
                        attempt=part_index,
                        max_attempts=max_calls,
                    )
                    return current_text

        return current_text

    async def call_gemini_api(self, messages: List[Dict[str, Any]], user_id: str, privacy_context: Dict[str, Any]) -> str:
        """Two-Tier Model Strategy: Flash-Lite (reasoning) -> Flash (final output)."""

        reasoning_result, tool_results = await self._call_gemini_reasoning_loop(messages, user_id, privacy_context)

        if tool_results and not _is_tool_result_sufficient(tool_results):
            partial_ok = self.config.SEARCH_ALLOW_PARTIAL_ANSWER and _has_minimum_search_evidence(tool_results)
            if self.config.SEARCH_ENABLE_EXTRA_RETRIEVAL_PASS and not partial_ok:
                self.logger.info(f"Evidence insufficient for {user_id}. Running one additional retrieval pass.")
                followup_messages = [msg.copy() for msg in messages]
                followup_messages.append({
                    "role": "user",
                    "parts": [{"text": get_extra_retrieval_prompt()}],
                })

                retry_reasoning, retry_tool_results = await self._call_gemini_reasoning_loop(followup_messages, user_id, privacy_context)
                if retry_reasoning and retry_reasoning not in {"Reasoning completed", "Reasoning loop failed"}:
                    reasoning_result = retry_reasoning
                if retry_tool_results:
                    tool_results = f"{tool_results}\n\n[RETRY PASS]\n{retry_tool_results}" if tool_results else retry_tool_results
            else:
                self.logger.info(
                    f"Evidence below strict threshold for {user_id}, continuing with partial evidence mode={self.config.SEARCH_ALLOW_PARTIAL_ANSWER}."
                )

        final_output = await self._call_gemini_final(messages, reasoning_result, tool_results, user_id, privacy_context)
        return final_output

    async def _call_gemini_reasoning_loop(self, messages: List[Dict[str, Any]], user_id: str, privacy_context: Dict[str, Any]) -> Tuple[str, str]:
        MAX_RETRIES = self.config.REASONING_MAX_API_RETRIES
        reasoning_model_alias = self.reasoning_model_alias

        is_admin = bool(privacy_context.get("is_admin"))
        tools = self.tools_mgr.get_all_tools(is_admin=is_admin)
        generation_config = {
            "temperature": 0.35,
            "top_p": 0.9,
            "top_k": 40,
            "max_output_tokens": 2600,
        }

        reasoning_messages = [msg.copy() for msg in messages]
        tool_results_list: List[str] = []
        web_search_calls = 0
        iteration = 0

        for attempt in range(MAX_RETRIES):
            api_key: Optional[str] = None
            model_name: Optional[str] = None
            used_model_alias: Optional[str] = None
            key_reservation: Optional[Dict[str, str]] = None

            try:
                current_time_str = datetime.now().strftime("%A, %d %B %Y %H:%M")
                time_context = f"Current time: {current_time_str}\n"
                admin_cross_user_evidence = str(privacy_context.get("admin_cross_user_evidence") or "")
                extra_admin_context = f"\n\n{admin_cross_user_evidence}\n" if admin_cross_user_evidence else ""
                system_instruction = (
                    time_context
                    + self._build_identity_capability_instruction(privacy_context)
                    + get_lite_reasoning_prompt()
                    + extra_admin_context
                )

                # Thay thế động tên bot
                bot_name = privacy_context.get("bot_name", "Chad Gibiti")
                system_instruction = system_instruction.replace("Chad Gibiti", bot_name)

                while iteration < self.config.REASONING_MAX_LOOPS:
                    quota_ok = await self.api_mgr._acquire_gemini_quota(
                        reasoning_messages,
                        generation_config["max_output_tokens"],
                        reasoning_model_alias,
                        extra_text=system_instruction,
                    )
                    if not quota_ok:
                        return ("API busy, please retry shortly.", "")

                    api_key, model_name, used_model_alias, key_reservation = await self.api_mgr._get_best_api_key(reasoning_model_alias)
                    if not api_key or not model_name:
                        return ("API unavailable, please retry shortly.", "")

                    self.logger.info(f"Reasoning loop {iteration} for user {user_id} ({model_name})")
                    await self.api_mgr._throttle_api_request(api_key)

                    response = await self.api_mgr._generate_gemini_content(
                        api_key=api_key,
                        model_name=model_name,
                        system_instruction=system_instruction,
                        generation_config=generation_config,
                        messages=reasoning_messages,
                        tools=tools,
                    )
                    self.api_mgr._commit_selected_key(key_reservation)
                    
                    # Successfully completed a reasoning step loop without network error
                    iteration += 1

                    candidate = response.candidates[0] if response.candidates else None
                    if not (candidate and candidate.content and candidate.content.parts):
                        if api_key:
                            self.api_mgr._mark_key_as_failed(
                                api_key,
                                used_model_alias,
                                duration=300,
                                reason="empty_candidate",
                                reservation=key_reservation,
                            )
                        raise ValueError(
                            f"Empty candidate returned from reasoning loop for key ...{api_key[-4:] if api_key else 'None'}"
                        )

                    has_function_calls = False
                    model_parts = []
                    function_response_parts = []

                    for part in candidate.content.parts:
                        if part.function_call and part.function_call.name:
                            has_function_calls = True
                            fc = part.function_call
                            tool_name = (fc.name or "").lower()
                            args = dict(fc.args) if fc.args else {}
                            self.logger.info(f"[Reasoning Loop {iteration}] Model requested tool: {fc.name} args={args}")
                            model_parts.append(part)

                            # Intercept JSON parsing errors from the wrapper
                            if "_parsing_error" in args:
                                error_msg = args["_parsing_error"]
                                raw_args = args.get("_raw_arguments", "")
                                tool_res = "System Error: Failed to parse tool arguments as valid JSON. Error: {} Raw input was: {} Please fix your JSON formatting and try again.".format(error_msg, raw_args)
                                self.logger.warning(f"[Reasoning Loop {iteration}] Tool {fc.name} parsing failed: {error_msg}")
                                tool_results_list.append(f"[{fc.name}|error=json_parse_failed]")
                                func_res = {"name": fc.name, "response": {"content": str(tool_res)}}
                                if getattr(fc, 'id', None):
                                    func_res['id'] = fc.id
                                function_response_parts.append({"function_response": func_res})
                                continue

                            max_search_calls = getattr(self.config, "MAX_SEARCH_CALLS_PER_TURN", 5)
                            if tool_name == "web_search" and web_search_calls >= max_search_calls:
                                budget_msg = get_search_budget_prompt()
                                self.logger.info(f"[Reasoning Loop {iteration}] Tool {fc.name} blocked by search budget.")
                                func_res = {"name": "web_search", "response": {"content": budget_msg}}
                                if getattr(fc, 'id', None):
                                    func_res['id'] = fc.id
                                function_response_parts.append({"function_response": func_res})
                                continue

                            tool_res = await self.tools_mgr.call_tool(fc, user_id)
                            self.logger.info(f"[Reasoning Loop {iteration}] Tool {fc.name} returned content (length={len(str(tool_res))})")
                            if tool_name == "web_search":
                                web_search_calls += 1
                                intent_query = (args.get("query") or "").strip()
                                tool_results_list.append(f"[{fc.name}|intent={intent_query}] {tool_res}")
                            else:
                                tool_results_list.append(f"[{fc.name}] {tool_res}")

                            func_res = {"name": fc.name, "response": {"content": str(tool_res)}}
                            if getattr(fc, 'id', None):
                                func_res['id'] = fc.id
                            function_response_parts.append({"function_response": func_res})
                        
                        elif part.text and has_function_calls:
                            # We can also append text parts from the model to the model_parts if they exist alongside function calls
                            model_parts.append(part)

                    if has_function_calls:
                        reasoning_messages.append({"role": "model", "parts": model_parts})
                        reasoning_messages.append({"role": "user", "parts": function_response_parts})
                        continue
                    
                    part = candidate.content.parts[0]
                    if part.text:
                        text = part.text.strip()

                        tool_code_match = re.search(r'<tool_code>(.*?)</tool_code>', text, re.IGNORECASE | re.DOTALL)
                        tool_matches = []
                        if tool_code_match:
                            tool_code_content = tool_code_match.group(1)
                            tool_matches = re.findall(r'(web_search|calculate|get_weather|image_recognition|save_note|retrieve_notes|delete_note|manage_user_role)\s*\(\s*([^)]+)\)', tool_code_content, re.IGNORECASE)
                        elif text.strip().upper().startswith("TOOL_CALL:"):
                            tool_matches = re.findall(r'(web_search|calculate|get_weather|image_recognition|save_note|retrieve_notes|delete_note|manage_user_role)\s*\(\s*([^)]+)\)', text, re.IGNORECASE)

                        if tool_matches:
                            executed_tool = False
                            for tool_name, args_str in tool_matches:
                                self.logger.info(f"[Reasoning Loop {iteration}] Detected parsed tool call in text: {tool_name}({args_str})")
                                args_dict = {}
                                for arg_match in re.finditer(r'(\w+)\s*=\s*["\']([^"\']+)["\']', args_str):
                                    key, value = arg_match.groups()
                                    args_dict[key] = value

                                if not args_dict:
                                    continue

                                tool_name_l = tool_name.lower()
                                if tool_name_l == "web_search" and not args_dict.get("query"):
                                    continue

                                max_search_calls = getattr(self.config, "MAX_SEARCH_CALLS_PER_TURN", 5)
                                if tool_name_l == "web_search" and web_search_calls >= max_search_calls:
                                    budget_msg = get_search_budget_prompt()
                                    self.logger.info(f"[Reasoning Loop {iteration}] Parsed tool {tool_name_l} blocked by search budget.")
                                    reasoning_messages.append({"role": "model", "parts": [{"text": text}]})
                                    reasoning_messages.append({
                                        "role": "user",
                                        "parts": [{"function_response": {"name": "web_search", "response": {"content": budget_msg}}}]
                                    })
                                    executed_tool = True
                                    break

                                fc = TextParsedFunctionCall(tool_name_l, args_dict)
                                tool_res = await self.tools_mgr.call_tool(fc, user_id)
                                self.logger.info(f"[Reasoning Loop {iteration}] Parsed tool {tool_name_l} returned content (length={len(str(tool_res))})")
                                if tool_name_l == "web_search":
                                    web_search_calls += 1
                                    intent_query = (args_dict.get("query") or "").strip()
                                    tool_results_list.append(f"[{tool_name_l}|intent={intent_query}] {tool_res}")
                                else:
                                    tool_results_list.append(f"[{tool_name_l}] {tool_res}")

                                reasoning_messages.append({"role": "model", "parts": [{"text": text}]})
                                reasoning_messages.append({
                                    "role": "user",
                                    "parts": [{"function_response": {"name": tool_name_l, "response": {"content": str(tool_res)}}}]
                                })
                                executed_tool = True
                                break

                            if executed_tool:
                                continue

                        if text and len(text) > 3:
                            self.logger.info(f"[Reasoning Loop {iteration}] Finished reasoning. Output text summary: {text[:150]}...")
                            tool_results_str = "\n".join(tool_results_list) if tool_results_list else ""
                            return (text, tool_results_str)
                        break

                    self.logger.info(f"[Reasoning Loop {iteration}] Loop broken or ended without text. Continuing.")
                    break

                tool_results_str = "\n".join(tool_results_list) if tool_results_list else ""
                return ("Reasoning completed", tool_results_str)

            except Exception as e:
                error_str = str(e)

                if "Empty candidate" in error_str:
                    self.logger.warning(f"⚠️ {error_str}. Rotating key and retrying attempt {attempt + 1}/{MAX_RETRIES}.")
                    await asyncio.sleep(1)
                    continue

                if self.api_mgr._is_invalid_key_error(error_str):
                    if api_key:
                        self.api_mgr._mark_key_as_failed(
                            api_key,
                            used_model_alias,
                            duration=86400,
                            reason="invalid_key",
                            permanently_exhaust=True,
                            reservation=key_reservation,
                        )
                    self.logger.warning("Lite model received invalid API key error. Rotating key immediately.")
                    continue

                if self.api_mgr._is_rate_limit_error(error_str):
                    error_type = "unavailable" if self.api_mgr._is_unavailable_error(error_str) else "rate_limit"
                    wait_time = 2 + (attempt * 2)

                    if api_key:
                        self.logger.warning(
                            f"⚠️ Lite Key ...{api_key[-4:]} {error_type}. Retrying with preserved reasoning state "
                            f"(attempt {attempt + 1}/{MAX_RETRIES})."
                        )
                        self.api_mgr._mark_key_as_failed(api_key, used_model_alias, duration=60, reason=error_type, reservation=key_reservation)
                    else:
                        self.logger.warning(
                            f"⚠️ Lite transient {error_type} without selected key. Retrying with preserved reasoning state "
                            f"(attempt {attempt + 1}/{MAX_RETRIES})."
                        )

                    self.logger.info(
                        f"Reasoning state preserved: messages={len(reasoning_messages)} "
                        f"tool_results={len(tool_results_list)} web_search_calls={web_search_calls}"
                    )
                    self.logger.info(f"⏱️ Reasoning retry backoff {wait_time}s ({error_type}).")
                    await asyncio.sleep(wait_time)
                    continue

                if self.api_mgr._is_connection_error(e):
                    if api_key:
                        self.api_mgr._mark_key_as_failed(
                            api_key,
                            used_model_alias,
                            duration=120,
                            reason="endpoint_down",
                            reservation=key_reservation,
                        )
                    self.logger.warning(
                        f"Lite model endpoint unreachable; rotating key (attempt {attempt + 1}/{MAX_RETRIES})."
                    )
                    continue

                self.api_mgr._log_gemini_exception(
                    stage="reasoning_lite",
                    error=e,
                    user_id=user_id,
                    model_alias=used_model_alias,
                    model_name=model_name,
                    api_key=api_key,
                    attempt=attempt + 1,
                    max_attempts=MAX_RETRIES,
                )
                await asyncio.sleep(1 + attempt)
                continue

        tool_results_str = "\n".join(tool_results_list) if tool_results_list else ""
        return "Reasoning loop failed", tool_results_str

    async def _call_gemini_final(self, original_messages: List[Dict[str, Any]], reasoning_result: str, tool_results: str, user_id: str, privacy_context: Dict[str, Any]) -> str:
        MAX_RETRIES = max(5, self.config.FINAL_MAX_API_RETRIES)
        final_model_alias = self.final_model_alias

        if tool_results and not _is_tool_result_sufficient(tool_results):
            if self.config.SEARCH_ALLOW_PARTIAL_ANSWER and _has_minimum_search_evidence(tool_results):
                self.logger.info(f"Using partial evidence response mode for user {user_id}.")
                reasoning_result = (
                    (reasoning_result or "")
                    + "\n\n" + get_partial_evidence_prompt()
                ).strip()
            else:
                self.logger.info(f"Evidence still limited for {user_id}; auto-switching to strict uncertainty response mode.")
                reasoning_result = (
                    (reasoning_result or "")
                    + "\n\n" + get_auto_retrieval_limit_prompt()
                ).strip()

        for attempt in range(MAX_RETRIES):
            api_key: Optional[str] = None
            model_name: Optional[str] = None
            used_model_alias: Optional[str] = None
            key_reservation: Optional[Dict[str, str]] = None

            try:
                current_time_str = datetime.now().strftime("%A, %d %B %Y %H:%M")
                time_context = f"SYSTEM ALERT: Current Date/Time is {current_time_str}.\n\n"

                user_input = ""
                if original_messages and original_messages[-1].get("role") == "user":
                    user_input = original_messages[-1].get("parts", [{}])[0].get("text", "")

                user_context_block = _prepare_user_context_block(user_input, privacy_context)

                three_block_template = get_three_block_context_prompt()
                three_block_context = (
                    three_block_template
                    .replace("[USER_CONTEXT_BLOCK]", user_context_block)
                    .replace("[REASONING_RESULT]", reasoning_result or "")
                    .replace("[TOOL_RESULTS]", tool_results if tool_results else "(No tools were called)")
                )

                admin_cross_user_evidence = str(privacy_context.get("admin_cross_user_evidence") or "")
                extra_admin_context = f"\n\n{admin_cross_user_evidence}\n" if admin_cross_user_evidence else ""
                system_with_context = (
                    time_context
                    + self._build_identity_capability_instruction(privacy_context)
                    + get_azuris_system_prompt()
                    + extra_admin_context
                    + three_block_context
                )

                # Thay thế động tên bot
                bot_name = privacy_context.get("bot_name", "Chad Gibiti")
                system_with_context = system_with_context.replace("Chad Gibiti", bot_name)

                api_key, model_name, used_model_alias, key_reservation = await self.api_mgr._get_best_api_key(final_model_alias)
                if not api_key or not model_name:
                    self.logger.warning(f"⚠️ ALL KEYS FROZEN - Fallback to lite model for user {user_id}")
                    return await self._fallback_lite_as_flash(original_messages, reasoning_result, tool_results, user_id, privacy_context)

                generation_config = {
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "top_k": 40,
                    "max_output_tokens": int(getattr(self.config, "FINAL_MAX_OUTPUT_TOKENS", 8192) or 8192),
                }

                final_messages = [{
                    "role": "user",
                    "parts": [{"text": _long_output_prompt(get_final_synthesis_prompt())}]
                }]

                quota_ok = await self.api_mgr._acquire_gemini_quota(
                    final_messages,
                    generation_config["max_output_tokens"],
                    final_model_alias,
                    extra_text=system_with_context,
                )
                if not quota_ok:
                    self.logger.warning("Final model quota gate blocked; trying lite fallback finalizer.")
                    return await self._fallback_lite_as_flash(original_messages, reasoning_result, tool_results, user_id, privacy_context)

                await self.api_mgr._throttle_api_request(api_key)

                self.logger.info(f"Final output for user {user_id} ({model_name}, attempt {attempt + 1}/{MAX_RETRIES})")

                stream_generator = self.api_mgr._generate_gemini_content_stream(
                    api_key=api_key,
                    model_name=model_name,
                    system_instruction=system_with_context,
                    generation_config=generation_config,
                    messages=final_messages,
                )

                full_text_parts = []
                finish_reason = "stop"
                async for chunk in stream_generator:
                    if hasattr(chunk, "candidates") and chunk.candidates:
                        cand = chunk.candidates[0]
                        if cand.content and cand.content.parts:
                            for part in cand.content.parts:
                                if part.text:
                                    full_text_parts.append(part.text)
                        if getattr(cand, "finish_reason", None):
                            finish_reason = cand.finish_reason

                accumulated_text = "".join(full_text_parts)

                # Construct Mock Response
                class MockPart:
                    def __init__(self, text):
                        self.text = text
                class MockContent:
                    def __init__(self, text):
                        self.parts = [MockPart(text)]
                class MockCandidate:
                    def __init__(self, text, finish_reason):
                        self.content = MockContent(text)
                        class MockFinishReason:
                            def __init__(self, name):
                                self.name = name
                        self.finish_reason = MockFinishReason(finish_reason)
                class MockResponse:
                    def __init__(self, text, finish_reason):
                        self.candidates = [MockCandidate(text, finish_reason)]

                response = MockResponse(accumulated_text, finish_reason)
                self.api_mgr._commit_selected_key(key_reservation)

                candidate = response.candidates[0] if response.candidates else None
                if not (candidate and candidate.content and candidate.content.parts):
                    if api_key:
                        self.api_mgr._mark_key_as_failed(
                            api_key,
                            used_model_alias,
                            duration=300,
                            reason="empty_candidate",
                            reservation=key_reservation,
                        )
                    self.logger.warning(
                        f"Final output empty candidate for {user_id} with key ...{api_key[-4:] if api_key else 'None'} "
                        f"(attempt {attempt + 1}/{MAX_RETRIES}), rotating key and retrying."
                    )
                    await asyncio.sleep(1)
                    continue

                text = _candidate_text(candidate)
                if text and len(text) > 5:
                    if _is_truncated_candidate(candidate):
                        self.logger.info(f"Final output hit token limit for {user_id}; requesting continuation chunks.")
                        return await self._continue_final_output(
                            accumulated_text=text,
                            system_instruction=system_with_context,
                            generation_config=generation_config,
                            model_alias=final_model_alias,
                            user_id=user_id,
                            stage="final_flash",
                        )
                    if _looks_semantically_incomplete(text):
                        self.logger.info(f"Final output looks semantically incomplete for {user_id}; requesting continuation.")
                        return await self._continue_final_output(
                            accumulated_text=text,
                            system_instruction=system_with_context,
                            generation_config=generation_config,
                            model_alias=final_model_alias,
                            user_id=user_id,
                            stage="final_flash_semantic",
                        )
                    return text

                self.logger.warning(
                    f"Final output empty text for {user_id} "
                    f"(attempt {attempt + 1}/{MAX_RETRIES}), retrying."
                )
                await asyncio.sleep(1 + attempt)
                continue

            except Exception as e:
                error_str = str(e)

                if self.api_mgr._is_invalid_key_error(error_str):
                    if api_key:
                        self.api_mgr._mark_key_as_failed(
                            api_key,
                            used_model_alias,
                            duration=86400,
                            reason="invalid_key",
                            permanently_exhaust=True,
                            reservation=key_reservation,
                        )
                    self.logger.warning(f"⚠️ Flash model invalid key on attempt {attempt + 1}/{MAX_RETRIES}; rotating immediately.")
                    continue

                if self.api_mgr._is_rate_limit_error(error_str):
                    error_type = "unavailable" if self.api_mgr._is_unavailable_error(error_str) else "rate_limit"
                    if api_key:
                        self.logger.warning(
                            f"⚠️ Flash Key ...{api_key[-4:]} {error_type}. Attempt {attempt + 1}/{MAX_RETRIES}"
                        )
                        self.api_mgr._mark_key_as_failed(api_key, used_model_alias, duration=60, reason=error_type, reservation=key_reservation)

                    wait_time = 2 + (attempt * 2)
                    self.logger.info(f"⏱️ Waiting {wait_time}s before retry ({error_type})...")
                    await asyncio.sleep(wait_time)

                    if attempt == MAX_RETRIES - 1:
                        self.logger.warning(f"❌ Flash model exhausted ({MAX_RETRIES} retries). Fallback to lite model for {user_id}")
                        return await self._fallback_lite_as_flash(original_messages, reasoning_result, tool_results, user_id, privacy_context)

                    continue

                if self.api_mgr._is_connection_error(e):
                    if api_key:
                        self.api_mgr._mark_key_as_failed(
                            api_key,
                            used_model_alias,
                            duration=120,
                            reason="endpoint_down",
                            reservation=key_reservation,
                        )
                    self.logger.warning(f"⚠️ Flash model endpoint unreachable; rotating key (attempt {attempt + 1}/{MAX_RETRIES}).")
                    continue

                self.api_mgr._log_gemini_exception(
                    stage="final_flash",
                    error=e,
                    user_id=user_id,
                    model_alias=used_model_alias,
                    model_name=model_name,
                    api_key=api_key,
                    attempt=attempt + 1,
                    max_attempts=MAX_RETRIES,
                )
                continue

        self.logger.warning(f"❌ Final output completely failed. Using fallback lite model for {user_id}")
        return await self._fallback_lite_as_flash(original_messages, reasoning_result, tool_results, user_id, privacy_context)

    async def _fallback_lite_as_flash(self, original_messages: List[Dict[str, Any]], reasoning_result: str, tool_results: str, user_id: str, privacy_context: Dict[str, Any]) -> str:
        MAX_RETRIES = self.config.FALLBACK_MAX_API_RETRIES
        fallback_model_alias = self.fallback_model_alias
        user_facing_error = "Xin lỗi, mình chưa lấy được kết quả ổn định lúc này. Bạn thử lại sau ít phút nhé."

        for attempt in range(MAX_RETRIES):
            api_key: Optional[str] = None
            model_name: Optional[str] = None
            used_model_alias: Optional[str] = None
            key_reservation: Optional[Dict[str, str]] = None

            try:
                user_input = ""
                if original_messages and original_messages[-1].get("role") == "user":
                    user_input = original_messages[-1].get("parts", [{}])[0].get("text", "")

                current_time_str = datetime.now().strftime("%A, %d %B %Y %H:%M")
                time_context = f"SYSTEM ALERT: Current Date/Time is {current_time_str}.\n\n"
                user_context_block = _prepare_user_context_block(user_input, privacy_context)
                admin_cross_user_evidence = str(privacy_context.get("admin_cross_user_evidence") or "")
                extra_admin_context = f"\n\n{admin_cross_user_evidence}\n" if admin_cross_user_evidence else ""
                system_with_context = (
                    time_context
                    + self._build_identity_capability_instruction(privacy_context)
                    + extra_admin_context
                    + _build_fallback_system_prompt(
                        user_context_block,
                        reasoning_result,
                        tool_results,
                    )
                )

                # Thay thế động tên bot
                bot_name = privacy_context.get("bot_name", "Chad Gibiti")
                system_with_context = system_with_context.replace("Chad Gibiti", bot_name)

                api_key, model_name, used_model_alias, key_reservation = await self.api_mgr._get_best_api_key(fallback_model_alias)
                if not api_key or not model_name:
                    return user_facing_error

                generation_config = {
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "top_k": 40,
                    "max_output_tokens": int(getattr(self.config, "FALLBACK_MAX_OUTPUT_TOKENS", 8192) or 8192),
                }

                final_messages = [{
                    "role": "user",
                    "parts": [{"text": _long_output_prompt(get_final_synthesis_prompt())}],
                }]

                quota_ok = await self.api_mgr._acquire_gemini_quota(
                    final_messages,
                    generation_config["max_output_tokens"],
                    fallback_model_alias,
                    extra_text=system_with_context,
                )
                if not quota_ok:
                    return user_facing_error

                await self.api_mgr._throttle_api_request(api_key)

                self.logger.info(f"Fallback: Using {model_name} for {user_id} (attempt {attempt + 1}/3)")

                response = await self.api_mgr._generate_gemini_content(
                    api_key=api_key,
                    model_name=model_name,
                    system_instruction=system_with_context,
                    generation_config=generation_config,
                    messages=final_messages,
                )
                self.api_mgr._commit_selected_key(key_reservation)

                candidate = response.candidates[0] if response.candidates else None
                if not (candidate and candidate.content and candidate.content.parts):
                    if api_key:
                        self.api_mgr._mark_key_as_failed(
                            api_key,
                            used_model_alias,
                            duration=300,
                            reason="empty_candidate",
                            reservation=key_reservation,
                        )
                    self.logger.warning(
                        f"Fallback empty candidate for {user_id} with key ...{api_key[-4:] if api_key else 'None'} "
                        f"(attempt {attempt + 1}/{MAX_RETRIES}), rotating key and retrying."
                    )
                    continue

                text = _candidate_text(candidate)
                if text and len(text) > 5:
                    self.logger.info(f"✅ Fallback success for {user_id}")
                    if _is_truncated_candidate(candidate):
                        self.logger.info(f"Fallback output hit token limit for {user_id}; requesting continuation chunks.")
                        return await self._continue_final_output(
                            accumulated_text=text,
                            system_instruction=system_with_context,
                            generation_config=generation_config,
                            model_alias=fallback_model_alias,
                            user_id=user_id,
                            stage="fallback_lite",
                        )
                    if _looks_semantically_incomplete(text):
                        self.logger.info(f"Fallback output looks semantically incomplete for {user_id}; requesting continuation.")
                        return await self._continue_final_output(
                            accumulated_text=text,
                            system_instruction=system_with_context,
                            generation_config=generation_config,
                            model_alias=fallback_model_alias,
                            user_id=user_id,
                            stage="fallback_lite_semantic",
                        )
                    return text

            except Exception as e:
                error_str = str(e)

                if self.api_mgr._is_invalid_key_error(error_str):
                    if api_key:
                        self.api_mgr._mark_key_as_failed(
                            api_key,
                            used_model_alias,
                            duration=86400,
                            reason="invalid_key",
                            permanently_exhaust=True,
                            reservation=key_reservation,
                        )
                    self.logger.warning(f"⚠️ Lite fallback invalid key on attempt {attempt + 1}/3; rotating immediately.")
                    continue

                if self.api_mgr._is_rate_limit_error(error_str):
                    error_type = "unavailable" if self.api_mgr._is_unavailable_error(error_str) else "rate_limit"
                    self.logger.warning(f"⚠️ Lite fallback transient {error_type}. Attempt {attempt + 1}/3")
                    if api_key:
                        self.api_mgr._mark_key_as_failed(api_key, used_model_alias, duration=60, reason=error_type, reservation=key_reservation)
                    await asyncio.sleep(2 + attempt * 2)
                    continue

                if self.api_mgr._is_connection_error(e):
                    if api_key:
                        self.api_mgr._mark_key_as_failed(
                            api_key,
                            used_model_alias,
                            duration=120,
                            reason="endpoint_down",
                            reservation=key_reservation,
                        )
                    self.logger.warning("⚠️ Lite fallback endpoint unreachable; rotating key.")
                    continue

                self.api_mgr._log_gemini_exception(
                    stage="fallback_lite",
                    error=e,
                    user_id=user_id,
                    model_alias=used_model_alias,
                    model_name=model_name,
                    api_key=api_key,
                    attempt=attempt + 1,
                    max_attempts=MAX_RETRIES,
                )
                continue

        return user_facing_error
