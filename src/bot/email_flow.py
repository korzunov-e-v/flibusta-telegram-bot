from pydantic import ValidationError
from telegram import Update

from src import mailer
from src.bot import texts, throttle, verification
from src.bot.delivery import DAY, deliver_book
from src.bot.helpers import Context, get_user_data
from src.custom_logging import get_logger
from src.database import crud
from src.schemas import EmailData

logger = get_logger(__name__)


def parse_email(text: str) -> str | None:
    try:
        return str(EmailData(email=text.strip()).email)
    except ValidationError:
        return None


async def begin_verification(
    update: Update,
    context: Context,
    email: str,
    *,
    book_id: str | None = None,
    book_format: str | None = None,
) -> None:
    """Отправляет код на адрес и переводит диалог в ожидание кода."""
    message = update.effective_message
    user = update.effective_user

    if message is None or user is None:
        return

    sent_codes = await crud.count_sent_emails(user.id, crud.KIND_CODE, DAY)

    if sent_codes >= verification.MAX_CODES_PER_DAY:
        await message.reply_text(texts.EMAIL_CODE_LIMIT)
        return

    code = verification.generate_code()
    log_extra = {"user_id": user.id, "email": mailer.mask_email(email)}

    # в лимит идёт сама попытка: письмо могло уйти, даже если SMTP вернул ошибку
    await crud.log_sent_email(user.id, crud.KIND_CODE)

    try:
        await mailer.send_code(code, email)
    except Exception:
        logger.exception("Verification email send error", extra=log_extra)
        await message.reply_text(texts.EMAIL_CODE_SEND_FAILED)
        return

    verification.await_code(
        get_user_data(context),
        email=email,
        code=code,
        book_id=book_id,
        book_format=book_format,
    )
    logger.info("Verification code sent", extra=log_extra)

    await message.reply_text(
        texts.EMAIL_CODE_SENT.format(email=email, minutes=verification.CODE_TTL // 60)
    )


async def handle_email_input(
    update: Update,
    context: Context,
    flow: verification.EmailFlow,
    text: str,
) -> None:
    message = update.effective_message

    if message is None:
        return

    email = parse_email(text)

    if email is None:
        await message.reply_text(texts.EMAIL_INVALID_RETRY)
        return

    await begin_verification(
        update,
        context,
        email,
        book_id=flow.book_id,
        book_format=flow.book_format,
    )


async def handle_code_input(update: Update, context: Context, text: str) -> None:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if message is None or user is None or chat is None:
        return

    result, flow = verification.check_code(get_user_data(context), text)

    if result is verification.CodeCheck.EXPIRED or flow is None:
        await message.reply_text(texts.EMAIL_CODE_EXPIRED)
        return

    if result is verification.CodeCheck.EXHAUSTED:
        await message.reply_text(texts.EMAIL_CODE_EXHAUSTED)
        return

    if result is verification.CodeCheck.WRONG:
        await message.reply_text(texts.EMAIL_CODE_WRONG.format(left=flow.attempts_left))
        return

    await crud.set_email(user.id, flow.email)
    logger.info(
        "Email verified",
        extra={"user_id": user.id, "email": mailer.mask_email(flow.email)},
    )

    await message.reply_text(texts.EMAIL_SAVED.format(email=flow.email))

    if flow.book_id and flow.book_format:
        with throttle.heavy.slot(user.id):
            await deliver_book(
                context,
                chat_id=chat.id,
                user_id=user.id,
                mode="email",
                book_id=flow.book_id,
                book_format=flow.book_format,
            )
