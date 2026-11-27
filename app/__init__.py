"""Flask 演练页：单命名空间 NetworkPolicy 等价清理。"""
from __future__ import annotations

from flask import Flask, render_template, request

from .parser import FormError, MAX_POLICIES, parse_form
from .seed import seed_view, view_from_form
from .solver import solve


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_POLICIES"] = MAX_POLICIES

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            view=seed_view(),
            result=None,
            error=None,
            max_policies=MAX_POLICIES,
        )

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post("/clean")
    def clean():
        view = view_from_form(request.form)
        try:
            pods, policies, deletable = parse_form(request.form)
            result = solve(pods, policies, deletable)
        except FormError as exc:
            return (
                render_template(
                    "index.html",
                    view=view,
                    result=None,
                    error=str(exc),
                    max_policies=MAX_POLICIES,
                ),
                400,
            )
        # 清理后仍保留完整录入区（标签可继续修改），结果区展示删除项与前后矩阵
        return render_template(
            "index.html",
            view=view,
            result=result,
            error=None,
            max_policies=MAX_POLICIES,
        )

    return app
