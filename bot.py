import os
import json
import time
import logging
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional, List, Tuple

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ================== ENV ==================
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
ALLOWED_CHAT_ID = int((os.getenv("ALLOWED_CHAT_ID") or "0").strip() or "0")
TAXI_TOPIC_ID = int((os.getenv("TAXI_TOPIC_ID") or "199").strip() or "199")
STATE_FILE = (os.getenv("STATE_FILE") or "state.json").strip()

REMIND_EVERY_MIN_DEFAULT = int((os.getenv("REMIND_EVERY_MIN") or "10").strip() or "10")

ADMIN_IDS_RAW = (os.getenv("ADMIN_IDS") or "").strip()
ADMIN_IDS = set()
if ADMIN_IDS_RAW:
    for x in ADMIN_IDS_RAW.split(","):
        x = x.strip()
        if x.isdigit():
            ADMIN_IDS.add(int(x))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi. Variables ga BOT_TOKEN qo'ying.")
if not ALLOWED_CHAT_ID:
    raise RuntimeError("ALLOWED_CHAT_ID topilmadi. Variables ga ALLOWED_CHAT_ID qo'ying.")

# ================== LOGGING ==================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("saudiya-taxi-bot")

# ================== STATE ==================
def load_state() -> Dict[str, Any]:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"orders": {}, "users": {}, "settings": {}}
    except Exception:
        log.exception("state load failed")
        return {"orders": {}, "users": {}, "settings": {}}

def save_state(state: Dict[str, Any]) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        log.exception("state save failed")

STATE = load_state()
STATE.setdefault("orders", {})
STATE.setdefault("users", {})
STATE.setdefault("settings", {})

def get_remind_every_sec() -> int:
    sec = int(STATE["settings"].get("remind_every_sec", REMIND_EVERY_MIN_DEFAULT * 60))
    return max(60, sec)

def set_remind_every_min(minutes: int) -> None:
    minutes = max(1, int(minutes))
    STATE["settings"]["remind_every_sec"] = minutes * 60
    save_state(STATE)

def new_order_id() -> str:
    return str(int(time.time() * 1000))

# ================== DATA MODELS ==================
@dataclass
class Order:
    order_id: str
    user_id: int
    user_name: str
    user_username: str

    pickup_lat: Optional[float] = None
    pickup_lon: Optional[float] = None
    pickup_text: str = ""

    drop_lat: Optional[float] = None
    drop_lon: Optional[float] = None
    drop_text: str = ""

    people: str = ""
    when: str = ""

    phone: str = ""
    username_confirm: str = ""

    price_text: str = "Kelishilgan narxda"

    status: str = "pending"     # pending -> posted -> assigned -> cancelled
    driver_id: Optional[int] = None
    driver_name: str = ""
    driver_username: str = ""

    group_message_id: Optional[int] = None

# ================== HELPERS ==================
def is_allowed_group(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and chat.id == ALLOWED_CHAT_ID)

def is_admin(user_id: int) -> bool:
    return (user_id in ADMIN_IDS) if ADMIN_IDS else False

def user_display(update: Update) -> Tuple[str, str]:
    u = update.effective_user
    if not u:
        return ("", "")
    name = (u.full_name or "").strip()
    username = f"@{u.username}" if u.username else ""
    return name, username

def maps_link(lat: float, lon: float) -> str:
    return f"https://maps.google.com/?q={lat},{lon}"

