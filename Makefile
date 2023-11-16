build:
	docker compose -f docker-compose.yml build
up:
	docker compose -f docker-compose.yml up -d
down:
	docker compose -f docker-compose.yml down
logs:
	docker compose -f docker-compose.yml logs --tail=100 -f flibusta-tg-bot
restart:
	docker compose -f docker-compose.yml restart flibusta-tg-bot
exec:
	docker compose -f docker-compose.yml exec flibusta-tg-bot /bin/sh

