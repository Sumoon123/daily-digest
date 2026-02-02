import os
import smtplib
import requests
import logging
import json
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime
from dotenv import load_dotenv
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor, as_completed

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 加载环境变量
load_dotenv()

# 初始化 Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# 配置
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
MODEL_NAME = "models/gemini-2.5-flash"

def get_database_info():
    """获取数据库信息（包括标题）"""
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28"
    }
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            title = data.get('title', [{}])[0].get('plain_text', '未命名')
            logging.info(f"正在查询 Notion Database: '{title}' (ID: {DATABASE_ID})")
            return title
        else:
            logging.error(f"获取数据库信息失败: {response.status_code}")
            return None
    except Exception as e:
        logging.error(f"获取数据库信息失败: {e}")
        return None

def get_page_content(page_id):
    """获取 Notion 页面的 child blocks（文章内容）"""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28"
    }
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            logging.warning(f"获取页面内容失败 {page_id}: {response.status_code}")
            return None
        
        data = response.json()
        blocks = data.get('results', [])
        
        # 提取所有文本内容
        full_text = ""
        for block in blocks:
            block_type = block.get('type', '')
            block_data = block.get(block_type, {})
            
            # 获取文本数组
            text_array = []
            if 'rich_text' in block_data:
                text_array = block_data['rich_text']
            elif 'text' in block_data:
                text_array = block_data['text']
            
            # 提取纯文本
            if text_array:
                for text_segment in text_array:
                    if 'plain_text' in text_segment:
                        full_text += text_segment['plain_text']
                full_text += "\n"
        
        return full_text.strip() if full_text else None
        
    except Exception as e:
        logging.error(f"获取页面内容失败 {page_id}: {e}")
        return None

