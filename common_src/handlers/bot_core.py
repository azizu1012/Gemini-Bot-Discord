import discord
from discord.ext import commands
from discord import app_commands
from collections import defaultdict, deque
from datetime import datetime
from typing import Dict, Deque, Any, Optional

from core.config import logger, ADMIN_ID
from database.repository import DatabaseRepository
from services.memory_service import MemoryService
from managers.cleanup_manager import CleanupManager
from managers.premium_manager import PremiumManager
from tools.tools import ToolsManager


class BotCore:
    """Core bot initialization and event handling."""
    
    def __init__(self, config):
        self.config = config
        self.logger = logger
        self.db_repo = DatabaseRepository()
        self.memory_service = MemoryService()
        self.cleanup_mgr = CleanupManager()
        self.premium_mgr = PremiumManager()
        self.tools_mgr = ToolsManager()
        
        # Global state
        self.mention_history: Dict[str, list] = {}
        self.confirmation_pending: Dict[str, Dict[str, Any]] = {}
        self.admin_confirmation_pending: Dict[str, Dict[str, Any]] = {}
        self.user_queue: defaultdict[str, Deque[datetime]] = defaultdict(deque)
        self.processing_users = set()
        
        # Discord bot setup
        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        self.bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)
        
        # Register events
        self._register_events()
        self._register_commands()
    
    def _register_events(self):
        """Register bot events."""
        @self.bot.event
        async def on_ready():
            try:
                synced = await self.bot.tree.sync()
                self.logger.info(f"Synced {len(synced)} slash commands!")
            except Exception as e:
                self.logger.error(f"Error syncing slash commands: {e}")
            
            await self.db_repo.init_db()
            self.memory_service.init_json_memory()
            
            self.logger.info("Running DB cleanup...")
            await self.db_repo.cleanup_db()
            self.logger.info("Running local file cleanup...")
            await self.cleanup_mgr.cleanup_local_files()
            
            await self.db_repo.backup_db()
            self.logger.info(f'{self.bot.user} is online!')
        
        @self.bot.event
        async def on_message(message: discord.Message):
            user_id = str(message.author.id)
            if user_id in self.processing_users:
                self.logger.warning(f"User {user_id} already processing, skipping duplicate.")
                return
            
            try:
                self.processing_users.add(user_id)
                # Message handling delegated to MessageHandler
            finally:
                if user_id in self.processing_users:
                    self.processing_users.remove(user_id)
        
        @self.bot.event
        async def on_command_error(ctx: commands.Context, error: commands.CommandError):
            if isinstance(error, commands.CommandNotFound):
                self.logger.warning(f"Command not found: '{ctx.message.content}' from User: {ctx.author}")
                return
            self.logger.error(f"Command error: {error}")
    
    def _register_commands(self):
        """Register slash commands."""
        
        def is_admin():
            async def predicate(interaction: discord.Interaction) -> bool:
                return str(interaction.user.id) == ADMIN_ID
            return app_commands.check(predicate)
        
        @self.bot.tree.command(name="reset-chat", description="Clear your chat history")
        async def reset_chat_slash(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            user_id = str(interaction.user.id)
            self.confirmation_pending[user_id] = {'timestamp': datetime.now(), 'awaiting': True}
            await interaction.followup.send("Clear chat history? Reply **yes** or **y** in 60 seconds! 😳", ephemeral=True)
        
        @self.bot.tree.command(name="premium", description="Manage premium user status (ADMIN ONLY)")
        @app_commands.describe(
            user="User to check/add/remove",
            action="Action: 'check', 'add', or 'remove'"
        )
        @app_commands.choices(action=[
            app_commands.Choice(name="Check", value="check"),
            app_commands.Choice(name="Add", value="add"),
            app_commands.Choice(name="Remove", value="remove"),
        ])
        @is_admin()
        async def premium_slash(interaction: discord.Interaction, user: discord.User, action: app_commands.Choice[str]):
            try:
                await interaction.response.defer(ephemeral=True)
            except discord.errors.NotFound:
                self.logger.error(f"Interaction not found for premium command.")
                try:
                    await interaction.user.send("Error processing premium command.")
                except discord.Forbidden:
                    pass
                return
            
            requester_id = str(interaction.user.id)
            target_user_id = str(user.id)
            
            if action.value == "check" and requester_id == target_user_id:
                await interaction.followup.send(
                    f"You are the admin! 🥰",
                    ephemeral=True
                )
                return
            
            if action.value == "check":
                if self.premium_mgr.is_premium_user(target_user_id):
                    await interaction.followup.send(f"{user.display_name} is Premium ✨", ephemeral=True)
                else:
                    await interaction.followup.send(f"{user.display_name} is not Premium 😔", ephemeral=True)
            elif action.value == "add":
                if self.premium_mgr.add_premium_user(target_user_id):
                    await interaction.followup.send(f"Added {user.display_name} to Premium 🎉", ephemeral=True)
                else:
                    await interaction.followup.send(f"{user.display_name} already Premium", ephemeral=True)
            elif action.value == "remove":
                if self.premium_mgr.remove_premium_user(target_user_id):
                    await interaction.followup.send(f"Removed {user.display_name} from Premium 💔", ephemeral=True)
                else:
                    await interaction.followup.send(f"{user.display_name} not in Premium list", ephemeral=True)
        
        @self.bot.tree.command(name="reset-all", description="Clear all DB (ADMIN ONLY)")
        @is_admin()
        async def reset_all_slash(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            admin_id = str(interaction.user.id)
            self.admin_confirmation_pending[admin_id] = {'timestamp': datetime.now(), 'awaiting': True}
            await interaction.followup.send("⚠️ **ADMIN CONFIRM**: Reply **YES RESET** in 60 seconds to clear all DB!", ephemeral=True)
        
        @self.bot.tree.command(name="message_to", description="Send message to user (ADMIN ONLY)")
        @app_commands.describe(
            user="Target user",
            message="Message content",
            channel="Optional channel"
        )
        @is_admin()
        async def message_to_slash(interaction: discord.Interaction, user: discord.User, message: str, channel: Optional[discord.TextChannel] = None):
            await interaction.response.defer(ephemeral=True)
            user_id = str(user.id)
            cleaned_message = ' '.join(message.strip().split())
            
            try:
                target_user = await self.bot.fetch_user(int(user_id))
            except (ValueError, discord.NotFound):
                await interaction.followup.send("Invalid user ID or not found! 😕", ephemeral=True)
                return
            
            try:
                if channel:
                    if not isinstance(channel, discord.TextChannel):
                        await interaction.followup.send("Channel must be text channel! 😅", ephemeral=True)
                        return
                    if not interaction.guild:
                        await interaction.followup.send("Cannot use channel in DM.", ephemeral=True)
                        return
                    if channel.guild != interaction.guild:
                        await interaction.followup.send("Channel must be in same server! 😢", ephemeral=True)
                        return
                    if not channel.permissions_for(interaction.guild.me).send_messages:
                        await interaction.followup.send("Bot has no send permission! 😓", ephemeral=True)
                        return
                    await channel.send(f"💌 From admin to {target_user.mention}: {cleaned_message}")
                    await interaction.followup.send(f"Sent to {target_user.display_name} in {channel.mention}! ✨", ephemeral=True)
                else:
                    decorated = f"━━━━━━━━━━━━━━━━━━━━━━\nMessage from admin:\n\n{cleaned_message}\n\n━━━━━━━━━━━━━━━━━━━━━━"
                    if len(decorated) > 1500:
                        decorated = cleaned_message[:1450] + "\n...(truncated)"
                    await target_user.send(decorated)
                    await interaction.followup.send(f"DM sent to {target_user.display_name}! ✨", ephemeral=True)
            except discord.Forbidden:
                await interaction.followup.send(f"Cannot send message to {target_user.display_name}! 😢", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"Error sending message! 😓 Error: {str(e)}", ephemeral=True)
                self.logger.error(f"Error sending message to {user_id}: {e}")
    
    async def start(self, token: str):
        """Start the bot."""
        async with self.bot:
            await self.bot.start(token)
