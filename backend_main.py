import os
import json
import uuid
import random
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, List, Optional, Set

import redis
import jwt
from passlib.context import CryptContext
from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    status,
    File,
    UploadFile,
    Form,
)
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi import WebSocket, WebSocketDisconnect, APIRouter
from pydantic import BaseModel, EmailStr
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    DateTime,
    Float,
    Boolean,
    Text,
    select,
    and_,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("order_sega")

# JWT & auth
SECRET_KEY = "YOUR_SECRET_KEY_HERE"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# DB / Redis
Base = declarative_base()
DATABASE_URL = "postgresql://user:password@localhost/restaurant_db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
redis_client = redis.Redis(host="localhost", port=6379, db=0)


# Models
class OrderStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY = "ready"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class PaymentStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentMethod(str, Enum):
    CASH = "cash"
    CREDIT_CARD = "credit_card"


class OrderType(str, Enum):
    DINE_IN = "dine_in"
    TAKEAWAY = "takeaway"


class SoftDeleteMixin:
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = datetime.now(timezone.utc)


class Order(Base, SoftDeleteMixin):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String, unique=True, index=True)
    customer_id = Column(String, index=True)
    items = Column(Text)
    total_amount = Column(Float)
    status = Column(String, default=OrderStatus.PENDING)
    saga_id = Column(String, index=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    order_type = Column(String, default="takeaway")
    table_number = Column(String, nullable=True)


class Payment(Base, SoftDeleteMixin):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True, index=True)
    payment_id = Column(String, unique=True, index=True)
    order_id = Column(String, index=True)
    amount = Column(Float)
    status = Column(String, default=PaymentStatus.PENDING)
    method = Column(String, default=PaymentMethod.CASH)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))


class Kitchen(Base, SoftDeleteMixin):
    __tablename__ = "kitchen_orders"
    id = Column(Integer, primary_key=True, index=True)
    kitchen_order_id = Column(String, unique=True, index=True)
    order_id = Column(String, index=True)
    items = Column(Text)
    status = Column(String, default="received")
    estimated_time = Column(Integer)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))


class Delivery(Base, SoftDeleteMixin):
    __tablename__ = "deliveries"
    id = Column(Integer, primary_key=True, index=True)
    delivery_id = Column(String, unique=True, index=True)
    order_id = Column(String, index=True)
    address = Column(String)
    status = Column(String, default="pending")
    driver_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))


class MenuItem(Base, SoftDeleteMixin):
    __tablename__ = "menu_items"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    price = Column(Float)
    description = Column(Text, nullable=True)
    image_url = Column(String, nullable=True)


class Customer(Base, SoftDeleteMixin):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(String, unique=True, index=True)
    name = Column(String)
    email = Column(String, unique=True, index=True)
    phone = Column(String, nullable=True)


class OrderStatusHistory(Base, SoftDeleteMixin):
    __tablename__ = "order_status_history"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String, index=True)
    status = Column(String)
    changed_at = Column(DateTime, default=datetime.now(timezone.utc))


class UserRole(str, Enum):
    CUSTOMER = "customer"
    STAFF = "staff"
    ADMIN = "admin"


class User(Base, SoftDeleteMixin):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String, default=UserRole.CUSTOMER)
    customer_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))


# Pydantic
class OrderCreate(BaseModel):
    customer_id: str
    items: List[Dict]
    order_type: OrderType = OrderType.TAKEAWAY
    table_number: Optional[str] = None
    payment_method: PaymentMethod = PaymentMethod.CASH


class OrderResponse(BaseModel):
    order_id: str
    status: str
    total_amount: float


class PaymentConfirmation(BaseModel):
    success: bool


class PaymentResponse(BaseModel):
    payment_id: str
    status: str
    amount: float
    method: Optional[str] = None


class CustomerCreate(BaseModel):
    customer_id: str
    name: str
    email: str
    phone: Optional[str] = None


class CustomerResponse(BaseModel):
    customer_id: str
    name: str
    email: str
    phone: Optional[str] = None


class MenuItemResponse(BaseModel):
    id: int
    name: str
    price: float
    description: Optional[str] = None
    image_url: Optional[str] = None


class OrderStatusHistoryResponse(BaseModel):
    order_id: str
    status: str
    changed_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str
    role: str


class TokenData(BaseModel):
    username: Optional[str] = None


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    role: UserRole = UserRole.CUSTOMER
    customer_id: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: str
    customer_id: Optional[str] = None


