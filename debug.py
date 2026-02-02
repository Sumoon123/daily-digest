from dotenv import load_dotenv
from notion_client import Client
import logging

logging.basicConfig(level=logging.DEBUG)
load_dotenv()

# 尝试连接
try:
    notion = Client(auth=os.getenv("NOTION_API_KEY"))
    print("✓ Notion Client 初始化成功")
    
    # 测试查询
    db_id = os.getenv("NOTION_DATABASE_ID")
    print(f"Database ID: {db_id}")
    
    # 先不做过滤，直接查询
    print("正在测试查询...")
    response = notion.databases.query(database_id=db_id)
    print(f"✓ 查询成功！找到 {len(response['results'])} 个条目")
    
except Exception as e:
    print(f"✗ 错误: {e}")
    print(f"错误类型: {type(e).__name__}")
