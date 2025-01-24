from telethon import TelegramClient, Button, errors
from telethon.sessions import StringSession
from telethon.tl.types import User
import asyncio
import logging
import re
from datetime import datetime
from typing import Dict, Optional, Tuple, Any

from config import API_ID, API_HASH

logger = logging.getLogger(__name__)

class AccountManager:
    def __init__(self, db):
        """Initialize AccountManager with database connection"""
        self.db = db
        self.connection_steps: Dict[int, Dict[str, Any]] = {}  # user_id: {step, data}
        self.clients: Dict[str, Dict[str, Any]] = {}  # phone: {client, phone_code_hash}

    async def start_connection(self, event) -> None:
        """Start account connection process"""
        try:
            buttons = [[Button.inline("❌ Cancel", "cancel")]]
            
            text = """
📱 *Add New Account*

Please send the phone number you want to connect.
Format: `+1234567890`

Notes:
• Number must include country code
• Don't use spaces or special characters
• Process can be cancelled anytime

*Security Assurance:*
✅ Secure session storage
✅ Encrypted credentials
✅ Admin-only access
"""
            await event.edit(text, buttons=buttons, parse_mode='markdown')
            
            self.connection_steps[event.sender_id] = {
                "step": "phone",
                "data": {},
                "start_time": datetime.now()
            }
        except Exception as e:
            logger.error(f"Error starting connection: {str(e)}")
            await event.edit("❌ An error occurred while starting connection process.")

    async def handle_connection_step(self, event) -> None:
        """Handle each step of connection process"""
        try:
            user_data = self.connection_steps.get(event.sender_id)
            if not user_data:
                return

            if user_data["step"] == "phone":
                await self._handle_phone_step(event, user_data)
            elif user_data["step"] == "code":
                await self._handle_code_step(event, user_data)
            elif user_data["step"] == "2fa":
                await self._handle_2fa_step(event, user_data)
        except Exception as e:
            logger.error(f"Error handling connection step: {str(e)}")
            await event.respond("❌ An error occurred during connection process.")
            await self.cancel_connection(event)

    async def _handle_phone_step(self, event, user_data: Dict) -> None:
        """Handle phone number input step"""
        try:
            phone = event.text.strip()
            if not phone.startswith('+'):
                phone = '+' + phone

            if not self._validate_phone(phone):
                await event.respond("""
❌ *Invalid Phone Number*
Please send a valid phone number including country code.
Example: `+1234567890`
""", parse_mode='markdown')
                return

            if self.db.phone_exists(phone):
                await event.respond("""
⚠️ *Phone Already Registered*
This phone number is already connected to the bot.
Use delete option first if you want to reconnect.
""", parse_mode='markdown')
                return

            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.connect()
            
            self.clients[phone] = {
                'client': client,
                'phone_code_hash': None
            }
            
            user_data["data"]["phone"] = phone
            user_data["step"] = "code"
            
            code_request = await client.send_code_request(phone)
            self.clients[phone]['phone_code_hash'] = code_request.phone_code_hash
            
            await event.respond("""
📤 *Verification Code Sent*

Please enter the code you received:
• Format: `12345` (space-separated if needed)
• You have 3 attempts
• Code expires in 5 minutes

⚠️ Make sure to check your Telegram app!
""", parse_mode='markdown')
            
        except errors.PhoneNumberInvalidError:
            await event.respond("❌ Invalid phone number. Please try again.")
        except errors.FloodWaitError as e:
            await event.respond(f"""
⚠️ *Flood Wait Error*
Please wait {e.seconds} seconds before trying again.
This is a Telegram security measure.
""", parse_mode='markdown')
        except Exception as e:
            logger.error(f"Error in phone step: {str(e)}")
            await event.respond(f"❌ An error occurred: {str(e)}")
            await self._cleanup_client(phone)

    async def _handle_code_step(self, event, user_data: Dict) -> None:
        """Handle verification code step"""
        try:
            phone = user_data["data"]["phone"]
            client_data = self.clients[phone]
            client = client_data['client']
            phone_code_hash = client_data['phone_code_hash']
            
            code = event.text.strip().replace(" ", "")
            user_data["data"]["code"] = code
            
            try:
                user = await client.sign_in(
                    phone=phone,
                    code=code,
                    phone_code_hash=phone_code_hash
                )
                await self._handle_successful_login(event, client, phone, user)
                
            except errors.SessionPasswordNeededError:
                user_data["step"] = "2fa"
                await event.respond("""
🔐 *Two-Factor Authentication Required*

Please enter your 2FA password:
• You have 3 attempts
• Case sensitive
• Press Cancel to abort
""", parse_mode='markdown')
                
            except errors.PhoneCodeInvalidError:
                await self._handle_invalid_code(event, user_data)

        except Exception as e:
            logger.error(f"Error in code step: {str(e)}")
            await event.respond(f"❌ An error occurred: {str(e)}")
            await self._cleanup_client(phone)

    async def _handle_2fa_step(self, event, user_data: Dict) -> None:
        """Handle 2FA password step"""
        try:
            phone = user_data["data"]["phone"]
            client_data = self.clients[phone]
            client = client_data['client']
            password = event.text.strip()
            
            try:
                user = await client.sign_in(password=password)
                await self._handle_successful_login(event, client, phone, user)
                
            except errors.PasswordHashInvalidError:
                await self._handle_invalid_password(event, user_data)
                    
        except Exception as e:
            logger.error(f"Error in 2FA step: {str(e)}")
            await event.respond(f"❌ An error occurred: {str(e)}")
            await self._cleanup_client(phone)

    async def _handle_successful_login(self, event, client: TelegramClient, 
                                     phone: str, user: User) -> None:
        """Handle successful login and save session"""
        try:
            session_string = StringSession.save(client.session)
            success = self.db.add_session(
                phone,
                session_string,
                user.id,
                user.first_name,
                user.last_name or ""
            )
            
            if success:
                duration = datetime.now() - self.connection_steps[event.sender_id]["start_time"]
                
                await event.respond(f"""
✅ *Account Successfully Connected!*

📱 *Account Details:*
• Phone: `{phone}`
• Name: {user.first_name} {user.last_name or ''}
• User ID: `{user.id}`
• Connected in: {duration.seconds} seconds

🔐 *Session String:*
`{session_string}`

⚠️ Keep this session string safe and never share it!

You can now use this account for invite operations.
""", parse_mode='markdown')
            else:
                await event.respond("❌ Failed to save session to database.")
                
        except Exception as e:
            logger.error(f"Error saving session: {str(e)}")
            await event.respond("❌ Error saving session.")
        finally:
            await self._cleanup_session(event.sender_id, phone)

    async def cancel_connection(self, event) -> None:
        """Cancel ongoing connection process"""
        try:
            if event.sender_id in self.connection_steps:
                user_data = self.connection_steps[event.sender_id]
                if "phone" in user_data["data"]:
                    phone = user_data["data"]["phone"]
                    await self._cleanup_client(phone)
                await self._cleanup_session(event.sender_id)
                
                await event.edit("""
❌ *Process Cancelled*
All temporary data has been cleared.
You can start new connection anytime.
""", parse_mode='markdown')
        except Exception as e:
            logger.error(f"Error cancelling connection: {str(e)}")

    async def show_delete_options(self, event) -> None:
        """Show account deletion options"""
        try:
            sessions = self.db.get_all_sessions()
            if not sessions:
                await event.edit("""
ℹ️ *No Connected Accounts*
Use the connect option to add accounts.
""", parse_mode='markdown')
                return

            buttons = [[Button.inline("🗑 Delete All", "delete_all")]]
            
            for session in sessions:
                phone = session[0]
                buttons.append([Button.inline(f"🗑 Delete {phone}", f"delete_{phone}")])
                
            buttons.append([Button.inline("❌ Cancel", "cancel")])
            
            accounts_text = "*Connected Accounts:*\n\n"
            for session in sessions:
                phone, _, _, first_name, last_name, status = session
                name = f"{first_name} {last_name}".strip()
                stats = self.db.get_session_stats(phone)
                
                accounts_text += f"""
📱 *{phone}*
• Name: {name}
• Status: {status}
• Total Invites: {stats['total_invites']}
• Flood Count: {stats['flood_count']}
• Success Rate: {self._calculate_success_rate(stats)}%
"""
            
            await event.edit(accounts_text, buttons=buttons, parse_mode='markdown')
        except Exception as e:
            logger.error(f"Error showing delete options: {str(e)}")
            await event.edit("❌ Error loading account list.")

    async def _cleanup_client(self, phone: str) -> None:
        """Clean up client connection"""
        if phone in self.clients:
            try:
                await self.clients[phone]['client'].disconnect()
            except:
                pass
            del self.clients[phone]

    async def _cleanup_session(self, user_id: int, phone: Optional[str] = None) -> None:
        """Clean up session data"""
        if phone:
            await self._cleanup_client(phone)
        if user_id in self.connection_steps:
            del self.connection_steps[user_id]

    async def _handle_invalid_code(self, event, user_data: Dict) -> None:
        """Handle invalid verification code"""
        if "code_attempts" not in user_data["data"]:
            user_data["data"]["code_attempts"] = 1
        else:
            user_data["data"]["code_attempts"] += 1
            
        if user_data["data"]["code_attempts"] >= 3:
            await event.respond("❌ Too many invalid attempts. Process cancelled.")
            await self.cancel_connection(event)
        else:
            await event.respond(f"""
⚠️ *Invalid Code*
Please try again. ({user_data['data']['code_attempts']}/3 attempts)

Make sure to:
• Enter all digits
• Use latest code received
• Check for spaces or typos
""", parse_mode='markdown')

    async def _handle_invalid_password(self, event, user_data: Dict) -> None:
        """Handle invalid 2FA password"""
        if "password_attempts" not in user_data["data"]:
            user_data["data"]["password_attempts"] = 1
        else:
            user_data["data"]["password_attempts"] += 1
            
        if user_data["data"]["password_attempts"] >= 3:
            await event.respond("❌ Too many invalid attempts. Process cancelled.")
            await self.cancel_connection(event)
        else:
            await event.respond(f"""
⚠️ *Invalid 2FA Password*
Please try again. ({user_data['data']['password_attempts']}/3 attempts)

Note: Password is case sensitive!
""", parse_mode='markdown')

    def _validate_phone(self, phone: str) -> bool:
        """Validate phone number format"""
        pattern = r'^\+[1-9]\d{6,14}$'
        return bool(re.match(pattern, phone))

    def _calculate_success_rate(self, stats: dict) -> float:
        """Calculate success rate percentage"""
        total = stats['total_success'] + stats['total_failed']
        if total == 0:
            return 0.0
        return round((stats['total_success'] / total) * 100, 2)
