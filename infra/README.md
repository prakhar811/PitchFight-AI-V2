# Local infrastructure

PostgreSQL, MongoDB, and Redis run locally via Docker Compose. FastAPI stays on the host and connects through `localhost`.

## 1. Prerequisite

Docker Desktop must be running.

## 2. Create a local environment file if needed

From the repository root:

```powershell
Copy-Item .env.example .env
```

Do not overwrite an existing `.env`. Do not commit `.env`.

## 3. Validate Compose configuration

```powershell
docker compose config
```

## 4. Start infrastructure

```powershell
docker compose up -d
```

## 5. View service state

```powershell
docker compose ps
```

Expected containers: `pitchfight-postgres`, `pitchfight-mongo`, `pitchfight-redis`.

## 6. View logs

```powershell
docker compose logs postgres
docker compose logs mongo
docker compose logs redis
```

## 7. Stop containers without deleting data

```powershell
docker compose stop
```

## 8. Restart

```powershell
docker compose start
```

## 9. Stop/remove containers while keeping named volumes

```powershell
docker compose down
```

Named volumes (`pitchfight_postgres_data`, `pitchfight_mongo_data`, `pitchfight_redis_data`) are kept.

## 10. Warning: deleting data

```powershell
docker compose down -v
```

This **deletes** the database volumes and all stored data. Do not use it casually.
