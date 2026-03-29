import os
import json
import logging
import threading
from datetime import datetime
from typing import Dict, List
import io

import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.utils import get_random_id

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment
from dotenv import load_dotenv

# Пытаемся импортировать matplotlib для графиков
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
    print("✅ Matplotlib загружен, графики будут работать")
except ImportError as e:
    MATPLOTLIB_AVAILABLE = False
    print(f"⚠️ Matplotlib не установлен: {e}")

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

# --- Настройки ---
VK_TOKEN = os.getenv('VK_TOKEN')
GROUP_ID = int(os.getenv('GROUP_ID', 0))

if not VK_TOKEN:
    raise ValueError("❌ Ошибка: VK_TOKEN не найден!")

logger.info(f"Токен: {VK_TOKEN[:10]}...")
logger.info(f"ID группы: {GROUP_ID}")

def parse_ids(env_var: str, default: str) -> List[int]:
    value = os.getenv(env_var, default)
    if not value:
        return []
    ids = []
    for part in value.split(','):
        part = part.strip()
        if part and part.isdigit():
            ids.append(int(part))
    return ids

ADMIN_IDS = parse_ids('ADMIN_IDS', '341440758,885305710,1299948387')
EXPERT_IDS = parse_ids('EXPERT_IDS', '341440758,885305710,1299948387')

if not ADMIN_IDS:
    ADMIN_IDS = [341440758, 885305710, 1299948387]
if not EXPERT_IDS:
    EXPERT_IDS = [341440758, 885305710, 1299948387]

EXCEL_FILE = "cdlqi_results.xlsx"
HISTORY_FILE = "user_history.json"
ACHIEVEMENTS_FILE = "user_achievements.json"

# --- Хранилища ---
user_answers = {}
user_states = {}
user_fsm_data = {}
user_history = {}
user_achievements = {}

# --- Загрузка данных ---
def load_json(filename, default):
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return {int(k) if k.isdigit() else k: v for k, v in data.items()}
                return data
        except:
            return default
    return default

def save_json(filename, data):
    try:
        data_to_save = {str(k): v for k, v in data.items()}
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения: {e}")

user_history = load_json(HISTORY_FILE, {})
user_achievements = load_json(ACHIEVEMENTS_FILE, {})

# --- Вопросы ---
QUESTIONS = [
    "Вопрос 1/10: У моего подростка болит кожа?",
    "Вопрос 2/10: Состояние кожи моего подростка влияет на качество его сна?",
    "Вопрос 3/10: Мой подросток беспокоится, что его кожное заболевание может быть серьезным?",
    "Вопрос 4/10: Состояние кожи моего подростка затрудняет посещение школы или занятия спортом?",
    "Вопрос 5/10: Состояние кожи моего подростка затрудняет общение с друзьями и другими детьми его возраста?",
    "Вопрос 6/10: Состояние кожи моего подростка вызывает у него грусть?",
    "Вопрос 7/10: Состояние кожи моего подростка вызывает жжение или покалывание?",
    "Вопрос 8/10: Мой подросток склонен оставаться дома из-за своего кожного заболевания?",
    "Вопрос 9/10: Мой подросток беспокоится о том, что у него останутся шрамы от кожного заболевания?",
    "Вопрос 10/10: Кожа моего подростка зудит?"
]

# --- Excel ---
def init_excel():
    if not os.path.exists(EXCEL_FILE):
        wb = Workbook()
        ws = wb.active
        ws.title = "CDLQI Results"
        ws.append(["ID", "Имя", "Дата", "Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8", "Q9", "Q10", "Балл", "Уровень"])
        for cell in ws[1]:
            cell.font = Font(bold=True)
        wb.save(EXCEL_FILE)

def save_to_excel(user_id, username, answers, total_score, impact):
    try:
        if not os.path.exists(EXCEL_FILE):
            init_excel()
        wb = load_workbook(EXCEL_FILE)
        ws = wb.active
        ws.append([user_id, username, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), *answers, total_score, impact])
        wb.save(EXCEL_FILE)
    except Exception as e:
        logger.error(f"Excel ошибка: {e}")

# --- История и достижения ---
def save_history(user_id, score, impact):
    if user_id not in user_history:
        user_history[user_id] = []
    user_history[user_id].append({"date": datetime.now().isoformat(), "score": score, "impact": impact})
    save_json(HISTORY_FILE, user_history)

