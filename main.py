import asyncio
import random
import os
import threading
from flask import Flask
from threading import Thread

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    PollAnswerHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

# ─────────────────────────────────────────────
# FLASK WEB SERVER (Heartbeat for Render/Hosting)
# ─────────────────────────────────────────────
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run_web_server():
    # Render provides a PORT environment variable automatically
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.daemon = True # Ensures thread dies when main process exits
    t.start()

# ─────────────────────────────────────────────
# CONSTANTS & CONFIG
# ─────────────────────────────────────────────
TOKEN = os.getenv("TOKEN")
NAME, GROUP, SUBJECT, QUIZ = range(4)

# ─────────────────────────────────────────────
# LOAD QUESTIONS
# ─────────────────────────────────────────────
def load_questions(file_path: str) -> list:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw = f.readlines()
    except FileNotFoundError:
        print(f"[WARN] Not found: {file_path}")
        return []

    questions = []
    block = []
    for line in raw:
        stripped = line.strip()
        if stripped == "":
            if len(block) == 5:
                questions.append({
                    "question": block[0][:255],
                    "options":  [b[:100] for b in block[1:5]],
                })
            block = []
        else:
            block.append(stripped)

    if len(block) == 5:
        questions.append({
            "question": block[0][:255],
            "options":  [b[:100] for b in block[1:5]],
        })
    return questions

# Load all subjects
SUBJECTS = {
    "Anesthesia":          load_questions("Anesthesiology and Resuscitation.txt"),
    "Pharmacology":        load_questions("Clinical Pharmacology.txt"),
    "Dermatology":         load_questions("Dermatovenerology.txt"),
    "ENT":                 load_questions("ENT.txt"),
    "Gynecology":          load_questions("Gynecology.txt"),
    "Infectious Diseases": load_questions("Infectious diseases.txt"),
    "Internal Medicine":   load_questions("Internal Medicine.txt"),
    "Neurology":           load_questions("Neurology.txt"),
    "Neurosurgery":        load_questions("Neurosurgery.txt"),
    "Oncology":            load_questions("Oncology.txt"),
    "Pediatrics":          load_questions("Pediatrics.txt"),
    "Psychiatry":          load_questions("Psychiatry.txt"),
    "Public Health":       load_questions("Public health.txt"),
    "TB":                  load_questions("TB.txt"),
    "Urology":             load_questions("Urology.txt"),
}

# ─────────────────────────────────────────────
# KEYBOARDS & HELPERS
# ─────────────────────────────────────────────
def subject_keyboard() -> InlineKeyboardMarkup:
    keys = list(SUBJECTS.keys())
    rows = []
    for i in range(0, len(keys), 2):
        row = [InlineKeyboardButton(keys[i], callback_data=f"subj|{keys[i]}")]
        if i + 1 < len(keys):
            row.append(InlineKeyboardButton(keys[i+1], callback_data=f"subj|{keys[i+1]}"))
        rows.append(row)
    return InlineKeyboardMarkup(rows)

def stop_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🛑 End Quiz", callback_data="end_quiz")]])

def get_session(context, user_id): return context.bot_data.get(f"session_{user_id}")
def set_session(context, user_id, data): context.bot_data[f"session_{user_id}"] = data
def clear_session(context, user_id): context.bot_data.pop(f"session_{user_id}", None)

# ─────────────────────────────────────────────
# CORE BOT LOGIC (Polls, Scores, Conv)
# ─────────────────────────────────────────────
async def show_final_score(ud: dict, context: ContextTypes.DEFAULT_TYPE):
    score, total = ud["score"], max(ud["index"], 1)
    pct = round(score / total * 100)
    grade = "🏆 Excellent!" if pct >= 90 else "👍 Good job!" if pct >= 70 else "📖 Keep practicing!"
    text = f"🏁 *Quiz Result*\n\n👤 {ud['name']} | Group: {ud['group']}\n📚 Subject: {ud['subject']}\n✅ Score: {score}/{total} ({pct}%)\n{grade}"
    try:
        await context.bot.send_message(ud["user_id"], text, parse_mode="Markdown")
    except:
        await context.bot.send_message(ud["chat_id"], text, parse_mode="Markdown")
    ud["active"] = False

