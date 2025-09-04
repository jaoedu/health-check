from contextlib import asynccontextmanager, suppress
from time import perf_counter
import asyncio
from typing import Dict

from fastapi import FastAPI, HTTPException, status
from loguru import logger


# ----------------------------
# App & Lifespan
# ----------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Startup: inicializando aplicação")
    # Estados da aplicação
    app.state.dep_ok = True  # simula “dependência” (ex.: DB) ligada
    app.state.model_ready = False  # simula carga de recurso pesado

    # Carrega algo em background sem bloquear readiness imediatamente
    async def load_heavy_resource():
        await asyncio.sleep(3)  # simula carga
        app.state.model_ready = True
        logger.info("✅ Recurso pesado carregado (model_ready=True)")

    bg_task = asyncio.create_task(load_heavy_resource())

    try:
        yield
    finally:
        logger.info("🛑 Shutdown: finalizando aplicação")
        bg_task.cancel()
        with suppress(asyncio.CancelledError):
            await bg_task


app = FastAPI(
    title="HealthCheck Demo",
    version="1.0.0",
    description="Endpoints de liveness/readiness com simulação de dependência.",
    lifespan=lifespan,
)


# ----------------------------
# Helpers
# ----------------------------
async def check_dependency(app: FastAPI) -> None:
    """
    Simula verificação de uma dependência (DB/Redis/etc)
    """
    await asyncio.sleep(0.05)  # simula latência
    if not app.state.dep_ok:
        raise RuntimeError("Dependência simulada fora do ar")


async def check_model_loaded(app: FastAPI) -> None:
    """
    Exemplo de condição interna (modelo de ML carregado).
    """
    if not app.state.model_ready:
        raise RuntimeError("Modelo ainda carregando")


async def gather_with_timeout(timeout: float, *aws) -> None:
    """
    Executa checagens em paralelo com timeout.
    Cancela o que sobrou se uma falhar/estourar tempo.
    """
    tasks = [asyncio.create_task(coro) for coro in aws]
    try:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=timeout)
    except Exception:
        for t in tasks:
            if not t.done():
                t.cancel()
                with suppress(asyncio.CancelledError):
                    await t
        raise


def ok(payload: Dict) -> Dict:
    base = {"status": "pass", "version": app.version}
    base.update(payload)
    return base


def fail(detail: str) -> HTTPException:
    # 503 comunica “indisponível temporário” (readiness não ok)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"status": "fail", "reason": detail},
    )


# ----------------------------
# Endpoints de Health
# ----------------------------
@app.get("/health/live", tags=["Health"])
async def liveness():
    # Liveness deve ser leve: nada de dependências externas aqui.
    return ok({"checks": [{"name": "process", "status": "pass"}]})


@app.get("/health/ready", tags=["Health"])
async def readiness():
    t0 = perf_counter()
    try:
        # Exemplo: dependencia externa + modelo carregado
        await gather_with_timeout(
            1.5,
            check_dependency(app),
            check_model_loaded(app),
        )
        dt_ms = round((perf_counter() - t0) * 1000, 2)
        return ok(
            {
                "checks": [
                    {"name": "dependency", "status": "pass"},
                    {"name": "model_loaded", "status": "pass"},
                ],
                "latency_ms": dt_ms,
            }
        )
    except Exception as exc:
        logger.error(f"Readiness FAIL: {exc}")
        raise fail(str(exc))


# ----------------------------
# Endpoints de DEMO (simular falha/recuperar)
# ----------------------------
@app.post("/admin/dep/down", tags=["Admin (Demo)"], status_code=204)
async def admin_dep_down():
    app.state.dep_ok = False
    logger.warning("💥 Dependência simulada: DOWN")
    return None


@app.post("/admin/dep/up", tags=["Admin (Demo)"], status_code=204)
async def admin_dep_up():
    app.state.dep_ok = True
    logger.info("🧯 Dependência simulada: UP")
    return None