# helpers
def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)


def get_password_hash(pw):
    return pwd_context.hash(pw)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# Saga classes
class SagaStep:
    def __init__(self, name: str, action_func, compensation_func):
        self.name = name
        self.action_func = action_func
        self.compensation_func = compensation_func


class SagaOrchestrator:
    def __init__(self):
        self.steps: List[SagaStep] = []

    def add_step(self, step: SagaStep):
        self.steps.append(step)

    async def execute(self, saga_id: str, payload: Dict):
        executed_steps_json = redis_client.hget(f"saga:{saga_id}", "executed_steps")
        executed_steps = json.loads(executed_steps_json) if executed_steps_json else []

        redis_client.hset(f"saga:{saga_id}", "status", "executing")
        redis_client.hset(f"saga:{saga_id}", "payload", json.dumps(payload))

        try:
            for step in self.steps:
                if step.name in executed_steps:
                    logger.info(
                        "Step %s already executed for saga %s. Skipping.",
                        step.name,
                        saga_id,
                    )
                    continue

                logger.info("Executing step: %s for saga %s", step.name, saga_id)
                result = await step.action_func(payload)

                if not result.get("success", False):
                    logger.warning(
                        "Step %s failed for saga %s. Initiating compensation.",
                        step.name,
                        saga_id,
                    )
                    await self.compensate(saga_id, payload)
                    return {"success": False, "error": result.get("error")}

                # persist updated payload (e.g. payment_id)
                try:
                    redis_client.hset(f"saga:{saga_id}", "payload", json.dumps(payload))
                except Exception as e:
                    logger.warning(
                        "Failed to update saga payload in redis for %s: %s", saga_id, e
                    )

                executed_steps.append(step.name)
                redis_client.hset(
                    f"saga:{saga_id}", "executed_steps", json.dumps(executed_steps)
                )

            redis_client.hset(f"saga:{saga_id}", "status", "completed")
            logger.info("Saga %s completed successfully.", saga_id)
            return {"success": True}
        except Exception as e:
            logger.exception("Unexpected error during saga %s execution.", saga_id)
            await self.compensate(saga_id, payload)
            return {"success": False, "error": str(e)}

    async def compensate(self, saga_id: str, payload: Dict):
        logger.info("Compensating saga %s...", saga_id)
        redis_client.hset(f"saga:{saga_id}", "status", "compensating")

        executed_steps_json = redis_client.hget(f"saga:{saga_id}", "executed_steps")
        executed_steps = json.loads(executed_steps_json) if executed_steps_json else []

        for step_name in reversed(executed_steps):
            step = next((s for s in self.steps if s.name == step_name), None)
            if step and step.compensation_func:
                logger.info(
                    "Executing compensation for step: %s for saga %s",
                    step.name,
                    saga_id,
                )
                await step.compensation_func(payload)
            else:
                logger.debug("No compensation function for step: %s", step_name)

        redis_client.hset(f"saga:{saga_id}", "status", "compensated")
        logger.info("Saga %s compensated.", saga_id)


# FastAPI app
app = FastAPI(title="訂單服務 - Orchestration")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
IMAGES_DIR = os.path.join(STATIC_DIR, "images")
os.makedirs(IMAGES_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# DB dependency
def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# auth deps
async def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
):
    creds_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise creds_exc
    except jwt.PyJWTError:
        raise creds_exc

    stmt = select(User).where(and_(User.username == username, User.is_deleted == False))
    result = db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise creds_exc
    return user


async def get_staff_user(current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.STAFF, UserRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="需要店員權限"
        )
    return current_user


async def get_customer_user(current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.CUSTOMER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="需要顧客帳號"
        )
    return current_user


# business functions used by saga steps
async def process_payment(payload: Dict):
    db = SessionLocal()
    try:
        payment_id = str(uuid.uuid4())
        payment = Payment(
            payment_id=payment_id,
            order_id=payload["order_id"],
            amount=payload["total_amount"],
            status=PaymentStatus.PENDING,
            method=payload.get("payment_method", PaymentMethod.CASH),
        )
        db.add(payment)
        db.commit()
        db.refresh(payment)
        payload["payment_id"] = payment_id
        return {
            "success": True,
            "message": "Payment record created, awaiting manual confirmation.",
        }
    except Exception as e:
        db.rollback()
        logger.exception("process_payment failed")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


