"""
Main Telegram bot handler for Terabox video downloader
"""
import logging
import os
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
from typing import Optional

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
    
    async def handle_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        """Handle incoming Terabox link"""
        user_message = update.message.text.strip()
        user_id = update.message.from_user.id
        
        logger.info(f"User {user_id} sent: {user_message[:50]}...")
        
        # Show typing indicator
        await update.message.chat.send_action(ChatAction.TYPING)
        
        # Validate basic URL structure
        if not user_message.startswith('http'):
            await update.message.reply_text(
                "❌ Please send a valid URL starting with http:// or https://"
            )
            return WAITING_FOR_LINK
        
        # Show processing message
        processing_msg = await update.message.reply_text(
            "⏳ Processing your link...\n"
            "Fetching stream information..."
        )
        
        try:
            # Process the link
            file_path, filename = await process_terabox_link(user_message)
            
            if not file_path:
                await processing_msg.edit_text(
                    "❌ Failed to process the link.\n\n"
                    "Possible reasons:\n"
                    "• Invalid Terabox link\n"
                    "• Link has expired\n"
                    "• Video is no longer available\n"
                    "• API service is unavailable\n\n"
                    "Please try another link."
                )
                return WAITING_FOR_LINK
            
            # Check file size before sending
            file_size = os.path.getsize(file_path)
            file_size_mb = file_size / (1024 * 1024)
            
            if file_size_mb > 2000:  # Telegram API limit is 2000MB for bots
                await processing_msg.edit_text(
                    f"⚠️ File is too large ({file_size_mb:.1f}MB) to send via Telegram.\n\n"
                    f"File saved at: {file_path}"
                )
                return WAITING_FOR_LINK
            
            # Update message to show uploading status
            await processing_msg.edit_text(
                f"✅ Download complete!\n"
                f"📤 Uploading to Telegram ({file_size_mb:.1f}MB)...\n"
                f"This may take a moment..."
            )
            
            await update.message.chat.send_action(ChatAction.UPLOAD_VIDEO)
            
            # Send video to user
            with open(file_path, 'rb') as video_file:
                await update.message.reply_video(
                    video=video_file,
                    caption=f"📹 {filename}\nSize: {file_size_mb:.1f}MB",
                    write_timeout=300
                )
            
            # Clean up the file
            try:
                os.remove(file_path)
                logger.info(f"Cleaned up: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up {file_path}: {e}")
            
            # Increment download count in database
            db.increment_download_count(user_id)
            
            await processing_msg.delete()
            
        except Exception as e:
            logger.error(f"Error processing link: {e}")
            await processing_msg.edit_text(
                f"❌ An error occurred: {str(e)}\n\n"
                f"Please try again or contact support."
            )
        
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
