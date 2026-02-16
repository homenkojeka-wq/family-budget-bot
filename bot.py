import os
import logging
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json

# Налаштування логування
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Стани розмови
CHOOSING_CATEGORY, ENTERING_AMOUNT = range(2)

# Категорії витрат
CATEGORIES = {
    '🍕 Їжа': 'Їжа',
    '🏠 Квартира': 'Квартира',
    '💡 Комуналка': 'Комуналка',
    '🏃 Спорт і навчання': 'Спорт і навчання',
    '🎉 Розваги': 'Розваги',
    '👕 Одяг': 'Одяг',
    '💊 Ліки': 'Ліки',
    '📦 Інше': 'Інше'
}

# Підключення до Google Sheets
def get_google_sheet():
    try:
        # Отримуємо credentials з змінної оточення
        creds_json = os.environ.get('GOOGLE_CREDENTIALS')
        if not creds_json:
            logger.error("GOOGLE_CREDENTIALS не знайдено!")
            return None
        
        creds_dict = json.loads(creds_json)
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        # Відкриваємо таблицю за назвою
        sheet_name = os.environ.get('SHEET_NAME', 'Сімейний бюджет')
        sheet = client.open(sheet_name).sheet1
        return sheet
    except Exception as e:
        logger.error(f"Помилка підключення до Google Sheets: {e}")
        return None

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # Створюємо клавіатуру з категоріями
    keyboard = [
        [KeyboardButton('🍕 Їжа'), KeyboardButton('🏠 Квартира')],
        [KeyboardButton('💡 Комуналка'), KeyboardButton('🏃 Спорт і навчання')],
        [KeyboardButton('🎉 Розваги'), KeyboardButton('👕 Одяг')],
        [KeyboardButton('💊 Ліки'), KeyboardButton('📦 Інше')],
        [KeyboardButton('📊 Статистика'), KeyboardButton('❌ Скасувати')]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"Привіт, {user.first_name}! 👋\n\n"
        "Я допоможу вам вести облік сімейного бюджету 💰\n\n"
        "Оберіть категорію витрат:",
        reply_markup=reply_markup
    )
    
    return CHOOSING_CATEGORY

# Обробка вибору категорії
async def category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == '📊 Статистика':
        await show_stats(update, context)
        return CHOOSING_CATEGORY
    
    if text == '❌ Скасувати':
        await update.message.reply_text("Операцію скасовано. Оберіть категорію:")
        return CHOOSING_CATEGORY
    
    if text in CATEGORIES:
        context.user_data['category'] = CATEGORIES[text]
        await update.message.reply_text(
            f"Категорія: {text}\n"
            "Введіть суму витрат в євро (тільки число):\n"
            "Наприклад: 25.50"
        )
        return ENTERING_AMOUNT
    
    await update.message.reply_text("Будь ласка, оберіть категорію з меню:")
    return CHOOSING_CATEGORY

# Обробка введення суми
async def amount_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.replace(',', '.'))
        
        if amount <= 0:
            await update.message.reply_text("Сума має бути більше 0. Спробуйте ще раз:")
            return ENTERING_AMOUNT
        
        # Отримуємо дані
        user = update.effective_user
        category = context.user_data.get('category', 'Невідомо')
        date = datetime.now().strftime('%d.%m.%Y')
        time = datetime.now().strftime('%H:%M')
        
        # Записуємо в Google Sheets
        sheet = get_google_sheet()
        if sheet:
            try:
                row = [date, time, user.first_name, category, amount]
                sheet.append_row(row)
                
                await update.message.reply_text(
                    f"✅ Витрату додано!\n\n"
                    f"👤 {user.first_name}\n"
                    f"📂 {category}\n"
                    f"💶 {amount:.2f} €\n"
                    f"📅 {date} {time}\n\n"
                    "Оберіть наступну категорію або подивіться статистику:"
                )
            except Exception as e:
                logger.error(f"Помилка запису в таблицю: {e}")
                await update.message.reply_text(
                    "⚠️ Помилка збереження. Перевірте налаштування таблиці.\n"
                    "Оберіть категорію:"
                )
        else:
            await update.message.reply_text(
                "⚠️ Помилка підключення до таблиці.\n"
                "Оберіть категорію:"
            )
        
        return CHOOSING_CATEGORY
        
    except ValueError:
        await update.message.reply_text(
            "⚠️ Невірний формат суми!\n"
            "Введіть число (наприклад: 25.50):"
        )
        return ENTERING_AMOUNT

# Показати статистику
async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sheet = get_google_sheet()
    if not sheet:
        await update.message.reply_text("⚠️ Помилка підключення до таблиці.")
        return
    
    try:
        # Отримуємо всі записи
        all_records = sheet.get_all_records()
        
        if not all_records:
            await update.message.reply_text("📊 Поки немає жодної витрати.")
            return
        
        # Поточний місяць та рік
        current_month = datetime.now().strftime('%m.%Y')
        
        # Підраховуємо витрати
        total = 0
        categories_total = {}
        user_total = {}
        
        for record in all_records:
            date = record.get('Дата', '')
            if current_month in date:
                amount = float(record.get('Сума', 0))
                category = record.get('Категорія', 'Інше')
                user = record.get('Користувач', 'Невідомо')
                
                total += amount
                categories_total[category] = categories_total.get(category, 0) + amount
                user_total[user] = user_total.get(user, 0) + amount
        
        # Формуємо повідомлення
        month_name = datetime.now().strftime('%B %Y')
        message = f"📊 <b>Статистика за {month_name}</b>\n\n"
        message += f"💶 <b>Загальні витрати: {total:.2f} €</b>\n\n"
        
        message += "📂 <b>По категоріям:</b>\n"
        for category, amount in sorted(categories_total.items(), key=lambda x: x[1], reverse=True):
            percentage = (amount / total * 100) if total > 0 else 0
            message += f"  • {category}: {amount:.2f} € ({percentage:.1f}%)\n"
        
        message += "\n👥 <b>По користувачам:</b>\n"
        for user, amount in sorted(user_total.items(), key=lambda x: x[1], reverse=True):
            percentage = (amount / total * 100) if total > 0 else 0
            message += f"  • {user}: {amount:.2f} € ({percentage:.1f}%)\n"
        
        await update.message.reply_text(message, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Помилка при отриманні статистики: {e}")
        await update.message.reply_text("⚠️ Помилка при отриманні статистики.")

# Команда /stats
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_stats(update, context)

# Скасування операції
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Операцію скасовано. Використайте /start для початку роботи."
    )
    return ConversationHandler.END

# Головна функція
def main():
    # Отримуємо токен з змінної оточення
    token = os.environ.get('TELEGRAM_TOKEN')
    if not token:
        logger.error("TELEGRAM_TOKEN не знайдено!")
        return
    
    # Створюємо додаток
    application = Application.builder().token(token).build()
    
    # Обробник розмови
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSING_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, category_chosen)],
            ENTERING_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, amount_entered)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('stats', stats_command))
    
    # Запускаємо бота
    logger.info("Бот запущено!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
