from __future__ import annotations

import ast
import importlib.util
import pkgutil

# Python 3.14: legacy AST node aliases removed. Werkzeug still expects them.
if not hasattr(ast, "Str"):
    ast.Str = ast.Constant  # type: ignore[attr-defined]
if not hasattr(ast, "Bytes"):
    ast.Bytes = ast.Constant  # type: ignore[attr-defined]
if not hasattr(ast, "Num"):
    ast.Num = ast.Constant  # type: ignore[attr-defined]
if not hasattr(ast, "NameConstant"):
    ast.NameConstant = ast.Constant  # type: ignore[attr-defined]

# Provide legacy attribute access on ast.Constant for older AST APIs.
if not hasattr(ast.Constant, "s"):
    def _get_s(self):
        return self.value

    def _set_s(self, value):
        self.value = value

    ast.Constant.s = property(_get_s, _set_s)  # type: ignore[attr-defined]

if not hasattr(ast.Constant, "n"):
    def _get_n(self):
        return self.value

    def _set_n(self, value):
        self.value = value

    ast.Constant.n = property(_get_n, _set_n)  # type: ignore[attr-defined]

# Flask 3.0 + Python 3.14 compatibility: pkgutil.get_loader was removed.
if not hasattr(pkgutil, "get_loader"):
    def _get_loader(name: str):
        try:
            spec = importlib.util.find_spec(name)
        except (ValueError, ImportError):
            return None
        return spec.loader if spec else None

    pkgutil.get_loader = _get_loader  # type: ignore[attr-defined]

from flask import Flask
from reactpy.backend.flask import Options, configure

from config import FLASK_DEBUG, PORT, RUN_DB_INIT
from db import close_db, get_db_pool, init_db
from routes.api import register_api_routes
from ui.components import APP_HEAD, App


app = Flask(__name__)
app.teardown_appcontext(close_db)


def maybe_init_db_on_startup() -> None:
    """Optionally initialize/upgrade schema at process startup.

    IMPORTANT: Do not run schema changes on the request path; it can cause slow first loads
    and unstable interactive sessions. To run once, set RUN_DB_INIT=1, restart the app,
    then set RUN_DB_INIT=0 again.
    """
    if not RUN_DB_INIT:
        return

    db = None
    try:
        db = get_db_pool().getconn()
        init_db(db)
    finally:
        if db is not None:
            try:
                db.rollback()
            except Exception:
                pass
            get_db_pool().putconn(db)


register_api_routes(app)
maybe_init_db_on_startup()

configure(
    app,
    App,
    Options(head=APP_HEAD),
)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=FLASK_DEBUG,
    )
