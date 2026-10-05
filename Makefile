.PHONY: up down logs test lint fmt migrate makemigrations seed shell superuser

# Всё гоняется в контейнере: так же, как в CI
RUN = docker compose run --rm --user root --entrypoint sh web -c

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f web

test:
	$(RUN) "pytest"

lint:
	$(RUN) "ruff check ."

fmt:
	$(RUN) "ruff check --fix ."

migrate:
	$(RUN) "python manage.py migrate"

makemigrations:
	$(RUN) "python manage.py makemigrations"

# Группы прав, двое сотрудников и десяток заявок
seed:
	$(RUN) "python manage.py seed_demo"

superuser:
	docker compose exec web python manage.py createsuperuser

shell:
	docker compose exec web python manage.py shell
