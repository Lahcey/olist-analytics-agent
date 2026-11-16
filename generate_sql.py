from getpass import getpass
from pathlib import Path

from openai import OpenAI


# 从项目目录读取之前准备的数据库说明
guide_path = Path(__file__).with_name("database_guide.txt")
database_guide = guide_path.read_text(encoding="utf-8-sig")

# 运行时输入密钥，不将密钥写进代码
api_key = getpass("请输入阿里云百炼 API Key：").strip()

if not api_key:
    raise ValueError("API Key 不能为空。")

# 这是阿里云百炼北京地域的兼容接口地址
client = OpenAI(
    api_key=api_key,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    timeout=60.0,
    max_retries=0,
)

question = input("请输入你的数据问题：").strip()

if not question:
    raise ValueError("问题不能为空。")

system_prompt = f"""
你是 PostgreSQL 数据分析助手。

请根据数据库说明，为用户问题生成一条 SQL。

要求：
1. 只查询说明中允许使用的视图。
2. 遵守数据库说明中的指标口径。
3. 只输出 SQL，不要输出 Markdown 代码块。
4. 如果现有数据无法回答，只输出：无法回答。
5. 不要编造字段或数据。

数据库说明：
{database_guide}
"""

response = client.chat.completions.create(
    model="qwen3.7-flash",
    messages=[
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": question,
        },
    ],
    max_tokens=600,
    extra_body={"enable_thinking": False},
)

generated_sql = response.choices[0].message.content

print("\n模型生成的内容：")
print(generated_sql)

if response.usage:
    print("\n本次 Token 用量：")
    print(f"输入：{response.usage.prompt_tokens}")
    print(f"输出：{response.usage.completion_tokens}")