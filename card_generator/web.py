"""One-page web form: uvicorn card_generator.web:app"""

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from card_generator.llm import LLM, GigaChatClient, LazyClient, LLMError
from card_generator.pipeline import make_card
from card_generator.render import to_dict, to_markdown
from card_generator.schema import InputError

PAGE = Path(__file__).resolve().parent / "static" / "index.html"


def create_app(llm_factory: Callable[[], LLM] = GigaChatClient.from_env) -> FastAPI:
    app = FastAPI(title="Черновик карточки КИП")
    llm = LazyClient(llm_factory)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return PAGE.read_text(encoding="utf-8")

    @app.post("/api/card")
    async def card(request: Request, draft_anyway: bool = False):
        raw = await request.body()
        try:
            # The model call takes seconds; keep it off the event loop.
            result = await run_in_threadpool(make_card, raw, llm, None, draft_anyway)
        except InputError as exc:
            return JSONResponse({"errors": exc.messages}, status_code=422)
        except LLMError as exc:
            return JSONResponse({"errors": [f"Ошибка модели: {exc}"]}, status_code=502)
        return {**to_dict(result), "markdown": to_markdown(result)}

    return app


app = create_app()
