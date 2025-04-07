# LXMFY Weather Bot

An LXMFY bot that provides weather information for a given location using Open-Meteo's API.

## Usage

```bash
poetry install
poetry run python bot.py
```

or 

```bash
poetry run python bot.py --debug
```

## Docker

```bash
docker build -t weather-bot .
docker run -d --name weather-bot weather-bot
```

## Docker Compose

```bash
docker-compose up -d
```
