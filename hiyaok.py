"""
Telegram Manager Bot
Features:
- Admin-only access
- Multiple admin support
- Session management with 2FA
- Invite management with flood protection
"""

import os
from telethon import TelegramClient, events, Button, functions
from telethon.tl.functions.channels import JoinChannelRequest, InviteToChannelRequest
from telethon.tl.types import InputPhoneContact
from telethon.errors import (
    FloodWaitError, 
    UserAlreadyParticipantError, 
    PhoneNumberBannedError, 
    SessionPasswordNeededError,
    UserPrivacyRestrictedError,
    UserNotMutualContactError
)
from telethon.sessions import StringSession
import asyncio
import json
import vobject
import asyncio
import nest_asyncio
nest_asyncio.apply()
import time
from datetime import datetime
import logging

# Configuration
API_ID = "23207350"
API_HASH = "03464b6c80a5051eead6835928e48189"
BOT_TOKEN = "7679634554:AAEdPm3H0P0KsfZSTe9x7DHzKa49JecWj8M"

# Safe delays (in seconds)
INVITE_DELAY = 5  # Delay between invites
ACCOUNT_SWITCH_DELAY = 5  # Delay when switching accounts
ERROR_DELAY = 5  # Delay after error
MAX_RETRIES = 3  # Maximum retry attempts

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    filename='telegram_bot.log'
)
logger = logging.getLogger(__name__)

# Initialize bot
bot = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# Store user sessions, states and admins
user_sessions = {}
user_states = {}
SESSIONS_FILE = "sessions.json"
ADMINS_FILE = "admins.json"

class InviteProgress:
    def __init__(self, total_numbers, accounts):
        self.total_numbers = total_numbers
        self.accounts = accounts
        self.current_number = 0
        self.successful = 0
        self.failed = 0
        self.processed_numbers = set()  # Track already processed numbers
        self.account_stats = {phone: {'success': 0, 'failed': 0, 'errors': []} for phone in accounts}
        self.current_account = None
        self.status_message = None
        self.last_update_time = 0
        
    async def update_status(self, message=None, force=False):
        """Update status message with current progress"""
        current_time = time.time()
        if not force and current_time - self.last_update_time < 3:
            return
            
        self.last_update_time = current_time
        
        status = (
            f"📊 **Progress Report**\n\n"
            f"📱 Current Account: {self.current_account}\n"
            f"📈 Progress: {self.current_number}/{self.total_numbers}\n"
            f"✅ Successful: {self.successful}\n"
            f"❌ Failed: {self.failed}\n\n"
            f"📋 Account Stats:\n"
        )
        
        for phone, stats in self.account_stats.items():
            status += (
                f"\n🔹 {phone}:\n"
                f"  ✓ Success: {stats['success']}\n"
                f"  ✗ Failed: {stats['failed']}\n"
            )
            if stats['errors']:
                status += f"  ⚠️ Last Error: {stats['errors'][-1]}\n"
        
        if message:
            status += f"\n📌 {message}"
            
        try:
            if self.status_message is None:
                self.status_message = await bot.send_message(
                    self.status_message.chat_id,
                    status
                )
            else:
                await self.status_message.edit(status)
        except Exception as e:
            logger.error(f"Error updating status: {str(e)}")

# File handling functions
def ensure_directories():
    """Ensure all required directories exist"""
    os.makedirs('sessions', exist_ok=True)
    os.makedirs('logs', exist_ok=True)

def load_admins():
    """Load admin list from file"""
    if os.path.exists(ADMINS_FILE):
        with open(ADMINS_FILE, 'r') as f:
            return json.load(f)
    return {"admins": []}

def save_admins(admins):
    """Save admin list to file"""
    with open(ADMINS_FILE, 'w') as f:
        json.dump(admins, f)

