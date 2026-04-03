# AGENTS.md

## Objetivo
Scrapear datos de `ufcstats.com`, mantener un dataset incremental local y publicar una base SQLite consumible por el bot UFC.

Fecha de referencia de este documento: **2026-04-03**.

## Mapa Rápido del Proyecto
- `run_ufc.py`: CLI principal.
- `scrapers/ufc/scraper.py`: scrape de peleas completadas (incremental por `state.json`).
- `scrapers/ufc/upcoming.py`: scrape de cartelera de eventos próximos.
- `scrapers/ufc/parsers.py`: parseo HTML de eventos, cartelera y pelea.
- `scrapers/ufc/models.py`: modelos de salida serializables a JSON.
- `convert_to_sqlite.py`: transforma JSONs a `data/ufc/ufc.db`.
- `deploy.sh`: runbook semanal (scrape + conversión + `scp` a servidor).

## Contratos de Datos
- `data/ufc/state.json`:
  - Clave `scraped_event_ids: string[]`.
  - Define incrementalidad para `scrape` (si un evento está acá, se salta en corridas normales).
- `data/ufc/fights.json`:
  - 1 objeto por pelea.
  - Incluye contexto de evento, metadatos de finalización, stats totales por peleador y desglose por round.
- `data/ufc/upcoming.json`:
  - 1 objeto por pelea futura (sin stats), con `card_order`.
- `data/ufc/ufc.db`:
  - `fights`: datos planos por pelea.
  - `fight_rounds`: 1 fila por round por peleador.
  - `upcoming_fights`: cartelera próxima.

## Comandos Operativos
- Setup:
  - `python3 -m venv .venv`
  - `.venv/bin/pip install -r requirements.txt`
  - `.venv/bin/playwright install chromium`
- Scrape incremental de completadas:
  - `.venv/bin/python run_ufc.py scrape --since-year 2016`
- Scrape de upcoming:
  - `.venv/bin/python run_ufc.py scrape-upcoming`
- Reprocesar evento(s) específico(s):
  - `.venv/bin/python run_ufc.py scrape --event-id <EVENT_ID>`
  - Repetible: `--event-id A --event-id B`
- Full rescrape (costoso):
  - `.venv/bin/python run_ufc.py scrape --all`
- Convertir a SQLite:
  - `.venv/bin/python convert_to_sqlite.py`
- Deploy semanal:
  - `./deploy.sh`
  - Solo convertir + subir: `./deploy.sh --skip-scrape`

## Definiciones Importantes
- `event_id`: ID del evento UFCStats (path `/event-details/{id}`).
- `fight_id`: ID de pelea UFCStats (path `/fight-details/{id}`).
- `fighter_1` / `fighter_2`: orden proveniente de tabla/evento; no asumir “esquina roja/azul”.
- `sig_str`, `total_str`, `td`, etc.: formato `{landed, attempted}`.
- `ctrl`: tiempo de control como string (ej. `1:32`), no numérico.
- `bonuses`: array de tags normalizados (`PERF`, `FIGHT`, `SUB`, `KO`).

## Estado Real Observado (2026-04-03)
- `fights`: 5103 filas.
- `fight_rounds`: 24948 filas.
- `upcoming_fights`: 78 filas.
- `scraped_event_ids`: 425.
- Hallazgo de calidad:
  - 12 peleas en `fights` sin stats (`method` vacío y métricas nulas), todas del evento `9a70f67ad2187fa3` (UFC Fight Night: Moicano vs. Duncan, **April 04, 2026**).
  - Interpretación: evento futuro entró al flujo de “completed” antes de cerrarse.

## Guardrails Operativos
- No versionar artefactos de datos grandes:
  - `data/ufc/fights.json`, `state.json`, `upcoming.json`, `ufc.db` están ignorados por git.
- No usar `--all` salvo pedido explícito.
- Correr incremental con `--since-year 2016` para costos/tiempo razonables.
- Mantener `state.json` consistente:
  - Si se quiere re-scrapear un evento ya marcado, usar `--event-id` explícito.
- Evitar depender de `ORDER BY event_date` textual en SQLite:
  - `event_date` está en formato `"Month DD, YYYY"` y ordena alfabéticamente, no cronológicamente.

## Checklist de Verificación Post-Run
- Conteos básicos:
  - `sqlite3 data/ufc/ufc.db "SELECT COUNT(*) FROM fights; SELECT COUNT(*) FROM fight_rounds; SELECT COUNT(*) FROM upcoming_fights;"`
- Detección de peleas sin stats:
  - `sqlite3 data/ufc/ufc.db "SELECT event_id,event_name,event_date,COUNT(*) FROM fights WHERE f1_sig_str_landed IS NULL GROUP BY event_id ORDER BY COUNT(*) DESC;"`
- Smoke de upcoming:
  - `sqlite3 data/ufc/ufc.db "SELECT event_name,event_date,COUNT(*) FROM upcoming_fights GROUP BY event_id ORDER BY event_date;"`

## Riesgos y Comportamientos a Tener Presentes
- Cambios de HTML en UFCStats pueden romper parseos (clases BEM, estructura de tablas).
- El parser intenta expandir secciones “Per Round”; si falla, puede quedar `rounds=[]`.
- `deploy.sh` usa ruta de key SSH local con espacios/paréntesis; no modificar sin validar quoting.
- `logs/` hoy está sin trackear; sirve para auditoría local pero no para historia git.

## Estrategia Recomendada para Cambios
- Cambios de parseo:
  - Editar en `scrapers/ufc/parsers.py`.
  - Validar con 1 evento viejo + 1 evento reciente + 1 upcoming.
- Cambios de modelo:
  - Coordinar `models.py` + `convert_to_sqlite.py` para mantener paridad JSON/DB.
- Cambios de flujo:
  - Ajustar `run_ufc.py` y `deploy.sh` en conjunto si impacta operación semanal.

## Mejoras Prioritarias Sugeridas
- Guardar adicionalmente `event_date_iso` (`YYYY-MM-DD`) para sorting/queries robustas.
- Bloquear ingestión en `fights` de eventos futuros o con stats vacías.
- Agregar tests de parsers con fixtures HTML versionados.
- Escribir JSON de forma atómica (tmp + rename) para evitar corrupción por interrupciones.
