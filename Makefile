.PHONY: install lint format run clean

install:
	poetry install

lint:
	poetry run ruff check .

format:
	poetry run ruff format .

run:
	poetry run weather-bot

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
