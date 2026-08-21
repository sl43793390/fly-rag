from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI
# from llama_index import SimpleDirectoryReader, VectorStoreIndex, SimpleDirectoryReader

from llama_index.core.agent.workflow import FunctionAgent

client = OpenAI(
    model_name="deepseek-v4-flash-0731",
    api_key="sk-jXUqP7ZDLe04UyydraigPomfC4TQPZmCz7MwLcRLKBVjHrQJ",
    api_base="https://www.dmxapi.cn/v1",
)
# response = client.complete("你好")
# print(response)


def multiply(a: float, b: float) -> float:
    """Multiply two numbers and returns the product"""
    return a * b
def add(a: float, b: float) -> float:
    """Add two numbers and returns the sum"""
    return a + b

### =====================agent 可以使用 multiply 和 add 函数===================
# workflow = FunctionAgent(
#     tools=[multiply, add],
#     llm=client,
#     system_prompt="You are an agent that can perform basic mathematical operations using tools.",
# )
# async def main():
#     response = await workflow.run(user_msg="What is 20+(2*4)?")
#     print(response)
# import asyncio
# asyncio.run(main())






