async def compensate_payment(payload: Dict):
    if "payment_id" in payload:
        db = SessionLocal()
        try:
            stmt = select(Payment).where(
                and_(
                    Payment.payment_id == payload["payment_id"],
                    Payment.is_deleted == False,
                )
            )
            res = db.execute(stmt)
            payment = res.scalar_one_or_none()
            if payment and payment.status in [
                PaymentStatus.PENDING,
                PaymentStatus.COMPLETED,
            ]:
                payment.status = PaymentStatus.REFUNDED
                db.commit()
                logger.info(
                    "Payment %s refunded for order %s.",
                    payment.payment_id,
                    payment.order_id,
                )
        except Exception:
            logger.exception("Error during payment compensation")
        finally:
            db.close()


async def prepare_kitchen(payload: Dict):
    db = SessionLocal()
    try:
        kitchen_order_id = str(uuid.uuid4())
        kitchen_order = Kitchen(
            kitchen_order_id=kitchen_order_id,
            order_id=payload["order_id"],
            items=json.dumps(payload["items"]),
            status="received",
            estimated_time=30,
        )
        db.add(kitchen_order)
        db.commit()
        db.refresh(kitchen_order)
        if random.random() > 0.05:
            kitchen_order.status = "preparing"
            db.commit()
            payload["kitchen_order_id"] = kitchen_order_id
            logger.info(
                "Kitchen order %s for order %s is preparing.",
                kitchen_order_id,
                payload["order_id"],
            )
            return {"success": True}
        else:
            db.rollback()
            logger.warning(
                "Kitchen preparation failed for order %s.", payload["order_id"]
            )
            return {"success": False, "error": "Kitchen unavailable"}
    except Exception:
        db.rollback()
        logger.exception("Error during kitchen preparation")
        return {"success": False, "error": "internal"}
    finally:
        db.close()


async def compensate_kitchen(payload: Dict):
    if "kitchen_order_id" in payload:
        db = SessionLocal()
        try:
            stmt = select(Kitchen).where(
                and_(
                    Kitchen.kitchen_order_id == payload["kitchen_order_id"],
                    Kitchen.is_deleted == False,
                )
            )
            res = db.execute(stmt)
            k = res.scalar_one_or_none()
            if k:
                k.status = "cancelled"
                db.commit()
                logger.info("Kitchen order %s cancelled.", k.kitchen_order_id)
        except Exception:
            logger.exception("Error during kitchen compensation")
        finally:
            db.close()


# delivery step exists but not used in orchestration by default; implemented to keep code self-contained
async def arrange_delivery(payload: Dict):
    db = SessionLocal()
    try:
        delivery_id = str(uuid.uuid4())
        delivery = Delivery(
            delivery_id=delivery_id,
            order_id=payload["order_id"],
            address=payload.get("delivery_address", ""),
            status="pending",
        )
        db.add(delivery)
        db.commit()
        db.refresh(delivery)
        delivery.status = "assigned"
        delivery.driver_id = f"driver_{random.randint(1,10)}"
        db.commit()
        payload["delivery_id"] = delivery_id
        logger.info(
            "Delivery %s for order %s assigned to %s.",
            delivery_id,
            payload["order_id"],
            delivery.driver_id,
        )
        return {"success": True}
    except Exception:
        db.rollback()
        logger.exception("Error during delivery arrangement")
        return {"success": False, "error": "internal"}
    finally:
        db.close()


async def compensate_delivery(payload: Dict):
    if "delivery_id" in payload:
        db = SessionLocal()
        try:
            stmt = select(Delivery).where(
                and_(
                    Delivery.delivery_id == payload["delivery_id"],
                    Delivery.is_deleted == False,
                )
            )
            res = db.execute(stmt)
            d = res.scalar_one_or_none()
            if d:
                d.status = "cancelled"
                db.commit()
                logger.info("Delivery %s cancelled.", d.delivery_id)
        except Exception:
            logger.exception("Error during delivery compensation")
        finally:
            db.close()


# WebSocket management
connected_staffs: Set[WebSocket] = set()
ws_lock = asyncio.Lock()


async def notify_staffs(message: Dict):
    payload = json.dumps(message)
    async with ws_lock:
        stale = []
        for ws in list(connected_staffs):
            try:
                await ws.send_text(payload)
            except Exception:
                stale.append(ws)
        for s in stale:
            connected_staffs.discard(s)


