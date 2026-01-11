from fastapi import FastAPI, Depends, HTTPException  # Импортируем ядро фреймворка и инструменты для зависимостей
from sqlalchemy import create_engine, Column, Integer, Float, String, Date  # Инструменты для описания таблиц
from sqlalchemy.ext.declarative import declarative_base  # Базовый класс для моделей таблиц
from sqlalchemy.orm import sessionmaker, Session  # Инструменты для работы с сессиями (подключениями) к БД
from datetime import date, datetime  # Работа с датами
import pydantic  # Валидация данных на входе
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request, Form
from fastapi.responses import RedirectResponse
import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Указываем, где лежат шаблоны
templates = Jinja2Templates(directory="templates")

# --- НАСТРОЙКА БАЗЫ ДАННЫХ ---

# Читаем URL базы из настроек Render.
# Если его там нет (например, запускаешь локально), используем SQLite.
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    # Render выдает ссылку postgres://, но SQLAlchemy требует postgresql://
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./expenses.db"

# Для SQLite нужен специальный аргумент, для Postgres он не нужен
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# --- ОПИСАНИЕ ТАБЛИЦЫ (MODEL) ---

class Expense(Base):
    __tablename__ = "expenses"  # Имя таблицы в самой базе данных
    id = Column(Integer, primary_key=True, index=True)  # Уникальный ID каждой записи
    amount = Column(Float)  # Сумма траты (число с плавающей точкой)
    description = Column(String)  # Описание: на что потратили (чечевица, бензин и т.д.)
    created_at = Column(Date, default=date.today)  # Дата записи (автоматом ставит "сегодня")


# Команда SQLAlchemy создать таблицу в файле .db, если её еще не существует
Base.metadata.create_all(bind=engine)


# --- ВАЛИДАЦИЯ ДАННЫХ (SCHEMAS) ---

class ExpenseCreate(pydantic.BaseModel):
    # Эта схема описывает, какие данные мы ждем от фронтенда/пользователя при создании траты
    amount: float
    description: str


# --- ИНИЦИАЛИЗАЦИЯ APP ---

app = FastAPI(title="Seniors Detoks Tracker")


# Функция-зависимость (Dependency). Она открывает сессию к базе и гарантирует её закрытие после ответа
def get_db():
    db = SessionLocal()  # Открываем коннект
    try:
        yield db  # Передаем его в функцию эндпоинта
    finally:
        db.close()  # Закрываем коннект в любом случае (даже при ошибке)


# --- КОНСТАНТЫ БЮДЖЕТА ---

TOTAL_START_BUDGET = 47300.0  # Твои 400 евро + 2600 динар
END_DATE = date(2026, 2, 10)  # Дата-дедлайн


# --- ЭНДПОИНТЫ (API) ---

@app.post("/spend")
def add_expense(expense: ExpenseCreate, db: Session = Depends(get_db)):
    """Добавляет новую трату в базу данных"""
    # Превращаем Pydantic-объект в модель SQLAlchemy
    db_expense = Expense(amount=expense.amount, description=expense.description)
    db.add(db_expense)  # Кладем в корзину для сохранения
    db.commit()  # Сохраняем (записываем в файл .db)
    return {"status": "ok", "saved": expense}


@app.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db)):
    """Главная ручка для контроля ГТР: считает сколько осталось и какой лимит на сегодня"""
    # Достаем все записи из таблицы расходов
    all_expenses = db.query(Expense).all()
    # Считаем сумму всех потраченных денег
    total_spent = sum(e.amount for e in all_expenses)

    # Считаем, сколько денег осталось от изначального бюджета
    remaining_budget = TOTAL_START_BUDGET - total_spent

    # Считаем количество дней до 10 февраля (включая сегодняшний)
    today = date.today()
    days_left = (END_DATE - today).days

    # ГЛАВНАЯ ЛОГИКА: делим остаток денег на остаток дней.
    # Если дней 0 или меньше, лимитом считается весь остаток.
    daily_limit = remaining_budget / days_left if days_left > 0 else remaining_budget

    # Возвращаем JSON с полезной инфой для твоего спокойствия
    return {
        "remaining_total_rsd": round(remaining_budget, 2),  # Округление до 2 знаков
        "days_left": days_left,  # Дней до "зарплаты"
        "daily_limit_rsd": round(daily_limit, 2),  # Сколько можно тратить сегодня
        "total_spent": round(total_spent, 2),  # Сколько уже ушло
        "today": today  # Текущая дата для сверки
    }


@app.get("/history")
def get_history(limit: int = 10, db: Session = Depends(get_db)):
    """
    Возвращает список последних трат.
    Параметр limit позволяет указать, сколько записей выводить (по дефолту 10).
    """
    # Делаем запрос к таблице Expense:
    # .order_by(Expense.id.desc()) — сортируем так, чтобы самые свежие были сверху
    # .limit(limit) — берем только указанное количество записей
    history = db.query(Expense).order_by(Expense.id.desc()).limit(limit).all()

    return {
        "count": len(history),
        "history": history
    }


# Главная страница фронтенда
@app.get("/", response_class=HTMLResponse)
async def read_item(request: Request, db: Session = Depends(get_db)):
    # Забираем данные из твоих же функций
    status = get_dashboard(db)
    history_data = get_history(limit=10, db=db)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "status": status,
        "history": history_data["history"]
    })


# Ручка для формы (чтобы перенаправлять обратно на главную после добавления)
@app.post("/ui/add")
async def ui_add_expense(amount: float = Form(...), description: str = Form(...), db: Session = Depends(get_db)):
    db_expense = Expense(amount=amount, description=description)
    db.add(db_expense)
    db.commit()
    return RedirectResponse(url="/", status_code=303)

# Эндпоинт для удаления траты через интерфейс
@app.post("/ui/delete/{expense_id}")
async def ui_delete_expense(expense_id: int, db: Session = Depends(get_db)):
    expense = db.query(Expense).filter(Expense.id == expense_id).first()
    if expense:
        db.delete(expense)
        db.commit()
    return RedirectResponse(url="/", status_code=303)
