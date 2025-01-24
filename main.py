from telethon import TelegramClient, events, Button
from telethon.tl.types import User
import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional

# Import local modules
from config import API_ID, API_HASH, BOT_TOKEN, ADMIN_IDS, START_MESSAGE, HELP_MESSAGE
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
        self.db = Database(DB_NAME)  # Initialize database first
        self.bot = None  # Initialize in start method
        self.account_manager = None
        self.invite_manager = None
        self.active_processes: Dict[int, str] = {}

    def is_admin(self, user_id: int) -> bool:
        """Check if user is an admin"""
        return user_id in ADMIN_IDS

    async def show_start_menu(self, event) -> None:
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
            parse_mode='markdown'
        )

    async def setup_handlers(self) -> None:
        """Setup all event handlers"""
        
        @self.bot.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            if not self.is_admin(event.sender_id):
                await event.respond("🔒 This bot is private.")
                return
            await self.show_start_menu(event)

        @self.bot.on(events.CallbackQuery())
        async def callback_handler(event):
            if not self.is_admin(event.sender_id):
                await event.answer("⚠️ You're not authorized.")
                return

            data = event.data.decode()
            
            if data == "help":
                await event.edit(HELP_MESSAGE, parse_mode='markdown')
            
            elif data in ["connect", "delete", "invite"]:
                self.active_processes[event.sender_id] = data
                if data == "connect":
                    await self.account_manager.start_connection(event)
                elif data == "delete":
                    await self.account_manager.show_delete_options(event)
                elif data == "invite":
                    await self.invite_manager.start_invite_process(event)
            
            elif data == "cancel":
                process = self.active_processes.get(event.sender_id)
                if process:
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
                
            process = self.active_processes.get(event.sender_id)
            if process:
                if process == "connect":
                    await self.account_manager.handle_connection_step(event)
                elif process == "invite":
                    await self.invite_manager.handle_invite_step(event)

    async def initialize(self) -> None:
        """Initialize bot components"""
        try:
            # Initialize bot client
            self.bot = TelegramClient('bot', API_ID, API_HASH)
            await self.bot.start(bot_token=BOT_TOKEN)
            
            # Initialize managers after bot is started
            self.account_manager = AccountManager(self.db)
            self.invite_manager = InviteManager(self.db)
            
            # Setup event handlers
            await self.setup_handlers()
            
            # Print startup info
            me = await self.bot.get_me()
            logger.info(f"""
🤖 Bot Started Successfully!
• Username: @{me.username}
• Name: {me.first_name}
• Bot ID: {me.id}
• Database: {DB_NAME}
• Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
• Number of Admins: {len(ADMIN_IDS)}
            """)
        except Exception as e:
            logger.error(f"❌ Error initializing bot: {str(e)}")
            raise

    async def start(self) -> None:
        """Start the bot"""
        try:
            await self.initialize()
            await self.bot.run_until_disconnected()
        except Exception as e:
            logger.error(f"❌ Error running bot: {str(e)}")
            raise
        finally:
            if self.bot:
                await self.bot.disconnect()
            if self.db:
                self.db.close()

def main():
    """Main entry point"""
    try:
        bot = MultiAccountBot()
        asyncio.run(bot.start())
    except KeyboardInterrupt:
        logger.info("\n⚠️ Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {str(e)}")

if __name__ == '__main__':
    main()