@app.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008)
        return
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            await websocket.close(code=1008)
            return
    except Exception:
        await websocket.close(code=1008)
        return

    db = SessionLocal()
    try:
        stmt = select(User).where(
            and_(User.username == username, User.is_deleted == False)
        )
        res = db.execute(stmt)
        user = res.scalar_one_or_none()
    finally:
        db.close()

    if not user or user.role not in [UserRole.STAFF, UserRole.ADMIN]:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    async with ws_lock:
        connected_staffs.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        async with ws_lock:
            connected_staffs.discard(websocket)


# routes
@app.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    stmt = select(User).where(
        and_(User.username == form_data.username, User.is_deleted == False)
    )
    res = db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用戶名或密碼不正確",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer", "role": user.role}


user_router = APIRouter(prefix="/orchestration/users", tags=["User"])


@user_router.post("", response_model=UserResponse)
async def create_user(user: UserCreate, db: Session = Depends(get_db)):
    stmt = select(User).where(User.username == user.username)
    res = db.execute(stmt)
    if res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用戶名已被註冊")
    stmt = select(User).where(User.email == user.email)
    res = db.execute(stmt)
    if res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="電子郵件已被註冊")

    customer_id = None
    if user.role == UserRole.CUSTOMER:
        if not user.customer_id:
            customer_id = str(uuid.uuid4())
            db_customer = Customer(
                customer_id=customer_id, name=user.username, email=user.email
            )
            db.add(db_customer)
            db.commit()
            db.refresh(db_customer)
        else:
            stmt = select(Customer).where(
                and_(
                    Customer.customer_id == user.customer_id,
                    Customer.is_deleted == False,
                )
            )
            res = db.execute(stmt)
            if not res.scalar_one_or_none():
                raise HTTPException(
                    status_code=404, detail=f"顧客ID '{user.customer_id}' 不存在"
                )
            customer_id = user.customer_id

    db_user = User(
        username=user.username,
        email=user.email,
        hashed_password=get_password_hash(user.password),
        role=user.role,
        customer_id=customer_id,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return UserResponse(
        id=db_user.id,
        username=db_user.username,
        email=db_user.email,
        role=db_user.role,
        customer_id=db_user.customer_id,
    )


@user_router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        role=current_user.role,
        customer_id=current_user.customer_id,
    )


app.include_router(user_router)


@app.post("/orchestration/orders", response_model=OrderResponse)
async def create_order(
    order: OrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_customer_user),
):
    if current_user.customer_id != order.customer_id:
        raise HTTPException(status_code=403, detail="無法以其他顧客身份下單")
    if order.order_type == OrderType.DINE_IN and (
        not order.table_number or order.table_number.strip() == ""
    ):
        raise HTTPException(status_code=400, detail="內用訂單必須提供桌號")

    total_amount = sum(item["price"] * item["quantity"] for item in order.items)
    order_id = str(uuid.uuid4())
    saga_id = str(uuid.uuid4())

    db_order = Order(
        order_id=order_id,
        customer_id=order.customer_id,
        items=json.dumps(order.items),
        total_amount=total_amount,
        saga_id=saga_id,
        status=OrderStatus.PENDING,
        order_type=(
            order.order_type.value
            if isinstance(order.order_type, OrderType)
            else order.order_type
        ),
        table_number=order.table_number,
    )
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    db.add(OrderStatusHistory(order_id=order_id, status=db_order.status))
    db.commit()

    redis_client.hset(f"saga:{saga_id}", "status", "pending_start")
    redis_client.hset(f"saga:{saga_id}", "executed_steps", json.dumps([]))
    redis_client.hset(f"saga:{saga_id}", "order_id", order_id)

    orchestrator = SagaOrchestrator()
    orchestrator.add_step(SagaStep("payment", process_payment, compensate_payment))
    orchestrator.add_step(SagaStep("kitchen", prepare_kitchen, compensate_kitchen))

    payload = {
        "order_id": order_id,
        "customer_id": order.customer_id,
        "items": order.items,
        "total_amount": total_amount,
        "order_type": (
            order.order_type.value
            if isinstance(order.order_type, OrderType)
            else order.order_type
        ),
        "table_number": order.table_number,
        "payment_method": order.payment_method.value,
    }

    logger.info("Starting orchestration for order %s with saga %s.", order_id, saga_id)
    result = await orchestrator.execute(saga_id, payload)

    if result["success"]:
        db_order.status = OrderStatus.PENDING
        logger.info(
            "Order %s initiated successfully. Payment awaiting confirmation.", order_id
        )
    else:
        db_order.status = OrderStatus.CANCELLED
        logger.warning(
            "Order %s cancelled during initial orchestration: %s",
            order_id,
            result.get("error"),
        )
    db.commit()

    try:
        payment_id = payload.get("payment_id")
        if not payment_id:
            db2 = SessionLocal()
            try:
                stmt = (
                    select(Payment)
                    .where(
                        and_(Payment.order_id == order_id, Payment.is_deleted == False)
                    )
                    .order_by(Payment.created_at.desc())
                )
                res = db2.execute(stmt)
                p = res.scalar_one_or_none()
                if p:
                    payment_id = p.payment_id
            finally:
                db2.close()
        notify_msg = {
            "type": "new_order",
            "order_id": order_id,
            "total_amount": total_amount,
            "customer_id": order.customer_id,
            "payment_id": payment_id,
            "saga_id": saga_id,
        }
        asyncio.create_task(notify_staffs(notify_msg))
    except Exception:
        logger.exception("Notify staffs failed")

    return OrderResponse(
        order_id=order_id, status=db_order.status, total_amount=total_amount
    )


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/orchestration/orders/{order_id}/payment", response_model=PaymentResponse)
def get_order_payment(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Order).where(
        and_(Order.order_id == order_id, Order.is_deleted == False)
    )
    res = db.execute(stmt)
    order = res.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if (
        current_user.role == UserRole.CUSTOMER
        and current_user.customer_id != order.customer_id
    ):
        raise HTTPException(status_code=403, detail="無權查看此訂單的付款資訊")

    stmt = (
        select(Payment)
        .where(and_(Payment.order_id == order_id, Payment.is_deleted == False))
        .order_by(Payment.created_at.desc())
    )
    res = db.execute(stmt)
    payment = res.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found for this order")
    return PaymentResponse(
        payment_id=payment.payment_id,
        status=payment.status,
        amount=payment.amount,
        method=payment.method,
    )


