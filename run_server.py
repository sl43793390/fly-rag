"""
run_server
~~~~~~~~~~
API 服务启动入口(等价于 uvicorn api.main:app)。

用法::

    python run_server.py            # 默认 0.0.0.0:8000
    set API_PORT=9000 && python run_server.py
"""
import uvicorn

from api.api_config import API_HOST, API_PORT

if __name__ == "__main__":
    uvicorn.run("api.main:app", host=API_HOST, port=API_PORT, reload=False)
