import os
import asyncio
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telethon import TelegramClient, events
from telethon.tl.functions.channels import JoinChannelRequest

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
API_ID = 30158256
API_HASH = '547889500d1e8399c3da0a8ecff5f461'
BOT_TOKEN = '8468878569:AAGOCTKXZdx7Ut8jAkS38qwtSo0h_ZMuGoA'

# Hardcoded Channels for automatic forwarding
SOURCE_CHANNEL_ID = -1001728487830  # @Quotex_SuperBot
DEST_CHANNEL_ID = -1003722624508    # @twtnwmenrn

# Conversation states
PHONE, OTP = range(2)

# User data storage
user_sessions = {}

async def start_forwarding(client, user_id):
    """Sets up the automatic forwarding handler for a client."""
    
    # Try to join the source channel to ensure the account can "see" the messages
    try:
        await client(JoinChannelRequest(SOURCE_CHANNEL_ID))
    except Exception as e:
        logger.warning(f"Failed to join channel {SOURCE_CHANNEL_ID}: {e}")

    @client.on(events.NewMessage(chats=SOURCE_CHANNEL_ID))
    async def handler(event):
        # Immediate forwarding without any logging or extra checks in the critical path
        try:
            await client.send_message(DEST_CHANNEL_ID, event.message)
        except Exception:
            pass

    # Background task for connectivity (non-blocking)
    async def keep_alive():
        while True:
            try:
                if not client.is_connected():
                    await client.connect()
                
                # Ensure we are authorized and active
                if await client.is_user_authorized():
                    # Explicitly set status to online every cycle
                    from telethon.tl.functions.account import UpdateStatusRequest
                    await client(UpdateStatusRequest(offline=False))
                    
                    # Minimal check to keep connection alive
                    await client.get_me()
            except Exception as e:
                logger.debug(f"Keep alive error: {e}")
            await asyncio.sleep(1) # Check every 1 second as requested

    if not client.is_connected():
        await client.connect()
    
    # Pre-cache
    try:
        await client.get_entity(SOURCE_CHANNEL_ID)
    except Exception:
        pass

    asyncio.create_task(client.run_until_disconnected())
    asyncio.create_task(keep_alive())

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [KeyboardButton("লগইন (Login)")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("স্বাগতম! লগইন করতে নিচের বাটনে চাপ দিন।", reply_markup=reply_markup)

async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("আপনার টেলিগ্রাম নম্বরটি দিন (যেমন: +88017XXXXXXXX):")
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text
    context.user_data['phone'] = phone
    
    session_name = f"session_{update.effective_user.id}"
    client = TelegramClient(session_name, API_ID, API_HASH)
    await client.connect()
    
    try:
        sent_code = await client.send_code_request(phone)
        context.user_data['phone_code_hash'] = sent_code.phone_code_hash
        user_sessions[update.effective_user.id] = client
        await update.message.reply_text("আপনার টেলিগ্রামে একটি OTP পাঠানো হয়েছে। সেটি এখানে দিন:")
        return OTP
    except Exception as e:
        await update.message.reply_text(f"ত্রুটি: {str(e)}")
        await client.disconnect()
        return ConversationHandler.END

async def get_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    otp = update.message.text
    phone = context.user_data['phone']
    phone_code_hash = context.user_data['phone_code_hash']
    client = user_sessions.get(update.effective_user.id)
    
    try:
        await client.sign_in(phone, otp, phone_code_hash=phone_code_hash)
        await update.message.reply_text("লগইন সফল হয়েছে! অটোমেটিক ফরোয়ার্ডিং চালু হচ্ছে...")
        
        # Start forwarding immediately after login
        await start_forwarding(client, update.effective_user.id)
        
        await update.message.reply_text(f"ফরোয়ার্ডিং সচল: @Quotex_SuperBot -> @twtnwmenrn")
        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(f"লগইন ব্যর্থ হয়েছে: {str(e)}")
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("অপারেশন বাতিল করা হয়েছে।")
    return ConversationHandler.END

if __name__ == '__main__':
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('^লগইন \(Login\)$'), login_start)
        ],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_otp)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(conv_handler)
    
    # Try to resume sessions for already logged in users on restart
    async def resume_sessions():
        for filename in os.listdir('.'):
            if filename.startswith("session_") and filename.endswith(".session"):
                try:
                    user_id = int(filename.split('_')[1].split('.')[0])
                    session_name = filename.replace(".session", "")
                    client = TelegramClient(session_name, API_ID, API_HASH)
                    await client.connect()
                    if await client.is_user_authorized():
                        user_sessions[user_id] = client
                        await start_forwarding(client, user_id)
                        logger.info(f"Resumed session for user {user_id}")
                except Exception as e:
                    logger.error(f"Failed to resume session {filename}: {e}")

    # Run resume in the event loop
    loop = asyncio.get_event_loop()
    loop.create_task(resume_sessions())
    
    print("Bot is starting...")
    application.run_polling()