@app.post("/orchestration/payments/{payment_id}/confirm")
async def confirm_orchestration_payment(
    payment_id: str,
    confirmation: PaymentConfirmation,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_staff_user),
):
    stmt = select(Payment).where(
        and_(Payment.payment_id == payment_id, Payment.is_deleted == False)
    )
    res = db.execute(stmt)
    payment = res.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    if payment.status != PaymentStatus.PENDING:
        raise HTTPException(status_code=400, detail="Payment is not in pending status")

    stmt = select(Order).where(
        and_(Order.order_id == payment.order_id, Order.is_deleted == False)
    )
    res = db.execute(stmt)
    order = res.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Associated order not found")

    orchestrator = SagaOrchestrator()
    orchestrator.add_step(SagaStep("payment", process_payment, compensate_payment))
    orchestrator.add_step(SagaStep("kitchen", prepare_kitchen, compensate_kitchen))

    saga_id = order.saga_id
    payload_json = redis_client.hget(f"saga:{saga_id}", "payload")
    if not payload_json:
        raise HTTPException(
            status_code=404, detail="Saga payload not found for this order."
        )
    payload = json.loads(payload_json)

    if confirmation.success:
        payment.status = PaymentStatus.COMPLETED
        db.commit()
        db.add(
            OrderStatusHistory(order_id=order.order_id, status=OrderStatus.CONFIRMED)
        )
        db.commit()
        logger.info(
            "Orchestration Payment %s confirmed successfully. Resuming saga.",
            payment_id,
        )

        executed_steps_json = redis_client.hget(f"saga:{saga_id}", "executed_steps")
        executed_steps = json.loads(executed_steps_json) if executed_steps_json else []
        if "payment" not in executed_steps:
            executed_steps.append("payment")
            redis_client.hset(
                f"saga:{saga_id}", "executed_steps", json.dumps(executed_steps)
            )

        order.status = OrderStatus.CONFIRMED
        db.commit()

        continuation_result = await orchestrator.execute(saga_id, payload)

        if continuation_result["success"]:
            order.status = OrderStatus.DELIVERED
            db.add(
                OrderStatusHistory(
                    order_id=order.order_id, status=OrderStatus.DELIVERED
                )
            )
            db.commit()
            logger.info(
                "Orchestration saga for order %s completed after manual payment confirmation.",
                order.order_id,
            )
        else:
            order.status = OrderStatus.CANCELLED
            db.add(
                OrderStatusHistory(
                    order_id=order.order_id, status=OrderStatus.CANCELLED
                )
            )
            db.commit()
            logger.warning(
                "Orchestration saga for order %s failed after payment confirmation: %s",
                order.order_id,
                continuation_result.get("error"),
            )
    else:
        payment.status = PaymentStatus.FAILED
        db.commit()
        db.add(
            OrderStatusHistory(order_id=order.order_id, status=OrderStatus.CANCELLED)
        )
        db.commit()
        logger.info(
            "Orchestration Payment %s marked as failed. Initiating saga compensation.",
            payment_id,
        )
        await orchestrator.compensate(saga_id, payload)
        order.status = OrderStatus.CANCELLED
        db.commit()
        saga_status_raw = redis_client.hget(f"saga:{saga_id}", "status")
        saga_status = saga_status_raw.decode("utf-8") if saga_status_raw else None
        return {
            "message": "Payment failed and saga compensation initiated.",
            "total_amount": order.total_amount,
            "saga_status": saga_status,
        }


