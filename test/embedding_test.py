
from openai import OpenAI
from openai.types import embedding

import os

def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)

client = OpenAI(
    api_key=_env("OPENAI_API_KEY", "sk"),
    base_url=_env("OPENAI_BASE_URL", "https://www.dmxapi.cn/v1")
)
res = client.embeddings.create(
    model="text-embedding-3-small",
    input=["你好"])
    
print(len(res.data[0].embedding))
print(res.data[0].embedding)



















