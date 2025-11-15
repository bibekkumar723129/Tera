"""
Main Telegram bot handler for Terabox video downloader
"""
import logging
import os
import re
import asyncio
from pathlib import Path
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
from telegram.constants import ChatAction
from typing import Optional, List
from urllib.parse import urlparse

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
        
        welcome_message = f"""
🎬 Welcome to Terabox Video Downloader Bot!

👋 Hello {user.first_name}!

I can help you download videos from Terabox links.

📝 Simply send me a Terabox link like:
• https://terabox.com/s/...
• https://terabox.com/folder/...

⚠️ Features:
✅ Download video files
✅ Automatic format detection
✅ Direct Telegram upload (when size permits)
✅ Download history tracking

🔒 Privacy: Links are processed but not stored.

Use /help for more information.
        """
        await update.message.reply_text(welcome_message)
        return WAITING_FOR_LINK
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command"""
        help_message = """
📚 Help - Available Commands:

/start - Show welcome message
/help - Show this help message
/cancel - Cancel current operation

🔗 How to use:
1. Send me a Terabox link
2. I'll download the video
3. Send it back to you on Telegram

⏱️ Processing time depends on video size.
📊 Max file size: 2GB

⚠️ Note: Very large files may take time to process.
        """
        await update.message.reply_text(help_message)
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle /cancel command"""
        await update.message.reply_text("Operation cancelled. Send another link or use /start")
        return ConversationHandler.END
    
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
        
        # Extract all Terabox links from the message
        links = self.extract_terabox_links(user_message)
        
        # Also check message entities for URL links (in case they're formatted as clickable links)
        if update.message.entities:
            logger.debug(f"Message has {len(update.message.entities)} entities")
            for entity in update.message.entities:
                if entity.type == 'url':
                    # Extract the URL from the message
                    url = user_message[entity.offset:entity.offset + entity.length]
                    logger.debug(f"Found entity URL: {url}")
                    if 'terabox' in url.lower() and url not in links:
                        links.append(url)
        
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

    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors"""
        logger.error(f"Update {update} caused error {context.error}")
        
        if update and update.message:
            await update.message.reply_text(
                "❌ An unexpected error occurred. Please try again."
            )
    
    def setup_handlers(self) -> None:
        """Setup all command and message handlers"""
        # Create conversation handler
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start_command)],
            states={
                WAITING_FOR_LINK: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_link),
                ]
            },
            fallbacks=[
                CommandHandler("cancel", self.cancel_command),
            ]
        )
        
        # Add handlers
        self.app.add_handler(conv_handler)
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_link))
        self.app.add_error_handler(self.error_handler)
    
    async def set_commands(self) -> None:
        """Set bot commands"""
        commands = [
            BotCommand("start", "Start the bot"),
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
