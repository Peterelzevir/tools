import os
import json
import asyncio
import time
from datetime import datetime
from telethon import TelegramClient, errors
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty
from concurrent.futures import ThreadPoolExecutor
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich import print
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TextColumn,
    TimeRemainingColumn,
    TimeElapsedColumn
)
from rich.live import Live
from rich.table import Table
from rich.layout import Layout
import vobject
import logging
from rich.logging import RichHandler

# Configure logging with Rich
logging.basicConfig(
    level="INFO",
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)]
)

log = logging.getLogger("rich")

# ASCII Art with updated style
ASCII_ART = """
[bold magenta]
██████╗ ██╗   ██╗    ██╗  ██╗██╗██╗   ██╗ █████╗  ██████╗ ██╗  ██╗
██╔══██╗╚██╗ ██╔╝    ██║  ██║██║╚██╗ ██╔╝██╔══██╗██╔═══██╗██║ ██╔╝
██████╔╝ ╚████╔╝     ███████║██║ ╚████╔╝ ███████║██║   ██║█████╔╝ 
██╔══██╗  ╚██╔╝      ██╔══██║██║  ╚██╔╝  ██╔══██║██║   ██║██╔═██╗ 
██████╔╝   ██║       ██║  ██║██║   ██║   ██║  ██║╚██████╔╝██║  ██╗
╚═════╝    ╚═╝       ╚═╝  ╚═╝╚═╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝
[/bold magenta]
[bold cyan]
████████╗███████╗██╗     ███████╗████████╗ ██████╗  ██████╗ ██╗     
╚══██╔══╝██╔════╝██║     ██╔════╝╚══██╔══╝██╔═══██╗██╔═══██╗██║     
   ██║   █████╗  ██║     █████╗     ██║   ██║   ██║██║   ██║██║     
   ██║   ██╔══╝  ██║     ██╔══╝     ██║   ██║   ██║██║   ██║██║     
   ██║   ███████╗███████╗███████╗   ██║   ╚██████╔╝╚██████╔╝███████╗
   ╚═╝   ╚══════╝╚══════╝╚══════╝   ╚═╝    ╚═════╝  ╚═════╝ ╚══════╝
[/bold cyan]"""

console = Console()
CONFIG_FILE = "config.json"
SESSIONS_DIR = "sessions"
LOG_DIR = "logs"

