from fastapi.templating import Jinja2Templates

from app.ai.answer_markdown import render_answer_markdown

templates = Jinja2Templates(directory="app/templates")
templates.env.filters["answer_markdown"] = render_answer_markdown