@app.get("/orchestration/orders/{order_id}", response_model=OrderResponse)
def get_order_status_orchestration(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Order).where(
        and_(Order.order_id == order_id, Order.is_deleted == False)
    )
    res = db.execute(stmt)
    order = res.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if (
        current_user.role == UserRole.CUSTOMER
        and current_user.customer_id != order.customer_id
    ):
        raise HTTPException(status_code=403, detail="無權查看此訂單")
    return OrderResponse(
        order_id=order.order_id, status=order.status, total_amount=order.total_amount
    )


@app.get("/orchestration/orders", response_model=List[OrderResponse])
def list_orders(
    customer_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == UserRole.CUSTOMER:
        customer_id = current_user.customer_id
    stmt = select(Order).where(Order.is_deleted == False)
    if customer_id:
        stmt = stmt.where(Order.customer_id == customer_id)
    res = db.execute(stmt)
    orders = res.scalars().all()
    return [
        OrderResponse(order_id=o.order_id, status=o.status, total_amount=o.total_amount)
        for o in orders
    ]


@app.post("/orchestration/orders/{order_id}/cancel")
async def cancel_order(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Order).where(
        and_(Order.order_id == order_id, Order.is_deleted == False)
    )
    res = db.execute(stmt)
    order = res.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if (
        current_user.role == UserRole.CUSTOMER
        and current_user.customer_id != order.customer_id
    ):
        raise HTTPException(status_code=403, detail="無權取消此訂單")
    if order.status in [OrderStatus.CANCELLED, OrderStatus.DELIVERED]:
        raise HTTPException(status_code=400, detail="Order cannot be cancelled")
    order.status = OrderStatus.CANCELLED
    db.commit()
    db.add(OrderStatusHistory(order_id=order_id, status=OrderStatus.CANCELLED))
    db.commit()
    return {"message": f"Order {order_id} cancelled."}


# kitchen & delivery routers with list and single-get
kitchen_router = APIRouter(prefix="/orchestration/kitchen", tags=["Kitchen"])


@kitchen_router.get("/orders/{kitchen_order_id}")
def get_kitchen_order_status(
    kitchen_order_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_staff_user),
):
    stmt = select(Kitchen).where(
        and_(Kitchen.kitchen_order_id == kitchen_order_id, Kitchen.is_deleted == False)
    )
    res = db.execute(stmt)
    k = res.scalar_one_or_none()
    if not k:
        raise HTTPException(status_code=404, detail="Kitchen order not found")
    return {
        "kitchen_order_id": k.kitchen_order_id,
        "order_id": k.order_id,
        "status": k.status,
        "estimated_time": k.estimated_time,
        "created_at": k.created_at,
    }


@kitchen_router.get("/orders")
def list_kitchen_orders(
    status: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_staff_user),
):
    stmt = select(Kitchen).where(Kitchen.is_deleted == False)
    if status:
        stmt = stmt.where(Kitchen.status == status)
    stmt = stmt.order_by(Kitchen.created_at.desc()).limit(limit)
    res = db.execute(stmt)
    items = res.scalars().all()
    return [
        {
            "kitchen_order_id": k.kitchen_order_id,
            "order_id": k.order_id,
            "status": k.status,
            "estimated_time": k.estimated_time,
            "items": k.items,
            "created_at": k.created_at.isoformat(),
        }
        for k in items
    ]


