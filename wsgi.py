"""容器启动入口：gunicorn 以 /workspace 包根加载 app 工厂。"""
from app import create_app

application = create_app()

if __name__ == "__main__":
    application.run(host="0.0.0.0", port=8000)