def order_card_text(o: Order) -> str:
    pickup = o.pickup_text
    if o.pickup_lat is not None and o.pickup_lon is not None:
        pickup += f"\n📍 Pickup: {maps_link(o.pickup_lat, o.pickup_lon)}"

    drop = o.drop_text
    if o.drop_lat is not None and o.drop_lon is not None:
        drop += f"\n🏁 Dropoff: {maps_link(o.drop_lat, o.drop_lon)}"

    contact_lines = []
    if o.phone:
        contact_lines.append(f"📞 Telefon: {o.phone}")
    if o.username_confirm:
        contact_lines.append(f"👤 Telegram: {o.username_confirm}")
    contact_block = "\n".join(contact_lines) if contact_lines else "👤 Aloqa: (kiritilmagan)"

    status_line = {
        "posted": "Holat: ⏳ Haydovchi kutilmoqda",
        "assigned": "Holat: ✅ Haydovchi biriktirildi",
        "cancelled": "Holat: ❌ Bekor qilindi",
        "pending": "Holat: 📝 To‘ldirilmoqda",
    }.get(o.status, f"Holat: {o.status}")

    driver_line = ""
    if o.status == "assigned":
        d = o.driver_username or o.driver_name or "Haydovchi"
        driver_line = f"\n🚖 Haydovchi: {d}"

    price_line = f"💰 Narx: {o.price_text or 'Kelishilgan narxda'}"

    return (
        "🚕 TAKSI BUYURTMA\n\n"
        f"🆔 ID: {o.order_id}\n\n"
        f"📍 Qayerdan:\n{pickup}\n\n"
        f"🏁 Qayerga:\n{drop}\n\n"
        f"👥 Odamlar: {o.people}\n"
        f"⏰ Vaqt: {o.when}\n"
        f"{price_line}\n\n"
        f"{contact_block}\n\n"
        f"{status_line}"
        f"{driver_line}"
    )

def order_keyboard(o: Order) -> InlineKeyboardMarkup:
    if o.status == "posted":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Qabul qilish", callback_data=f"accept:{o.order_id}")],
            [InlineKeyboardButton("❌ Bekor qilish (mijoz)", callback_data=f"cancel:{o.order_id}")],
        ])
    if o.status == "assigned":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Haydovchi bekor qildi (qayta e’lon)", callback_data=f"driver_cancel:{o.order_id}")],
            [InlineKeyboardButton("✅ Band", callback_data=f"noop:{o.order_id}")],
        ])
    if o.status == "cancelled":
        return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor qilingan", callback_data=f"noop:{o.order_id}")]])
    return InlineKeyboardMarkup([])

def get_user_step(user_id: int) -> str:
    return (STATE.get("users", {}).get(str(user_id), {}) or {}).get("step", "")

def set_user_step(user_id: int, step: str, order_id: Optional[str] = None) -> None:
    users = STATE.setdefault("users", {})
    users.setdefault(str(user_id), {})
    users[str(user_id)]["step"] = step
    if order_id is not None:
        users[str(user_id)]["order_id"] = order_id
    save_state(STATE)

def get_user_order_id(user_id: int) -> Optional[str]:
    return (STATE.get("users", {}).get(str(user_id), {}) or {}).get("order_id")

def has_active_order(user_id: int) -> bool:
    for o in STATE.get("orders", {}).values():
        if o.get("user_id") == user_id and o.get("status") in ("pending", "posted", "assigned"):
            return True
    return False

def store_order(o: Order) -> None:
    STATE["orders"][o.order_id] = asdict(o)
    save_state(STATE)

def load_order(order_id: str) -> Optional[Order]:
    data = (STATE.get("orders", {}) or {}).get(order_id)
    if not data:
        return None
    return Order(**data)

def update_order(o: Order) -> None:
    store_order(o)

def delete_job(job_queue, name: str) -> None:
    try:
        jobs = job_queue.get_jobs_by_name(name)
        for j in jobs:
            j.schedule_removal()
    except Exception:
        pass

def remind_job_name(order_id: str) -> str:
    return f"remind:{order_id}"

async def post_order_to_group(context: ContextTypes.DEFAULT_TYPE, o: Order, delete_old: bool = False) -> Optional[int]:
    if delete_old and o.group_message_id:
        try:
            await context.bot.delete_message(chat_id=ALLOWED_CHAT_ID, message_id=o.group_message_id)
        except Exception:
            pass

    sent = await context.bot.send_message(
        chat_id=ALLOWED_CHAT_ID,
        message_thread_id=TAXI_TOPIC_ID,
        text=order_card_text(o),
        reply_markup=order_keyboard(o),
        disable_web_page_preview=True,
    )
    return sent.message_id

