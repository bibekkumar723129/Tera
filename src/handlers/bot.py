"""
Main Telegram bot handler for Terabox video downloader
"""
import logging
import os
import re
import asyncio
from pathlib import Path
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
)
from telegram.constants import ChatAction
from typing import Optional, List
from urllib.parse import urlparse
from datetime import datetime, timedelta

import config
from src.handlers.download import process_terabox_link
from src.database import db

# Configure logging
logging.basicConfig(
    level=config.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Conversation states
WAITING_FOR_LINK = 1


class TeraboxBot:
    """Telegram bot for downloading Terabox videos"""
    
    def __init__(self, token: str):
        self.token = token
        self.app = None
        self.download_queue = []  # Queue of download requests
        self.processing = {}  # Track currently processing users
    
    def get_queue_priority(self, user_id: int) -> tuple:
        """Get priority for queue (lower = higher priority)"""
        user_data = db.get_user(user_id)
        is_premium = user_data.get('is_premium', False) if user_data else False
        
        # Premium users get priority 0, free users get priority 1
        priority = 0 if is_premium else 1
        timestamp = datetime.utcnow()
        
        return (priority, timestamp, user_id)
    
    def add_to_queue(self, user_id: int, url: str) -> None:
        """Add download request to queue"""
        priority = self.get_queue_priority(user_id)
        self.download_queue.append({
            'priority': priority,
            'user_id': user_id,
            'url': url,
            'added_at': datetime.utcnow()
        })
        # Sort by priority
        self.download_queue.sort(key=lambda x: x['priority'])
    
    def get_processing_delay(self, user_id: int) -> float:
        """Get processing speed multiplier based on premium status"""
        user_data = db.get_user(user_id)
        is_premium = user_data.get('is_premium', False) if user_data else False
        
        if hasattr(config, 'QUEUE_PROCESSING_SPEED'):
            speed_multiplier = config.QUEUE_PROCESSING_SPEED.get('premium', 1.0) \
                if is_premium else config.QUEUE_PROCESSING_SPEED.get('free', 3.0)
        else:
            speed_multiplier = 1.0 if is_premium else 3.0
        
        return speed_multiplier
    
    async def check_quota_and_download(self, user_id: int, url: str, 
                                       context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Check if user can download (quota) and process if allowed"""
        # Check daily quota
        if db.check_quota_exceeded(user_id):
            user_data = db.get_user(user_id)
            is_premium = user_data.get('is_premium', False) if user_data else False
            
            daily_limit = int(os.getenv('PREMIUM_DAILY_DOWNLOADS', 100)) \
                if is_premium else int(os.getenv('FREE_DAILY_DOWNLOADS', 5))
            
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ **Daily Quota Exceeded**\n\n"
                     f"You have reached your daily download limit of {daily_limit}.\n\n"
                     f"Your quota will reset at midnight UTC."
                     f"{'' if is_premium else '\n\n⭐ Upgrade to Premium for 100+ downloads/day!'}"
            )
            return False
        
        # Increment daily quota
        db.increment_daily_downloads(user_id)
        
        # Increment total downloads
        db.increment_download_count(user_id)
        
        return True
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        """Handle /start command"""
        user = update.message.from_user
        user_id = user.id
        
        # Add user to database
        db.add_user(
            user_id=user_id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username
        )
        
        # Check and validate premium status (auto-downgrade if expired)
        is_premium = db.check_and_update_premium_status(user_id)
        
        # Get user premium status and expiry info
        user_data = db.get_user(user_id)
        expiry_info = db.get_time_until_premium_expiry(user_id)
        
        welcome_message = f"""👋 **Welcome to Terabox Downloader Bot!**

Hi {user.first_name}! 

🎥 I can download videos from Terabox links for you.

📝 **How to use:**
1. Send me a Terabox link
2. I'll download it
3. Get your video back instantly

⭐ **Premium Benefits:**
• 🔄 Auto-upload videos to your channel
• 📊 Priority support
• ⚡ Faster processing
"""
        
        # Add premium status to message
        if is_premium:
            premium_badge = f"✅ **PREMIUM ACTIVE** - Expires in {expiry_info.get('expires_in_days', 0)} days"
            welcome_message += f"\n{premium_badge}"
            if expiry_info.get('expires_soon'):
                welcome_message += "\n⚠️ Your premium is expiring soon!"
        
        welcome_message += "\n\nUse the menu below to explore features!"
        
        await update.message.reply_text(welcome_message, parse_mode='Markdown', reply_markup=self.get_main_keyboard(is_premium))
        return WAITING_FOR_LINK
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command"""
        help_message = """❓ **Help - Available Commands:**

**/start** - Show welcome and main menu
**/stats** - View your download statistics  
**/help** - Show this help message
**/cancel** - Cancel current operation

🔗 **How to Use:**
1. Send me a Terabox link
2. I'll download the video
3. You get it back instantly

📊 **Link Format Examples:**
• https://terabox.com/s/...
• https://terabox.com/folder/...
• https://1024terabox.com/s/...
• https://teraboxlink.com/s/...

⭐ **Premium Features:**
• 🔄 Auto-upload to your channel
• 📊 Priority support
• ⚡ Faster processing

⏱️ Processing time depends on video size.
📥 Max file size: 2GB
"""
        await update.message.reply_text(help_message, parse_mode='Markdown', reply_markup=self.get_back_keyboard())
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle /cancel command"""
        await update.message.reply_text("❌ Operation cancelled. Send another link or use /start", reply_markup=self.get_back_keyboard())
        return ConversationHandler.END
    
    async def stats_command_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /stats command"""
        await self.stats_command(update, context)
    
    def extract_terabox_links(self, text: str) -> List[str]:
        """Extract all Terabox links from text
        Handles:
        - Multiple links in one message
        - Links mixed with other text
        - Different Terabox URL formats (terabox.com, 1024terabox.com, teraboxlink.com, etc.)
        - Both /s/ (share) and /folder/ links
        - Emojis and special characters before/after links
        """
        # More flexible pattern that matches any terabox variant domain
        # Matches: terabox.com, 1024terabox.com, teraboxlink.com, etc.
        # Pattern allows for any characters (including emojis) before the URL
        terabox_pattern = r'https?://[a-zA-Z0-9.]*terabox[a-zA-Z0-9.]*\.com/(?:s|folder)/[a-zA-Z0-9_-]+'
        
        links = re.findall(terabox_pattern, text, re.IGNORECASE)
        
        logger.debug(f"Regex extraction from text: '{text[:100]}...' found {len(links)} link(s)")
        
        # Remove duplicates while preserving order
        seen = set()
        unique_links = []
        for link in links:
            if link not in seen:
                seen.add(link)
                unique_links.append(link)
        
        logger.debug(f"Final unique links: {unique_links}")
        return unique_links
    
    async def handle_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        """Handle incoming message with Terabox links"""
        user_message = update.message.text.strip()
        user_id = update.message.from_user.id
        
        logger.info(f"User {user_id} sent: {user_message[:50]}...")
        logger.debug(f"Full message text: {repr(user_message)}")
        
        # Show typing indicator
        await update.message.chat.send_action(ChatAction.TYPING)
        
        # Extract all Terabox links from the message using regex (most reliable method)
        links = self.extract_terabox_links(user_message)
        logger.debug(f"Extracted {len(links)} link(s) using regex: {links}")
        
        if not links:
            await update.message.reply_text(
                "❌ No Terabox links found in your message.\n\n"
                "Please send a valid Terabox URL like:\n"
                "https://terabox.com/s/..."
            )
            return WAITING_FOR_LINK
        
        logger.info(f"Extracted {len(links)} link(s) from message")
        
        # Check quota before processing any links
        if not await self.check_quota_and_download(user_id, links[0], context):
            return WAITING_FOR_LINK
        
        # Process links one by one
        for link in links:
            try:
                # Show processing message
                processing_msg = await update.message.reply_text(
                    "⏳ **Processing your link...**\n\n"
                    f"🔗 {link[:50]}...\n\n"
                    "Downloading and preparing video..."
                )
                
                logger.info(f"Processing link: {link}")
                
                # Process the link
                try:
                    file_path, filename = await process_terabox_link(link)
                except RuntimeError as re_err:
                    # Handle specific errors
                    if 'anti-bot' in str(re_err):
                        logger.warning(f"Anti-bot detected for link: {link}")
                        await processing_msg.edit_text(
                            "❌ **Download Failed**\n\n"
                            "⚠️ The API is protected with reCAPTCHA.\n\n"
                            "Please try again later."
                        )
                        continue
                    else:
                        logger.error(f"Runtime error during extraction: {re_err}")
                        await processing_msg.edit_text(
                            f"❌ **Download Failed**\n\n"
                            f"Error: {str(re_err)}\n\n"
                            "Please try again or use a different link."
                        )
                        continue
                
                if not file_path:
                    logger.warning(f"Failed to process link: {link}")
                    await processing_msg.edit_text(
                        "❌ **Download Failed**\n\n"
                        "Could not extract video from the link.\n\n"
                        "Please check if the link is valid and try again."
                    )
                    continue
                
                # Check file size before sending
                file_size = os.path.getsize(file_path)
                file_size_mb = file_size / (1024 * 1024)
                
                if file_size_mb > 2000:  # Telegram API limit is 2000MB for bots
                    logger.warning(f"File too large: {file_size_mb:.1f}MB")
                    try:
                        os.remove(file_path)
                    except:
                        pass
                    await processing_msg.edit_text(
                        f"❌ **File Too Large**\n\n"
                        f"📊 Size: {file_size_mb:.1f}MB\n\n"
                        f"Telegram limit: 2000MB\n"
                        "Unfortunately, this file exceeds Telegram's limits."
                    )
                    continue
                
                # Update message to show upload stage
                await processing_msg.edit_text(
                    "📤 **Uploading to Telegram...**\n\n"
                    f"📹 {filename}\n"
                    f"📊 Size: {file_size_mb:.1f}MB\n\n"
                    "This may take a few moments..."
                )
                
                await update.message.chat.send_action(ChatAction.UPLOAD_VIDEO)
                
                # Send video to user
                with open(file_path, 'rb') as video_file:
                    await update.message.reply_video(
                        video=video_file,
                        caption=f"📹 {filename}\n📊 Size: {file_size_mb:.1f}MB",
                        write_timeout=300
                    )
                
                # Send to store channel if configured
                if config.STORE_CHANNEL:
                    try:
                        with open(file_path, 'rb') as video_file:
                            await self.app.bot.send_video(
                                chat_id=config.STORE_CHANNEL,
                                video=video_file,
                                caption=f"📹 {filename}\nUser: {update.message.from_user.mention_html()}\nSize: {file_size_mb:.1f}MB",
                                parse_mode='HTML',
                                write_timeout=300
                            )
                        logger.info(f"Sent to store channel: {filename}")
                    except Exception as e:
                        logger.warning(f"Failed to send to store channel: {e}")
                
                # Update message to show completion
                await processing_msg.edit_text(
                    "✅ **Download Complete**\n\n"
                    f"📹 {filename}\n"
                    f"📊 Size: {file_size_mb:.1f}MB\n\n"
                    "✔️ Video uploaded and archived in store channel!"
                )
                
                # Clean up the file
                try:
                    os.remove(file_path)
                    logger.info(f"Cleaned up: {file_path}")
                except Exception as e:
                    logger.warning(f"Failed to clean up {file_path}: {e}")
                
                # Add to download history (premium users get permanent history)
                db.add_to_history(user_id, filename, file_size, link)
                
            except Exception as e:
                logger.error(f"Error processing link {link}: {e}")
                try:
                    await processing_msg.edit_text(
                        f"❌ **An Error Occurred**\n\n"
                        f"Error: {str(e)}\n\n"
                        "Please try again."
                    )
                except:
                    pass
        
        return WAITING_FOR_LINK

    
    async def handle_link_from_caption(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        """Handle Terabox links from media captions (photo, document, video, etc.)"""
        # Extract caption text from media
        caption_text = None
        if update.message.caption:
            caption_text = update.message.caption.strip()
        elif update.message.photo:
            # Photo with caption
            caption_text = update.message.caption
        elif update.message.document:
            # Document with caption
            caption_text = update.message.caption
        elif update.message.video:
            # Video with caption
            caption_text = update.message.caption
        
        if not caption_text:
            logger.debug(f"Media message without caption detected from user {update.message.from_user.id}")
            await update.message.reply_text(
                "❌ No caption found in your media.\n\n"
                "Please send media with a caption containing a Terabox link like:\n"
                "https://terabox.com/s/..."
            )
            return WAITING_FOR_LINK
        
        logger.info(f"User {update.message.from_user.id} sent media with caption: {caption_text[:50]}...")
        
        # Process the caption text as if it were a regular message
        # We need to manually call handle_link logic with caption text
        user_id = update.message.from_user.id
        logger.debug(f"Full caption text: {repr(caption_text)}")
        
        # Show typing indicator
        await update.message.chat.send_action(ChatAction.TYPING)
        
        # Extract all Terabox links from the caption using regex
        links = self.extract_terabox_links(caption_text)
        logger.debug(f"Extracted {len(links)} link(s) from caption: {links}")
        
        if not links:
            await update.message.reply_text(
                "❌ No Terabox links found in the caption.\n\n"
                "Please send media with a caption containing a valid Terabox URL like:\n"
                "https://terabox.com/s/..."
            )
            return WAITING_FOR_LINK
        
        logger.info(f"Extracted {len(links)} link(s) from caption")
        
        # Check quota before processing any links
        if not await self.check_quota_and_download(user_id, links[0], context):
            return WAITING_FOR_LINK
        
        # Process each link (same logic as handle_link)
        for link in links:
            try:
                # Show processing message
                processing_msg = await update.message.reply_text(
                    "⏳ **Processing your link...**\n\n"
                    f"🔗 {link[:50]}...\n\n"
                    "Downloading and preparing video..."
                )
                
                logger.info(f"Processing link from caption: {link}")
                
                # Process the link
                try:
                    file_path, filename = await process_terabox_link(link)
                except RuntimeError as re_err:
                    # Handle specific errors
                    if 'anti-bot' in str(re_err):
                        logger.warning(f"Anti-bot detected for link: {link}")
                        await processing_msg.edit_text(
                            "❌ **Download Failed**\n\n"
                            "⚠️ The API is protected with reCAPTCHA.\n\n"
                            "Please try again later."
                        )
                        continue
                    else:
                        logger.error(f"Runtime error during extraction: {re_err}")
                        await processing_msg.edit_text(
                            f"❌ **Download Failed**\n\n"
                            f"Error: {str(re_err)}\n\n"
                            "Please try again or use a different link."
                        )
                        continue
                
                if not file_path:
                    logger.warning(f"Failed to process link: {link}")
                    await processing_msg.edit_text(
                        "❌ **Download Failed**\n\n"
                        "Could not extract video from the link.\n\n"
                        "Please check if the link is valid and try again."
                    )
                    continue
                
                # Check file size before sending
                file_size = os.path.getsize(file_path)
                file_size_mb = file_size / (1024 * 1024)
                
                if file_size_mb > 2000:  # Telegram API limit is 2000MB for bots
                    logger.warning(f"File too large: {file_size_mb:.1f}MB")
                    try:
                        os.remove(file_path)
                    except:
                        pass
                    await processing_msg.edit_text(
                        f"❌ **File Too Large**\n\n"
                        f"📊 Size: {file_size_mb:.1f}MB\n\n"
                        f"Telegram limit: 2000MB\n"
                        "Unfortunately, this file exceeds Telegram's limits."
                    )
                    continue
                
                # Update message to show upload stage
                await processing_msg.edit_text(
                    "📤 **Uploading to Telegram...**\n\n"
                    f"📹 {filename}\n"
                    f"📊 Size: {file_size_mb:.1f}MB\n\n"
                    "This may take a few moments..."
                )
                
                await update.message.chat.send_action(ChatAction.UPLOAD_VIDEO)
                
                # Send video to user
                with open(file_path, 'rb') as video_file:
                    await update.message.reply_video(
                        video=video_file,
                        caption=f"📹 {filename}\n📊 Size: {file_size_mb:.1f}MB",
                        write_timeout=300
                    )
                
                # Send to store channel if configured
                if config.STORE_CHANNEL:
                    try:
                        with open(file_path, 'rb') as video_file:
                            await self.app.bot.send_video(
                                chat_id=config.STORE_CHANNEL,
                                video=video_file,
                                caption=f"📹 {filename}\nUser: {update.message.from_user.mention_html()}\nSize: {file_size_mb:.1f}MB",
                                parse_mode='HTML',
                                write_timeout=300
                            )
                        logger.info(f"Sent to store channel: {filename}")
                    except Exception as e:
                        logger.warning(f"Failed to send to store channel: {e}")
                
                # Send to premium user's auto-upload channel if enabled
                auto_upload_channel = db.get_auto_upload_channel(user_id)
                if auto_upload_channel:
                    try:
                        with open(file_path, 'rb') as video_file:
                            await self.app.bot.send_video(
                                chat_id=auto_upload_channel,
                                video=video_file,
                                caption=f"📹 {filename}\n📊 Size: {file_size_mb:.1f}MB\n\n✅ Auto-uploaded via bot",
                                write_timeout=300
                            )
                        logger.info(f"Auto-uploaded to premium user's channel {auto_upload_channel}: {filename}")
                    except Exception as e:
                        logger.warning(f"Failed to auto-upload to {auto_upload_channel}: {e}")
                        await update.message.reply_text(f"⚠️ Failed to auto-upload: {str(e)[:100]}")
                
                # Update message to show completion
                await processing_msg.edit_text(
                    "✅ **Download Complete**\n\n"
                    f"📹 {filename}\n"
                    f"📊 Size: {file_size_mb:.1f}MB\n\n"
                    f"✔️ Video {'auto-uploaded to your channel and ' if auto_upload_channel else ''}archived!"
                )
                
                # Clean up the file
                try:
                    os.remove(file_path)
                    logger.info(f"Cleaned up: {file_path}")
                except Exception as e:
                    logger.warning(f"Failed to clean up {file_path}: {e}")
                
                # Add to download history (premium users get permanent history)
                db.add_to_history(user_id, filename, file_size, link)
                
            except Exception as e:
                logger.error(f"Error processing link {link} from caption: {e}")
                try:
                    await processing_msg.edit_text(
                        f"❌ **An Error Occurred**\n\n"
                        f"Error: {str(e)}\n\n"
                        "Please try again."
                    )
                except:
                    pass
        
        return WAITING_FOR_LINK

    # ============= UI METHODS (INLINE KEYBOARDS) =============
    
    def get_main_keyboard(self, is_premium: bool = False) -> InlineKeyboardMarkup:
        """Create main menu keyboard"""
        buttons = [
            [InlineKeyboardButton("📊 Stats", callback_data="stats"),
             InlineKeyboardButton("❓ Help", callback_data="help")],
            [InlineKeyboardButton("🎬 Quality", callback_data="quality"),
             InlineKeyboardButton("✏️ Rename", callback_data="rename")],
            [InlineKeyboardButton("⭐ Premium", callback_data="premium")]
        ]
        
        if is_premium:
            buttons.insert(2, [InlineKeyboardButton("🔄 Auto-Upload Setup", callback_data="auto_upload")])
        
        return InlineKeyboardMarkup(buttons)
    
    def get_premium_keyboard(self) -> InlineKeyboardMarkup:
        """Create premium menu keyboard"""
        buttons = [
            [InlineKeyboardButton("💸 Get Premium 💸", callback_data="get_premium_qr")],
            [InlineKeyboardButton("✅ Activate Premium (30 days)", callback_data="activate_premium")],
            [InlineKeyboardButton("🔄 Auto-Upload Setup", callback_data="auto_upload")],
            [InlineKeyboardButton("⬅️ Back", callback_data="back_main")]
        ]
        return InlineKeyboardMarkup(buttons)
    
    def get_back_keyboard(self) -> InlineKeyboardMarkup:
        """Create back button keyboard"""
        buttons = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_main")]]
        return InlineKeyboardMarkup(buttons)
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /stats command or stats callback"""
        user_id = update.message.from_user.id if update.message else update.callback_query.from_user.id
        
        # Get user stats from database
        user_stats = db.get_user_stats(user_id)
        downloads_count = user_stats.get('downloads_count', 0)
        downloads_today = user_stats.get('downloads_today', 0)
        join_date = user_stats.get('joined_at', datetime.now())
        
        # Get full user data for premium info
        user_data = db.get_user(user_id)
        is_premium = user_data.get('is_premium', False)
        premium_until = user_data.get('premium_until', None)
        
        # Format join date
        if isinstance(join_date, str):
            join_date = datetime.fromisoformat(join_date)
        days_member = (datetime.now() - join_date).days if join_date else 0
        
        # Create stats message with premium badge
        premium_badge = "⭐ **PREMIUM USER** ⭐" if is_premium else "🆓 **FREE USER**"
        
        stats_msg = f"""{premium_badge}

📊 **Your Statistics**

👤 User ID: `{user_id}`
📥 Total Downloads: **{downloads_count}**
📊 Today's Downloads: **{downloads_today}**
📅 Member Since: **{join_date.strftime('%d %B %Y') if join_date else 'Unknown'}**
⏳ Days as Member: **{days_member}**

{'✅ Premium Until: **' + premium_until.strftime('%d %B %Y') + '**' if premium_until and is_premium else ''}

{'⚡ Priority processing enabled' if is_premium else '💡 Tip: Upgrade to Premium for priority processing!'}
"""
        
        keyboard = [[InlineKeyboardButton("🏆 TOP USERS", callback_data="top_users")],
                    [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_main")]]
        
        if update.message:
            await update.message.reply_text(stats_msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.callback_query.edit_message_text(stats_msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def top_users_display(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Display top premium users leaderboard"""
        query = update.callback_query
        
        top_users = db.get_premium_users_sorted(limit=10, sort_by='premium_days_purchased')
        
        if not top_users:
            top_msg = "🏆 **TOP PREMIUM USERS**\n\nNo premium users yet. Be the first!"
        else:
            top_msg = "🏆 **TOP PREMIUM USERS**\n\n"
            for idx, user in enumerate(top_users, 1):
                user_id = user.get('user_id', 'N/A')
                name = user.get('first_name', 'Unknown')
                days = user.get('premium_days_purchased', 0)
                
                medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}️⃣"
                top_msg += f"{medal} **{name}** - {days} premium days\n"
        
        keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_main")]]
        await query.edit_message_text(top_msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def quality_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show quality selection menu"""
        query = update.callback_query
        user_id = query.from_user.id
        
        quality_msg = """🎬 **Select Your Preferred Video Quality**

Higher quality = larger file size
Lower quality = faster download

Current Preference: **{}**
""".format(db.get_quality_preference(user_id).upper())
        
        keyboard = [
            [InlineKeyboardButton("📺 Auto (Recommended)", callback_data="quality_auto"),
             InlineKeyboardButton("🎬 1080p (Best)", callback_data="quality_1080p")],
            [InlineKeyboardButton("🎞️ 720p", callback_data="quality_720p"),
             InlineKeyboardButton("📹 480p", callback_data="quality_480p")],
            [InlineKeyboardButton("🎥 360p (Fastest)", callback_data="quality_360p")],
            [InlineKeyboardButton("◀️ Back", callback_data="back_main")]
        ]
        
        await query.edit_message_text(quality_msg, parse_mode='Markdown',
                                      reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def rename_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show auto-rename configuration"""
        query = update.callback_query
        user_id = query.from_user.id
        
        pattern = db.get_auto_rename_pattern(user_id)
        current_pattern = pattern if pattern else "Not configured"
        
        rename_msg = f"""✏️ **File Auto-Rename Settings**

Auto-rename allows you to customize downloaded filenames automatically.

Current Pattern: **{current_pattern}**

Available placeholders:
• `{{date}}` - Current date (YYYY-MM-DD)
• `{{time}}` - Current time (HH-MM-SS)
• `{{counter}}` - Sequential number
• `{{filename}}` - Original filename

Example: `Downloaded_{{date}}_{{filename}}`

Send /setrename <pattern> to configure.
"""
        
        keyboard = [
            [InlineKeyboardButton("❌ Clear Pattern", callback_data="rename_clear")],
            [InlineKeyboardButton("◀️ Back", callback_data="back_main")]
        ]
        
        await query.edit_message_text(rename_msg, parse_mode='Markdown',
                                      reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def get_premium_qr(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show QR code for premium payment"""
        query = update.callback_query
        user_id = query.from_user.id
        
        # Premium pricing information
        qr_code_url = "https://i.ibb.co/hFjZ6CWD/photo-2025-08-10-02-24-51-7536777335068950548.jpg"
        
        premium_pricing_text = """💎 **PREMIUM PRICING & PAYMENT**

**Available Plans:**

🥉 **Basic Premium** - $4.99/month
   • Priority processing
   • 100 downloads/day
   • Auto-upload feature

🥈 **Pro Premium** - $9.99/month
   • Everything in Basic +
   • 500 downloads/day
   • Bulk download support
   • Custom file naming

🥇 **VIP Premium** - $19.99/month
   • Everything in Pro +
   • Unlimited downloads
   • Direct support
   • Ad-free experience

━━━━━━━━━━━━━━━━━━━━━

📸 **How to Purchase:**

1️⃣ Scan the QR code below with your payment app
2️⃣ Complete the payment
3️⃣ Take a screenshot of confirmation
4️⃣ Click "Send Screenshot to Admin" button
5️⃣ Admin will verify and activate your premium

🔐 All payments are secure and verified!
"""
        
        keyboard = [
            [InlineKeyboardButton("📸 Send Screenshot to Admin", callback_data="send_payment_screenshot")],
            [InlineKeyboardButton("⬅️ Back to Premium", callback_data="premium")]
        ]
        
        # Send QR code image
        try:
            await query.edit_message_media(
                media=InputMediaPhoto(
                    media=qr_code_url,
                    caption=premium_pricing_text,
                    parse_mode='Markdown'
                ),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.warning(f"Could not edit media, sending as new message: {e}")
            # Fallback: send message with text and photo separately
            await query.edit_message_text(premium_pricing_text, parse_mode='Markdown')
            await query.message.reply_photo(
                photo=qr_code_url,
                caption="💳 **Scan this QR code to pay**",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    async def send_payment_screenshot_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle screenshot submission for payment verification"""
        query = update.callback_query
        user_id = query.from_user.id
        user_name = query.from_user.first_name
        
        # Set context to wait for screenshot
        context.user_data['waiting_for_screenshot'] = True
        context.user_data['screenshot_user_id'] = user_id
        context.user_data['screenshot_user_name'] = user_name
        
        instruction_msg = """📸 **Send Payment Screenshot**

Please take a screenshot of your payment confirmation and send it here.

The screenshot should clearly show:
✅ Payment amount
✅ Transaction ID
✅ Timestamp/Date
✅ Payment status (Completed/Confirmed)

Once received, I'll forward it to the admin for verification.
⏳ Verification usually takes 5-10 minutes.

Send the screenshot below (you can also send multiple images):
"""
        
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="premium")]]
        
        await query.edit_message_text(instruction_msg, parse_mode='Markdown',
                                      reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def premium_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle premium menu"""
        query = update.callback_query
        user_id = query.from_user.id
        
        # Get user premium status
        user_data = db.get_user(user_id)
        is_premium = user_data.get('is_premium', False)
        premium_until = user_data.get('premium_until', None)
        
        premium_msg = f"""⭐ **PREMIUM FEATURES**

Current Status: {'✅ Active' if is_premium else '❌ Inactive'}
{f"Valid Until: {premium_until.strftime('%d %B %Y')}" if is_premium and premium_until else ''}

🎁 **Premium Benefits:**
• 🔄 Auto-Upload to Your Channel
• 📊 Priority Support
• ⚡ Faster Processing
• 🎯 Bulk Download Support

💰 Price: Free for first 30 days trial!
"""
        
        await query.edit_message_text(premium_msg, parse_mode='Markdown', reply_markup=self.get_premium_keyboard())
    
    async def activate_premium(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle premium activation"""
        query = update.callback_query
        user_id = query.from_user.id
        
        # Set premium for 30 days
        premium_until = datetime.now() + timedelta(days=30)
        db.set_premium(user_id, True, premium_until)
        
        activate_msg = """✅ **Premium Activated!**

🎉 You now have 30 days of Premium access!

🔄 Auto-Upload Feature is ready to use.
Visit the Premium menu to set up your channel.

Thank you for supporting us! 💖
"""
        
        await query.edit_message_text(activate_msg, parse_mode='Markdown', reply_markup=self.get_back_keyboard())
    
    async def setup_auto_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle auto-upload setup"""
        query = update.callback_query
        user_id = query.from_user.id
        
        # Check if user is premium
        user_data = db.get_user(user_id)
        is_premium = user_data.get('is_premium', False)
        
        if not is_premium:
            await query.edit_message_text(
                "❌ **Auto-Upload is a Premium Feature**\n\n"
                "Please activate Premium first to use this feature.",
                parse_mode='Markdown',
                reply_markup=self.get_back_keyboard()
            )
            return
        
        # Ask for channel ID
        setup_msg = """🔄 **Auto-Upload Setup**

Please send me your channel ID where you want videos to be auto-uploaded.

You can find your channel ID by:
1. Open your channel
2. Click on channel name
3. Copy the number from URL: https://t.me/c/YOUR_CHANNEL_ID

Format: Send as -100xxxxxxxxxx or just the number
"""
        
        context.user_data['awaiting_channel_id'] = True
        await query.edit_message_text(setup_msg, parse_mode='Markdown', reply_markup=self.get_back_keyboard())
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle all button callbacks"""
        query = update.callback_query
        await query.answer()
        
        callback_data = query.data
        
        if callback_data == "stats":
            await self.stats_command(update, context)
        elif callback_data == "help":
            help_message = """❓ **Help - How to Use**

1️⃣ **Send Terabox Link**
   Send me any Terabox link (can be mixed with other text)

2️⃣ **I'll Download It**
   Processing video...

3️⃣ **Get Your Video**
   Video will be sent to you on Telegram

📝 **Supported Link Types:**
   • Share links (/s/)
   • Folder links (/folder/)
   • All Terabox domains

⭐ **Premium Features:**
   • Auto-upload videos to your channel
   • Get started with /premium command

🔧 **Commands:**
   /start - Main menu
   /stats - Your statistics
   /premium - Premium features
   /cancel - Cancel operation
"""
            await query.edit_message_text(help_message, parse_mode='Markdown', reply_markup=self.get_back_keyboard())
        elif callback_data == "premium":
            await self.premium_menu(update, context)
        elif callback_data == "activate_premium":
            await self.activate_premium(update, context)
        elif callback_data == "auto_upload":
            await self.setup_auto_upload(update, context)
        elif callback_data == "quality":
            await self.quality_menu(update, context)
        elif callback_data.startswith("quality_"):
            user_id = query.from_user.id
            quality = callback_data.replace("quality_", "")
            db.set_quality_preference(user_id, quality)
            await query.answer(f"✅ Quality set to {quality.upper()}")
            await self.quality_menu(update, context)
        elif callback_data == "rename":
            await self.rename_menu(update, context)
        elif callback_data == "rename_clear":
            user_id = query.from_user.id
            db.set_auto_rename_pattern(user_id, None)
            await query.answer("✅ Rename pattern cleared")
            await self.rename_menu(update, context)
        elif callback_data == "top_users":
            await self.top_users_display(update, context)
        elif callback_data == "get_premium_qr":
            await self.get_premium_qr(update, context)
        elif callback_data == "send_payment_screenshot":
            await self.send_payment_screenshot_handler(update, context)
        elif callback_data == "back_main":
            user_id = query.from_user.id
            user_data = db.get_user(user_id)
            is_premium = user_data.get('is_premium', False)
            
            main_msg = """👋 **Welcome to Terabox Downloader**

🎥 Send me a Terabox link and I'll download the video for you!

Use the buttons below to access features:
"""
            await query.edit_message_text(main_msg, parse_mode='Markdown', reply_markup=self.get_main_keyboard(is_premium))

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors"""
        logger.error(f"Update {update} caused error {context.error}")
        
        # Only respond to user messages, not channel posts or other updates
        if update and update.message:
            try:
                await update.message.reply_text(
                    "❌ An unexpected error occurred. Please try again."
                )
            except Exception as e:
                logger.error(f"Failed to send error message: {e}")
    
    
    async def handle_payment_screenshot(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle payment screenshot submission"""
        if not context.user_data.get('waiting_for_screenshot'):
            return
        
        user_id = update.message.from_user.id
        user_name = update.message.from_user.first_name
        
        if update.message.photo:
            # Get the largest photo
            photo = update.message.photo[-1]
            file_id = photo.file_id
            
            # Notify user
            await update.message.reply_text(
                "✅ **Screenshot Received!**\n\n"
                "📧 Your screenshot has been sent to the admin for verification.\n\n"
                "⏳ Verification usually takes 5-10 minutes.\n"
                "You'll receive a notification once your premium is activated!\n\n"
                "Thank you! 🙏",
                parse_mode='Markdown'
            )
            
            # Send to admin (if admin ID is configured)
            admin_id = int(os.getenv('ADMIN_ID', 0))
            if admin_id:
                try:
                    admin_msg = f"""
📸 **New Payment Screenshot**

👤 User ID: `{user_id}`
👤 User Name: {user_name}

⏳ Please verify and activate premium access.

/addpremium {user_id} 30
"""
                    await context.bot.send_photo(
                        chat_id=admin_id,
                        photo=file_id,
                        caption=admin_msg,
                        parse_mode='Markdown'
                    )
                    logger.info(f"Screenshot from user {user_id} sent to admin")
                except Exception as e:
                    logger.error(f"Failed to send screenshot to admin: {e}")
            
            # Clear the flag
            context.user_data['waiting_for_screenshot'] = False
        else:
            await update.message.reply_text(
                "❌ Please send a photo/image of your payment screenshot.\n\n"
                "You can send multiple images if needed."
            )
    
    def setup_handlers(self) -> None:
        """Setup all command and message handlers"""
        # Create conversation handler
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start_command)],
            states={
                WAITING_FOR_LINK: [
                    # Handle text messages and media with captions
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_link),
                    MessageHandler(filters.CAPTION, self.handle_link_from_caption),
                ]
            },
            fallbacks=[
                CommandHandler("cancel", self.cancel_command),
            ]
        )
        
        # Add handlers
        self.app.add_handler(conv_handler)
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(CommandHandler("stats", self.stats_command_handler))
        self.app.add_handler(CallbackQueryHandler(self.button_callback))
        
        # Photo handler for payment screenshots (high priority, before text handler)
        self.app.add_handler(MessageHandler(filters.PHOTO, self.handle_payment_screenshot))
        
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_link))
        # Also handle captions from media (photo, document, video, etc.) outside conversation
        self.app.add_handler(MessageHandler(filters.CAPTION, self.handle_link_from_caption))
        self.app.add_error_handler(self.error_handler)
    
    async def set_commands(self) -> None:
        """Set bot commands"""
        commands = [
            BotCommand("start", "Start the bot and show main menu"),
            BotCommand("stats", "Show your download statistics"),
            BotCommand("help", "Show help message"),
            BotCommand("cancel", "Cancel current operation"),
        ]
        await self.app.bot.set_my_commands(commands)
    
    async def start(self) -> None:
        """Start the bot"""
        self.app = Application.builder().token(self.token).build()
        
        self.setup_handlers()
        await self.set_commands()
        
        logger.info("Starting bot...")
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        
        logger.info("Bot is running!")
    
    async def stop(self) -> None:
        """Stop the bot"""
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
            logger.info("Bot stopped")
    
    async def notify_restart(self) -> None:
        """Notify all users and admin about bot restart"""
        if not self.app:
            return
        
        try:
            logger.info("Sending restart notifications to users...")
            
            # Get all user IDs from database
            user_ids = db.get_all_user_ids()
            
            restart_message = """
✅ **Bot Restarted**

The Terabox Video Downloader Bot has been restarted and is now online!

🚀 Ready to process your download requests.

Use /start to get started!
            """
            
            # Send to all users
            sent_count = 0
            for user_id in user_ids:
                try:
                    await self.app.bot.send_message(
                        chat_id=user_id,
                        text=restart_message,
                        parse_mode='Markdown'
                    )
                    sent_count += 1
                except Exception as e:
                    logger.debug(f"Failed to send restart message to {user_id}: {e}")
            
            logger.info(f"Restart notification sent to {sent_count} users")
            
            # Send to admin if configured
            if config.ADMIN_ID:
                try:
                    admin_message = f"""
✅ **Bot Restarted**

The Terabox Video Downloader Bot has been restarted successfully!

📊 **Stats:**
• Total users: {db.get_total_users()}
• Notifications sent: {sent_count}

🚀 Bot is now online and ready!
                    """
                    await self.app.bot.send_message(
                        chat_id=int(config.ADMIN_ID),
                        text=admin_message,
                        parse_mode='Markdown'
                    )
                    logger.info(f"Restart notification sent to admin {config.ADMIN_ID}")
                except Exception as e:
                    logger.error(f"Failed to send restart message to admin: {e}")
        except Exception as e:
            logger.error(f"Error sending restart notifications: {e}")


def create_bot(token: str) -> TeraboxBot:
    """Factory function to create bot instance"""
    return TeraboxBot(token)