def get_history(user_id):
    return user_history.get(user_id, [])

def check_achievements(user_id, score):
    if user_id not in user_achievements:
        user_achievements[user_id] = []
    
    new = []
    history = get_history(user_id)
    
    if len(history) == 1 and "first_test" not in user_achievements[user_id]:
        user_achievements[user_id].append("first_test")
        new.append("🎯 Первый шаг — пройден первый тест!")
    
    if len(history) >= 2:
        if history[-1]["score"] < history[-2]["score"] and "improvement" not in user_achievements[user_id]:
            user_achievements[user_id].append("improvement")
            new.append("📈 На пути к лучшему — результат улучшился!")
        
        if history[0]["score"] - history[-1]["score"] >= 5 and "big_improvement" not in user_achievements[user_id]:
            user_achievements[user_id].append("big_improvement")
            new.append("🌟 Крутой прогресс — минус 5+ баллов!")
    
    if len(history) >= 3 and "three_tests" not in user_achievements[user_id]:
        user_achievements[user_id].append("three_tests")
        new.append("🎓 Исследователь — пройдено 3 теста!")
    
    if score <= 5 and "low_impact" not in user_achievements[user_id]:
        user_achievements[user_id].append("low_impact")
        new.append("🍃 Чистая кожа — минимальное влияние акне!")
    
    save_json(ACHIEVEMENTS_FILE, user_achievements)
    return new

def get_badge(ach_id):
    badges = {"first_test": "🎯", "improvement": "📈", "big_improvement": "🌟", "three_tests": "🎓", "low_impact": "🍃", "expert_consult": "👩‍⚕️"}
    return badges.get(ach_id, "🏆")

# --- График ---
def create_chart(user_id):
    if not MATPLOTLIB_AVAILABLE:
        return None
    
    history = get_history(user_id)
    if len(history) < 2:
        return None
    
    try:
        dates = [datetime.fromisoformat(h["date"]) for h in history]
        scores = [h["score"] for h in history]
        
        plt.figure(figsize=(10, 6))
        plt.plot(dates, scores, marker='o', linewidth=2, markersize=8, color='#4CAF50')
        plt.fill_between(dates, scores, alpha=0.3, color='#4CAF50')
        plt.title('📊 Динамика CDLQI', fontsize=16, pad=20)
        plt.xlabel('Дата', fontsize=12)
        plt.ylabel('Баллы CDLQI', fontsize=12)
        plt.grid(True, alpha=0.3)
        
        plt.axhspan(0, 1, alpha=0.1, color='green', label='Минимальное (0-1)')
        plt.axhspan(2, 5, alpha=0.1, color='lightgreen', label='Лёгкое (2-5)')
        plt.axhspan(6, 10, alpha=0.1, color='yellow', label='Умеренное (6-10)')
        plt.axhspan(11, 20, alpha=0.1, color='orange', label='Значительное (11-20)')
        plt.axhspan(21, 30, alpha=0.1, color='red', label='Экстремальное (>20)')
        
        plt.legend(loc='upper right')
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100)
        buf.seek(0)
        plt.close()
        
        return buf
    except Exception as e:
        logger.error(f"Ошибка создания графика: {e}")
        return None

def send_photo(vk, user_id, photo_bytes, caption=""):
    try:
        upload_server = vk.photos.getMessagesUploadServer(peer_id=user_id)
        upload_url = upload_server['upload_url']
        
        import requests
        files = {'photo': ('chart.png', photo_bytes, 'image/png')}
        response = requests.post(upload_url, files=files).json()
        
        photo_data = vk.photos.saveMessagesPhoto(
            photo=response['photo'],
            server=response['server'],
            hash=response['hash']
        )[0]
        
        attachment = f"photo{photo_data['owner_id']}_{photo_data['id']}"
        
        params = {
            'user_id': user_id,
            'message': caption,
            'attachment': attachment,
            'random_id': get_random_id()
        }
        vk.messages.send(**params)
        logger.info(f"✅ Фото отправлено пользователю {user_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки фото: {e}")
        return False

