import os
import uuid
import time
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)
from dotenv import load_dotenv

from db import SessionLocal, engine, Base
from models import User, Subject, Lab, LabFile

# --- Настройка ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Директория для файлов
UPLOAD_DIR = "/app/lab_files"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# --- Принудительное создание таблиц с проверкой ---
def initialize_database():
    print("🔄 Инициализация базы данных...")
    
    max_retries = 10  # Увеличим количество попыток
    for attempt in range(max_retries):
        try:
            print(f"⏳ Попытка {attempt + 1}/{max_retries} создания таблиц...")
            
            # Импортируем все модели чтобы они зарегистрировались в Base
            from models import User, Subject, Lab, LabFile
            
            # Создаем все таблицы
            Base.metadata.create_all(bind=engine)
            
            # Проверяем созданные таблицы
            from sqlalchemy import inspect
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            
            expected_tables = ['users', 'subjects', 'labs', 'lab_files']
            missing_tables = [table for table in expected_tables if table not in tables]
            
            if missing_tables:
                print(f"⚠️  Отсутствуют таблицы: {missing_tables}")
                if attempt < max_retries - 1:
                    print("⏳ Ждем 5 секунд перед повторной попыткой...")
                    time.sleep(5)
                    continue
                else:
                    print("❌ Не удалось создать все таблицы")
                    return False
            else:
                print(f"✅ Все таблицы успешно созданы: {tables}")
                return True
            
        except Exception as e:
            print(f"❌ Ошибка при создании таблиц (попытка {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                print("⏳ Ждем 5 секунд перед повторной попыткой...")
                time.sleep(5)
            else:
                print("❌ Не удалось создать таблицы после всех попыток")
                return False

# Инициализируем базу данных
print("🚀 Запуск инициализации БД...")
if not initialize_database():
    print("❌ Критическая ошибка: не удалось создать таблицы в БД")
    exit(1)

print("✅ База данных готова к работе!")

# --- Состояния для диалогов ---
ASK_SUBJECT = 1
ASK_NOTIFY = 2
ASK_LAB_SUBJECT = 3
ASK_LAB_TITLE = 4
ASK_LAB_DESC = 5
ASK_LAB_DEADLINE = 6
ASK_LAB_FILES = 7
ASK_EDIT_LAB = 8
ASK_EDIT_SUBJECT = 9

# --- Главное меню ---
def get_main_keyboard(is_admin=False):
    buttons = [
        ["Мои предметы"],
        ["Актуально"]
    ]
    if is_admin:
        buttons.append(["Админ панель"])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

# --- Админ панель ---
def get_admin_keyboard():
    keyboard = [
        [InlineKeyboardButton("Оповестить", callback_data="notify")],
        [InlineKeyboardButton("Добавить предмет", callback_data="add_subject")],
        [InlineKeyboardButton("Добавить лабораторную", callback_data="add_lab")],
        [InlineKeyboardButton("Управление предметами", callback_data="manage_subjects")],
        [InlineKeyboardButton("Управление лабораторными", callback_data="manage_labs")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Старт ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = SessionLocal()
    tg_id = update.effective_user.id
    user = session.query(User).filter_by(tg_id=tg_id).first()

    if not user:
        user = User(tg_id=tg_id, is_admin=(tg_id == ADMIN_ID))
        session.add(user)
        session.commit()
    else:
        user.is_admin = (tg_id == ADMIN_ID)
        session.commit()

    keyboard = get_main_keyboard(user.is_admin)
    text = "Добро пожаловать!"
    
    if user.is_admin:
        text += "\nВы админ, используйте админские кнопки ниже."
        await update.message.reply_text(text, reply_markup=keyboard)
        await update.message.reply_text("Админ панель:", reply_markup=get_admin_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=keyboard)
    
    session.close()

# --- Админ панель ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = SessionLocal()
    tg_id = update.effective_user.id
    user = session.query(User).filter_by(tg_id=tg_id).first()
    
    if user and user.is_admin:
        await update.message.reply_text("Админ панель:", reply_markup=get_admin_keyboard())
    else:
        await update.message.reply_text("У вас нет доступа к админ панели.")
    
    session.close()

# --- Мои предметы ---
async def my_subjects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = SessionLocal()
    subjects = session.query(Subject).all()
    if not subjects:
        await update.message.reply_text("Пока предметов нет.")
    else:
        keyboard = [[InlineKeyboardButton(s.name, callback_data=f"subject:{s.id}")] for s in subjects]
        await update.message.reply_text("Ваши предметы:", reply_markup=InlineKeyboardMarkup(keyboard))
    session.close()

# --- Кнопки Inline для админа и предметов ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("subject:"):
        await show_subject_details(query, context)
        
    elif data.startswith("lab:"):
        await show_lab_details(query, context)

    elif data.startswith("lab_files:"):
        await show_lab_files(query, context)
        
    elif data.startswith("download_file:"):  # Добавьте этот обработчик
        await download_lab_file(query, context)
        
    elif data.startswith("delete_lab:"):
        await delete_lab(query, context)
        
    elif data.startswith("edit_lab:"):
        await edit_lab_start(query, context)
        
    elif data.startswith("delete_subject:"):
        await delete_subject(query, context)
        
    elif data.startswith("edit_subject:"):
        await edit_subject_start(query, context)

    elif data == "add_subject":
        await add_subject_start(update, context)
    elif data == "notify":
        await notify_start(update, context)
    elif data == "add_lab":
        await add_lab_start(update, context)
    elif data == "manage_subjects":
        await manage_subjects(query, context)
    elif data == "manage_labs":
        await manage_labs(query, context)

# --- Показать детали предмета ---
async def show_subject_details(query, context):
    session = SessionLocal()
    sid = int(query.data.split(":")[1])
    subject = session.query(Subject).get(sid)
    
    if subject:
        # Создаем кнопки для каждой лабораторной
        keyboard = []
        for lab in subject.labs:
            keyboard.append([InlineKeyboardButton(lab.title, callback_data=f"lab:{lab.id}")])
        
        # Добавляем админские кнопки если пользователь админ
        tg_id = query.from_user.id
        user = session.query(User).filter_by(tg_id=tg_id).first()
        
        if user and user.is_admin:
            keyboard.append([
                InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_subject:{subject.id}"),
                InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete_subject:{subject.id}")
            ])
        
        keyboard.append([InlineKeyboardButton("⬅️ Назад к предметам", callback_data="back_to_subjects")])
        
        if not subject.labs:
            await query.edit_message_text(
                f"📚 {subject.name}\n\nПока нет лабораторных работ.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query.edit_message_text(
                f"📚 {subject.name}\n\nВыберите лабораторную:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    session.close()

# --- Показать детали лабораторной ---
async def show_lab_details(query, context):
    session = SessionLocal()
    lid = int(query.data.split(":")[1])
    lab = session.query(Lab).get(lid)
    
    if lab:
        # Формируем сообщение с информацией о лабе
        text = f"📌 <b>{lab.title}</b>\n\n"
        text += f"📝 <b>Описание:</b>\n{lab.desc or 'Нет описания'}\n\n"
        text += f"⏳ <b>Дедлайн:</b> {lab.deadline or 'не установлен'}\n\n"
        text += f"📚 <b>Предмет:</b> {lab.subject.name}"
        
        # Создаем кнопки
        keyboard = []
        
        # Добавляем админские кнопки если пользователь админ
        tg_id = query.from_user.id
        user = session.query(User).filter_by(tg_id=tg_id).first()
        
        if user and user.is_admin:
            keyboard.extend([
                [InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_lab:{lab.id}")],
                [InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete_lab:{lab.id}")]
            ])
        
        keyboard.extend([
            [InlineKeyboardButton("📎 Файлы лабораторной", callback_data=f"lab_files:{lab.id}")],
            [InlineKeyboardButton("⬅️ Назад к предмету", callback_data=f"subject:{lab.subject.id}")]
        ])
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    session.close()

# --- Показать файлы лабораторной ---
async def show_lab_files(query, context):
    session = SessionLocal()
    lid = int(query.data.split(":")[1])
    lab = session.get(Lab, lid)
    
    if lab and lab.files:
        text = f"📁 Файлы лабораторной '{lab.title}':\n\n"
        
        keyboard = []
        for lab_file in lab.files:
            file_size_kb = lab_file.file_size / 1024 if lab_file.file_size else 0
            file_size_text = f"{file_size_kb:.1f} KB" if file_size_kb < 1024 else f"{file_size_kb/1024:.1f} MB"
            
            # Добавляем иконки для разных типов файлов
            file_icons = {
                '.pdf': '📕', '.docx': '📘', '.txt': '📄',
                '.xlsx': '📊', '.xls': '📊', '.zip': '📦',
                '.py': '🐍', '.pcap': '🌐', '.tar': '📦',
                '.jpg': '🖼️', '.jpeg': '🖼️', '.png': '🖼️'
            }
            
            file_ext = os.path.splitext(lab_file.file_name)[1].lower()
            icon = file_icons.get(file_ext, '📄')
            
            text += f"{icon} {lab_file.file_name} ({file_size_text})\n"
            keyboard.append([InlineKeyboardButton(
                f"{icon} Скачать {lab_file.file_name}", 
                callback_data=f"download_file:{lab_file.id}"
            )])
        
        keyboard.append([InlineKeyboardButton("⬅️ Назад к лабораторной", callback_data=f"lab:{lab.id}")])
        
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await query.message.reply_text("📭 Для этой лабораторной пока нет файлов.")
    
    session.close()

# --- Функции для работы с файлами ---
async def download_file_to_server(file_id, file_name, context):
    """Скачивает файл из Telegram и сохраняет на сервер"""
    try:
        print(f"🔄 Начинаем загрузку файла: {file_name}")
        
        # Получаем файл от Telegram
        file = await context.bot.get_file(file_id)
        
        # Генерируем уникальное имя файла
        file_extension = os.path.splitext(file_name)[1]
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        file_path = os.path.join(UPLOAD_DIR, unique_filename)
        
        # Скачиваем файл на сервер
        await file.download_to_drive(file_path)
        
        # Проверяем, что файл создался
        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            print(f"✅ Файл сохранен: {file_path} ({file_size} байт)")
            return unique_filename, file_path
        else:
            print(f"❌ Файл не был создан: {file_path}")
            return None, None
        
    except Exception as e:
        print(f"❌ Ошибка при скачивании файла {file_name}: {e}")
        return None, None

async def send_file_from_server(update, file_path, file_name):
    """Отправляет файл пользователю с сервера"""
    try:
        # Проверяем существование файла
        if not os.path.exists(file_path):
            await update.message.reply_text(f"❌ Файл {file_name} не найден на сервере")
            return False
        
        # Открываем и отправляем файл
        with open(file_path, 'rb') as file:
            file_name_lower = file_name.lower()
            
            if file_name_lower.endswith(('.jpg', '.jpeg', '.png', '.gif')):
                await update.message.reply_photo(photo=file, caption=f"📸 {file_name}")
            elif file_name_lower.endswith(('.mp4', '.avi', '.mov', '.mkv')):
                await update.message.reply_video(video=file, caption=f"🎥 {file_name}")
            else:
                await update.message.reply_document(document=file, caption=f"📄 {file_name}")
        
        print(f"✅ Файл отправлен: {file_name}")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при отправке файла {file_name}: {e}")
        await update.message.reply_text(f"❌ Ошибка при отправке файла {file_name}")
        return False

# --- Управление предметами ---
async def manage_subjects(query, context):
    session = SessionLocal()
    subjects = session.query(Subject).all()
    
    if not subjects:
        await query.message.reply_text("Нет предметов для управления.")
    else:
        keyboard = []
        for subject in subjects:
            keyboard.append([
                InlineKeyboardButton(f"✏️ {subject.name}", callback_data=f"edit_subject:{subject.id}"),
                InlineKeyboardButton(f"🗑️", callback_data=f"delete_subject:{subject.id}")
            ])
        
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_admin")])
        
        await query.edit_message_text(
            "Управление предметами:\n\nВыберите предмет для редактирования или удаления:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    session.close()

# --- Управление лабораторными ---
async def manage_labs(query, context):
    session = SessionLocal()
    labs = session.query(Lab).all()
    
    if not labs:
        await query.message.reply_text("Нет лабораторных для управления.")
    else:
        keyboard = []
        for lab in labs:
            keyboard.append([
                InlineKeyboardButton(f"✏️ {lab.title}", callback_data=f"edit_lab:{lab.id}"),
                InlineKeyboardButton(f"🗑️", callback_data=f"delete_lab:{lab.id}")
            ])
        
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_admin")])
        
        await query.edit_message_text(
            "Управление лабораторными:\n\nВыберите лабораторную для редактирования или удаления:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    session.close()

# --- Удалить лабораторную ---
async def delete_lab(query, context):
    session = SessionLocal()
    lid = int(query.data.split(":")[1])
    lab = session.query(Lab).get(lid)
    
    if lab:
        lab_title = lab.title
        subject_id = lab.subject_id
        session.delete(lab)
        session.commit()
        await query.message.reply_text(f"Лабораторная '{lab_title}' удалена!")
        
        # Возвращаемся к предмету
        subject = session.query(Subject).get(subject_id)
        if subject:
            await show_subject_details(query, context)
    else:
        await query.message.reply_text("Лабораторная не найдена.")
    
    session.close()

# --- Удалить предмет ---
async def delete_subject(query, context):
    session = SessionLocal()
    sid = int(query.data.split(":")[1])
    subject = session.query(Subject).get(sid)
    
    if subject:
        subject_name = subject.name
        # Удаляем все лабораторные этого предмета
        for lab in subject.labs:
            session.delete(lab)
        session.delete(subject)
        session.commit()
        await query.message.reply_text(f"Предмет '{subject_name}' и все связанные лабораторные удалены!")
        
        # Возвращаемся к списку предметов
        await manage_subjects(query, context)
    else:
        await query.message.reply_text("Предмет не найден.")
    
    session.close()

# --- Начать редактирование лабораторной ---
async def edit_lab_start(query, context):
    session = SessionLocal()
    lid = int(query.data.split(":")[1])
    lab = session.query(Lab).get(lid)
    
    if lab:
        context.user_data['edit_lab_id'] = lid
        keyboard = [
            [InlineKeyboardButton("📝 Название", callback_data="edit_lab_title")],
            [InlineKeyboardButton("📄 Описание", callback_data="edit_lab_desc")],
            [InlineKeyboardButton("⏳ Дедлайн", callback_data="edit_lab_deadline")],
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"lab:{lid}")]
        ]
        
        await query.edit_message_text(
            f"Редактирование лабораторной: {lab.title}\n\nЧто вы хотите изменить?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    session.close()
    return ASK_EDIT_LAB

# --- Начать редактирование предмета ---
async def edit_subject_start(query, context):
    session = SessionLocal()
    sid = int(query.data.split(":")[1])
    subject = session.query(Subject).get(sid)
    
    if subject:
        context.user_data['edit_subject_id'] = sid
        await query.message.reply_text(f"Введите новое название для предмета '{subject.name}':")
        return ASK_EDIT_SUBJECT
    session.close()

# --- Сохранить изменения предмета ---
async def edit_subject_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = SessionLocal()
    subject_id = context.user_data.get('edit_subject_id')
    new_name = update.message.text.strip()
    
    if subject_id and new_name:
        subject = session.query(Subject).get(subject_id)
        if subject:
            old_name = subject.name
            subject.name = new_name
            session.commit()
            await update.message.reply_text(f"Предмет '{old_name}' переименован в '{new_name}'!")
        else:
            await update.message.reply_text("Предмет не найден.")
    else:
        await update.message.reply_text("Название предмета не может быть пустым.")
    
    context.user_data.clear()
    session.close()
    return ConversationHandler.END

# --- Обработка кнопок назад ---
async def handle_back_buttons(query, context):
    data = query.data
    
    if data == "back_to_subjects":
        session = SessionLocal()
        subjects = session.query(Subject).all()
        if not subjects:
            await query.edit_message_text("Пока предметов нет.")
        else:
            keyboard = [[InlineKeyboardButton(s.name, callback_data=f"subject:{s.id}")] for s in subjects]
            await query.edit_message_text("Ваши предметы:", reply_markup=InlineKeyboardMarkup(keyboard))
        session.close()
        
    elif data == "back_to_admin":
        await query.edit_message_text("Админ панель:", reply_markup=get_admin_keyboard())

# --- Админ: Добавить предмет ---
async def add_subject_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.message.reply_text("Введите название предмета:")
    else:
        await update.message.reply_text("Введите название предмета:")
    return ASK_SUBJECT

async def add_subject_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = SessionLocal()
    name = update.message.text.strip()
    if name:
        new_subj = Subject(name=name)
        session.add(new_subj)
        session.commit()
        await update.message.reply_text(f"Предмет '{name}' добавлен!")
    else:
        await update.message.reply_text("Название предмета не может быть пустым.")
    session.close()
    return ConversationHandler.END

# --- Админ: Оповестить ---
async def notify_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.message.reply_text("Введите сообщение для рассылки всем пользователям:")
    else:
        await update.message.reply_text("Введите сообщение для рассылки всем пользователям:")
    return ASK_NOTIFY

async def notify_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = SessionLocal()
    text = update.message.text
    users = session.query(User).all()
    sent_count = 0
    
    for u in users:
        try:
            await context.bot.send_message(u.tg_id, f"📢 Оповещение от админа:\n{text}")
            sent_count += 1
        except Exception as e:
            print(f"Не удалось отправить сообщение пользователю {u.tg_id}: {e}")
    
    await update.message.reply_text(f"Сообщение отправлено {sent_count} пользователям.")
    session.close()
    return ConversationHandler.END

# --- Админ: Добавить лабораторную ---
async def add_lab_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = SessionLocal()
    subjects = session.query(Subject).all()
    if not subjects:
        query = update.callback_query
        if query:
            await query.message.reply_text("Нет предметов для добавления лабораторной.")
        else:
            await update.message.reply_text("Нет предметов для добавления лабораторной.")
        session.close()
        return ConversationHandler.END
    
    keyboard = [[InlineKeyboardButton(s.name, callback_data=f"lab_subj:{s.id}")] for s in subjects]
    
    query = update.callback_query
    if query:
        await query.message.reply_text("Выберите предмет:", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text("Выберите предмет:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    session.close()
    return ASK_LAB_SUBJECT

async def add_lab_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    subject_id = int(query.data.split(":")[1])
    context.user_data['lab_subject_id'] = subject_id
    
    await query.message.reply_text("Введите название лабораторной:")
    return ASK_LAB_TITLE

async def add_lab_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['lab_title'] = update.message.text
    await update.message.reply_text("Введите описание лабораторной:")
    return ASK_LAB_DESC

async def add_lab_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['lab_desc'] = update.message.text
    await update.message.reply_text("Введите дедлайн лабораторной:")
    return ASK_LAB_DEADLINE

async def add_lab_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['lab_deadline'] = update.message.text
    await update.message.reply_text(
        "Теперь пришлите файлы для лабораторной (если есть). "
        "Можно присылать несколько файлов.\n"
        "Когда закончите, отправьте /done\n"
        "Чтобы пропустить, отправьте /skip"
    )
    return ASK_LAB_FILES

async def add_lab_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'lab_files' not in context.user_data:
        context.user_data['lab_files'] = []
    
    # Поддерживаемые типы файлов
    supported_extensions = ['.txt', '.pdf', '.docx', '.xlsx', '.xls', '.zip', '.py', '.pcap', '.tar', '.jpg', '.jpeg', '.png']
    
    if update.message.document:
        file = update.message.document
        file_extension = os.path.splitext(file.file_name)[1].lower()
        
        # Проверяем поддержку типа файла
        if file_extension not in supported_extensions:
            await update.message.reply_text(
                f"❌ Формат файла {file_extension} не поддерживается.\n"
                f"📋 Поддерживаемые форматы: {', '.join(supported_extensions)}"
            )
            return ASK_LAB_FILES
        
        # Скачиваем файл на сервер
        unique_filename, file_path = await download_file_to_server(
            file.file_id, 
            file.file_name, 
            context
        )
        
        if unique_filename and file_path:
            context.user_data['lab_files'].append({
                'file_id': file.file_id,
                'file_name': file.file_name,
                'file_size': file.file_size,
                'unique_filename': unique_filename,
                'file_path': file_path
            })
            await update.message.reply_text(f"✅ Файл '{file.file_name}' загружен на сервер!")
        else:
            await update.message.reply_text(f"❌ Ошибка при загрузке файла '{file.file_name}'")
    
    elif update.message.photo:
        # Для фото берем самое большое изображение
        photo = update.message.photo[-1]
        unique_filename, file_path = await download_file_to_server(
            photo.file_id, 
            "photo.jpg", 
            context
        )
        
        if unique_filename and file_path:
            context.user_data['lab_files'].append({
                'file_id': photo.file_id,
                'file_name': 'photo.jpg',
                'file_size': photo.file_size,
                'unique_filename': unique_filename,
                'file_path': file_path
            })
            await update.message.reply_text("✅ Фото загружено на сервер!")
        else:
            await update.message.reply_text("❌ Ошибка при загрузке фото")
    
    return ASK_LAB_FILES

#Актуальные лабы
async def actual_labs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает все предметы и доступные лабораторные в компактном виде"""
    session = SessionLocal()
    
    try:
        subjects = session.query(Subject).all()
        
        if not subjects:
            await update.message.reply_text("📭 Пока нет предметов и лабораторных работ.")
            return
        
        message = "📚 <b>АКТУАЛЬНЫЕ ЛАБОРАТОРНЫЕ</b>\n\n"
        
        for subject in subjects:
            if subject.labs:
                message += f"<b>📖 {subject.name}</b>\n"
                
                for lab in subject.labs:
                    # Форматируем дедлайн (если есть)
                    deadline_text = f" | ⏳ {lab.deadline}" if lab.deadline else ""
                    message += f"   • {lab.title}{deadline_text}\n"
                
                message += "\n"
        
        await update.message.reply_text(message, parse_mode='HTML')
        
    except Exception as e:
        await update.message.reply_text("❌ Произошла ошибка при получении данных")
        print(f"Ошибка в actual_labs: {e}")
    
    finally:
        session.close()

async def add_lab_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = SessionLocal()
    
    subject_id = context.user_data.get('lab_subject_id')
    title = context.user_data.get('lab_title')
    desc = context.user_data.get('lab_desc')
    deadline = context.user_data.get('lab_deadline')
    files_data = context.user_data.get('lab_files', [])
    
    if subject_id and title:
        try:
            # Создаем лабораторную
            new_lab = Lab(
                title=title,
                desc=desc,
                deadline=deadline,
                subject_id=subject_id
            )
            session.add(new_lab)
            session.flush()  # Получаем ID новой лабораторной
            
            # Сохраняем информацию о файлах в БД
            for file_info in files_data:
                lab_file = LabFile(
                    lab_id=new_lab.id,
                    file_name=file_info['file_name'],
                    file_path=file_info['file_path'],
                    file_size=file_info['file_size']
                )
                session.add(lab_file)
            
            session.commit()
            
            text = f"✅ Лабораторная '{title}' добавлена!\n\n"
            text += f"📝 Описание: {desc or 'нет'}\n"
            text += f"⏳ Дедлайн: {deadline or 'не установлен'}\n"
            text += f"📎 Файлов: {len(files_data)}"
            
            await update.message.reply_text(text)
            
            # Отправляем подтверждение загрузки файлов
            if files_data:
                files_list = "\n".join([f"• {f['file_name']}" for f in files_data])
                await update.message.reply_text(f"📁 Загруженные файлы:\n{files_list}")
            
        except Exception as e:
            session.rollback()
            await update.message.reply_text(f"❌ Ошибка при добавлении лабораторной в БД: {e}")
            print(f"❌ Ошибка БД: {e}")
    else:
        await update.message.reply_text("❌ Ошибка: не указаны название или предмет лабораторной.")
    
    context.user_data.clear()
    session.close()
    return ConversationHandler.END

async def download_lab_file(query, context):
    session = SessionLocal()
    file_id = int(query.data.split(":")[1])
    lab_file = session.get(LabFile, file_id)
    
    if lab_file and lab_file.file_path:
        try:
            # Отправляем файл пользователю
            success = await send_file_from_server(query, lab_file.file_path, lab_file.file_name)
            if success:
                await query.answer(f"✅ Файл {lab_file.file_name} отправлен!")
            else:
                await query.answer("❌ Ошибка при отправке файла")
        except Exception as e:
            await query.answer("❌ Ошибка при загрузке файла")
            print(f"❌ Ошибка: {e}")
    else:
        await query.answer("❌ Файл не найден")
    
    session.close()

async def add_lab_skip_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['lab_files'] = []
    return await add_lab_finish(update, context)

# --- Отмена ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Операция отменена.")
    return ConversationHandler.END

# --- MAIN ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Основные хендлеры
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("cancel", cancel))
    
    app.add_handler(MessageHandler(filters.Regex("^Мои предметы$"), my_subjects))
    app.add_handler(MessageHandler(filters.Regex("^Админ панель$"), admin_panel))
    app.add_handler(MessageHandler(filters.Regex("^Актуально$"), actual_labs))

    # ConversationHandler для добавления предмета
    conv_add_subject = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_subject_start, pattern="^add_subject$")],
        states={
            ASK_SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_subject_save)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    # ConversationHandler для оповещения
    conv_notify = ConversationHandler(
        entry_points=[CallbackQueryHandler(notify_start, pattern="^notify$")],
        states={
            ASK_NOTIFY: [MessageHandler(filters.TEXT & ~filters.COMMAND, notify_send)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    # ConversationHandler для добавления лабораторной
    conv_add_lab = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_lab_start, pattern="^add_lab$")],
        states={
            ASK_LAB_SUBJECT: [CallbackQueryHandler(add_lab_subject, pattern="^lab_subj:")],
            ASK_LAB_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_lab_title)],
            ASK_LAB_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_lab_desc)],
            ASK_LAB_DEADLINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_lab_deadline)],
            ASK_LAB_FILES: [
                MessageHandler(filters.Document.ALL | filters.PHOTO, add_lab_files),
                CommandHandler("done", add_lab_finish),
                CommandHandler("skip", add_lab_skip_files)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    # ConversationHandler для редактирования предмета
    conv_edit_subject = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_subject_start, pattern="^edit_subject:")],
        states={
            ASK_EDIT_SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_subject_save)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    # Добавляем ConversationHandlers
    app.add_handler(conv_add_subject)
    app.add_handler(conv_notify)
    app.add_handler(conv_add_lab)
    app.add_handler(conv_edit_subject)
    
    # Обычный обработчик кнопок (должен быть последним)
    app.add_handler(CallbackQueryHandler(button_handler))

    app.run_polling()

if __name__ == "__main__":
    main()