def schedule_reminder(app: Application, order_id: str) -> None:
    if not app.job_queue:
        return
    name = remind_job_name(order_id)
    delete_job(app.job_queue, name)
    app.job_queue.run_repeating(
        callback=reminder_tick,
        interval=get_remind_every_sec(),
        first=get_remind_every_sec(),
        name=name,
        data={"order_id": order_id},
    )

def reschedule_all_posted(app: Application) -> None:
    if not app.job_queue:
        return
    try:
        for job in list(app.job_queue.jobs()):
            if job.name and job.name.startswith("remind:"):
                job.schedule_removal()
    except Exception:
        pass

    for oid, data in (STATE.get("orders", {}) or {}).items():
        if data.get("status") == "posted":
            schedule_reminder(app, oid)

# ================== DM FLOW UI ==================
def kb_request_location() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Lokatsiya yuborish", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

def kb_request_contact() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📞 Telefon raqamni yuborish", request_contact=True)],
         [KeyboardButton("⏭ O‘tkazib yuborish")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

def kb_people() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("1"), KeyboardButton("2"), KeyboardButton("3"), KeyboardButton("4")],
         [KeyboardButton("5+"), KeyboardButton("⛔ Bekor qilish")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

def kb_when() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("Hozir"), KeyboardButton("Vaqt yozaman")],
         [KeyboardButton("⛔ Bekor qilish")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

# ================== COMMANDS ==================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat and update.effective_chat.type == ChatType.PRIVATE:
        await update.effective_message.reply_text(
            "Assalomu alaykum!\n\n"
            "🚕 Taksi buyurtma berish uchun /taksi yozing.\n"
            "Bekor qilish: /cancel"
        )

async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or update.effective_chat.type != ChatType.PRIVATE:
        return
    uid = update.effective_user.id
    oid = get_user_order_id(uid)
    step = get_user_step(uid)
    if not step or not oid:
        await update.effective_message.reply_text("Bekor qilinadigan jarayon yo‘q.", reply_markup=ReplyKeyboardRemove())
        return

    o = load_order(oid)
    if o and o.status == "pending":
        o.status = "cancelled"
        update_order(o)

    set_user_step(uid, "", None)
    STATE["users"].setdefault(str(uid), {})
    STATE["users"][str(uid)].pop("order_id", None)
    save_state(STATE)

    await update.effective_message.reply_text("Jarayon bekor qilindi.", reply_markup=ReplyKeyboardRemove())

async def taxi_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat:
        return

    # ===== GROUP/SUPERGROUP =====
    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        if not is_allowed_group(update):
            return
        current_tid = getattr(update.effective_message, "message_thread_id", None)
        if current_tid != TAXI_TOPIC_ID:
            return  # JIM

        await update.effective_message.reply_text(
            "Taksi buyurtma berish uchun botga shaxsiy chatda yozing:\n"
            "1) Bot profiliga kiring\n"
            "2) Start bosing\n"
            "3) /taksi yozing"
        )
        return

    # ===== PRIVATE =====
    if chat.type == ChatType.PRIVATE:
        uid = update.effective_user.id

        if has_active_order(uid):
            await update.effective_message.reply_text(
                "Sizda aktiv buyurtma bor. Avval uni yakunlang yoki /cancel qiling."
            )
            return

        name, username = user_display(update)
        oid = new_order_id()

        o = Order(
            order_id=oid,
            user_id=uid,
            user_name=name or "User",
            user_username=username or "",
            pickup_text="",
            drop_text="",
            people="",
            when="",
            phone="",
            username_confirm=username or "",
            price_text="Kelishilgan narxda",
            status="pending",
        )
        store_order(o)

        set_user_step(uid, "pickup_location", oid)

        await update.effective_message.reply_text(
            "📍 Qayerdasiz?\nLokatsiyani yuboring.",
            reply_markup=kb_request_location(),
        )

# ================== ADMIN COMMANDS ==================
async def setinterval_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else 0
    if not is_admin(uid):
        return

    if not context.args:
        cur = get_remind_every_sec() // 60
        await update.effective_message.reply_text(f"Hozirgi interval: {cur} daqiqa.\nMisol: /setinterval 10")
        return

    try:
        minutes = int(context.args[0])
    except Exception:
        await update.effective_message.reply_text("Noto‘g‘ri. Misol: /setinterval 10")
        return

    set_remind_every_min(minutes)
    reschedule_all_posted(context.application)

    await update.effective_message.reply_text(f"✅ Reminder interval: {max(1, minutes)} daqiqaga o‘zgardi.")

async def setprice_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else 0
    if not is_admin(uid):
        return

    if len(context.args) < 2:
        await update.effective_message.reply_text("Misol: /setprice 1700000000000 25 SAR\nYoki: /setprice 1700000000000 Kelishilgan narxda")
        return

    order_id = context.args[0].strip()
    price_text = " ".join(context.args[1:]).strip()

    o = load_order(order_id)
    if not o:
        await update.effective_message.reply_text("Order topilmadi.")
        return

    o.price_text = price_text if price_text else "Kelishilgan narxda"
    update_order(o)

    if o.group_message_id and o.status in ("posted", "assigned"):
        try:
            await context.bot.edit_message_text(
                chat_id=ALLOWED_CHAT_ID,
                message_id=o.group_message_id,
                message_thread_id=TAXI_TOPIC_ID,
                text=order_card_text(o),
                reply_markup=order_keyboard(o),
                disable_web_page_preview=True,
            )
        except Exception:
            pass

    await update.effective_message.reply_text(f"✅ Narx yangilandi: {o.price_text}")

# ================== PRIVATE MESSAGE ROUTER ==================
async def private_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or update.effective_chat.type != ChatType.PRIVATE:
        return

    msg = update.effective_message
    if not msg:
        return

    uid = update.effective_user.id
    step = get_user_step(uid)
    oid = get_user_order_id(uid)

    if not step or not oid:
        return

    o = load_order(oid)
    if not o:
        set_user_step(uid, "", None)
        return

    if msg.text and msg.text.strip() == "⛔ Bekor qilish":
        await cancel_cmd(update, context)
        return

    if step == "pickup_location":
        if msg.location:
            o.pickup_lat = msg.location.latitude
            o.pickup_lon = msg.location.longitude
            o.pickup_text = "Lokatsiya yuborildi"
            update_order(o)
            set_user_step(uid, "pickup_text", oid)
            await msg.reply_text("Pickup joyni qisqa yozing (misol: Masjid Nabaviy, Gate 25):", reply_markup=ReplyKeyboardRemove())
            return
        await msg.reply_text("Iltimos, lokatsiya yuboring.", reply_markup=kb_request_location())
        return

    if step == "pickup_text":
        if msg.text and msg.text.strip():
            o.pickup_text = msg.text.strip()
            update_order(o)
            set_user_step(uid, "drop_choice", oid)
            await msg.reply_text("🏁 Qayerga borasiz?\nLokatsiya yuborsangiz ham bo‘ladi, yoki matn bilan yozing.")
            return
        await msg.reply_text("Pickup joyni matn bilan yozing.")
        return

    if step == "drop_choice":
        if msg.location:
            o.drop_lat = msg.location.latitude
            o.drop_lon = msg.location.longitude
            o.drop_text = "Lokatsiya yuborildi"
            update_order(o)
            set_user_step(uid, "drop_text", oid)
            await msg.reply_text("Dropoff joyni qisqa yozing (misol: Madina Airport):")
            return

        if msg.text and msg.text.strip():
            o.drop_text = msg.text.strip()
            update_order(o)
            set_user_step(uid, "people", oid)
            await msg.reply_text("👥 Nechta odam?", reply_markup=kb_people())
            return

        await msg.reply_text("Dropoff uchun lokatsiya yuboring yoki matn yozing.")
        return

    if step == "drop_text":
        if msg.text and msg.text.strip():
            o.drop_text = msg.text.strip()
            update_order(o)
            set_user_step(uid, "people", oid)
            await msg.reply_text("👥 Nechta odam?", reply_markup=kb_people())
            return
        await msg.reply_text("Dropoff joyni matn bilan yozing.")
        return

    if step == "people":
        if msg.text and msg.text.strip() in {"1", "2", "3", "4", "5+"}:
            o.people = msg.text.strip()
            update_order(o)
            set_user_step(uid, "when", oid)
            await msg.reply_text("⏰ Qachon?", reply_markup=kb_when())
            return
        await msg.reply_text("Iltimos, tugmalardan birini tanlang.", reply_markup=kb_people())
        return

    if step == "when":
        if msg.text and msg.text.strip() == "Hozir":
            o.when = "Hozir"
            update_order(o)
            set_user_step(uid, "phone", oid)
            await msg.reply_text("📞 Telefon raqamni yuboring (yoki o‘tkazib yuboring):", reply_markup=kb_request_contact())
            return

        if msg.text and msg.text.strip() == "Vaqt yozaman":
            set_user_step(uid, "when_text", oid)
            await msg.reply_text("Vaqtni yozing (misol: 18:30):", reply_markup=ReplyKeyboardRemove())
            return

        await msg.reply_text("Iltimos, tugmalardan tanlang.", reply_markup=kb_when())
        return

    if step == "when_text":
        if msg.text and msg.text.strip():
            o.when = msg.text.strip()
            update_order(o)
            set_user_step(uid, "phone", oid)
            await msg.reply_text("📞 Telefon raqamni yuboring (yoki o‘tkazib yuboring):", reply_markup=kb_request_contact())
            return
        await msg.reply_text("Vaqtni matn bilan yozing (misol: 18:30).")
        return

    if step == "phone":
        if msg.contact and msg.contact.phone_number:
            o.phone = msg.contact.phone_number
            update_order(o)
            set_user_step(uid, "username_confirm", oid)
            await msg.reply_text("Telegram username’ni yozing (misol: @aliatt0r). Agar yo‘q bo‘lsa: yo‘q", reply_markup=ReplyKeyboardRemove())
            return

        if msg.text and msg.text.strip() == "⏭ O‘tkazib yuborish":
            o.phone = ""
            update_order(o)
            set_user_step(uid, "username_confirm", oid)
            await msg.reply_text("Telegram username’ni yozing (misol: @aliatt0r). Agar yo‘q bo‘lsa: yo‘q", reply_markup=ReplyKeyboardRemove())
            return

        if msg.text and msg.text.strip():
            o.phone = msg.text.strip()
            update_order(o)
            set_user_step(uid, "username_confirm", oid)
            await msg.reply_text("Telegram username’ni yozing (misol: @aliatt0r). Agar yo‘q bo‘lsa: yo‘q", reply_markup=ReplyKeyboardRemove())
            return

        await msg.reply_text("Telefon raqam yuboring yoki o‘tkazib yuboring.", reply_markup=kb_request_contact())
        return

    if step == "username_confirm":
        if msg.text and msg.text.strip():
            txt = msg.text.strip()
            if txt.lower() in {"yoq", "yo'q", "yo‘q", "yoq.", "yo'q."}:
                o.username_confirm = ""
            else:
                if not txt.startswith("@"):
                    txt = "@" + txt
                o.username_confirm = txt

            update_order(o)

            o.status = "posted"
            update_order(o)

            try:
                mid = await post_order_to_group(context, o, delete_old=False)
                o.group_message_id = mid
                update_order(o)
            except Exception:
                log.exception("send order to group failed")
                await msg.reply_text("Xatolik: buyurtmani guruhga yuborib bo‘lmadi. Admin bilan bog‘laning.")
                set_user_step(uid, "", None)
                return

            schedule_reminder(context.application, o.order_id)

            await msg.reply_text(
                "✅ Buyurtmangiz taksi bo‘limiga yuborildi.\n"
                "Haydovchi topilishi bilan sizga xabar beraman.",
                reply_markup=ReplyKeyboardRemove(),
            )

            set_user_step(uid, "", None)
            STATE["users"].setdefault(str(uid), {})
            STATE["users"][str(uid)].pop("order_id", None)
            save_state(STATE)
            return

        await msg.reply_text("Username yozing (misol: @aliatt0r) yoki 'yo‘q' deb yozing.")
        return

# ================== REMINDER JOB ==================
async def reminder_tick(context: ContextTypes.DEFAULT_TYPE):
    order_id = (context.job.data or {}).get("order_id")
    if not order_id:
        return

    o = load_order(order_id)
    if not o:
        delete_job(context.job_queue, remind_job_name(order_id))
        return

    if o.status != "posted":
        delete_job(context.job_queue, remind_job_name(order_id))
        return

    try:
        mid = await post_order_to_group(context, o, delete_old=True)
        o.group_message_id = mid
        update_order(o)
    except Exception:
        log.exception("reminder repost failed")

# ================== CALLBACKS (GROUP BUTTONS) ==================
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data:
        return

    # Faqat allowed group + taxi topic ichida ishlasin
    if not q.message or not q.message.chat:
        await q.answer()
        return
    if q.message.chat.id != ALLOWED_CHAT_ID:
        await q.answer()
        return
    if getattr(q.message, "message_thread_id", None) != TAXI_TOPIC_ID:
        await q.answer()
        return

    # callback format tekshirish
    if ":" not in q.data:
        await q.answer()
        return

    action, order_id = q.data.split(":", 1)

    o = load_order(order_id)
    if not o:
        await q.answer("Buyurtma topilmadi.", show_alert=True)
        return

    # ========== CUSTOMER CANCEL ==========
    if action == "cancel":
        if q.from_user.id != o.user_id:
            await q.answer("Bekor qilish faqat buyurtmachiga mumkin.", show_alert=True)
            return
        if o.status in ("cancelled",):
            await q.answer("Allaqachon bekor qilingan.", show_alert=True)
            return
        if o.status == "assigned":
            await q.answer("Haydovchi biriktirilgan. Bekor qilib bo‘lmaydi.", show_alert=True)
            return

        o.status = "cancelled"
        update_order(o)
        if context.job_queue:
            delete_job(context.job_queue, remind_job_name(order_id))

        try:
            if o.group_message_id:
                await context.bot.edit_message_text(
                    chat_id=ALLOWED_CHAT_ID,
                    message_id=o.group_message_id,
                    message_thread_id=TAXI_TOPIC_ID,
                    text=order_card_text(o),
                    reply_markup=order_keyboard(o),
                    disable_web_page_preview=True,
                )
        except Exception:
            pass

        try:
            await context.bot.send_message(chat_id=o.user_id, text="❌ Buyurtma bekor qilindi.")
        except Exception:
            pass

        await q.answer("Bekor qilindi.")
        return

    # ========== ACCEPT ==========
    if action == "accept":
        if o.status != "posted":
            await q.answer("Bu buyurtma endi aktiv emas.", show_alert=True)
            return

        o.status = "assigned"
        o.driver_id = q.from_user.id
        o.driver_name = q.from_user.full_name or ""
        o.driver_username = f"@{q.from_user.username}" if q.from_user.username else ""
        update_order(o)

        if context.job_queue:
            delete_job(context.job_queue, remind_job_name(order_id))

        try:
            if o.group_message_id:
                await context.bot.edit_message_text(
                    chat_id=ALLOWED_CHAT_ID,
                    message_id=o.group_message_id,
                    message_thread_id=TAXI_TOPIC_ID,
                    text=order_card_text(o),
                    reply_markup=order_keyboard(o),
                    disable_web_page_preview=True,
                )
        except Exception:
            pass

        try:
            driver_disp = o.driver_username or o.driver_name or "Haydovchi"
            await context.bot.send_message(
                chat_id=o.user_id,
                text=(
                    "✅ Haydovchi topildi!\n"
                    f"🚖 Haydovchi: {driver_disp}\n\n"
                    "Aloqa uchun haydovchiga yozing."
                ),
            )
        except Exception:
            pass

        try:
            passenger_disp = o.username_confirm or o.user_username or o.user_name
            lines = [
                "✅ Siz buyurtmani qabul qildingiz.",
                f"👤 Mijoz: {passenger_disp}",
                f"💰 Narx: {o.price_text or 'Kelishilgan narxda'}",
            ]
            if o.phone:
                lines.append(f"📞 Telefon: {o.phone}")
            if o.pickup_lat is not None and o.pickup_lon is not None:
                lines.append(f"📍 Pickup: {maps_link(o.pickup_lat, o.pickup_lon)}")
            lines.append(f"📍 Qayerdan: {o.pickup_text}")
            if o.drop_lat is not None and o.drop_lon is not None:
                lines.append(f"🏁 Dropoff: {maps_link(o.drop_lat, o.drop_lon)}")
            lines.append(f"🏁 Qayerga: {o.drop_text}")
            lines.append(f"👥 Odamlar: {o.people}")
            lines.append(f"⏰ Vaqt: {o.when}")

            await context.bot.send_message(chat_id=o.driver_id, text="\n".join(lines))
        except Exception:
            pass

        await q.answer("Qabul qilindi ✅")
        return

    # ========== DRIVER CANCEL (REPOST IMMEDIATELY) ==========
    if action == "driver_cancel":
        uid = q.from_user.id
        if not (uid == (o.driver_id or -1) or is_admin(uid)):
            await q.answer("Bu tugma faqat haydovchi yoki admin uchun.", show_alert=True)
            return

        if o.status != "assigned":
            await q.answer("Bu order hozir assigned emas.", show_alert=True)
            return

        o.status = "posted"
        o.driver_id = None
        o.driver_name = ""
        o.driver_username = ""
        update_order(o)

        try:
            mid = await post_order_to_group(context, o, delete_old=True)
            o.group_message_id = mid
            update_order(o)
        except Exception:
            log.exception("driver_cancel repost failed")
            await q.answer("Qayta e’lon qilishda xatolik.", show_alert=True)
            return

        schedule_reminder(context.application, o.order_id)

        try:
            await context.bot.send_message(
                chat_id=o.user_id,
                text="⚠️ Haydovchi buyurtmani bekor qildi. Buyurtma qayta e’lon qilindi, haydovchi kutilmoqda."
            )
        except Exception:
            pass

        await q.answer("Qayta e’lon qilindi ✅")
        return

    if action == "noop":
        await q.answer("Bu buyurtma band.", show_alert=False)
        return

    await q.answer()

# ================== MAIN ==================
async def on_startup(app: Application):
    reschedule_all_posted(app)

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(on_startup).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("taksi", taxi_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))

    app.add_handler(CommandHandler("setinterval", setinterval_cmd))
    app.add_handler(CommandHandler("setprice", setprice_cmd))

    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & (filters.TEXT | filters.LOCATION | filters.CONTACT), private_router))
    app.add_handler(CallbackQueryHandler(on_callback))

    log.info(
        "✅ Taksi bot ishga tushdi. ALLOWED_CHAT_ID=%s TAXI_TOPIC_ID=%s remind=%smin",
        ALLOWED_CHAT_ID,
        TAXI_TOPIC_ID,
        get_remind_every_sec() // 60,
    )
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
