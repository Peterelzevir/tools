from telethon import TelegramClient, Button, errors
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest, InviteToChannelRequest
from telethon.tl.types import InputPhoneContact
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest

import asyncio
import re
import logging
from typing import Dict, List, Set, Tuple
from datetime import datetime, timedelta

from config import API_ID, API_HASH

logger = logging.getLogger(__name__)

class InviteManager:
    def __init__(self, db):
        self.db = db
        self.invite_tasks: Dict[int, Dict] = {}  # user_id: {step, data}
        self.active_invites: Dict[int, bool] = {}  # user_id: is_active

    async def start_invite_process(self, event):
        """Start the invite process"""
        sessions = self.db.get_all_sessions()
        if not sessions:
            await event.edit("""
❌ *No Accounts Available*
Please connect some accounts first using the Connect option.
""", parse_mode='markdown')
            return
        
        # Show account status
        status_text = "*Available Accounts:*\n\n"
        for session in sessions:
            phone = session[0]
            stats = self.db.get_session_stats(phone)
            status_text += f"""
📱 `{phone}`
• Invites Today: {stats['total_invites']}
• Flood Count: {stats['flood_count']}
• Status: Active
"""

        buttons = [[Button.inline("❌ Cancel", "cancel")]]
        await event.edit(f"""
👥 *Start Mass Invite Process*

{status_text}

Please send the group/channel link:
• Format: `https://t.me/username` or `@username`
• Make sure the group exists
• Bot must be admin in group
""", buttons=buttons, parse_mode='markdown')
        
        self.invite_tasks[event.sender_id] = {
            "step": "group_link",
            "data": {
                "sessions": sessions,
                "start_time": datetime.now()
            }
        }

    async def handle_invite_step(self, event):
        """Handle each step of invite process"""
        user_data = self.invite_tasks.get(event.sender_id)
        if not user_data:
            return

        if user_data["step"] == "group_link":
            await self._handle_group_link(event, user_data)
        elif user_data["step"] == "numbers_file":
            await self._handle_numbers_file(event, user_data)
        elif user_data["step"] == "delay":
            await self._handle_delay_input(event, user_data)

    async def _handle_group_link(self, event, user_data):
        """Handle group link input"""
        link = event.text.strip()
        if not self._validate_group_link(link):
            await event.respond("""
❌ *Invalid Group Link*
Please send a valid group link or username.
Example: `https://t.me/groupname` or `@groupname`
""", parse_mode='markdown')
            return
                
        # Save link and move to next step
        user_data["data"]["group_link"] = link
        user_data["step"] = "numbers_file"
        
        await event.respond("""
📱 *Send Phone Numbers File*

Accepted formats:
• TXT file with one number per line
• VCF contact file

Format for TXT:
```
+1234567890
+9876543210
```
Note: Numbers can be with/without + prefix
""", parse_mode='markdown')

    async def _handle_numbers_file(self, event, user_data):
        """Process uploaded numbers file"""
        try:
            if not event.file:
                await event.respond("❌ Please send a valid file containing phone numbers.")
                return
                    
            file_data = await event.download_media(bytes)
            numbers = self._extract_numbers(file_data.decode())
                
            if not numbers:
                await event.respond("❌ No valid phone numbers found in file.")
                return
                    
            user_data["data"]["numbers"] = numbers
            user_data["step"] = "delay"

            # Calculate distribution preview
            sessions = user_data["data"]["sessions"]
            numbers_per_account = len(numbers) // len(sessions)
            extra_numbers = len(numbers) % len(sessions)
                
            preview = f"""
📊 *Numbers Distribution Preview*

Total Numbers: {len(numbers)}
Available Accounts: {len(sessions)}

Distribution:
• Base numbers per account: {numbers_per_account}
• Extra numbers: {extra_numbers}
• Chunk size: 5 (parallel processing)

⚙️ Please set delay between invites:
• Recommended: 30-60 seconds
• Format: Send number in seconds
• Example: `30`
"""
            
            buttons = [[Button.inline("❌ Cancel", "cancel")]]
            await event.respond(preview, buttons=buttons, parse_mode='markdown')

        except Exception as e:
            logger.error(f"Error processing file: {str(e)}")
            await event.respond(f"❌ Error processing file: {str(e)}")

    async def _handle_delay_input(self, event, user_data):
        """Handle delay setting input"""
        try:
            delay = int(event.text.strip())
            if delay < 0:
                await event.respond("❌ Delay must be a positive number.")
                return
                    
            user_data["data"]["delay"] = delay
            
            numbers = user_data["data"]["numbers"]
            sessions = user_data["data"]["sessions"]
            
            # Calculate estimated time
            total_operations = len(numbers)
            estimated_time = (total_operations * delay) / len(sessions)
            formatted_time = str(timedelta(seconds=estimated_time))
                
            confirmation = f"""
⚡️ *Ready to Start Invite Process*

📊 Configuration:
• Total Numbers: {len(numbers)}
• Active Accounts: {len(sessions)}
• Delay: {delay} seconds
• Parallel Processing: 5 numbers/batch

⏱ Estimated Time: {formatted_time}

🔄 Process Details:
• All accounts work simultaneously
• Smart task distribution
• Auto-help system for flood
• Real-time progress updates

Ready to start?
"""
            
            buttons = [
                [Button.inline("✅ Start", "start_invite")],
                [Button.inline("❌ Cancel", "cancel")]
            ]
                
            await event.respond(confirmation, buttons=buttons, parse_mode='markdown')
            user_data["step"] = "confirm"
                
        except ValueError:
            await event.respond("""
❌ *Invalid Input*
Please send a valid number for delay.
Example: `30`
""", parse_mode='markdown')

    async def start_invitation_process(self, event):
        """Main invitation process handler"""
        user_data = self.invite_tasks[event.sender_id]
        if not user_data or user_data["step"] != "confirm":
            return
            
        self.active_invites[event.sender_id] = True
        progress_msg = await event.respond("🚀 *Starting Invitation Process...*", parse_mode='markdown')
        
        # Shared state for task management
        shared_state = {
            "failed_tasks": [],  # List of (phone, numbers) that need help
            "available_helpers": asyncio.Queue(),  # Queue of available helper clients
            "task_lock": asyncio.Lock(),  # Lock for task redistribution
            "progress": {},  # Track progress per account
            "start_time": datetime.now()
        }

        clients = []  # Initialize clients list for cleanup
        try:
            numbers = user_data["data"]["numbers"]
            sessions = user_data["data"]["sessions"]
            delay = user_data["data"]["delay"]
            group_link = user_data["data"]["group_link"]
            
            # Distribute numbers among sessions
            distribution = self._distribute_numbers(numbers, sessions)
            
            # Initialize clients and join group
            for session in sessions:
                phone, session_string = session[0], session[1]
                try:
                    client = TelegramClient(
                        StringSession(session_string),
                        API_ID,
                        API_HASH
                    )
                    await client.connect()
                    
                    try:
                        await client(JoinChannelRequest(group_link))
                        clients.append((client, phone))
                        shared_state["progress"][phone] = {
                            "invited": 0,
                            "failed": 0,
                            "status": "Active"
                        }
                    except Exception as e:
                        logger.error(f"Error joining group with {phone}: {str(e)}")
                        await progress_msg.edit(f"""
⚠️ *Join Group Error*
Account: `{phone}`
Error: {str(e)}
""", parse_mode='markdown')
                        continue
                        
                except Exception as e:
                    logger.error(f"Error connecting client {phone}: {str(e)}")
                    continue
            
            if not clients:
                await progress_msg.edit("❌ *No accounts could join the group.*", parse_mode='markdown')
                return
                
            # Start invite tasks for each client
            main_tasks = []
            for client, phone in clients:
                numbers_for_client = distribution.get(phone, [])
                if numbers_for_client:
                    chunked_numbers = self._chunk_numbers(numbers_for_client, 5)
                    for chunk in chunked_numbers:
                        task = asyncio.create_task(
                            self._invite_with_client(
                                client,
                                phone,
                                chunk,
                                group_link,
                                delay,
                                progress_msg,
                                shared_state
                            )
                        )
                        main_tasks.append((phone, task))
            
            # Start helper task
            helper_task = asyncio.create_task(
                self._help_with_failed_tasks(
                    shared_state,
                    group_link,
                    delay,
                    progress_msg
                )
            )
            
            # Run all tasks
            for phone, task in main_tasks:
                try:
                    await task
                except Exception as e:
                    logger.error(f"Error in main task for {phone}: {str(e)}")
            
            # Wait for helper to finish remaining tasks
            while shared_state["failed_tasks"]:
                await asyncio.sleep(1)
                
            # Cancel helper task
            helper_task.cancel()
            
            # Generate final report
            end_time = datetime.now()
            duration = end_time - shared_state["start_time"]
            
            final_report = """
✅ *Invite Process Completed*

📊 *Account Details:*\n"""
            
            total_invited = 0
            total_failed = 0
            
            for phone, stats in shared_state["progress"].items():
                invited = stats["invited"]
                failed = stats["failed"]
                total_invited += invited
                total_failed += failed
                
                final_report += f"""
📱 `{phone}`:
• Invited: {invited}
• Failed: {failed}
• Success Rate: {self._calculate_success_rate(invited, failed)}%
"""
            
            final_report += f"""
📈 *Final Summary:*
• Total Invited: {total_invited}
• Total Failed: {total_failed}
• Success Rate: {self._calculate_success_rate(total_invited, total_failed)}%
• Duration: {str(duration).split('.')[0]}
• Accounts Used: {len(clients)}
"""
            
            await progress_msg.edit(final_report, parse_mode='markdown')
            
        except Exception as e:
            logger.error(f"Error in invite process: {str(e)}")
            await progress_msg.edit(f"""
❌ *Error During Invite Process*
Error: {str(e)}
""", parse_mode='markdown')
            
        finally:
            # Cleanup
            self.active_invites[event.sender_id] = False
            if event.sender_id in self.invite_tasks:
                del self.invite_tasks[event.sender_id]
                
            # Disconnect all clients
            for client, _ in clients:
                try:
                    await client.disconnect()
                except:
                    pass

    async def _invite_with_client(self, client, phone, numbers, group, delay, progress_msg, shared_state):
        """Process invite for a chunk of numbers"""
        invited = 0
        failed = 0
        remaining_numbers = list(numbers)
        
        try:
            while remaining_numbers and self.active_invites.get(progress_msg.chat_id):
                number = remaining_numbers[0]
                
                try:
                    # Import contact
                    contact = InputPhoneContact(
                        client_id=0,
                        phone=number,
                        first_name=f"User{number[-4:]}",
                        last_name=""
                    )
                    imported = await client(ImportContactsRequest([contact]))
                    
                    if imported.users:
                        user = imported.users[0]
                        try:
                            await client(InviteToChannelRequest(group, [user.id]))
                            invited += 1
                            remaining_numbers.pop(0)  # Remove successfully processed number
                            
                            # Update progress
                            async with shared_state["task_lock"]:
                                if phone not in shared_state["progress"]:
                                    shared_state["progress"][phone] = {"invited": 0, "failed": 0}
                                shared_state["progress"][phone]["invited"] = invited
                                await self._update_progress_message(
                                    progress_msg, 
                                    shared_state["progress"],
                                    shared_state["start_time"]
                                )
                                
                        except errors.FloodWaitError as e:
                            logger.warning(f"Account {phone} got flood wait for {e.seconds} seconds")
                            
                            # Add remaining numbers to failed tasks
                            async with shared_state["task_lock"]:
                                shared_state["failed_tasks"].append((phone, remaining_numbers))
                                shared_state["progress"][phone]["status"] = f"Flood ({e.seconds}s)"
                                await progress_msg.edit(f"""
⚠️ Account {phone} got flood wait for {e.seconds} seconds.
Remaining numbers will be processed by other accounts.
""", parse_mode='markdown')
                            raise
                            
                        except Exception as e:
                            failed += 1
                            remaining_numbers.pop(0)  # Skip failed number
                            logger.error(f"Error inviting {number}: {str(e)}")
                    else:
                        failed += 1
                        remaining_numbers.pop(0)  # Skip invalid number
                        
                    # Delete contact
                    try:
                        await client(DeleteContactsRequest(imported.users))
                    except:
                        pass
                        
                    await asyncio.sleep(delay)
                    
                except errors.FloodWaitError:
                    raise
                except Exception as e:
                    failed += 1
                    logger.error(f"Error processing {number}: {str(e)}")
                    remaining_numbers.pop(0)  # Skip failed number

            # If all numbers processed successfully, register as available helper
            if not remaining_numbers:
                await shared_state["available_helpers"].put((client, phone))
                shared_state["progress"][phone]["status"] = "Helper Available"
            
            # Update final progress
            async with shared_state["task_lock"]:
                shared_state["progress"][phone]["failed"] = failed
                await self._update_progress_message(
                    progress_msg,
                    shared_state["progress"],
                    shared_state["start_time"]
                )
                
            return invited, failed
            
        except Exception as e:
            logger.error(f"Error in invite process for {phone}: {str(e)}")
            return invited, failed

    async def _help_with_failed_tasks(self, shared_state, group, delay, progress_msg):
        """Helper function to process failed tasks using available helpers"""
        while True:
            if not shared_state["failed_tasks"]:
                await asyncio.sleep(1)
                continue
            
            try:
                helper_client, helper_phone = await shared_state["available_helpers"].get()
                
                async with shared_state["task_lock"]:
                    if not shared_state["failed_tasks"]:
                        continue
                        
                    failed_phone, numbers = shared_state["failed_tasks"].pop(0)
                    shared_state["progress"][helper_phone]["status"] = f"Helping {failed_phone}"
                    shared_state["progress"][failed_phone]["status"] = f"Being helped by {helper_phone}"
                    
                    await progress_msg.edit(f"""
🤝 Account {helper_phone} is helping with numbers from {failed_phone}
Remaining numbers: {len(numbers)}
""", parse_mode='markdown')
                    
                    try:
                        invited, failed = await self._invite_with_client(
                            helper_client,
                            helper_phone,
                            numbers,
                            group,
                            delay,
                            progress_msg,
                            shared_state
                        )
                        
                        # Update progress to show helped numbers
                        async with shared_state["task_lock"]:
                            if failed_phone not in shared_state["progress"]:
                                shared_state["progress"][failed_phone] = {"invited": 0, "failed": 0}
                            shared_state["progress"][failed_phone]["invited"] += invited
                            shared_state["progress"][failed_phone]["failed"] += failed
                            await self._update_progress_message(
                                progress_msg,
                                shared_state["progress"],
                                shared_state["start_time"]
                            )
                            
                    except Exception as e:
                        logger.error(f"Helper {helper_phone} failed: {str(e)}")
                        # Put failed numbers back if helper also fails
                        shared_state["failed_tasks"].append((failed_phone, numbers))
                        
            except Exception as e:
                logger.error(f"Error in helper task: {str(e)}")
                await asyncio.sleep(1)

    async def _update_progress_message(self, message, progress, start_time):
        """Update progress message with current status"""
        current_time = datetime.now()
        elapsed = current_time - start_time
        elapsed_str = str(elapsed).split('.')[0]

        text = "🔄 *Invite Progress Report*\n\n"
        
        total_invited = 0
        total_failed = 0
        
        # Account details
        for phone, stats in progress.items():
            invited = stats["invited"]
            failed = stats["failed"]
            status = stats.get("status", "Active")
            
            total_invited += invited
            total_failed += failed
            
            text += f"""
📱 `{phone}`:
✅ Invited: {invited}
❌ Failed: {failed}
📊 Status: {status}
"""
            
        # Summary
        text += f"""
📈 *Overall Progress:*
• Total Success: {total_invited}
• Total Failed: {total_failed}
• Total Processed: {total_invited + total_failed}
• Elapsed Time: {elapsed_str}

🔄 Process is running...
"""
        
        try:
            await message.edit(text, parse_mode='markdown')
        except Exception as e:
            logger.error(f"Error updating progress: {str(e)}")

    def _validate_group_link(self, link: str) -> bool:
        """Validate Telegram group/channel link format"""
        patterns = [
            r'^https?://t\.me/[a-zA-Z0-9_]+$',
            r'^@[a-zA-Z0-9_]+$',
            r'^[a-zA-Z0-9_]+$'
        ]
        return any(re.match(pattern, link) for pattern in patterns)

    def _extract_numbers(self, content: str) -> List[str]:
        """Extract valid phone numbers from file content"""
        numbers = set()
        
        for line in content.splitlines():
            number = re.sub(r'\D', '', line.strip())
            
            if number and len(number) >= 10:
                if not number.startswith('+'):
                    number = '+' + number
                numbers.add(number)
                
        return sorted(list(numbers))

    def _chunk_numbers(self, numbers: List[str], chunk_size: int) -> List[List[str]]:
        """Split numbers into smaller chunks for parallel processing"""
        return [numbers[i:i + chunk_size] for i in range(0, len(numbers), chunk_size)]

    def _distribute_numbers(self, numbers: List[str], sessions: List[Tuple]) -> Dict[str, List[str]]:
        """Distribute numbers among available sessions"""
        distribution = {}
        total_numbers = len(numbers)
        total_sessions = len(sessions)
        
        base_count = total_numbers // total_sessions
        extra = total_numbers % total_sessions
        
        start = 0
        for i, session in enumerate(sessions):
            phone = session[0]
            count = base_count + (1 if i < extra else 0)
            end = start + count
            distribution[phone] = numbers[start:end]
            start = end
            
        return distribution

    def _calculate_success_rate(self, success: int, failed: int) -> float:
        """Calculate success rate percentage"""
        total = success + failed
        if total == 0:
            return 0.0
        return round((success / total) * 100, 2)

    async def cancel_invite(self, event):
        """Cancel ongoing invite process"""
        if event.sender_id in self.active_invites:
            self.active_invites[event.sender_id] = False
            
        if event.sender_id in self.invite_tasks:
            del self.invite_tasks[event.sender_id]
            
        await event.edit("""
❌ *Invite Process Cancelled*
All operations have been stopped.
Temporary data has been cleared.
""", parse_mode='markdown')