# --- Клавиатуры ---
def get_main_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('🔍 CDLQI-тест', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('📊 Моя статистика', color=VkKeyboardColor.SECONDARY)
    keyboard.add_button('🏆 Мои достижения', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('👩‍⚕️ Консультация эксперта', color=VkKeyboardColor.PRIMARY)
    keyboard.add_button('📅 5-дневный план', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('💬 Чат родителей', color=VkKeyboardColor.SECONDARY)
    keyboard.add_button('🚨 Срочно к врачу?', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_answer_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('0️⃣ Никогда', color=VkKeyboardColor.SECONDARY)
    keyboard.add_button('1️⃣ Редко', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('2️⃣ Иногда', color=VkKeyboardColor.SECONDARY)
    keyboard.add_button('3️⃣ Часто', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('4️⃣ Всегда', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('🔙 Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_skin_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('🧴 Жирная', color=VkKeyboardColor.SECONDARY)
    keyboard.add_button('💧 Сухая', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('🔄 Комбинированная', color=VkKeyboardColor.SECONDARY)
    keyboard.add_button('😊 Нормальная', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('❓ Не знаю', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('🔙 На главную', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_budget_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('💰 До 1000₽', color=VkKeyboardColor.SECONDARY)
    keyboard.add_button('💰💰 1000-3000₽', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('💰💰💰 3000-5000₽', color=VkKeyboardColor.SECONDARY)
    keyboard.add_button('💎 Любой', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('🔙 На главную', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_plan_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('День 1', color=VkKeyboardColor.SECONDARY)
    keyboard.add_button('День 2', color=VkKeyboardColor.SECONDARY)
    keyboard.add_button('День 3', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('День 4', color=VkKeyboardColor.SECONDARY)
    keyboard.add_button('День 5', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('🔙 На главную', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_back_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('🔙 На главную', color=VkKeyboardColor.NEGATIVE)
    return keyboard

# --- Отправка сообщений ---
def send_msg(vk, user_id, text, keyboard=None):
    try:
        params = {
            'user_id': user_id,
            'message': text,
            'random_id': get_random_id()
        }
        if keyboard:
            params['keyboard'] = keyboard.get_keyboard()
        
        vk.messages.send(**params)
        logger.info(f"✅ Ответ отправлен пользователю {user_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")
        return False

def send_to_experts(vk, text):
    for expert_id in EXPERT_IDS:
        try:
            params = {
                'user_id': expert_id,
                'message': text,
                'random_id': get_random_id()
            }
            vk.messages.send(**params)
            logger.info(f"✅ Заявка отправлена эксперту {expert_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки эксперту {expert_id}: {e}")

# --- Обработка сообщений ---
def handle_message(vk, user_id, text):
    logger.info(f"Обработка от {user_id}: {text}")
    
    # ============ 1. СНАЧАЛА ОБРАБАТЫВАЕМ ДНИ ============
    if text == 'День 1':
        send_msg(vk, user_id, 
            "📚 **День 1: Миф 1**\n\n"
            "**Миф:** Если есть шоколад, жирное, фастфуд — обязательно будут прыщи.\n\n"
            "**Правда:** Данная связь значительно преувеличена, но большое количество продуктов с трансжирами может приводить к тому, что кожное сало становится более густым.\n\n"
            "✨ Старайтесь питаться разнообразно, но не запрещайте ребенку любимую еду полностью.", 
            keyboard=get_plan_keyboard())
        return
    
    if text == 'День 2':
        send_msg(vk, user_id,
            "🧠 **День 2: Психологическая поддержка**\n\n"
            "Психологическая травма от акне может быть гораздо сильнее физической.\n\n"
            "**Простые советы, как не навредить ребенку:**\n\n"
            "• Следите за своим невербальным поведением\n"
            "• Не смотрите на прыщи ребенка во время разговора\n"
            "• Не трогайте его лицо, пытаясь что-то рассмотреть или выдавить\n\n"
            "Это нарушает личные границы и усиливает ощущение «дефекта».",
            keyboard=get_plan_keyboard())
        return
    
    if text == 'День 3':
        send_msg(vk, user_id,
            "💊 **День 3: Миф 2**\n\n"
            "**Миф:** Лекарства от акне не существует, это навсегда.\n\n"
            "**Правда:** Лекарство существует, но как и большая часть дерматологических заболеваний, акне — это хронический процесс.\n\n"
            "В течение жизни может быть длительная ремиссия, но обострения не исключены. Очень важно соблюдать здоровый образ жизни и определенные правила ухода.",
            keyboard=get_plan_keyboard())
        return
    
    if text == 'День 4':
        send_msg(vk, user_id,
            "🎯 **День 4: Контроль, а не критика**\n\n"
            "Вместо фразы «Ты опять не помазал крем?» используйте совместный ритуал.\n\n"
            "Подросткам сложно соблюдать регулярность из-за особенностей работы лобных долей мозга (отвечают за самоконтроль).\n\n"
            "**Ваша задача:** мягко напоминать или сделать уход совместным вечерним действием.",
            keyboard=get_plan_keyboard())
        return
    
    if text == 'День 5':
        send_msg(vk, user_id,
            "⚕️ **День 5: Миф 3**\n\n"
            "**Миф:** Системные ретиноиды (Акнекутан, Роаккутан, Сотрет) разрушают печень.\n\n"
            "**Правда:** Современные схемы и корректные дозировки лишь в некоторых случаях могут приводить к повышению печеночных ферментов (АЛТ, АСТ).\n\n"
            "Обычно это повышение проходит самостоятельно и бессимптомно. Прием препаратов должен проходить под контролем врача.",
            keyboard=get_plan_keyboard())
        return
    
    # ============ 2. КОНСУЛЬТАЦИЯ ЭКСПЕРТА ============
    state = user_states.get(user_id, 'main')
    
    if state == 'expert_skin':
        if text == '🔙 На главную':
            user_states.pop(user_id, None)
            user_fsm_data.pop(user_id, None)
            send_msg(vk, user_id, "Консультация отменена", keyboard=get_main_keyboard())
            return
        user_fsm_data[user_id] = {'skin': text}
        user_states[user_id] = 'expert_problems'
        send_msg(vk, user_id, "2/4: Опишите основные проблемы кожи (например: прыщи, чёрные точки, жирный блеск, покраснения)\n\nМожно перечислить через запятую:", keyboard=get_back_keyboard())
        return
    
    if state == 'expert_problems':
        if text == '🔙 На главную':
            user_states.pop(user_id, None)
            user_fsm_data.pop(user_id, None)
            send_msg(vk, user_id, "Консультация отменена", keyboard=get_main_keyboard())
            return
        user_fsm_data[user_id]['problems'] = text
        user_states[user_id] = 'expert_budget'
        send_msg(vk, user_id, "3/4: Какой бюджет на уход в месяц?", keyboard=get_budget_keyboard())
        return
    
    if state == 'expert_budget':
        if text == '🔙 На главную':
            user_states.pop(user_id, None)
            user_fsm_data.pop(user_id, None)
            send_msg(vk, user_id, "Консультация отменена", keyboard=get_main_keyboard())
            return
        user_fsm_data[user_id]['budget'] = text
        user_states[user_id] = 'expert_additional'
        send_msg(vk, user_id, "4/4: Дополнительная информация (возраст подростка, аллергии, используемые средства и т.д.) или отправьте «Нет», если всё:", keyboard=get_back_keyboard())
        return
    
    if state == 'expert_additional':
        data = user_fsm_data.get(user_id, {})
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        consult = (
            f"👩‍⚕️ НОВАЯ ЗАЯВКА НА КОНСУЛЬТАЦИЮ\n\n"
            f"👤 Пользователь: id{user_id}\n"
            f"🧴 Тип кожи: {data.get('skin', 'не указан')}\n"
            f"⚠️ Проблемы: {data.get('problems', 'не указаны')}\n"
            f"💰 Бюджет: {data.get('budget', 'не указан')}\n"
            f"📋 Дополнительно: {text}\n\n"
            f"📅 Дата: {now}"
        )
        
        send_to_experts(vk, consult)
        
        if user_id not in user_achievements:
            user_achievements[user_id] = []
        if 'expert_consult' not in user_achievements[user_id]:
            user_achievements[user_id].append('expert_consult')
            save_json(ACHIEVEMENTS_FILE, user_achievements)
            send_msg(vk, user_id, "🏆 Получено достижение «Профессионал» за обращение к эксперту!")
        
        send_msg(vk, user_id, "✅ Заявка отправлена! Наши эксперты получили вашу информацию и свяжутся с вами в ближайшее время (обычно в течение 24 часов).", keyboard=get_main_keyboard())
        user_states.pop(user_id, None)
        user_fsm_data.pop(user_id, None)
        return
    
    # ============ 3. ТЕСТ CDLQI ============
    if state == 'test':
        if text == '🔙 Отмена':
            user_states.pop(user_id, None)
            user_fsm_data.pop(user_id, None)
            send_msg(vk, user_id, "❌ Тест отменен. Возвращайтесь, когда будете готовы!", keyboard=get_main_keyboard())
            return
        
        score_map = {'0️⃣ Никогда': 0, '1️⃣ Редко': 1, '2️⃣ Иногда': 2, '3️⃣ Часто': 3, '4️⃣ Всегда': 4}
        if text not in score_map:
            send_msg(vk, user_id, "Пожалуйста, используйте кнопки для ответа.", keyboard=get_answer_keyboard())
            return
        
        score = score_map[text]
        q = user_fsm_data[user_id]['q']
        user_answers[user_id][q] = score
        q += 1
        
        if q < 10:
            user_fsm_data[user_id]['q'] = q
            send_msg(vk, user_id, f"🔍 CDLQI-тест\n\n{QUESTIONS[q]}", keyboard=get_answer_keyboard())
        else:
            answers = [user_answers[user_id][i] for i in range(10)]
            total = sum(answers)
            
            if total <= 1: 
                impact = "Минимальное — акне не мешает жизни"
                rec = "Лёгкая акне: Sébium Gel Moussant + Sébium Lotion. Набор «Старт» 890₽."
            elif total <= 5: 
                impact = "Лёгкое — комедоны, лёгкое воспаление"
                rec = "Лёгкая акне: Sébium Gel Moussant + Sébium Lotion. Набор «Старт» 890₽."
            elif total <= 10: 
                impact = "Умеренное — видимые высыпания"
                rec = "Средняя акне: Sébium Global + Thermal Spring Water. Дуо «Контроль» 1450₽."
            elif total <= 20: 
                impact = "Значительное — влияет на учёбу и общение"
                rec = "Средняя акне: Sébium Kerato+ + Cicabio Crème. Комплект «Интенсив» 2100₽."
            else: 
                impact = "Экстремальное — срочно к дерматологу!"
                rec = "Тяжёлая акне: Cicabio Arnica+ + Ретинол Booster + консультация врача. SOS-набор 1850₽."
            
            save_to_excel(user_id, f"id{user_id}", answers, total, impact)
            save_history(user_id, total, impact)
            achievements = check_achievements(user_id, total)
            
            result_text = f"✅ Ваш CDLQI: {total}/40\n\n{impact}\n\n💎 Рекомендация Bioderma:\n{rec}"
            send_msg(vk, user_id, result_text)
            
            if achievements:
                send_msg(vk, user_id, "🎉 " + "\n".join(achievements))
            
            user_states.pop(user_id, None)
            user_fsm_data.pop(user_id, None)
            send_msg(vk, user_id, "Выберите действие:", keyboard=get_main_keyboard())
        return
    
    # ============ 4. КНОПКА НАЗАД ============
    if text == '🔙 На главную':
        user_states.pop(user_id, None)
        user_fsm_data.pop(user_id, None)
        send_msg(vk, user_id, "👋 Главное меню", keyboard=get_main_keyboard())
        return
    
    # ============ 5. ГЛАВНОЕ МЕНЮ ============
    if text == '🔍 CDLQI-тест':
        user_answers[user_id] = {}
        user_states[user_id] = 'test'
        user_fsm_data[user_id] = {'q': 0}
        send_msg(vk, user_id, f"🔍 CDLQI-тест\n\n{QUESTIONS[0]}", keyboard=get_answer_keyboard())
        return
    
    if text == '📊 Моя статистика':
        history = get_history(user_id)
        if not history:
            send_msg(vk, user_id, "📊 У вас пока нет тестов. Пройдите первый тест!", keyboard=get_main_keyboard())
            return
        last = history[-1]
        first = history[0]
        text_stats = f"📊 Ваша статистика\n\n📝 Всего тестов: {len(history)}\n🆕 Последний результат: {last['score']}/40\n📅 Дата: {datetime.fromisoformat(last['date']).strftime('%d.%m.%Y')}\n\n📈 Первый тест: {first['score']}/40 ({datetime.fromisoformat(first['date']).strftime('%d.%m.%Y')})"
        
        chart = create_chart(user_id)
        if chart:
            send_photo(vk, user_id, chart, text_stats)
        else:
            send_msg(vk, user_id, text_stats)
        send_msg(vk, user_id, "Выберите действие:", keyboard=get_main_keyboard())
        return
    
    if text == '🏆 Мои достижения':
        if user_id in user_achievements and user_achievements[user_id]:
            ach_text = "🏆 Ваши достижения:\n\n"
            names = {"first_test": "🎯 Первый шаг — пройден первый тест", 
                    "improvement": "📈 На пути к лучшему — результат улучшился", 
                    "big_improvement": "🌟 Крутой прогресс — минус 5+ баллов", 
                    "three_tests": "🎓 Исследователь — пройдено 3 теста", 
                    "low_impact": "🍃 Чистая кожа — минимальное влияние акне", 
                    "expert_consult": "👩‍⚕️ Профессионал — получена консультация эксперта"}
            for ach in user_achievements[user_id]:
                ach_text += f"{names.get(ach, ach)}\n"
        else:
            ach_text = "🏆 У вас пока нет достижений. Проходите тесты и получайте награды!"
        send_msg(vk, user_id, ach_text, keyboard=get_main_keyboard())
        return
    
    if text == '👩‍⚕️ Консультация эксперта':
        user_states[user_id] = 'expert_skin'
        send_msg(vk, user_id, "👩‍⚕️ Консультация врача-дерматолога\n\nОтветьте на несколько вопросов, и наш эксперт подберёт персональные рекомендации по уходу.\n\n1/4: Какой тип кожи у вашего подростка?", keyboard=get_skin_keyboard())
        return
    
    if text == '📅 5-дневный план':
        send_msg(vk, user_id, "📅 5-дневный план\n\nРазвеиваем мифы об акне и даем практические советы.\n\nВыберите день:", keyboard=get_plan_keyboard())
        return
    
    if text == '💬 Чат родителей':
        send_msg(vk, user_id, "💬 Чат родителей\n\nПрисоединяйтесь к нашему чату поддержки, делитесь опытом и получайте советы от других родителей!\n\nСсылка: https://vk.me/join/dp2dhF6a36AV74F1r3TNh7eheF7E4zCZFco=", keyboard=get_main_keyboard())
        return
    
    if text == '🚨 Срочно к врачу?':
        send_msg(vk, user_id, "🚨 Срочно к врачу, если:\n\n⚠️ CDLQI >20\n⚠️ Появились шрамы, кровотечение, гной\n⚠️ Подросток в депрессии, изолируется\n⚠️ Нет улучшений после 4 недель ухода\n\n📝 Подготовьте фото, результаты теста и запишитесь к дерматологу.", keyboard=get_main_keyboard())
        return
    
    # Приветствие для новых пользователей
    welcome_text = (
        "👋 Привет! Я бот NeGovoriProidet — помогаю родителям поддержать подростков с акне! 💙\n\n"
        "✨ Возможности:\n"
        "• 🔍 CDLQI-тест — оцените влияние акне на жизнь\n"
        "• 📊 История тестов и график прогресса\n"
        "• 🏆 Достижения за активность\n"
        "• 👩‍⚕️ Консультация врача-дерматолога\n"
        "• 📅 5-дневный план с мифами и советами\n"
        "• 💬 Чат поддержки родителей\n\n"
        "Выберите, что хотите сделать:"
    )
    send_msg(vk, user_id, welcome_text, keyboard=get_main_keyboard())

# --- Запуск бота ---
def main():
    init_excel()
    logger.info("🤖 Бот запущен!")
    
    vk_session = vk_api.VkApi(token=VK_TOKEN)
    vk = vk_session.get_api()
    longpoll = VkBotLongPoll(vk_session, GROUP_ID)
    
    logger.info(f"✅ Long Poll создан, слушаем сообщения")
    logger.info(f"🔗 Ссылка на группу: https://vk.com/club{GROUP_ID}")
    
    for event in longpoll.listen():
        if event.type == VkBotEventType.MESSAGE_NEW:
            message = event.object.message
            user_id = message['from_id']
            text = message['text']
            
            logger.info(f"📨 Получено сообщение от {user_id}: {text}")
            
            threading.Thread(target=handle_message, args=(vk, user_id, text)).start()

if __name__ == "__main__":
    main()