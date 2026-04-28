import asyncio
import random

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

import os
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise ValueError("TOKEN environment variable is not set!")

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

    print(f"[OK] {file_path} → {len(questions)} questions")
    return questions


# ─────────────────────────────────────────────
# SUBJECTS
# ─────────────────────────────────────────────
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
# KEYBOARDS
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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛑 End Quiz", callback_data="end_quiz")]
    ])


# ─────────────────────────────────────────────
# SESSION HELPERS
# ─────────────────────────────────────────────
def get_session(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> dict | None:
    return context.bot_data.get(f"session_{user_id}")

def set_session(context: ContextTypes.DEFAULT_TYPE, user_id: int, data: dict):
    context.bot_data[f"session_{user_id}"] = data

def clear_session(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    context.bot_data.pop(f"session_{user_id}", None)


# ─────────────────────────────────────────────
# SHOW FINAL SCORE — private DM only
# ─────────────────────────────────────────────
async def show_final_score(ud: dict, context: ContextTypes.DEFAULT_TYPE):
    score = ud["score"]
    total = max(ud["index"], 1)
    pct   = round(score / total * 100)
    grade = (
        "🏆 Excellent!"       if pct >= 90 else
        "👍 Good job!"        if pct >= 70 else
        "📖 Keep practicing!"
    )
    try:
        await context.bot.send_message(
            ud["user_id"],
            f"🏁 *Quiz Result*\n\n"
            f"👤 {ud['name']}  |  Group: {ud['group']}\n"
            f"📚 Subject: {ud['subject']}\n"
            f"✅ Score: {score}/{total} ({pct}%)\n"
            f"{grade}\n\n"
            f"Send /start for another quiz!",
            parse_mode="Markdown",
        )
    except Exception as e:
        print(f"[ERROR] Could not send private score: {e}")
        # Fallback — send in chat if private message fails
        await context.bot.send_message(
            ud["chat_id"],
            f"✅ *Your score:* {score}/{total} ({pct}%) — {grade}",
            parse_mode="Markdown",
        )
    ud["active"] = False


# ─────────────────────────────────────────────
# SEND QUESTION
# ─────────────────────────────────────────────
async def send_question(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        ud = get_session(context, user_id)
        if not ud:
            print(f"[ERROR] No session for user {user_id}")
            return

        idx     = ud["index"]
        qs      = ud["questions"]
        chat_id = ud["chat_id"]

        print(f"[DEBUG] Sending Q{idx+1}/{len(qs)} to user={user_id}")

        if idx >= len(qs):
            await show_final_score(ud, context)
            return

        q       = qs[idx]
        options = q["options"].copy()
        correct = options[0]
        random.shuffle(options)

        q_text = f"Q{idx+1}/{len(qs)}: {q['question']}"
        if len(q_text) > 255:
            q_text = q_text[:255]

        msg = await context.bot.send_poll(
            chat_id           = chat_id,
            question          = q_text,
            options           = options,
            type              = "quiz",
            correct_option_id = options.index(correct),
            is_anonymous      = False,
        )

        await context.bot.send_message(
            chat_id,
            "─────────────",
            reply_markup=stop_keyboard(),
        )

        print(f"[DEBUG] Poll sent — poll_id={msg.poll.id}")

        context.bot_data[f"poll_{msg.poll.id}"] = {
            "user_id":  user_id,
            "correct":  correct,
            "options":  options,
            "question": q["question"],
        }

    except Exception as e:
        print(f"[EXCEPTION send_question] {e}")
        import traceback; traceback.print_exc()


# ─────────────────────────────────────────────
# CONVERSATION STEPS
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Clear any old session on fresh start
    clear_session(context, user_id)
    context.user_data.clear()

    await update.message.reply_text(
        "👋 *Welcome to Yaseen's CBT Bot!*\n\nEnter your *name*:",
        parse_mode="Markdown",
    )
    return NAME


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Please enter a valid name:")
        return NAME
    context.user_data["name"] = name
    await update.message.reply_text("Enter your *group*:", parse_mode="Markdown")
    return GROUP


async def get_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group = update.message.text.strip()
    if not group:
        await update.message.reply_text("Please enter a valid group:")
        return GROUP
    context.user_data["group"] = group
    await update.message.reply_text(
        "📚 *Choose a subject:*",
        parse_mode="Markdown",
        reply_markup=subject_keyboard(),
    )
    return SUBJECT


async def select_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    # ── Stale button from before bot restart ──────────────────────
    # If we receive a subject tap but conv state is not SUBJECT,
    # it means the bot restarted. Tell user to /start again.
    if not data.startswith("subj|"):
        await query.answer("Please send /start first.", show_alert=True)
        return SUBJECT

    subject = data.split("|")[1]
    print(f"[DEBUG] Subject tapped: {subject}")

    if subject not in SUBJECTS or not SUBJECTS[subject]:
        await query.edit_message_text(
            f"❌ No questions for *{subject}*. Pick another:",
            parse_mode="Markdown",
            reply_markup=subject_keyboard(),
        )
        return SUBJECT

    user_id   = query.from_user.id
    questions = SUBJECTS[subject].copy()
    random.shuffle(questions)

    set_session(context, user_id, {
        "name":      context.user_data.get("name", "Student"),
        "group":     context.user_data.get("group", "-"),
        "subject":   subject,
        "questions": questions,
        "index":     0,
        "score":     0,
        "chat_id":   query.message.chat_id,
        "user_id":   user_id,
        "active":    True,
    })

    print(f"[DEBUG] Session created: user={user_id} subject={subject} count={len(questions)}")

    await query.edit_message_text(
        f"🚀 *{subject} Quiz Starting!*\n📝 {len(questions)} questions. Good luck!",
        parse_mode="Markdown",
    )

    await send_question(user_id, context)
    return QUIZ


# ─────────────────────────────────────────────
# STALE BUTTON HANDLER — catches old taps after restart
# registered in group=0 so it always fires
# ─────────────────────────────────────────────
async def handle_stale_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    data    = query.data or ""
    user_id = query.from_user.id
    ud      = get_session(context, user_id)

    # If it's a subject button but no active conv session exists
    if data.startswith("subj|") and not ud:
        await query.answer(
            "⚠️ Bot was restarted. Please send /start to begin.",
            show_alert=True,
        )
        await query.edit_message_text(
            "⚠️ *Bot was restarted.*\n\nPlease send /start to begin a new quiz.",
            parse_mode="Markdown",
        )
        return

    # If it's an end_quiz button but no active session
    if data == "end_quiz" and (not ud or not ud.get("active")):
        await query.answer(
            "⚠️ No active quiz. Send /start to begin.",
            show_alert=True,
        )
        await query.edit_message_text("⚠️ No active quiz found.")
        return


# ─────────────────────────────────────────────
# END QUIZ BUTTON
# ─────────────────────────────────────────────
async def end_quiz_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    ud      = get_session(context, user_id)

    if not ud or not ud.get("active"):
        await query.edit_message_text(
            "⚠️ No active quiz. Send /start to begin."
        )
        return

    await query.edit_message_text("🛑 Quiz ended.")
    await show_final_score(ud, context)


# ─────────────────────────────────────────────
# /stop COMMAND
# ─────────────────────────────────────────────
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ud      = get_session(context, user_id)
    if ud and ud.get("active"):
        await show_final_score(ud, context)
    else:
        await update.message.reply_text(
            "⚠️ No active quiz. Send /start to begin."
        )
    return ConversationHandler.END


# ─────────────────────────────────────────────
# POLL ANSWER HANDLER — group=0
# ─────────────────────────────────────────────
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        poll_answer = update.poll_answer
        poll_id     = poll_answer.poll_id
        user_id     = poll_answer.user.id

        print(f"[DEBUG] Answer received poll_id={poll_id} user={user_id}")

        poll_meta = context.bot_data.pop(f"poll_{poll_id}", None)
        if not poll_meta:
            # Bot restarted mid-quiz — poll data lost
            print(f"[WARN] poll_id not found — bot likely restarted mid-quiz")
            try:
                await context.bot.send_message(
                    poll_answer.user.id,
                    "⚠️ Bot was restarted. Your quiz session was lost.\n"
                    "Please send /start to begin a new quiz.",
                )
            except:
                pass
            return

        if poll_meta["user_id"] != user_id:
            return

        ud = get_session(context, user_id)
        if not ud or not ud.get("active"):
            print(f"[WARN] No active session for user={user_id}")
            return

        chosen  = poll_meta["options"][poll_answer.option_ids[0]]
        correct = poll_meta["correct"]
        chat_id = ud["chat_id"]

        ud["index"] += 1

        if chosen == correct:
            ud["score"] += 1
            await context.bot.send_message(chat_id, "✅ Correct!")
        else:
            await context.bot.send_message(
                chat_id,
                f"❌ Wrong!\n✔ *Correct:* {correct}",
                parse_mode="Markdown",
            )

        await send_question(user_id, context)

    except Exception as e:
        print(f"[EXCEPTION handle_answer] {e}")
        import traceback; traceback.print_exc()


# ─────────────────────────────────────────────
# /debug
# ─────────────────────────────────────────────
async def debug_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["*Questions loaded:*\n"]
    for name, qs in SUBJECTS.items():
        icon = "✅" if qs else "❌"
        lines.append(f"{icon} {name}: {len(qs)}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print("Bot starting...")

    app = ApplicationBuilder().token(TOKEN).build()

    # ── group=0 handlers — fire before ConversationHandler ────────
    app.add_handler(PollAnswerHandler(handle_answer), group=0)
    app.add_handler(CommandHandler("debug", debug_cmd), group=0)
    app.add_handler(CallbackQueryHandler(end_quiz_button,    pattern=r"^end_quiz$"), group=0)
    app.add_handler(CallbackQueryHandler(handle_stale_button, pattern=r"^(subj\||end_quiz)"), group=0)

    # ── ConversationHandler ───────────────────────────────────────
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
        allow_reentry=True,   # ← /start always works from any state
    )

    app.add_handler(conv, group=1)

    print("Bot running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()