@kitchen_router.post("/orders/{kitchen_order_id}/complete")
def complete_kitchen_order(
    kitchen_order_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_staff_user),  # 僅店員/管理員可操作
):
    # 取得 kitchen order
    stmt = select(Kitchen).where(
        and_(Kitchen.kitchen_order_id == kitchen_order_id, Kitchen.is_deleted == False)
    )
    res = db.execute(stmt)
    k = res.scalar_one_or_none()
    if not k:
        raise HTTPException(status_code=404, detail="Kitchen order not found")

    # 只有在 preparing 狀態才允許標記為 ready
    if k.status not in ["preparing", "received"]:
        raise HTTPException(
            status_code=400,
            detail="Kitchen order cannot be marked complete in current status",
        )

    # 更新 kitchen order 狀態
    k.status = "ready"
    db.commit()

    # 同步更新對應的 order（若存在），並加入歷史紀錄
    try:
        stmt_o = select(Order).where(
            and_(Order.order_id == k.order_id, Order.is_deleted == False)
        )
        res_o = db.execute(stmt_o)
        order = res_o.scalar_one_or_none()
        if order:
            order.status = OrderStatus.READY
            db.add(
                OrderStatusHistory(order_id=order.order_id, status=OrderStatus.READY)
            )
            db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "Failed to update order status when marking kitchen order complete"
        )

    return {"message": f"Kitchen order {kitchen_order_id} marked as ready."}


app.include_router(kitchen_router)


delivery_router = APIRouter(prefix="/orchestration/delivery", tags=["Delivery"])


@delivery_router.get("/orders/{delivery_id}")
def get_delivery_status(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_staff_user),
):
    stmt = select(Delivery).where(
        and_(Delivery.delivery_id == delivery_id, Delivery.is_deleted == False)
    )
    res = db.execute(stmt)
    d = res.scalar_one_or_none()
    if not d:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return {
        "delivery_id": d.delivery_id,
        "order_id": d.order_id,
        "status": d.status,
        "driver_id": d.driver_id,
        "created_at": d.created_at,
    }


@delivery_router.get("/orders")
def list_delivery_orders(
    status: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_staff_user),
):
    stmt = select(Delivery).where(Delivery.is_deleted == False)
    if status:
        stmt = stmt.where(Delivery.status == status)
    stmt = stmt.order_by(Delivery.created_at.desc()).limit(limit)
    res = db.execute(stmt)
    items = res.scalars().all()
    return [
        {
            "delivery_id": d.delivery_id,
            "order_id": d.order_id,
            "status": d.status,
            "driver_id": d.driver_id,
            "address": d.address,
            "created_at": d.created_at.isoformat(),
        }
        for d in items
    ]


app.include_router(delivery_router)


# menu routers
menu_router = APIRouter(prefix="/orchestration/menu", tags=["Menu"])


@menu_router.get("/items")
def get_menu_items(db: Session = Depends(get_db)):
    stmt = select(MenuItem).where(MenuItem.is_deleted == False)
    res = db.execute(stmt)
    items = res.scalars().all()
    return [
        {
            "id": item.id,
            "name": item.name,
            "price": item.price,
            "description": item.description,
            "image_url": item.image_url,
        }
        for item in items
    ]


app.include_router(menu_router)


menu_admin_router = APIRouter(prefix="/orchestration/menu/admin", tags=["MenuAdmin"])


@menu_admin_router.post("/items", response_model=MenuItemResponse)
def create_menu_item(
    name: str = Form(...),
    price: float = Form(...),
    description: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_staff_user),
):
    try:
        image_url = None
        if image:
            ext = os.path.splitext(image.filename)[1] or ".jpg"
            filename = f"{uuid.uuid4().hex}{ext}"
            filepath = os.path.join(IMAGES_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(image.file.read())
            image_url = f"/static/images/{filename}"
        db_item = MenuItem(
            name=name, price=price, description=description, image_url=image_url
        )
        db.add(db_item)
        db.commit()
        db.refresh(db_item)
        return db_item
    except Exception:
        db.rollback()
        logger.exception("Failed to create menu item")
        raise HTTPException(status_code=500, detail="internal")


@menu_admin_router.put("/items/{item_id}", response_model=MenuItemResponse)
def update_menu_item(
    item_id: int,
    name: str = Form(...),
    price: float = Form(...),
    description: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_staff_user),
):
    stmt = select(MenuItem).where(
        and_(MenuItem.id == item_id, MenuItem.is_deleted == False)
    )
    res = db.execute(stmt)
    db_item = res.scalar_one_or_none()
    if not db_item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    try:
        if image:
            ext = os.path.splitext(image.filename)[1] or ".jpg"
            filename = f"{uuid.uuid4().hex}{ext}"
            filepath = os.path.join(IMAGES_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(image.file.read())
            db_item.image_url = f"/static/images/{filename}"
        db_item.name = name
        db_item.price = price
        db_item.description = description
        db.commit()
        db.refresh(db_item)
        return db_item
    except Exception:
        db.rollback()
        logger.exception("Failed to update menu item")
        raise HTTPException(status_code=500, detail="internal")


@menu_admin_router.delete("/items/{item_id}")
def delete_menu_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_staff_user),
):
    stmt = select(MenuItem).where(
        and_(MenuItem.id == item_id, MenuItem.is_deleted == False)
    )
    res = db.execute(stmt)
    db_item = res.scalar_one_or_none()
    if not db_item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    db_item.is_deleted = True
    db_item.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"message": f"Menu item {item_id} deleted."}


