# 📚 Flibusta Telegram Bot

Telegram-бот для поиска и скачивания книг с Flibusta.

### Возможности

* 🔍 Поиск книг по названию и автору
* 📖 Просмотр информации и аннотации
* ⬇️ Скачивание в `fb2`, `epub`, `mobi`, `pdf`, `djvu`
* 📩 Отправка книг на E-mail
* 💾 Хранение E-mail пользователей в PostgreSQL
* 🐳 Запуск через Docker Compose

### Запуск

```bash
git clone https://github.com/korzunov-e-v/flibusta-telegram-bot.git
cd flibusta-telegram-bot
```

Создайте `.env`:

```env
TOKEN=your_telegram_bot_token
ADMINS=your_telegram_id

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASS=your_app_password

POSTGRES_DB=flibusta
POSTGRES_USER=flibusta
POSTGRES_PASSWORD=change_me
DATABASE_URL=postgresql://flibusta:change_me@postgres:5432/flibusta
```

Запустите:

```bash
docker compose up -d --build
```

PostgreSQL хранит данные в Docker volume, поэтому данные пользователей не пропадают при пересоздании контейнеров.

### Команды бота

```text
/start   — начать работу
/help    — справка
/email   — посмотреть или изменить E-mail
```