def load_sessions():
    """Load user sessions from file"""
    if os.path.exists(SESSIONS_FILE):
        with open(SESSIONS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_sessions():
    """Save user sessions to file"""
    with open(SESSIONS_FILE, 'w') as f:
        json.dump(user_sessions, f)

# Decorators
def admin_only(func):
    """Decorator to restrict access to admins only"""
    async def wrapper(event):
        user_id = event.sender_id
        admins = load_admins()
        if user_id not in admins["admins"]:
            await event.respond("⛔ Sorry, this feature is only available for admins!")
            return
        return await func(event)
    return wrapper

def require_session(func):
    """Decorator to require at least one active session"""
    async def wrapper(event):
        user_id = event.sender_id
        if not has_sessions(user_id):
            await event.respond(
                "⚠️ You need to connect at least one account first!\n"
                "Use the 'Connect Account' button to add an account."
            )
            return
        return await func(event)
    return wrapper

# Helper functions
def has_sessions(user_id):
    """Check if user has any active sessions"""
    return user_id in user_sessions and len(user_sessions[user_id]) > 0

async def get_pagination_buttons(accounts, page=0, items_per_page=5):
    """Generate pagination buttons for account list"""
    total_pages = (len(accounts) - 1) // items_per_page + 1
    buttons = []
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    
    for i, (phone, session) in enumerate(list(accounts.items())[start_idx:end_idx]):
        buttons.append([Button.inline(f"❌ Delete {phone}", f"delete_{phone}")])
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(Button.inline("⬅️ Previous", f"page_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(Button.inline("➡️ Next", f"page_{page+1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    return buttons

# Command handlers
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    """Handle /start command"""
    user_id = event.sender_id
    admins = load_admins()
    
    if user_id in admins["admins"]:
        buttons = [
            [Button.inline("ℹ️ Help", "help")],
            [Button.inline("📱 Connect Account", "connect")],
            [Button.inline("📋 List Accounts", "listaccount")],
            [Button.inline("📲 Invite Users", "invite")]
        ]
        
        if not has_sessions(user_id):
            await event.respond(
                "👋 Welcome Admin!\n\n"
                "⚠️ Please connect at least one account before using other features.\n"
                "Use the 'Connect Account' button to add your first account.",
                buttons=buttons
            )
        else:
            await event.respond(
                "👋 Welcome back Admin!\n\n"
                "Choose an option from the menu below:",
                buttons=buttons
            )
    else:
        await event.respond("⛔ Sorry, this bot is only available for admins!")

@bot.on(events.NewMessage(pattern='/addadmin'))
@admin_only
async def add_admin_handler(event):
    """Handle /addadmin command"""
    try:
        user_id = int(event.text.split()[1])
        admins = load_admins()
        if user_id not in admins["admins"]:
            admins["admins"].append(user_id)
            save_admins(admins)
            await event.respond(f"✅ User {user_id} added as admin!")
        else:
            await event.respond("⚠️ User is already an admin!")
    except (IndexError, ValueError):
        await event.respond("❌ Please provide a valid user ID\nFormat: /addadmin user_id")

@bot.on(events.NewMessage(pattern='/removeadmin'))
@admin_only
async def remove_admin_handler(event):
    """Handle /removeadmin command"""
    try:
        user_id = int(event.text.split()[1])
        admins = load_admins()
        if user_id in admins["admins"]:
            admins["admins"].remove(user_id)
            save_admins(admins)
            await event.respond(f"✅ User {user_id} removed from admins!")
        else:
            await event.respond("⚠️ User is not an admin!")
    except (IndexError, ValueError):
        await event.respond("❌ Please provide a valid user ID\nFormat: /removeadmin user_id")

# Button handlers
@bot.on(events.CallbackQuery(pattern='help'))
@admin_only
async def help_callback(event):
    """Handle help button press"""
    help_text = (
        "🤖 **Bot Features and Instructions:**\n\n"
        "1️⃣ **Connect Account** (📱)\n"
        "- Add Telegram accounts to the bot\n"
        "- Follow the prompts for phone number and OTP\n"
        "- Supports 2FA authentication\n"
        "- Maximum 3 attempts for verification\n\n"
        "2️⃣ **List Accounts** (📋)\n"
        "- View all connected accounts\n"
        "- Delete accounts using inline buttons\n"
        "- Navigate through pages if many accounts\n\n"
        "3️⃣ **Invite Users** (📲)\n"
        "- Upload .txt or .vcf file with phone numbers\n"
        "- Choose number of contacts to invite\n"
        "- Select target group\n"
        "- Pick accounts to use for inviting\n\n"
        "📝 **Admin Commands:**\n"
        "/addadmin [user_id] - Add new admin\n"
        "/removeadmin [user_id] - Remove admin\n\n"
        "⚠️ **Note:** All operations are rate-limited to prevent flooding"
    )
    await event.edit(help_text)

@bot.on(events.CallbackQuery(pattern='connect'))
@admin_only
async def connect_callback(event):
    """Handle connect account button press"""
    user_id = event.sender_id
    user_states[user_id] = {'state': 'awaiting_phone', 'attempts': 0}
    
    await event.edit(
        "📱 Please send your phone number in international format:\n"
        "Example: +1234567890"
    )

@bot.on(events.NewMessage(func=lambda e: user_states.get(e.sender_id, {}).get('state') == 'awaiting_phone'))
@admin_only
async def phone_handler(event):
    """Handle phone number input"""
    user_id = event.sender_id
    phone = event.text.strip()
    
    if not phone.startswith('+'):
        phone = '+' + phone
    
    try:
        client = TelegramClient(f'sessions/{phone}', API_ID, API_HASH)
        await client.connect()
        
        if not await client.is_user_authorized():
            await client.send_code_request(phone)
            user_states[user_id] = {
                'state': 'awaiting_code',
                'client': client,
                'phone': phone,
                'attempts': 0,
                'password_attempts': 0
            }
            await event.respond("📤 Code sent! Please enter the verification code:")
        else:
            string_session = client.session.save()
            if user_id not in user_sessions:
                user_sessions[user_id] = {}
            user_sessions[user_id][phone] = string_session
            save_sessions()
            await event.respond("✅ Account already authorized and saved!")
            
    except Exception as e:
        logger.error(f"Error in phone handler: {str(e)}")
        await event.respond(f"❌ Error: {str(e)}")
        user_states.pop(user_id, None)

@bot.on(events.NewMessage(func=lambda e: user_states.get(e.sender_id, {}).get('state') in ['awaiting_code', 'awaiting_2fa']))
@admin_only
async def code_handler(event):
    """Handle verification code and 2FA input"""
    user_id = event.sender_id
    state = user_states[user_id]
    client = state['client']
    phone = state['phone']
    
    try:
        if state['state'] == 'awaiting_code':
            try:
                await client.sign_in(phone, event.text.strip())
                string_session = client.session.save()
                if user_id not in user_sessions:
                    user_sessions[user_id] = {}
                user_sessions[user_id][phone] = string_session
                save_sessions()
                await event.respond(
                    "✅ Account successfully connected!\n\n"
                    f"📱 Phone: {phone}\n"
                    "🔑 Session saved"
                )
                user_states.pop(user_id, None)
                
            except SessionPasswordNeededError:
                state['state'] = 'awaiting_2fa'
                await event.respond(
                    "🔐 Two-factor authentication required!\n"
                    "Please enter your 2FA password:"
                )
                
            except Exception as e:
                state['attempts'] += 1
                if state['attempts'] >= 3:
                    await event.respond("❌ Maximum attempts reached. Please try again later.")
                    user_states.pop(user_id, None)
                else:
                    await event.respond(
                        f"❌ Invalid code. Please try again.\n"
                        f"Attempts remaining: {3 - state['attempts']}"
                    )
                    
        elif state['state'] == 'awaiting_2fa':
            try:
                await client.sign_in(password=event.text.strip())
                string_session = client.session.save()
                if user_id not in user_sessions:
                    user_sessions[user_id] = {}
                user_sessions[user_id][phone] = string_session
                save_sessions()
                await event.respond(
                    "✅ Account successfully connected with 2FA!\n\n"
                    f"📱 Phone: {phone}\n"
                    "🔑 Session saved"
                )
                user_states.pop(user_id, None)
                
            except Exception as e:
                state['password_attempts'] += 1
                if state['password_attempts'] >= 3:
                    await event.respond("❌ Maximum password attempts reached. Please try again later.")
                    user_states.pop(user_id, None)
                else:
                    await event.respond(
                        f"❌ Invalid 2FA password. Please try again.\n"
                        f"Attempts remaining: {3 - state['password_attempts']}"
                    )
    
    except Exception as e:
        logger.error(f"Error in code handler: {str(e)}")
        await event.respond(f"❌ Error: {str(e)}")
        user_states.pop(user_id, None)

@bot.on(events.CallbackQuery(pattern='listaccount'))
@admin_only
async def list_callback(event):
    """Handle list accounts button press"""
    user_id = event.sender_id
    if not has_sessions(user_id):
        await event.edit("📱 No accounts connected yet!")
        return
    
    buttons = await get_pagination_buttons(user_sessions[user_id])
    await event.edit("📋 Connected Accounts:", buttons=buttons)

@bot.on(events.CallbackQuery(pattern=r'delete_.*'))
@admin_only
async def delete_callback(event):
    """Handle delete account button press"""
    phone = event.data.decode('utf-8').split('_')[1]
    buttons = [
        [
            Button.inline("✅ Yes", f"confirmdelete_{phone}"),
            Button.inline("❌ No", "listaccount")
        ]
    ]
    await event.edit(f"❓ Are you sure you want to delete account {phone}?", buttons=buttons)

@bot.on(events.CallbackQuery(pattern=r'confirmdelete_.*'))
@admin_only
async def confirm_delete_callback(event):
    """Handle delete confirmation button press"""
    user_id = event.sender_id
    phone = event.data.decode('utf-8').split('_')[1]
    if phone in user_sessions[user_id]:
        del user_sessions[user_id][phone]
        save_sessions()
        await event.edit(f"✅ Account {phone} deleted successfully!")
    else:
        await event.edit("❌ Account not found!")

@bot.on(events.CallbackQuery(pattern='invite'))
@admin_only
@require_session
async def invite_callback(event):
    """Handle invite button press"""
    user_id = event.sender_id
    user_states[user_id] = {'state': 'awaiting_file'}
    
    await event.edit(
        "📁 Please send a .txt or .vcf file containing phone numbers.\n\n"
        "📝 Format .txt yang benar:\n"
        "2727272\n"
        "2882286\n\n"
        "⚠️ Satu nomor per baris, tanpa karakter tambahan"
    )

@bot.on(events.NewMessage(func=lambda e: user_states.get(e.sender_id, {}).get('state') == 'awaiting_file'))
@admin_only
async def file_handler(event):
    """Handle file upload for invites"""
    user_id = event.sender_id
    
    if not event.file:
        await event.respond("❌ Please send a valid .txt or .vcf file!")
        return
    
    file_path = await event.download_media()
    numbers = []
    
    try:
        if file_path.endswith('.txt'):
            with open(file_path, 'r') as f:
                # Read lines and process them
                raw_numbers = [line.strip() for line in f if line.strip()]
                
                # Validate format
                for num in raw_numbers:
                    # Check if number only contains digits and optionally starts with +
                    if not (num.isdigit() or (num.startswith('+') and num[1:].isdigit())):
                        await event.respond(
                            "❌ Invalid file format!\n\n"
                            "📝 Format yang benar:\n"
                            "2727272\n"
                            "2882286\n\n"
                            "⚠️ Satu nomor per baris, tanpa karakter tambahan"
                        )
                        return
                    
                    # Add + if not present
                    if not num.startswith('+'):
                        num = '+' + num
                    numbers.append(num)
        
        elif file_path.endswith('.vcf'):
            with open(file_path, 'r') as f:
                for vcard in vobject.readComponents(f.read()):
                    if hasattr(vcard, 'tel'):
                        for tel in vcard.tel_list:
                            num = tel.value
                            # Clean the number
                            num = ''.join(filter(lambda x: x.isdigit() or x == '+', num))
                            if not num.startswith('+'):
                                num = '+' + num
                            numbers.append(num)
        
        os.remove(file_path)
        
        if not numbers:
            await event.respond("❌ No valid phone numbers found in the file!")
            return
        
        user_states[user_id] = {
            'state': 'awaiting_count',
            'numbers': numbers
        }
        
        buttons = [Button.inline("✅ Continue", "set_invite_count")]
        await event.respond(
            f"📱 Found {len(numbers)} phone numbers.\n"
            "Click continue to proceed:",
            buttons=buttons
        )
        
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}")
        await event.respond(f"❌ Error processing file: {str(e)}")
        user_states.pop(user_id, None)

@bot.on(events.CallbackQuery(pattern='set_invite_count'))
@admin_only
async def set_count_callback(event):
    """Handle setting invite count"""
    user_id = event.sender_id
    state = user_states[user_id]
    
    await event.edit(
        f"📊 Total numbers available: {len(state['numbers'])}\n"
        "Please enter how many numbers you want to invite (maximum = total numbers):"
    )
    state['state'] = 'awaiting_invite_count'

@bot.on(events.NewMessage(func=lambda e: user_states.get(e.sender_id, {}).get('state') == 'awaiting_invite_count'))
@admin_only
async def invite_count_handler(event):
    """Handle invite count input"""
    user_id = event.sender_id
    state = user_states[user_id]
    
    try:
        count = int(event.text.strip())
        if count <= 0 or count > len(state['numbers']):
            raise ValueError()
        
        state['invite_count'] = count
        state['state'] = 'awaiting_group_link'
        
        await event.respond(
            "🔗 Please send the group link or username where you want to invite the users:"
        )
        
    except ValueError:
        await event.respond("❌ Please enter a valid number within the available range!")

@bot.on(events.NewMessage(func=lambda e: user_states.get(e.sender_id, {}).get('state') == 'awaiting_group_link'))
@admin_only
async def group_link_handler(event):
    """Handle group link input"""
    user_id = event.sender_id
    state = user_states[user_id]
    group_link = event.text.strip()
    
    if not group_link.startswith(('https://t.me/', '@')):
        await event.respond("❌ Please send a valid group link or username!")
        return
    
    state['group_link'] = group_link
    state['state'] = 'selecting_accounts'
    
    # Create account selection buttons
    accounts = list(user_sessions[user_id].keys())
    buttons = [[Button.inline("✅ Use All Accounts", "use_all_accounts")]]
    
    for phone in accounts:
        buttons.append([Button.inline(f"📱 {phone}", f"select_{phone}")])
    
    buttons.append([Button.inline("✅ Done", "custom_done"), Button.inline("❌ Cancel", "custom_cancel")])
    
    state['selected_accounts'] = set()
    
    await event.respond(
        "👥 Choose which accounts to use for inviting:\n"
        "Select individual accounts or use all accounts:",
        buttons=buttons
    )

@bot.on(events.CallbackQuery(pattern=r'select_.*'))
@admin_only
async def select_account_callback(event):
    """Handle account selection for invites"""
    user_id = event.sender_id
    state = user_states[user_id]
    phone = event.data.decode('utf-8').split('_')[1]
    
    if phone in state['selected_accounts']:
        state['selected_accounts'].remove(phone)
    else:
        state['selected_accounts'].add(phone)
    
    # Update buttons to show selection
    accounts = list(user_sessions[user_id].keys())
    buttons = [[Button.inline("✅ Use All Accounts", "use_all_accounts")]]
    
    for acc in accounts:
        prefix = "✅" if acc in state['selected_accounts'] else "📱"
        buttons.append([Button.inline(f"{prefix} {acc}", f"select_{acc}")])
    
    buttons.append([Button.inline("✅ Done", "custom_done"), Button.inline("❌ Cancel", "custom_cancel")])
    
    await event.edit(
        "👥 Choose which accounts to use for inviting:\n"
        f"Selected: {len(state['selected_accounts'])} accounts",
        buttons=buttons
    )

@bot.on(events.CallbackQuery(pattern='custom_done'))
@admin_only
async def custom_done_callback(event):
    """Handle completion of custom account selection"""
    user_id = event.sender_id
    state = user_states[user_id]
    
    if not state['selected_accounts']:
        await event.edit("❌ Please select at least one account!")
        return
    
    selected_phones = list(state['selected_accounts'])
    await event.edit("🔄 Starting invite process...")
    await process_invites(event, user_id, selected_phones, state['numbers'][:state['invite_count']], state['group_link'])

@bot.on(events.CallbackQuery(pattern='custom_cancel'))
@admin_only
async def custom_cancel_callback(event):
    """Handle cancellation of account selection"""
    user_id = event.sender_id
    user_states.pop(user_id, None)
    await event.edit("❌ Invite process cancelled")

@bot.on(events.CallbackQuery(pattern='use_all_accounts'))
@admin_only
async def use_all_accounts_callback(event):
    """Handle using all accounts for invites"""
    user_id = event.sender_id
    state = user_states[user_id]
    selected_phones = list(user_sessions[user_id].keys())
    
    await event.edit("🔄 Starting invite process...")
    await process_invites(event, user_id, selected_phones, state['numbers'][:state['invite_count']], state['group_link'])

async def process_single_invite(client, number, group_link, progress):
    """Process single invite to group via phone number"""
    try:
        # Create contact object
        contact = InputPhoneContact(
            client_id=0,
            phone=number,
            first_name=f"User_{number}",
            last_name=""
        )

        # Add contact temporarily
        contacts = await client(functions.contacts.ImportContactsRequest([contact]))

        if not contacts.users:
            raise Exception("No Telegram account found for this number")

        # Try to add to group
        await client(InviteToChannelRequest(
            channel=group_link,
            users=[contacts.users[0]]
        ))

        # Remove the temporarily added contact
        await client(functions.contacts.DeleteContactsRequest(
            id=[user.id for user in contacts.users]
        ))

        return True

    except UserPrivacyRestrictedError:
        raise Exception("User privacy settings prevent invitation")
    except UserNotMutualContactError:
        raise Exception("User must be mutual contact first")
    except FloodWaitError as e:
        raise FloodWaitError(e.seconds)
    except Exception as e:
        raise Exception(f"Failed to invite: {str(e)}")

async def process_invites(event, user_id, selected_phones, numbers, group_link):
    """Main function to process invites with flood protection"""
    progress = InviteProgress(len(numbers), selected_phones)
    progress.status_message = await event.respond("🔄 Initializing invite process...")
    
    current_number_index = 0
    successful_invites = set()  # Track successful invites
    
    for phone in selected_phones:
        if current_number_index >= len(numbers):
            break
            
        progress.current_account = phone
        await progress.update_status("Connecting to account...", force=True)
        
        try:
            # Load session string
            session_string = user_sessions[user_id][phone]
            
            # Create client from session string
            client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
            await client.connect()
            
            # Check authorization
            if not await client.is_user_authorized():
                progress.account_stats[phone]['errors'].append("Session expired, please reconnect account")
                continue
            
            # Join group first
            try:
                await progress.update_status("Joining group...")
                await client(JoinChannelRequest(group_link))
                await asyncio.sleep(5)
            except UserAlreadyParticipantError:
                pass
            except Exception as e:
                progress.account_stats[phone]['errors'].append(f"Couldn't join group: {str(e)}")
                await progress.update_status()
                continue
            
            # Process invites with this account
            invite_count = 0
            while current_number_index < len(numbers) and invite_count < 35:  # Limit per account
                number = numbers[current_number_index]
                
                # Skip if already invited
                if number in successful_invites:
                    current_number_index += 1
                    continue
                
                if not number.startswith('+'):
                    number = '+' + number
                
                try:
                    progress.current_number = current_number_index + 1
                    await progress.update_status(f"📲 Inviting {number}...")
                    
                    success = await process_single_invite(client, number, group_link, progress)
                    
                    if success:
                        successful_invites.add(number)  # Track successful invite
                        progress.successful += 1
                        progress.account_stats[phone]['success'] += 1
                        invite_count += 1
                        await progress.update_status(f"✅ Successfully invited {number}")
                    
                    await asyncio.sleep(INVITE_DELAY)  # Safe delay between invites
                    
                except FloodWaitError as e:
                    progress.account_stats[phone]['errors'].append(f"FloodWait: {e.seconds}s")
                    await progress.update_status(f"⚠️ FloodWait detected, switching account...")
                    break
                    
                except Exception as e:
                    progress.failed += 1
                    progress.account_stats[phone]['failed'] += 1
                    progress.account_stats[phone]['errors'].append(str(e))
                    await progress.update_status(f"❌ Error inviting {number}: {str(e)}")
                    await asyncio.sleep(5)
                    
                current_number_index += 1
            
            await client.disconnect()
            await asyncio.sleep(ACCOUNT_SWITCH_DELAY)  # Safe delay before switching accounts
            
        except Exception as e:
            logger.error(f"Error with account {phone}: {str(e)}")
            progress.account_stats[phone]['errors'].append(f"Account error: {str(e)}")
            await progress.update_status(f"❌ Error with account {phone}: {str(e)}")
            await asyncio.sleep(ERROR_DELAY)
    
    # Final report
    final_report = (
        "📊 **Invite Process Completed**\n\n"
        f"📱 Total Numbers Processed: {len(numbers)}\n"
        f"✅ Successfully Invited: {progress.successful}\n"
        f"❌ Failed: {progress.failed}\n\n"
        "📋 Account Details:\n"
    )
    
    for phone, stats in progress.account_stats.items():
        final_report += (
            f"\n🔹 {phone}:\n"
            f"  ✓ Successful: {stats['success']}\n"
            f"  ✗ Failed: {stats['failed']}\n"
        )
        if stats['errors']:
            final_report += "  ⚠️ Errors encountered:\n"
            for error in stats['errors'][-3:]:  # Show last 3 errors
                final_report += f"    - {error}\n"
                
    await progress.status_message.edit(final_report)
    user_states.pop(user_id, None)

# Error Handler
@bot.on(events.NewMessage(pattern='/cancel'))
@admin_only
async def cancel_handler(event):
    """Handle cancel command to reset user state"""
    user_id = event.sender_id
    if user_id in user_states:
        user_states.pop(user_id, None)
        await event.respond("✅ Current operation cancelled. You can start fresh now!")
    else:
        await event.respond("ℹ️ No active operation to cancel.")

# Main function to run the bot
def main():
    """Main function to start the bot"""
    # Ensure all required directories exist
    ensure_directories()
    
    # Load saved data
    global user_sessions
    user_sessions = load_sessions()
    
    # Print startup message
    print("🤖 Telegram Manager Bot is starting...")
    print("✨ Made with Telethon")
    print("⚡ Bot is ready to use!")
    
    try:
        print("📡 Starting message handler...")
        # Create and get event loop
        loop = asyncio.get_event_loop()
        loop.run_until_complete(bot.run_until_disconnected())
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        logger.error(f"Bot crashed: {str(e)}")
    finally:
        loop.close()

# Run the bot
if __name__ == '__main__':
    try:
        # Setup logging with proper file mode
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('bot.log', mode='a'),
                logging.StreamHandler()
            ]
        )
        
        logger.info("Bot is starting...")
        main()
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        raise