async def send_question(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    ud = get_session(context, user_id)
    if not ud: return
    idx, qs, chat_id = ud["index"], ud["questions"], ud["chat_id"]
    if idx >= len(qs):
        await show_final_score(ud, context)
        return
    q = qs[idx]
    options = q["options"].copy()
    correct = options[0]
    random.shuffle(options)
    msg = await context.bot.send_poll(
        chat_id=chat_id, question=f"Q{idx+1}/{len(qs)}: {q['question']}"[:255],
        options=options, type="quiz", correct_option_id=options.index(correct), is_anonymous=False
    )
    await context.bot.send_message(chat_id, "─────────────", reply_markup=stop_keyboard())
    context.bot_data[f"poll_{msg.poll.id}"] = {"user_id": user_id, "correct": correct, "options": options}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_session(context, update.effective_user.id)
    await update.message.reply_text("👋 *Welcome to CBT Bot!*\n\nEnter your *name*:", parse_mode="Markdown")
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("Enter your *group*:", parse_mode="Markdown")
    return GROUP

async def get_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["group"] = update.message.text.strip()
    await update.message.reply_text("📚 *Choose a subject:*", parse_mode="Markdown", reply_markup=subject_keyboard())
    return SUBJECT

async def select_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not query.data.startswith("subj|"): return SUBJECT
    subject = query.data.split("|")[1]
    questions = SUBJECTS[subject].copy()
    random.shuffle(questions)
    set_session(context, query.from_user.id, {
        "name": context.user_data.get("name", "Student"), "group": context.user_data.get("group", "-"),
        "subject": subject, "questions": questions, "index": 0, "score": 0,
        "chat_id": query.message.chat_id, "user_id": query.from_user.id, "active": True
    })
    await query.edit_message_text(f"🚀 *{subject} Quiz Starting!*", parse_mode="Markdown")
    await send_question(query.from_user.id, context)
    return QUIZ

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll_answer = update.poll_answer
    poll_meta = context.bot_data.pop(f"poll_{poll_answer.poll_id}", None)
    if not poll_meta: return
    ud = get_session(context, poll_answer.user.id)
    if not ud or not ud.get("active"): return
    chosen = poll_meta["options"][poll_answer.option_ids[0]]
    ud["index"] += 1
    if chosen == poll_meta["correct"]:
        ud["score"] += 1
        await context.bot.send_message(ud["chat_id"], "✅ Correct!")
    else:
        await context.bot.send_message(ud["chat_id"], f"❌ Wrong!\n✔ *Correct:* {poll_meta['correct']}", parse_mode="Markdown")
    await send_question(poll_answer.user.id, context)

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = get_session(context, update.effective_user.id)
    if ud and ud.get("active"): await show_final_score(ud, context)
    return ConversationHandler.END

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    if not TOKEN:
        raise ValueError("TOKEN environment variable is not set!")

    # 1. Start Web Server
    print("Starting Flask heartbeat server...")
    keep_alive()

    # 2. Start Bot
    print("Bot starting...")
    app_bot = ApplicationBuilder().token(TOKEN).build()

    app_bot.add_handler(PollAnswerHandler(handle_answer), group=0)
    
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            GROUP:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_group)],
            SUBJECT: [CallbackQueryHandler(select_subject, pattern=r"^subj\|")],
            QUIZ:    [],
        },
        fallbacks=[CommandHandler("stop", stop)],
        per_message=False,
        allow_reentry=True,
    )
    app_bot.add_handler(conv, group=1)
    app_bot.add_handler(CallbackQueryHandler(stop, pattern="^end_quiz$"), group=0)

    print("Bot running...")
    app_bot.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()