import logging
import openai
import json
import requests
from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

with open('config.json') as config_file:
    config = json.load(config_file)

TOKEN = config['telegram_bot_token']
ALLOWED_USER_IDS = config['allowed_user_ids']
OPENAI_API_KEY = config['openai_api_key']
NEWSAPI_API_KEY = config['newsapi_api_key']

client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
)

async def openai_query(user_message):
    instructions = "This is a prediction message from a telegram channel. Convert this message to a binance trade. I need the trade coin id and quantity:"
    full_prompt = instructions + user_message
    try:
        chat_completion = await client.chat.completions.create(
            messages=[
                {"role": "user", "content": full_prompt},
            ],
            model="gpt-4-0125-preview",
        )
        return chat_completion.choices[0].message.content 
    except openai.RateLimitError:
        return "I'm currently overwhelmed with requests. Please try again later."
    except openai.APIError as error:
        logging.error(f"An OpenAI API error occurred: {error}")
        return "Sorry, I encountered an API error. Please try again."
    except Exception as error:
        logging.error(f"An unexpected error occurred: {error}", exc_info=True)
        return "Sorry, I encountered an unexpected error. Please try again."
    
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in ALLOWED_USER_IDS:
        await update.message.reply_text('Hello, master!')
    else:
        await update.message.reply_text('Sorry, you are not authorized to use this bot.')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = "This bot allows specific authorized users to interact with it. Use /start to initiate interaction, /news to get news updates."
    await update.message.reply_text(help_text)

def fetch_top_news(country='us', pageSize=5):
    url = f"https://newsapi.org/v2/top-headlines?country={country}&pageSize={pageSize}&apiKey={NEWSAPI_API_KEY}"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()['articles'][:pageSize]
    else:
        logger.error(f"Failed to fetch news: {response.status_code} {response.text}")
        return []

def fetch_specific_news(query='latest', language='en', pageSize=5):
    url = f"https://newsapi.org/v2/everything?q={query}&language={language}&pageSize={pageSize}&apiKey={NEWSAPI_API_KEY}"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json().get('articles', [])[:pageSize]
    else:
        logger.error(f"Failed to fetch news: {response.status_code} {response.text}")
        return []

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    command = update.message.text.split()[0]
    if command == "/topnews":
        news_articles = fetch_top_news()
    else:
        query = ' '.join(update.message.text.split()[1:]) or 'latest'
        news_articles = fetch_specific_news(query=query)

    for article in news_articles:
        title = article['title']
        url = article['url']
        await update.message.reply_text(f"{title}\n{url}")

async def query_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text.split(maxsplit=1)[1]
    response = await openai_query(user_message)
    await update.message.reply_text(response)

def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("topnews", news_command))
    application.add_handler(CommandHandler("news", news_command))
    application.add_handler(CommandHandler("query", query_command))

    application.run_polling()

if __name__ == "__main__":
    main()