def get_unread_articles():
    """从 Notion 获取所有状态为空、收藏类型为文章、且有内容的页面"""
    db_title = get_database_info()
    
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    
    # 查询：状态为空 且 收藏类型为"文章"
    payload = {
        "filter": {
            "and": [
                {
                    "property": "状态",
                    "multi_select": {
                        "is_empty": True
                    }
                },
                {
                    "property": "收藏类型",
                    "select": {
                        "equals": "文章"
                    }
                }
            ]
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code != 200:
            logging.error(f"Notion API 错误: {response.status_code}")
            logging.error(f"响应内容: {response.text}")
            return []
        
        data = response.json()
        pages = []
        
        for page in data['results']:
            try:
                props = page['properties']
                page_id = page['id']
                
                # 获取标题
                title = "未命名"
                if '标题' in props:
                    title_prop = props['标题']
                    if title_prop.get('title') and len(title_prop['title']) > 0:
                        title = title_prop['title'][0].get('plain_text', '未命名')
                
                # 获取原链接
                original_url = ""
                if '原链接' in props:
                    url_prop = props['原链接']
                    if url_prop.get('type') == 'url':
                        original_url = url_prop.get('url', '')
                    elif url_prop.get('type') == 'rich_text' and url_prop.get('rich_text'):
                        original_url = url_prop['rich_text'][0].get('plain_text', '')
                
                if not original_url:
                    logging.warning(f"页面 {page_id} 没有找到原链接，跳过")
                    continue

                pages.append({
                    "id": page_id,
                    "title": title,
                    "original_url": original_url
                })
            except Exception as e:
                logging.warning(f"解析页面失败: {e}")
                continue
        
        logging.info(f"找到 {len(pages)} 篇待读文章，正在获取内容...")
        
        # 并行获取所有页面的内容
        articles_with_content = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_page = {executor.submit(get_page_content, page['id']): page for page in pages}
            
            for future in as_completed(future_to_page):
                page = future_to_page[future]
                try:
                    content = future.result()
                    if content and len(content) > 50:  # 至少有50个字符才算有效内容
                        articles_with_content.append({
                            "id": page['id'],
                            "title": page['title'],
                            "original_url": page['original_url'],
                            "content": content
                        })
                        logging.info(f"✓ 获取内容成功: {page['title'][:30]}...")
                    else:
                        logging.warning(f"页面内容为空或过短: {page['title']}")
                except Exception as e:
                    logging.error(f"获取内容失败 {page['title']}: {e}")
        
        logging.info(f"成功获取 {len(articles_with_content)} 篇文章的内容")
        return articles_with_content
        
    except Exception as e:
        logging.error(f"查询 Notion 失败: {e}")
        return []

def generate_single_summary(article):
    """第一步：为单篇文章生成摘要"""
    model = genai.GenerativeModel(MODEL_NAME)
    
    prompt = f"""你是一个专业的内容摘要专家。请对以下文章进行专业、简洁的总结，提炼其核心观点（200字以内）。

文章标题：{article['title']}
文章内容：
{article['content'][:10000]}  # 限制长度避免超出token

请直接输出摘要内容，不要包含标题或其他格式。"""
    
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logging.error(f"生成摘要失败 {article['title']}: {e}")
        return f"[摘要生成失败] {article['title']}"

def generate_all_summaries(articles):
    """并行为所有文章生成摘要"""
    logging.info(f"正在为 {len(articles)} 篇文章生成摘要...")
    
    summaries = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_article = {executor.submit(generate_single_summary, article): article for article in articles}
        
        for future in as_completed(future_to_article):
            article = future_to_article[future]
            try:
                summary = future.result()
                summaries.append({
                    "title": article['title'],
                    "original_url": article['original_url'],
                    "summary": summary
                })
            except Exception as e:
                logging.error(f"处理文章失败 {article['title']}: {e}")
    
    return summaries

def generate_final_digest(summaries):
    """第二步：将所有摘要整合成每日简报"""
    if not summaries:
        return None
    
    model = genai.GenerativeModel(MODEL_NAME)
    
    # 构建所有摘要的文本
    all_summaries_text = ""
    for idx, item in enumerate(summaries, 1):
        all_summaries_text += f"\n\n## {item['title']}\n"
        all_summaries_text += f"**本篇总结：**\n{item['summary']}\n"
        all_summaries_text += f"**原文链接：** {item['original_url']}\n"
        all_summaries_text += "---\n"
    
    prompt = f"""你是一个专业的编辑，请将以下多篇文章总结，排版成一篇格式清晰、易于阅读的"每日资讯简报"。

任务要求：
1. 在开头添加一个合适的总标题（例如：📚 每日阅读简报 - {datetime.now().strftime('%Y年%m月%d日')}）和一句简短的引言（50字以内）。
2. 根据文章内容，将它们分为几个有意义的类别（例如："行业动态"、"技术分析"、"市场趋势"、"深度思考"等）。
3. 在每个类别下，列出对应的文章。
4. 每篇文章请保留其【标题】、【内容总结】和【原文链接】。
5. 使用清晰的 Markdown 格式进行美化。
6. 语言：中文

待处理的内容如下：
{all_summaries_text}

请直接输出 Markdown 格式的简报内容。"""
    
    logging.info("正在生成最终的每日简报...")
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logging.error(f"生成简报失败: {e}")
        return None

def markdown_to_html(markdown_text):
    """将 Markdown 转换为 HTML"""
    try:
        import markdown
        html = markdown.markdown(markdown_text, extensions=['tables', 'fenced_code'])
        
        # 添加基本的样式
        styled_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f7;
        }}
        h1 {{
            color: #1a1a1a;
            border-bottom: 2px solid #0066cc;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #2c2c2c;
            margin-top: 30px;
            border-left: 4px solid #0066cc;
            padding-left: 10px;
        }}
        h3 {{
            color: #444;
            margin-top: 20px;
        }}
        a {{
            color: #0066cc;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        hr {{
            border: none;
            border-top: 1px solid #ddd;
            margin: 20px 0;
        }}
        blockquote {{
            border-left: 4px solid #ddd;
            padding-left: 15px;
            color: #666;
            font-style: italic;
            margin: 15px 0;
        }}
        .intro {{
            background: #fff;
            padding: 15px;
            border-radius: 8px;
            margin: 20px 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
    </style>
</head>
<body>
{html}
</body>
</html>"""
        return styled_html
    except ImportError:
        logging.warning("markdown 库未安装，使用纯文本发送")
        return f"<pre>{markdown_text}</pre>"

def send_email(html_content):
    """发送邮件"""
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    receiver = os.getenv("EMAIL_RECEIVER")
    
    if not sender or not password:
        logging.error("邮件配置缺失，无法发送")
        return False

    msg = MIMEText(html_content, 'html', 'utf-8')
    msg['Subject'] = Header(f'📚 每日阅读简报 - {datetime.now().strftime("%m月%d日")}', 'utf-8')
    msg['From'] = sender
    msg['To'] = receiver
    
    try:
        smtp_server = "smtp.163.com"
        server = smtplib.SMTP_SSL(smtp_server, 465) 
        server.login(sender, password)
        server.sendmail(sender, [receiver], msg.as_string())
        server.quit()
        logging.info(f"邮件已成功发送至 {receiver}！")
        return True
    except Exception as e:
        logging.error(f"邮件发送失败: {e}")
        return False

def mark_as_done(page_id):
    """更新 Notion 状态为已完成"""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    
    payload = {
        "properties": {
            "状态": {
                "multi_select": [
                    {"name": "已完成"}
                ]
            }
        }
    }
    
    try:
        response = requests.patch(url, headers=headers, json=payload)
        if response.status_code == 200:
            logging.info(f"页面 {page_id} 状态已更新为 '已完成'")
        else:
            logging.error(f"更新状态失败: {response.status_code} - {response.text}")
    except Exception as e:
        logging.error(f"更新 Notion 状态失败: {e}")

def main():
    logging.info("=== 开始执行每日简报任务 ===")
    
    # 1. 获取待读文章（包括内容）
    articles = get_unread_articles()
    if not articles:
        logging.info("没有找到待读文章或文章内容为空，任务结束。")
        return
    
    # 2. 第一步：为每篇文章生成摘要
    summaries = generate_all_summaries(articles)
    if not summaries:
        logging.error("没有成功生成任何摘要")
        return
    
    # 3. 第二步：整合所有摘要成每日简报
    markdown_digest = generate_final_digest(summaries)
    if not markdown_digest:
        logging.error("生成简报失败")
        return
    
    # 4. 转换为 HTML
    html_digest = markdown_to_html(markdown_digest)
    
    # 5. 发送邮件
    if send_email(html_digest):
        # 6. 更新状态
        logging.info("正在更新 Notion 状态...")
        for article in articles:
            mark_as_done(article['id'])
        logging.info(f"所有任务圆满完成！处理了 {len(articles)} 篇文章")
    else:
        logging.error("邮件发送失败，未更新 Notion 状态")

if __name__ == "__main__":
    main()