app.include_router(menu_admin_router)


# order history
history_router = APIRouter(
    prefix="/orchestration/orders/history", tags=["OrderHistory"]
)


@history_router.get("/{order_id}", response_model=List[OrderStatusHistoryResponse])
def get_order_history(order_id: str, db: Session = Depends(get_db)):
    stmt = (
        select(OrderStatusHistory)
        .where(
            and_(
                OrderStatusHistory.order_id == order_id,
                OrderStatusHistory.is_deleted == False,
            )
        )
        .order_by(OrderStatusHistory.changed_at)
    )
    res = db.execute(stmt)
    history = res.scalars().all()
    return history


app.include_router(history_router)


# customers
customer_router = APIRouter(prefix="/orchestration/customers", tags=["Customer"])


@customer_router.post("", response_model=CustomerResponse)
def create_customer(
    customer: CustomerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_staff_user),
):
    db_customer = Customer(**customer.dict())
    db.add(db_customer)
    db.commit()
    db.refresh(db_customer)
    return db_customer


@customer_router.get("/{customer_id}", response_model=CustomerResponse)
def get_customer(
    customer_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if (
        current_user.role == UserRole.CUSTOMER
        and current_user.customer_id != customer_id
    ):
        raise HTTPException(status_code=403, detail="無權查看其他顧客資料")
    stmt = select(Customer).where(
        and_(Customer.customer_id == customer_id, Customer.is_deleted == False)
    )
    res = db.execute(stmt)
    customer = res.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@customer_router.get("", response_model=List[CustomerResponse])
def list_customers(
    db: Session = Depends(get_db), current_user: User = Depends(get_staff_user)
):
    stmt = select(Customer).where(Customer.is_deleted == False)
    res = db.execute(stmt)
    customers = res.scalars().all()
    return customers


app.include_router(customer_router)


# DB create
Base.metadata.create_all(bind=engine)


# initial users
def create_initial_users():
    db = SessionLocal()
    try:
        stmt = select(User).where(User.role == UserRole.ADMIN)
        admin = db.execute(stmt).scalar_one_or_none()
        if not admin:
            admin_user = User(
                username="admin",
                email="admin@example.com",
                hashed_password=get_password_hash("admin"),
                role=UserRole.ADMIN,
            )
            db.add(admin_user)
        stmt = select(User).where(User.role == UserRole.STAFF)
        staff = db.execute(stmt).scalar_one_or_none()
        if not staff:
            staff_user = User(
                username="staff",
                email="staff@example.com",
                hashed_password=get_password_hash("staff"),
                role=UserRole.STAFF,
            )
            db.add(staff_user)
        stmt = select(User).where(User.role == UserRole.CUSTOMER)
        customer = db.execute(stmt).scalar_one_or_none()
        if not customer:
            customer_id = str(uuid.uuid4())
            db_customer = Customer(
                customer_id=customer_id, name="customer", email="customer@example.com"
            )
            db.add(db_customer)
            db.commit()
            customer_user = User(
                username="customer",
                email="customer@example.com",
                hashed_password=get_password_hash("customer"),
                role=UserRole.CUSTOMER,
                customer_id=customer_id,
            )
            db.add(customer_user)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Error creating initial users")
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    create_initial_users()
    logger.info("Orchestration service startup complete.")


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting Orchestration service on port 8002 (Order)")
    uvicorn.run(app, host="0.0.0.0", port=8002, log_level="info")
