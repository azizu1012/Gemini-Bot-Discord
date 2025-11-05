import discord
from discord.ext import commands
from discord import app_commands
from collections import defaultdict, deque
from datetime import datetime
from typing import Dict, Deque, Any, Optional

from config import logger, ADMIN_ID
from database import init_db, backup_db, cleanup_db
from memory import init_json_memory
from logger import log_message
from message_handler import handle_message

# --- KHỞI TẠO BOT ---
intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# --- GLOBAL VARS ---
mention_history: Dict[str, list] = {}
confirmation_pending: Dict[str, Dict[str, Any]] = {}
admin_confirmation_pending: Dict[str, Dict[str, Any]] = {}
user_queue: defaultdict[str, Deque[datetime]] = defaultdict(deque)

# --- EVENTS ---
@bot.event
async def on_ready() -> None:
    try:
        synced = await bot.tree.sync()
        logger.info(f"Đã sync {len(synced)} slash commands!")
    except Exception as e:
        logger.error(f"Lỗi sync slash: {e}")
    await init_db()
    init_json_memory()
    await cleanup_db()
    await backup_db()
    logger.info(f'{bot.user} online!')

@bot.event
async def on_message(message: discord.Message) -> None:
    await handle_message(message, bot, mention_history, confirmation_pending, admin_confirmation_pending, user_queue)



# --- SLASH COMMANDS ---
def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        return str(interaction.user.id) == ADMIN_ID
    return app_commands.check(predicate)

@bot.tree.command(name="reset-chat", description="Xóa lịch sử chat của bạn")
async def reset_chat_slash(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    user_id = str(interaction.user.id)
    confirmation_pending[user_id] = {'timestamp': datetime.now(), 'awaiting': True}
    await interaction.followup.send("Chắc chắn xóa lịch sử chat? Reply **yes** hoặc **y** trong 60 giây! 😳", ephemeral=True)

@bot.tree.command(name="reset-all", description="Xóa toàn bộ DB (CHỈ ADMIN)")
@is_admin()
async def reset_all_slash(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    admin_confirmation_pending[str(interaction.user.id)] = {'timestamp': datetime.now(), 'awaiting': True}
    await interaction.followup.send("⚠️ **ADMIN CONFIRM**: Reply **YES RESET** trong 60 giây để xóa toàn bộ DB + Memory!", ephemeral=True)

@bot.tree.command(name="message_to", description="Gửi tin nhắn tới user hoặc kênh (CHỈ ADMIN)")
@app_commands.describe(
    user="User nhận tin nhắn (chọn hoặc nhập ID)",
    message="Nội dung tin nhắn",
    channel="Kênh để gửi tin nhắn (tùy chọn, mặc định là DM)"
)
@is_admin()
async def message_to_slash(interaction: discord.Interaction, user: discord.User, message: str, channel: Optional[discord.TextChannel] = None) -> None:
    await interaction.response.defer(ephemeral=True)
    user_id = str(user.id)
    cleaned_message = ' '.join(message.strip().split())
    
    try:
        target_user = await bot.fetch_user(int(user_id))
    except (ValueError, discord.NotFound):
        await interaction.followup.send("ID user không hợp lệ hoặc không tìm thấy! 😕", ephemeral=True)
        return
    
    try:
        if channel:
            if not isinstance(channel, discord.TextChannel):
                await interaction.followup.send("Kênh phải là text channel! 😅", ephemeral=True)
                return
            if not interaction.guild:
                await interaction.followup.send("Lệnh này không thể dùng trong DM khi có kênh.", ephemeral=True)
                return
            if channel.guild != interaction.guild:
                await interaction.followup.send("Kênh phải cùng server! 😢", ephemeral=True)
                return
            if not channel.permissions_for(interaction.guild.me).send_messages:
                await interaction.followup.send("Bot không có quyền gửi tin nhắn trong kênh này! 😓", ephemeral=True)
                return
            await channel.send(f"💌 Từ admin tới {target_user.mention}: {cleaned_message}")
            await interaction.followup.send(f"Đã gửi tin nhắn tới {target_user.display_name} trong {channel.mention}! ✨", ephemeral=True)
        else:
            decorated = f"━━━━━━━━━━━━━━━━━━━━━━\nTin nhắn từ admin:\n\n{cleaned_message}\n\n━━━━━━━━━━━━━━━━━━━━━━"
            if len(decorated) > 1500:
                decorated = cleaned_message[:1450] + "\n...(cắt bớt)"
            await target_user.send(decorated)
            await interaction.followup.send(f"Đã gửi DM cho {target_user.display_name}! ✨", ephemeral=True)
        
        await log_message(str(interaction.user.id), "assistant", f"Sent message to {user_id}: {cleaned_message} {{'in channel ' + str(channel.id) if channel else 'via DM'}}")
    except discord.Forbidden:
        await interaction.followup.send(f"Không gửi được tin nhắn cho {target_user.display_name}! 😢 Có thể họ chặn bot hoặc không cùng server.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Lỗi gửi tin nhắn! 😓 Lỗi: {str(e)}", ephemeral=True)
        logger.error(f"Error sending message to {user_id}: {e}")

# --- COMMAND ERROR HANDLER ---
@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.CommandNotFound):
        logger.warning(f"Lệnh không tồn tại: '{ctx.message.content}' từ User: {ctx.author}")
        return
    logger.error(f"Lỗi command: {error}")
    # Nếu muốn bot báo lỗi cho user, bỏ comment dòng dưới
    # await ctx.send(f"Lỗi command: {error}")
