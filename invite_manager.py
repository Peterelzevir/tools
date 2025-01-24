from telethon import TelegramClient, Button, errors
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest, InviteToChannelRequest
from telethon.tl.types import InputPhoneContact
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest

import asyncio
import re
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

from config import API_ID, API_HASH

logger = logging.getLogger(__name__)

class InviteManager:
    def __init__(self, db):
        self.db = db
        self.invite_tasks = {}  # user_id: {step, data}
        self.active_invites = {}  # user_id: is_active
        self.chunk_size = 1000  # Max clients to process at once

    async def start_invite_process(self, event):
        try:
            sessions = self.db.get_all_sessions()
            if not sessions:
                await event.edit("""
❌ *No Accounts Available*
Please connect some accounts first using the Connect option.
""", parse_mode='markdown')
                return
            
            status_text = "*Available Accounts:*\n\n"
            for session in sessions[:5]:
                phone = session[0]
                stats = self.db.get_session_stats(phone)
                status_text += f"""
📱 `{phone}`
• Invites Today: {stats['total_invites']}
• Flood Count: {stats['flood_count']}
• Status: Active
"""
            
            if len(sessions) > 5:
                status_text += f"\n_...and {len(sessions)-5} more accounts_"

            buttons = [[Button.inline("❌ Cancel", "cancel")]]
            
            await event.edit(f"""
👥 *Start Mass Invite Process*

{status_text}

Total Active Accounts: {len(sessions)}

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
        except Exception as e:
            logger.error(f"Error in start invite process: {str(e)}")
            await event.edit("❌ An error occurred while starting invite process.")

    async def handle_invite_step(self, event):
        try:
            user_data = self.invite_tasks.get(event.sender_id)
            if not user_data:
                return

            if user_data["step"] == "group_link":
                await self._handle_group_link(event, user_data)
            elif user_data["step"] == "numbers_file":
                await self._handle_numbers_file(event, user_data)
            elif user_data["step"] == "delay":
                await self._handle_delay_input(event, user_data)
        except Exception as e:
            logger.error(f"Error in handle invite step: {str(e)}")
            await event.respond("❌ An error occurred during the process.")

    async def _handle_group_link(self, event, user_data):
        try:
            link = event.text.strip()
            if not self._validate_group_link(link):
                await event.respond("""
❌ *Invalid Group Link*
Please send a valid group link or username.
Example: `https://t.me/groupname` or `@groupname`
""", parse_mode='markdown')
                return
                    
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
            
        except Exception as e:
            logger.error(f"Error in handle group link: {str(e)}")
            await event.respond("❌ An error occurred while processing group link.")

    async def _handle_numbers_file(self, event, user_data):
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
            
            sessions = user_data["data"]["sessions"]
            numbers_per_account = len(numbers) // len(sessions)
            extra_numbers = len(numbers) % len(sessions)
                
            buttons = [[Button.inline("❌ Cancel", "cancel")]]
            
            preview = f"""
📊 *Numbers Distribution Preview*

Total Numbers: {len(numbers):,}
Available Accounts: {len(sessions):,}

Distribution Plan:
• Numbers per account: {numbers_per_account:,}
• Extra numbers: {extra_numbers}
• Processing: All accounts work in parallel

⚙️ Please set delay between invites:
• Recommended: 30-60 seconds
• Format: Send number in seconds
• Example: `30`
""" 
            await event.respond(preview, buttons=buttons, parse_mode='markdown')

        except Exception as e:
            logger.error(f"Error in handle numbers file: {str(e)}")
            await event.respond("❌ Error processing numbers file.")

    async def _handle_delay_input(self, event, user_data):
        try:
            delay = int(event.text.strip())
            if delay < 0:
                await event.respond("❌ Delay must be a positive number.")
                return
                    
            user_data["data"]["delay"] = delay
            
            numbers = user_data["data"]["numbers"]
            sessions = user_data["data"]["sessions"]
            
            estimated_time = (len(numbers) // len(sessions)) * (delay + 2)
            formatted_time = str(timedelta(seconds=estimated_time))
                
            confirmation = f"""
⚡️ *Ready to Start Invite Process*

📊 Configuration:
• Total Numbers: {len(numbers):,}
• Active Accounts: {len(sessions):,}
• Numbers per Account: {len(numbers) // len(sessions):,}
• Delay: {delay} seconds

⏱ Estimated Time: {formatted_time}
(May be faster due to parallel processing)

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
        if event.sender_id not in self.invite_tasks:
            return
            
        user_data = self.invite_tasks[event.sender_id]
        if user_data["step"] != "confirm":
            return
            
        self.active_invites[event.sender_id] = True
        progress_msg = await event.respond("🚀 *Starting Invitation Process...*", 
                                         parse_mode='markdown')
        
        shared_state = {
            "failed_tasks": [],
            "available_helpers": asyncio.Queue(),
            "task_lock": asyncio.Lock(),
            "progress": {},
            "start_time": datetime.now()
        }

        try:
            await self._process_invitation(event, user_data, shared_state, progress_msg)
        except Exception as e:
            logger.error(f"Error in invitation process: {str(e)}")
            await progress_msg.edit(f"❌ Error during invite process: {str(e)}")
        finally:
            self.active_invites[event.sender_id] = False
            if event.sender_id in self.invite_tasks:
                del self.invite_tasks[event.sender_id]

    async def _process_invitation(self, event, user_data, shared_state, progress_msg):
        try:
            numbers = user_data["data"]["numbers"]
            sessions = user_data["data"]["sessions"]
            delay = user_data["data"]["delay"]
            group_link = user_data["data"]["group_link"]
            
            success = 0
            total = len(sessions)
            session_chunks = [sessions[i:i + self.chunk_size] 
                            for i in range(0, len(sessions), self.chunk_size)]
            
            for chunk_num, session_chunk in enumerate(session_chunks, 1):
                await progress_msg.edit(f"""
🔄 *Processing Chunk {chunk_num}/{len(session_chunks)}*
• Processing {len(session_chunk)} accounts
• Previous success: {success}
• Remaining: {total - success}
""", parse_mode='markdown')
                
                # Setup clients
                clients = []
                shared_state["progress"].clear()
                
                setup_tasks = []
                for session in session_chunk:
                    phone, session_string = session[0], session[1]
                    task = self._setup_client(phone, session_string, group_link, shared_state)
                    setup_tasks.append(task)
                
                await asyncio.gather(*setup_tasks)
                
                for session in session_chunk:
                    phone = session[0]
                    if phone in shared_state["progress"]:
                        client = shared_state["progress"][phone].get("client")
                        if client:
                            clients.append((client, phone))
                
                if clients:
                    # Distribute numbers for this chunk
                    chunk_numbers = numbers[success:success + len(clients)]
                    distribution = self._distribute_numbers(chunk_numbers, clients)
                    
                    # Start invitation tasks
                    invite_tasks = []
                    for client, phone in clients:
                        if phone in distribution:
                            numbers_to_process = distribution[phone]
                            task = self._process_numbers(
                                client, phone, numbers_to_process,
                                group_link, delay, progress_msg, shared_state
                            )
                            invite_tasks.append(asyncio.create_task(task))
                    
                    # Start helper task
                    helper_task = asyncio.create_task(
                        self._help_with_failed_tasks(
                            shared_state, group_link, delay, progress_msg
                        )
                    )
                    
                    await asyncio.gather(*invite_tasks)
                    
                    # Wait for helper to finish remaining tasks
                    while shared_state["failed_tasks"]:
                        await asyncio.sleep(1)
                    
                    helper_task.cancel()
                    
                    # Update total success
                    success += sum(stats["invited"] 
                                 for stats in shared_state["progress"].values())
                
                # Clean up chunk
                for client, _ in clients:
                    try:
                        await client.disconnect()
                    except:
                        pass
                
                # Force garbage collection
                import gc
                gc.collect()
            
            # Generate final report
            await self._generate_final_report(progress_msg, shared_state, total)
            
        except Exception as e:
            logger.error(f"Error in invitation process: {str(e)}")
            raise

    async def _setup_client(self, phone, session_string, group_link, shared_state):
        try:
            client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
            await client.connect()
            
            try:
                await client(JoinChannelRequest(group_link))
                shared_state["progress"][phone] = {
                    "client": client,
                    "invited": 0,
                    "failed": 0,
                    "status": "Active"
                }
                return True
            except Exception as e:
                logger.error(f"Error joining group with {phone}: {str(e)}")
                shared_state["progress"][phone] = {
                    "client": None,
                    "invited": 0,
                    "failed": 0,
                    "status": f"Error: {str(e)}"
                }
                return False
                
        except Exception as e:
            logger.error(f"Error connecting client {phone}: {str(e)}")
            shared_state["progress"][phone] = {
                "client": None,
                "invited": 0,
                "failed": 0,
                "status": f"Error: {str(e)}"
            }
            return False

    async def _process_numbers(self, client, phone, numbers, group, delay, progress_msg, shared_state):
        invited = 0
        failed = 0
        
        try:
            for number in numbers:
                if not self.active_invites.get(progress_msg.chat_id):
                    break

                try:
                    # Import contact
                    contact = InputPhoneContact(
                        client_id=0,
                        phone=number,
                        first_name=f"User{number[-4:]}",
                        last_name=""
                    )
                    
                    try:
                        imported = await client(ImportContactsRequest([contact]))
                        if imported.users:
                            user = imported.users[0]
                            try:
                                await client(InviteToChannelRequest(group, [user.id]))
                                invited += 1
                                
                                # Update progress
                                async with shared_state["task_lock"]:
                                    shared_state["progress"][phone]["invited"] = invited
                                    await self._update_progress_message(
                                        progress_msg,
                                        shared_state["progress"],
                                        shared_state["start_time"]
                                    )

                            except errors.FloodWaitError as e:
                                logger.warning(f"Account {phone} got flood wait for {e.seconds}s")
                                remaining = numbers[numbers.index(number):]
                                async with shared_state["task_lock"]:
                                    shared_state["failed_tasks"].append((phone, remaining))
                                    shared_state["progress"][phone]["status"] = f"Flood ({e.seconds}s)"
                                raise

                            finally:
                                # Delete contact
                                try:
                                    await client(DeleteContactsRequest(imported.users))
                                except:
                                    pass

                    except errors.FloodWaitError:
                        raise
                    except Exception as e:
                        failed += 1
                        logger.error(f"Error inviting {number}: {str(e)}")

                except Exception as e:
                    failed += 1
                    logger.error(f"Error processing {number}: {str(e)}")

                await asyncio.sleep(delay)

            # If all numbers processed, register as helper
            if invited + failed == len(numbers):
                await shared_state["available_helpers"].put((client, phone))
                shared_state["progress"][phone]["status"] = "Helper Available"

            # Update final stats
            async with shared_state["task_lock"]:
                shared_state["progress"][phone]["failed"] = failed
                await self._update_progress_message(
                    progress_msg,
                    shared_state["progress"],
                    shared_state["start_time"]
                )

        except Exception as e:
            logger.error(f"Error in process for {phone}: {str(e)}")
            if not isinstance(e, errors.FloodWaitError):
                remaining = numbers[invited + failed:]
                if remaining:
                    async with shared_state["task_lock"]:
                        shared_state["failed_tasks"].append((phone, remaining))
                        shared_state["progress"][phone]["status"] = f"Error: {str(e)}"

    async def _help_with_failed_tasks(self, shared_state, group, delay, progress_msg):
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
                    
                    for number in numbers:
                        try:
                            contact = InputPhoneContact(
                                client_id=0,
                                phone=number,
                                first_name=f"User{number[-4:]}",
                                last_name=""
                            )
                            imported = await helper_client(ImportContactsRequest([contact]))
                            
                            if imported.users:
                                user = imported.users[0]
                                try:
                                    await helper_client(InviteToChannelRequest(group, [user.id]))
                                    
                                    async with shared_state["task_lock"]:
                                        shared_state["progress"][failed_phone]["invited"] += 1
                                        await self._update_progress_message(
                                            progress_msg,
                                            shared_state["progress"],
                                            shared_state["start_time"]
                                        )
                                        
                                except errors.FloodWaitError as e:
                                    logger.warning(f"Helper {helper_phone} got flood wait")
                                    remaining = numbers[numbers.index(number):]
                                    shared_state["failed_tasks"].append((helper_phone, remaining))
                                    shared_state["progress"][helper_phone]["status"] = f"Flood ({e.seconds}s)"
                                    break
                                    
                            # Delete contact
                            try:
                                await helper_client(DeleteContactsRequest(imported.users))
                            except:
                                pass
                                
                            await asyncio.sleep(delay)
                            
                        except Exception as e:
                            shared_state["progress"][failed_phone]["failed"] += 1
                            logger.error(f"Helper error processing {number}: {str(e)}")
                    
                    # Reset helper status if completed successfully
                    if helper_phone in shared_state["progress"]:
                        shared_state["progress"][helper_phone]["status"] = "Helper Available"
                        
            except Exception as e:
                logger.error(f"Error in helper task: {str(e)}")
                await asyncio.sleep(1)

    async def _update_progress_message(self, message, progress_data, start_time):
        try:
            current_time = datetime.now()
            elapsed = current_time - start_time
            elapsed_str = str(elapsed).split('.')[0]

            text = "🔄 *Invite Progress Report*\n\n"
            
            total_invited = 0
            total_failed = 0
            
            for phone, stats in progress_data.items():
                invited = stats["invited"]
                failed = stats["failed"]
                status = stats.get("status", "Active")
                
                total_invited += invited
                total_failed += failed
                
                text += f"""
📱 `{phone}`:
• Invited: {invited}
• Failed: {failed}
• Status: {status}
"""
            
            text += f"""
📈 *Overall Progress:*
• Total Success: {total_invited}
• Total Failed: {total_failed}
• Success Rate: {self._calculate_success_rate(total_invited, total_failed)}%
• Elapsed Time: {elapsed_str}

🔄 Process is running...
"""
            
            await message.edit(text, parse_mode='markdown')
        except Exception as e:
            logger.error(f"Error updating progress: {str(e)}")

    async def _generate_final_report(self, message, shared_state, total_accounts):
        try:
            end_time = datetime.now()
            duration = end_time - shared_state["start_time"]
            
            final_report = """
✅ *Invite Process Completed*

📊 *Account Details:*\n"""
            
            total_invited = 0
            total_failed = 0
            active_accounts = 0
            
            for phone, stats in shared_state["progress"].items():
                invited = stats["invited"]
                failed = stats["failed"]
                status = stats.get("status", "Completed")
                
                if invited > 0 or failed > 0:
                    active_accounts += 1
                
                total_invited += invited
                total_failed += failed
                
                final_report += f"""
📱 `{phone}`:
• Invited: {invited}
• Failed: {failed}
• Success Rate: {self._calculate_success_rate(invited, failed)}%
• Final Status: {status}
"""
            
            final_report += f"""
📈 *Final Summary:*
• Total Accounts: {total_accounts}
• Active Accounts: {active_accounts}
• Total Success: {total_invited}
• Total Failed: {total_failed}
• Overall Success Rate: {self._calculate_success_rate(total_invited, total_failed)}%
• Duration: {str(duration).split('.')[0]}

✨ Process completed successfully!
"""
            
            await message.edit(final_report, parse_mode='markdown')
        except Exception as e:
            logger.error(f"Error sending final report: {str(e)}")

    async def cancel_invite(self, event):
        try:
            if event.sender_id in self.active_invites:
                self.active_invites[event.sender_id] = False
            
            if event.sender_id in self.invite_tasks:
                del self.invite_tasks[event.sender_id]
            
            await event.edit("""
❌ *Invite Process Cancelled*
All operations have been stopped.
Temporary data has been cleared.
""", parse_mode='markdown')
        except Exception as e:
            logger.error(f"Error cancelling invite: {str(e)}")

    def _validate_group_link(self, link):
        patterns = [
            r'^https?://t\.me/[a-zA-Z0-9_]+$',
            r'^@[a-zA-Z0-9_]+$',
            r'^[a-zA-Z0-9_]+$'
        ]
        return any(re.match(pattern, link) for pattern in patterns)

    def _extract_numbers(self, content):
        numbers = set()
        for line in content.splitlines():
            number = re.sub(r'\D', '', line.strip())
            if number and len(number) >= 10:
                if not number.startswith('+'):
                    number = '+' + number
                numbers.add(number)
        return sorted(list(numbers))

    def _distribute_numbers(self, numbers, clients):
        distribution = {}
        total_numbers = len(numbers)
        total_clients = len(clients)
        
        base_count = total_numbers // total_clients
        extra = total_numbers % total_clients
        
        start = 0
        for i, (_, phone) in enumerate(clients):
            count = base_count + (1 if i < extra else 0)
            end = start + count
            distribution[phone] = numbers[start:end]
            start = end
            
        return distribution

    def _calculate_success_rate(self, success, failed):
        total = success + failed
        if total == 0:
            return 0.0
        return round((success / total) * 100, 2)
