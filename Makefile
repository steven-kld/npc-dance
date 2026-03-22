.PHONY: up down logs chat

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

chat:
	python3 chat.py
