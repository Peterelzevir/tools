# Telegram API Configuration 
API_ID = "23207350"  # Get from my.telegram.org
API_HASH = "03464b6c80a5051eead6835928e48189"  # Get from my.telegram.org
BOT_TOKEN = "7679634554:AAHnHcX8tDrEfTbP-cpjnCYc9Uiw0oK1mMw"  # Get from @BotFather

# Bot Admin Configuration
ADMIN_IDS = [5988451717, 5728683700, 1122334455]  # List ID admin yang diizinkan  # Your Telegram User ID

# Database Configuration
DB_NAME = "sessions.db"

# Message Templates
START_MESSAGE = """
🤖 *Welcome to Multi Account Manager Bot!*

I can help you manage multiple Telegram accounts and perform mass invites efficiently.
Press the buttons below to get started!
"""

HELP_MESSAGE = """
📚 *Available Commands & Features:*

1️⃣ *Connect Account* 
   • Add new Telegram accounts
   • Support 2FA accounts
   • Maximum 3 retry for wrong codes
   
2️⃣ *Delete Account*
   • Remove single account
   • Remove all accounts
   • Auto logout from Telegram
   
3️⃣ *Invite Members*
   • Support .txt and .vcf files
   • Parallel processing
   • Auto distribute tasks
   • Smart flood detection
   • Auto help system
   
⚙️ *How It Works:*
• Every account works simultaneously
• Process gets divided equally
• If account gets flood, others will help
• Real-time progress updates

🔒 *Security:*
• Admin-only access
• Secure session storage
• Auto delete contacts
• Safe logout system

❓ Need help? Contact: @your_username
"""

# Progress Messages
PROGRESS_INVITE = """
📊 *Invite Progress Report*
Time: {time}

{details}

📈 *Summary:*
✅ Total Success: {success}
❌ Total Failed: {failed}
⏳ Remaining: {remaining}
🕒 Elapsed Time: {elapsed}
"""

# Error Messages
FLOOD_MESSAGE = """
⚠️ *Flood Wait Detected*
Account: {phone}
Wait Time: {seconds} seconds
Status: Other accounts will handle remaining tasks
"""

SUCCESS_MESSAGE = """
✅ *Task Completed Successfully!*

📊 *Final Statistics:*
• Total Processed: {total}
• Success: {success}
• Failed: {failed}
• Total Time: {time}
• Accounts Used: {accounts}

📱 *Per Account Details:*
{details}

Thank you for using our service! 🙏
"""