class Logger:
    def __init__(self):
        self.ensure_log_dir()
        self.log_file = os.path.join(LOG_DIR, f"telegram_tool_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        self.console = Console(file=open(self.log_file, "a"))

    def ensure_log_dir(self):
        if not os.path.exists(LOG_DIR):
            os.makedirs(LOG_DIR)

    def log(self, message, level="info"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"
        
        if level == "info":
            console.print(f"[cyan]{formatted_message}[/cyan]")
            self.console.print(f"[cyan]{formatted_message}[/cyan]")
        elif level == "success":
            console.print(f"[green]{formatted_message}[/green]")
            self.console.print(f"[green]{formatted_message}[/green]")
        elif level == "error":
            console.print(f"[red]{formatted_message}[/red]")
            self.console.print(f"[red]{formatted_message}[/red]")
        elif level == "warning":
            console.print(f"[yellow]{formatted_message}[/yellow]")
            self.console.print(f"[yellow]{formatted_message}[/yellow]")

class AccountStats:
    def __init__(self):
        self.total_attempts = 0
        self.successful_invites = 0
        self.failed_invites = 0
        self.flood_wait_count = 0
        self.start_time = None
        self.end_time = None
        self.status = "waiting"
        self.current_contact = None
        self.error_details = []

    @property
    def duration(self):
        if self.start_time:
            end = self.end_time or datetime.now()
            return (end - self.start_time).total_seconds()
        return 0

    @property
    def success_rate(self):
        if self.total_attempts == 0:
            return 0
        return (self.successful_invites / self.total_attempts) * 100

class TelegramTool:
    def __init__(self):
        self.config = self.load_config()
        self.ensure_directories()
        self.logger = Logger()
        self.account_stats = {}

    def load_config(self):
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except FileNotFoundError:
            console.print("[red]Config file not found! Please create config.json with api_id and api_hash[/red]")
            exit(1)

    def ensure_directories(self):
        for directory in [SESSIONS_DIR, LOG_DIR]:
            if not os.path.exists(directory):
                os.makedirs(directory)

    async def create_progress_table(self, account_tasks):
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Account")
        table.add_column("Status")
        table.add_column("Progress")
        table.add_column("Success Rate")
        table.add_column("Flood Count")
        table.add_column("Last Contact")
        table.add_column("Duration")

        for task in account_tasks:
            phone = task['session'].replace('.session', '')
            stats = self.account_stats[phone]
            
            progress = f"{stats.successful_invites}/{task['total_contacts']}"
            success_rate = f"{stats.success_rate:.1f}%"
            duration = f"{stats.duration:.0f}s"
            
            status_color = {
                "waiting": "white",
                "working": "cyan",
                "flood": "yellow",
                "done": "green",
                "error": "red"
            }.get(stats.status, "white")

            table.add_row(
                phone,
                f"[{status_color}]{stats.status}[/{status_color}]",
                progress,
                success_rate,
                str(stats.flood_wait_count),
                str(stats.current_contact or "N/A"),
                duration
            )

        return table

    async def add_account(self):
        self.logger.log("Starting account addition process", "info")
        phone = Prompt.ask("[yellow]Enter phone number (with country code)")
        
        session_path = os.path.join(SESSIONS_DIR, f"{phone}.session")
        client = TelegramClient(session_path, self.config['api_id'], self.config['api_hash'])
        
        try:
            await client.connect()
            self.logger.log(f"Attempting connection for {phone}", "info")
            
            if not await client.is_user_authorized():
                await client.send_code_request(phone)
                self.logger.log("Verification code sent", "info")
                
                for attempt in range(3):
                    try:
                        code = Prompt.ask("[yellow]Enter the code you received")
                        await client.sign_in(phone, code)
                        break
                    except errors.SessionPasswordNeededError:
                        self.logger.log("Two-step verification required", "info")
                        password = Prompt.ask("[yellow]Enter your 2FA password", password=True)
                        await client.sign_in(password=password)
                        break
                    except errors.PhoneCodeInvalidError:
                        remaining = 2 - attempt
                        self.logger.log(f"Invalid code! {remaining} attempts remaining", "error")
                        if remaining == 0:
                            self.logger.log("All attempts failed", "error")
                            return
            
            me = await client.get_me()
            self.logger.log(f"Successfully logged in as {me.first_name} ({phone})", "success")
            
        except Exception as e:
            self.logger.log(f"Error during account addition: {str(e)}", "error")
        finally:
            await client.disconnect()

    async def delete_sessions(self):
        sessions = [f for f in os.listdir(SESSIONS_DIR) if f.endswith('.session')]
        
        if not sessions:
            self.logger.log("No sessions found!", "warning")
            return
            
        self.logger.log(f"Found {len(sessions)} sessions", "info")
        confirm = Confirm.ask("Are you sure you want to delete all sessions?")
        
        if confirm:
            for session in sessions:
                os.remove(os.path.join(SESSIONS_DIR, session))
                self.logger.log(f"Deleted session: {session}", "info")
            self.logger.log("All sessions deleted successfully!", "success")
        else:
            self.logger.log("Operation cancelled", "warning")

    async def invite_contacts(self):
        # Initialize status tracking
        sessions = [f for f in os.listdir(SESSIONS_DIR) if f.endswith('.session')]
        if not sessions:
            self.logger.log("No sessions found! Please add accounts first.", "error")
            return

        # Reset account stats
        self.account_stats = {
            session.replace('.session', ''): AccountStats()
            for session in sessions
        }

        # Get and validate group link
        group_link = Prompt.ask("[yellow]Enter group link or username")
        first_session = sessions[0]
        client = TelegramClient(
            os.path.join(SESSIONS_DIR, first_session),
            self.config['api_id'],
            self.config['api_hash']
        )
        
        async with client:
            try:
                if group_link.startswith('https://t.me/'):
                    group_username = group_link.split('/')[-1]
                else:
                    group_username = group_link
                    
                entity = await client.get_entity(group_username)
                self.logger.log(f"Group validated: {entity.title}", "success")
            except Exception as e:
                self.logger.log(f"Invalid group or cannot access: {str(e)}", "error")
                return

        # Process VCF file
        vcf_path = Prompt.ask("[yellow]Enter path to VCF file")
        if not os.path.exists(vcf_path):
            self.logger.log("VCF file not found!", "error")
            return

        try:
            with open(vcf_path, 'r', encoding='utf-8') as f:
                vcf_content = f.read()
            
            contacts = []
            for card in vobject.readComponents(vcf_content):
                if hasattr(card, 'tel'):
                    for tel in card.tel_list:
                        phone = ''.join(filter(str.isdigit, tel.value))
                        if phone:
                            contacts.append(phone)
            
            contacts = list(set(contacts))  # Remove duplicates
            self.logger.log(f"Processed {len(contacts)} unique contacts from VCF", "info")
            
        except Exception as e:
            self.logger.log(f"Error processing VCF: {str(e)}", "error")
            return

        # Get delay and confirmation
        delay = float(Prompt.ask("[yellow]Enter delay between invites (in seconds)", default="60"))
        
        if not Confirm.ask("Start inviting process?"):
            self.logger.log("Operation cancelled", "warning")
            return

        # Distribute contacts among accounts
        contacts_per_account = len(contacts) // len(sessions)
        remaining = len(contacts) % len(sessions)
        
        account_tasks = []
        start_idx = 0
        
        for i, session in enumerate(sessions):
            extra = 1 if i < remaining else 0
            end_idx = start_idx + contacts_per_account + extra
            account_contacts = contacts[start_idx:end_idx]
            start_idx = end_idx
            
            account_tasks.append({
                'session': session,
                'contacts': account_contacts,
                'total_contacts': len(account_contacts)
            })

        # Create live display layout
        layout = Layout()
        layout.split(
            Layout(name="header", size=3),
            Layout(name="progress"),
            Layout(name="footer", size=3)
        )

        async def process_account(task):
            session = task['session']
            phone = session.replace('.session', '')
            stats = self.account_stats[phone]
            stats.start_time = datetime.now()
            
            client = TelegramClient(
                os.path.join(SESSIONS_DIR, session),
                self.config['api_id'],
                self.config['api_hash']
            )
            
            try:
                async with client:
                    # Join group
                    try:
                        stats.status = "joining group"
                        await client(JoinChannelRequest(entity))
                        self.logger.log(f"Account {phone} joined group successfully", "success")
                    except Exception as e:
                        self.logger.log(f"Account {phone} failed to join group: {str(e)}", "error")
                        stats.error_details.append(f"Failed to join group: {str(e)}")
                        return

                    stats.status = "working"
                    for contact in task['contacts']:
                        stats.current_contact = contact
                        stats.total_attempts += 1
                        
                        try:
                            await client.invite_to_channel(entity, [contact])
                            stats.successful_invites += 1
                            self.logger.log(f"Account {phone} successfully invited {contact}", "success")
                            await asyncio.sleep(delay)
                            
                        except errors.FloodWaitError as e:
                            stats.flood_wait_count += 1
                            stats.failed_invites += 1
                            stats.error_details.append(f"Flood wait for {e.seconds}s")
                            stats.status = "flood"
                            self.logger.log(f"Account {phone} hit flood limit: {e.seconds}s wait required", "warning")
                            break
                            
                        except Exception as e:
                            stats.failed_invites += 1
                            error_msg = str(e)
                            stats.error_details.append(f"Failed to invite {contact}: {error_msg}")
                            self.logger.log(f"Account {phone} failed to invite {contact}: {error_msg}", "error")

                    if stats.status != "flood":
                        stats.status = "done"
                        
            except Exception as e:
                stats.status = "error"
                stats.error_details.append(f"Fatal error: {str(e)}")
                self.logger.log(f"Fatal error with account {phone}: {str(e)}", "error")
            finally:
                stats.end_time = datetime.now()

        # Manage redistribution of work from flooded accounts
        async def redistribute_work():
            while True:
                # Find flooded accounts with remaining work
                flooded_tasks = [
                    task for task in account_tasks 
                    if self.account_stats[task['session'].replace('.session', '')].status == "flood"
                    and task['contacts']  # Still has contacts to process
                ]
                
                # Find available accounts
                available_tasks = [
                    task for task in account_tasks
                    if self.account_stats[task['session'].replace('.session', '')].status == "done"
                ]
                
                if not flooded_tasks or not available_tasks:
                    await asyncio.sleep(5)
                    continue
                
                # Redistribute work
                for flooded_task in flooded_tasks:
                    flooded_phone = flooded_task['session'].replace('.session', '')
                    remaining_contacts = flooded_task['contacts']
                    
                    if not remaining_contacts:
                        continue
                        
                    chunks = len(available_tasks)
                    contacts_per_chunk = len(remaining_contacts) // chunks
                    
                    for i, available_task in enumerate(available_tasks):
                        start_idx = i * contacts_per_chunk
                        end_idx = start_idx + contacts_per_chunk if i < chunks - 1 else len(remaining_contacts)
                        
                        chunk = remaining_contacts[start_idx:end_idx]
                        if chunk:
                            available_phone = available_task['session'].replace('.session', '')
                            self.logger.log(
                                f"Redistributing {len(chunk)} contacts from {flooded_phone} to {available_phone}",
                                "info"
                            )
                            available_task['contacts'].extend(chunk)
                            self.account_stats[available_phone].status = "working"
                    
                    # Clear redistributed contacts
                    flooded_task['contacts'] = []

                await asyncio.sleep(5)

        # Create live display
        async def update_display():
            with Live(layout, refresh_per_second=4) as live:
                while True:
                    # Update header
                    total_contacts = sum(task['total_contacts'] for task in account_tasks)
                    total_invited = sum(stats.successful_invites for stats in self.account_stats.values())
                    total_failed = sum(stats.failed_invites for stats in self.account_stats.values())
                    
                    header = Table.grid()
                    header.add_row(f"[bold cyan]Total Progress: {total_invited}/{total_contacts} "
                                f"(Failed: {total_failed})[/bold cyan]")
                    layout["header"].update(header)
                    
                    # Update progress table
                    layout["progress"].update(await self.create_progress_table(account_tasks))
                    
                    # Update footer with error count
                    total_errors = sum(len(stats.error_details) for stats in self.account_stats.values())
                    footer = Table.grid()
                    footer.add_row(f"[bold red]Total Errors: {total_errors}[/bold red]")
                    layout["footer"].update(footer)
                    
                    # Check if all done
                    if all(stats.status in ['done', 'error', 'flood'] 
                          for stats in self.account_stats.values()):
                        break
                        
                    await asyncio.sleep(0.25)

        # Start all processes
        await asyncio.gather(
            update_display(),
            redistribute_work(),
            *[process_account(task) for task in account_tasks]
        )

        # Final summary
        self.logger.log("\n===== Final Summary =====", "info")
        
        summary_table = Table(show_header=True, header_style="bold magenta")
        summary_table.add_column("Account")
        summary_table.add_column("Final Status")
        summary_table.add_column("Success/Total")
        summary_table.add_column("Success Rate")
        summary_table.add_column("Flood Count")
        summary_table.add_column("Duration")
        summary_table.add_column("Errors")
        
        for task in account_tasks:
            phone = task['session'].replace('.session', '')
            stats = self.account_stats[phone]
            
            summary_table.add_row(
                phone,
                stats.status,
                f"{stats.successful_invites}/{task['total_contacts']}",
                f"{stats.success_rate:.1f}%",
                str(stats.flood_wait_count),
                f"{stats.duration:.0f}s",
                str(len(stats.error_details))
            )
        
        console.print(summary_table)
        
        # Print detailed error log if any
        error_count = sum(len(stats.error_details) for stats in self.account_stats.values())
        if error_count > 0:
            self.logger.log("\n===== Error Details =====", "error")
            for task in account_tasks:
                phone = task['session'].replace('.session', '')
                stats = self.account_stats[phone]
                if stats.error_details:
                    self.logger.log(f"\nAccount {phone}:", "error")
                    for i, error in enumerate(stats.error_details, 1):
                        self.logger.log(f"  {i}. {error}", "error")

    async def run(self):
        console.print(Panel(ASCII_ART))
        
        while True:
            console.print("\n[cyan]===== Menu =====[/cyan]")
            console.print("1. Add Account")
            console.print("2. Delete All Sessions")
            console.print("3. Invite Contacts")
            console.print("4. Exit")
            
            choice = Prompt.ask("Choose an option", choices=["1", "2", "3", "4"])
            
            if choice == "1":
                await self.add_account()
            elif choice == "2":
                await self.delete_sessions()
            elif choice == "3":
                await self.invite_contacts()
            else:
                self.logger.log("Goodbye!", "info")
                break

if __name__ == "__main__":
    tool = TelegramTool()
    asyncio.run(tool.run())
