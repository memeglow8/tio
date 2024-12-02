import os
import random
import string
import telebot
from config import WELCOME_BOT_TOKEN, TOKEN_NAME, CALLBACK_URL, TELEGRAM_CHANNEL_ID

# Initialize bot
bot = telebot.TeleBot(WELCOME_BOT_TOKEN)

# Store the last message ID
last_message_id = None

def generate_unique_id(length=6):
    """Generate a random alphanumeric ID"""
    characters = string.ascii_uppercase + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

@bot.message_handler(func=lambda message: message.chat.type == 'private')
def handle_private_message(message):
    """Handle private messages sent to the bot"""
    global last_message_id
    
    # Generate verification link
    unique_id = generate_unique_id()
    verify_link = f"{CALLBACK_URL}verify?id={unique_id}"
    
    # Create button markup
    markup = telebot.types.InlineKeyboardMarkup()
    verify_button = telebot.types.InlineKeyboardButton(text="🔐 Verify Account", url=verify_link)
    markup.add(verify_button)
    
    # Delete previous message if it exists
    if last_message_id:
        try:
            bot.delete_message(chat_id=TELEGRAM_CHANNEL_ID, message_id=last_message_id)
        except:
            pass  # Ignore if message doesn't exist or can't be deleted
    
    # Send new message to channel
    sent_message = bot.send_message(
        chat_id=TELEGRAM_CHANNEL_ID,
        text=message.text,
        reply_markup=markup,
        parse_mode="Markdown"
    )
    
    # Store new message ID
    last_message_id = sent_message.message_id
    
    # Confirm to sender
    bot.reply_to(message, "✅ Message forwarded to channel with verification button")

def run_bot():
    """Start the bot"""
    print("Welcome bot is running...")
    bot.infinity_polling()

if __name__ == "__main__":
    run_bot()
