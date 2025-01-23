from telethon import TelegramClient, events, Button
from telethon.tl.types import User
import asyncio
import logging
from datetime import datetime
from typing import Dict

from config import *
from database import Database
from account_manager import AccountManager
from invite_manager import InviteManager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MultiAccountBot:
    def __init__(self):
        """Initialize bot with required components"""
        self.bot = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)
        self.db = Database(DB_NAME)
        self.account_manager = AccountManager(self.db)
        self.invite_manager = InviteManager(self.db)
        self.active_processes: Dict[int, str] = {}
        
    def is_admin(self, user_id: int) -> bool:
        """Check if user is an admin"""
        return user_id in ADMIN_IDS  # ADMIN_IDS should be defined in config.py as a list/set
        
    async def show_start_menu(self, event):
        """Display main menu with inline buttons"""
        buttons = [
            [Button.inline("🔗 Connect Account", "connect"),
             Button.inline("🗑 Delete Account", "delete")],
            [Button.inline("👥 Invite Members", "invite"),
             Button.inline("ℹ️ Help", "help")],
        ]
        
        await event.respond(
            START_MESSAGE,
            buttons=buttons,
            parse_mode='Markdown'
        )

    async def setup_handlers(self):
        """Setup all event handlers"""
        
        @self.bot.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            if not self.is_admin(event.sender_id):
                return await event.respond("🔒 This bot is private.")
            await self.show_start_menu(event)

        @self.bot.on(events.CallbackQuery())
        async def callback_handler(event):
            if not self.is_admin(event.sender_id):
                return await event.answer("⚠️ You're not authorized.")

            data = event.data.decode()
            
            if data == "help":
                await event.edit(HELP_MESSAGE, parse_mode='markdown')
            
            elif data in ["connect", "delete", "invite"]:
                self.active_processes[event.sender_id] = data  # Allow starting new process without checks
                if data == "connect":
                    await self.account_manager.start_connection(event)
                elif data == "delete":
                    await self.account_manager.show_delete_options(event)
                elif data == "invite":
                    await self.invite_manager.start_invite_process(event)
            
            elif data == "cancel":
                if process := self.active_processes.get(event.sender_id):
                    if process == "connect":
                        await self.account_manager.cancel_connection(event)
                    elif process == "invite":
                        await self.invite_manager.cancel_invite(event)
                    
                    del self.active_processes[event.sender_id]
                    await event.edit("❌ Process cancelled.")

        @self.bot.on(events.NewMessage())
        async def message_handler(event):
            if not self.is_admin(event.sender_id):
                return
                
            if process := self.active_processes.get(event.sender_id):
                if process == "connect":
                    await self.account_manager.handle_connection_step(event)
                elif process == "invite":
                    await self.invite_manager.handle_invite_step(event)

    async def start(self):
        """Start the bot"""
        try:
            await self.setup_handlers()
            
            # Print startup info
            me = await self.bot.get_me()
            print(f"""
🤖 Bot Started Successfully!
• Username: @{me.username}
• Name: {me.first_name}
• Bot ID: {me.id}
• Database: {DB_NAME}
• Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
• Number of Admins: {len(ADMIN_IDS)}
            """)
            
            await self.bot.run_until_disconnected()
        except Exception as e:
            logger.error(f"❌ Error starting bot: {str(e)}")
            raise

if __name__ == '__main__':
    try:
        bot = MultiAccountBot()
        # Use existing event loop to avoid conflicts
        loop = asyncio.get_event_loop()
        loop.run_until_complete(bot.start())
    except KeyboardInterrupt:
        print("\n⚠️ Bot stopped by user")
    except Exception as e:
        print(f"❌ Fatal error: {str(e)}")