import logging
import json
import requests
import sqlite3
import os
from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, ConversationHandler

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

with open('config.json') as config_file:
    config = json.load(config_file)

TOKEN = config['telegram_bot_token']
ALLOWED_USER_IDS = config['allowed_user_ids']
OPENAI_API_KEY = config['openai_api_key']
NEWSAPI_API_KEY = config['newsapi_api_key']

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

def init_db():
    if not os.path.exists('user_data.db'):
        conn = sqlite3.connect('user_data.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS interests
                     (user_id INTEGER PRIMARY KEY, interests TEXT)''')
        conn.commit()
        conn.close()

init_db()

def get_user_interests(user_id):
    conn = sqlite3.connect('user_data.db')
    c = conn.cursor()
    c.execute("SELECT interests FROM interests WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0].split(', ') if result and result[0] else []

def set_user_interests(user_id, interests):
    interests = [interest for interest in interests if interest]  # Filter out empty strings
    conn = sqlite3.connect('user_data.db')
    c = conn.cursor()
    c.execute("REPLACE INTO interests (user_id, interests) VALUES (?, ?)", (user_id, ', '.join(interests)))
    conn.commit()
    conn.close()

def add_user_interest(user_id, interest):
    if interest:
        interests = set(get_user_interests(user_id))
        interests.add(interest)
        set_user_interests(user_id, list(interests))

def remove_user_interest(user_id, interest):
    interests = set(get_user_interests(user_id))
    interests.discard(interest)
    set_user_interests(user_id, list(interests))

ADD_INTEREST, REMOVE_INTEREST = range(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in ALLOWED_USER_IDS:
        await update.message.reply_text('Hello, master!')
    else:
        await update.message.reply_text('Sorry, you are not authorized to use this bot.')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = ("This bot allows specific authorized users to interact with it. Use /start to initiate interaction, "
                 "/news to get news updates, /interests to manage your interests, "
                 "/addinterest to add an interest, /removeinterest to remove an interest.")
    await update.message.reply_text(help_text)

async def interests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    interests = get_user_interests(user_id)
    if not interests:
        await update.message.reply_text("You have no interests set.")
    else:
        interests_list = "\n".join(f"{idx+1}. {interest}" for idx, interest in enumerate(interests))
        await update.message.reply_text(f"Your interests are:\n{interests_list}")

async def add_interest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Please provide the interest you want to add.")
    return ADD_INTEREST

async def receive_add_interest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    interest = update.message.text.strip()
    if interest:
        add_user_interest(user_id, interest)
        await update.message.reply_text(f"Added interest: {interest}")
    return ConversationHandler.END

async def remove_interest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Please provide the interest you want to remove.")
    return REMOVE_INTEREST

async def receive_remove_interest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    interest = update.message.text.strip()
    if interest:
        remove_user_interest(user_id, interest)
        await update.message.reply_text(f"Removed interest: {interest}")
    return ConversationHandler.END

def fetch_news(api_url):
    response = requests.get(api_url)
    if response.status_code == 200:
        return response.json()['articles']
    else:
        logger.error(f"Failed to fetch news: {response.status_code} {response.text}")
        return []

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    interests = get_user_interests(user_id)
    if not interests:
        await update.message.reply_text("You have no interests set. Use /addinterest to set your interests.")
        return
    
    command = update.message.text.split()[0]
    if command == "/topnews":
        articles = fetch_news(f"https://newsapi.org/v2/top-headlines?country=us&pageSize=20&apiKey={NEWSAPI_API_KEY}")
    else:
        query = ' '.join(update.message.text.split()[1:]) or 'latest'
        articles = fetch_news(f"https://newsapi.org/v2/everything?q={query}&language=en&pageSize=20&apiKey={NEWSAPI_API_KEY}")
    
    filtered_articles = await fetch_and_filter_news(interests, articles)
    if not filtered_articles:
        await update.message.reply_text("No relevant news found based on your interests.")
        return

    for article in filtered_articles:
        title = article['title']
        summary = article['description'] if article['description'] else "No summary available."
        url = article['url']
        await update.message.reply_text(f"{title}\n{summary}\n{url}")

async def fetch_and_filter_news(interests, articles):
    prompts = [f"{article['title']} {article['description']}" for article in articles]
    try:
        responses = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": f"Filter the following articles based on these interests: {', '.join(interests)}. "
                                                     f"For each article, respond with 'Relevant' if it matches any of the interests, "
                                                     f"or 'Not Relevant' if it does not."}] + 
                     [{"role": "user", "content": prompt} for prompt in prompts],
            max_tokens=50,
            n=len(prompts)
        )
        filtered_articles = []
        for article, response in zip(articles, responses.choices):
            if "Relevant" in response.message.content:
                filtered_articles.append(article)
        return filtered_articles
    except Exception as error:
        logging.error(f"Error in filtering news: {error}", exc_info=True)
        return []

async def test_gpt_integration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    test_prompt = "Technology advancements in 2024"
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": "Please generate a relevant news summary based on the following topic:"},
                      {"role": "user", "content": test_prompt}],
            max_tokens=100
        )
        result = response.choices[0].message.content
        await update.message.reply_text(f"GPT-4 Response:\n{result}")
    except Exception as error:
        logging.error(f"Error in GPT-4 integration test: {error}", exc_info=True)
        await update.message.reply_text(f"Error in GPT-4 integration test: {error}")

def main():
    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('addinterest', add_interest_command),
                      CommandHandler('removeinterest', remove_interest_command)],
        states={
            ADD_INTEREST: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_add_interest)],
            REMOVE_INTEREST: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_remove_interest)],
        },
        fallbacks=[],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("interests", interests_command))
    application.add_handler(CommandHandler("topnews", news_command))
    application.add_handler(CommandHandler("news", news_command))
    application.add_handler(CommandHandler("testgpt", test_gpt_integration))

    application.run_polling()

if __name__ == "__main__":
    main()