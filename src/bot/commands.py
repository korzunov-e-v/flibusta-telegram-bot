from telegram import Update

from src.bot import texts, verification
from src.bot.email_flow import begin_verification, parse_email
from src.bot.helpers import Context, get_user_data
from src.database import crud
from src.settings import settings


async def start_command(update: Update, context: Context) -> None:
    if update.effective_message is None:
        return

    verification.clear(get_user_data(context))

    await update.effective_message.reply_text(texts.START)


async def help_command(update: Update, _: Context) -> None:
    if update.effective_message is None:
        return

    await update.effective_message.reply_text(
        texts.help_text(
            chat_mb=settings.max_chat_file_mb,
            email_mb=settings.max_email_file_mb,
            daily=settings.email_daily_limit,
        )
    )


async def cancel_command(update: Update, context: Context) -> None:
    if update.effective_message is None:
        return

    cancelled = verification.clear(get_user_data(context))

    await update.effective_message.reply_text(
        texts.CANCELLED if cancelled else texts.NOTHING_TO_CANCEL
    )


async def email_command(update: Update, context: Context) -> None:
    message = update.effective_message
    user = update.effective_user

    if message is None or user is None:
        return

    current = await crud.get_email(user.id)

    if not context.args:
        lines = [texts.EMAIL_CURRENT.format(email=current) if current else texts.EMAIL_NOT_SET]
        flow = verification.load(get_user_data(context))

        if flow is not None and flow.stage == verification.STAGE_CODE and not flow.expired():
            lines.append(texts.EMAIL_CODE_PENDING.format(email=flow.email))

        await message.reply_text("\n\n".join(lines))
        return

    new_email = parse_email(context.args[0])

    if new_email is None:
        await message.reply_text(texts.EMAIL_INVALID)
        return

    if new_email == current:
        await message.reply_text(texts.EMAIL_UNCHANGED.format(email=current))
        return

    await begin_verification(update, context, new_email)


async def unknown_command(update: Update, _: Context) -> None:
    if update.effective_message is None:
        return

    await update.effective_message.reply_text(texts.UNKNOWN_COMMAND)
