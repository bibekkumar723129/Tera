"""
Main Telegram bot handler for Terabox video downloader
"""
import logging
import os
import re
import asyncio
from pathlib import Path
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
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
        
        # Get user premium status
        user_data = db.get_user(user_id)
        is_premium = user_data.get('is_premium', False) if user_data else False
        
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

Use the menu below to explore features!
"""
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
                
                # Increment download count in database
                db.increment_download_count(user_id)
                
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
                
                # Increment download count in database
                db.increment_download_count(user_id)
                
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
            [InlineKeyboardButton("⭐ Premium", callback_data="premium")]
        ]
        
        if is_premium:
            buttons.insert(1, [InlineKeyboardButton("🔄 Auto-Upload Setup", callback_data="auto_upload")])
        
        return InlineKeyboardMarkup(buttons)
    
    def get_premium_keyboard(self) -> InlineKeyboardMarkup:
        """Create premium menu keyboard"""
        buttons = [
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
        join_date = user_stats.get('join_date', datetime.now())
        
        # Get full user data for premium info
        user_data = db.get_user(user_id)
        is_premium = user_data.get('is_premium', False)
        premium_until = user_data.get('premium_until', None)
        
        # Format join date
        if isinstance(join_date, str):
            join_date = datetime.fromisoformat(join_date)
        days_member = (datetime.now() - join_date).days if join_date else 0
        
        # Create stats message
        stats_msg = f"""📊 **Your Statistics**

👤 User ID: `{user_id}`
📥 Total Downloads: **{downloads_count}**
📅 Member Since: **{join_date.strftime('%d %B %Y') if join_date else 'Unknown'}**
⏳ Days as Member: **{days_member}**

{'⭐ **PREMIUM** Status: **Active**' if is_premium else '⭐ **PREMIUM** Status: **Inactive**'}
{f"✅ Premium Until: **{premium_until.strftime('%d %B %Y')}**" if premium_until and is_premium else ''}

💡 Tip: Upgrade to Premium for Auto-Upload feature!
"""
        
        if update.message:
            await update.message.reply_text(stats_msg, parse_mode='Markdown', reply_markup=self.get_back_keyboard())
        else:
            await update.callback_query.edit_message_text(stats_msg, parse_mode='Markdown', reply_markup=self.get_back_keyboard())
    
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
