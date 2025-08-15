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
    update,
    delete,
    and_,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    Body,
    status,
    Security,
    File,
    UploadFile,
)
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from datetime import datetime, timezone, timedelta
from enum import Enum
import asyncio
import json
import uuid
from typing import Dict, List, Optional, Any, Union
import pika
import redis
import random
import jwt
from passlib.context import CryptContext
import os
from fastapi.staticfiles import StaticFiles

# JWT相關配置
SECRET_KEY = "YOUR_SECRET_KEY_HERE"  # 在生產環境中應該使用安全的密鑰
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# 密碼處理
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

Base = declarative_base()
DATABASE_URL = "postgresql://user:password@localhost/restaurant_db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Redis 客戶端
redis_client = redis.Redis(host="localhost", port=6379, db=0)


# 數據模型
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


# Adding Payment Method Enum
class PaymentMethod(str, Enum):
    CASH = "cash"
    CREDIT_CARD = "credit_card"
    # Add other payment methods as needed


# 添加一個基礎模型包含軟刪除欄位
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
    items = Column(Text)  # JSON string
    total_amount = Column(Float)
    status = Column(String, default=OrderStatus.PENDING)
    saga_id = Column(String, index=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))


class Payment(Base, SoftDeleteMixin):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    payment_id = Column(String, unique=True, index=True)
    order_id = Column(String, index=True)
    amount = Column(Float)
    status = Column(String, default=PaymentStatus.PENDING)
    method = Column(String, default=PaymentMethod.CASH)  # New column for payment method
    created_at = Column(DateTime, default=datetime.now(timezone.utc))


class Kitchen(Base, SoftDeleteMixin):
    __tablename__ = "kitchen_orders"

    id = Column(Integer, primary_key=True, index=True)
    kitchen_order_id = Column(String, unique=True, index=True)
    order_id = Column(String, index=True)
    items = Column(Text)
    status = Column(String, default="received")
    estimated_time = Column(Integer)  # minutes
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
    image_url = Column(String, nullable=True)  # 新增圖片 URL 欄位


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


# 用戶角色枚舉
class UserRole(str, Enum):
    CUSTOMER = "customer"
    STAFF = "staff"
    ADMIN = "admin"


# 用戶模型
class User(Base, SoftDeleteMixin):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String, default=UserRole.CUSTOMER)
    customer_id = Column(String, nullable=True)  # 關聯到Customer表的customer_id
    created_at = Column(DateTime, default=datetime.now(timezone.utc))


# Pydantic 模型
class OrderCreate(BaseModel):
    customer_id: str
    items: List[Dict]
    delivery_address: str
    payment_method: PaymentMethod = PaymentMethod.CASH  # New field for payment method


class OrderResponse(BaseModel):
    order_id: str
    status: str
    total_amount: float


class PaymentConfirmation(BaseModel):
    success: bool


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


class MenuItemCreate(BaseModel):
    name: str
    price: float
    description: Optional[str] = None


class MenuItemResponse(BaseModel):
    id: int
    name: str
    price: float
    description: Optional[str] = None
    image_url: Optional[str] = None  # 回傳圖片 URL


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


class UserLogin(BaseModel):
    username: str
    password: str


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


# 權限處理函數
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


class SagaStep:
    def __init__(self, name: str, action_func, compensation_func):
        self.name = name
        self.action_func = action_func
        self.compensation_func = compensation_func


class SagaOrchestrator:
    def __init__(self):
        self.steps: List[SagaStep] = []
        # Store executed steps in Redis to persist state across process restarts
        # This will be managed per saga_id

    def add_step(self, step: SagaStep):
        self.steps.append(step)

    async def execute(self, saga_id: str, payload: Dict):
        # Retrieve executed steps from Redis for idempotency and recovery
        executed_steps_json = redis_client.hget(f"saga:{saga_id}", "executed_steps")
        executed_steps = json.loads(executed_steps_json) if executed_steps_json else []

        redis_client.hset(f"saga:{saga_id}", "status", "executing")
        redis_client.hset(f"saga:{saga_id}", "payload", json.dumps(payload))

        try:
            for step in self.steps:
                if step.name in executed_steps:
                    print(
                        f"Step {step.name} already executed for saga {saga_id}. Skipping."
                    )
                    continue  # Skip already executed steps in case of retry/recovery

                print(f"Executing step: {step.name} for saga {saga_id}")
                result = await step.action_func(payload)

                if not result.get("success", False):
                    # Execution failed, initiate compensation
                    print(
                        f"Step {step.name} failed for saga {saga_id}. Initiating compensation."
                    )
                    await self.compensate(saga_id, payload)
                    return {"success": False, "error": result.get("error")}

                # Mark step as executed
                executed_steps.append(step.name)
                redis_client.hset(
                    f"saga:{saga_id}", "executed_steps", json.dumps(executed_steps)
                )

            redis_client.hset(f"saga:{saga_id}", "status", "completed")
            print(f"Saga {saga_id} completed successfully.")
            return {"success": True}

        except Exception as e:
            print(f"An unexpected error occurred during saga {saga_id} execution: {e}")
            await self.compensate(saga_id, payload)
            return {"success": False, "error": str(e)}

    async def compensate(self, saga_id: str, payload: Dict):
        print(f"Compensating saga {saga_id}...")
        redis_client.hset(f"saga:{saga_id}", "status", "compensating")

        executed_steps_json = redis_client.hget(f"saga:{saga_id}", "executed_steps")
        executed_steps = json.loads(executed_steps_json) if executed_steps_json else []

        # Iterate through steps in reverse order of execution
        for step_name in reversed(executed_steps):
            step = next((s for s in self.steps if s.name == step_name), None)
            if step and step.compensation_func:
                print(
                    f"Executing compensation for step: {step.name} for saga {saga_id}"
                )
                await step.compensation_func(payload)
            else:
                print(f"No compensation function for step: {step_name}")

        redis_client.hset(f"saga:{saga_id}", "status", "compensated")
        print(f"Saga {saga_id} compensated.")


# 建立 FastAPI app
app = FastAPI(title="訂單服務 - Orchestration")

# 建立 static/images 目錄並掛載
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
IMAGES_DIR = os.path.join(STATIC_DIR, "images")
os.makedirs(IMAGES_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# 共享依賴項
def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 使用者驗證相關函數
async def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except jwt.PyJWTError:
        raise credentials_exception

    stmt = select(User).where(
        and_(User.username == token_data.username, User.is_deleted == False)
    )
    result = db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception
    return user


async def get_staff_user(current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.STAFF, UserRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要店員權限",
        )
    return current_user


async def get_customer_user(current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.CUSTOMER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要顧客帳號",
        )
    return current_user


async def get_admin_user(current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理員權限",
        )
    return current_user


# 訂單相關函數
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
        return {"success": False, "error": str(e)}
    finally:
        db.close()


async def compensate_payment(payload: Dict):
    if "payment_id" in payload:
        db = SessionLocal()
        try:
            # SQLAlchemy 2.0 查詢
            stmt = select(Payment).where(
                and_(
                    Payment.payment_id == payload["payment_id"],
                    Payment.is_deleted == False,
                )
            )
            result = db.execute(stmt)
            payment = result.scalar_one_or_none()

            if payment and payment.status in [
                PaymentStatus.PENDING,
                PaymentStatus.COMPLETED,
            ]:
                payment.status = PaymentStatus.REFUNDED
                db.commit()
                print(
                    f"Payment {payment.payment_id} refunded for order {payment.order_id}."
                )
            elif payment:
                print(
                    f"Payment {payment.payment_id} for order {payment.order_id} is already {payment.status}, no refund needed/possible."
                )
        except Exception as e:
            print(
                f"Error during payment compensation for {payload.get('payment_id')}: {e}"
            )
        finally:
            db.close()


async def prepare_kitchen(payload: Dict):
    db = SessionLocal()
    try:
        # In orchestration, we might check payment status before proceeding
        # But the orchestrator will ensure the payment step completed (i.e., record created).
        # The actual "confirmed" status is handled by a separate manual action.
        # For this simplified orchestrator, we assume `process_payment` succeeded if the record exists.

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

        # Simulate kitchen preparation
        if random.random() > 0.05:  # 95% 成功率
            kitchen_order.status = "preparing"
            db.commit()
            payload["kitchen_order_id"] = kitchen_order_id
            print(
                f"Kitchen order {kitchen_order_id} for order {payload['order_id']} is preparing."
            )
            return {"success": True}
        else:
            db.rollback()  # Rollback the kitchen order creation if it fails immediately
            print(f"Kitchen preparation failed for order {payload['order_id']}.")
            return {"success": False, "error": "Kitchen unavailable"}
    except Exception as e:
        db.rollback()
        print(
            f"Error during kitchen preparation for order {payload.get('order_id')}: {e}"
        )
        return {"success": False, "error": str(e)}
    finally:
        db.close()


async def compensate_kitchen(payload: Dict):
    if "kitchen_order_id" in payload:
        db = SessionLocal()
        try:
            # SQLAlchemy 2.0 查詢
            stmt = select(Kitchen).where(
                and_(
                    Kitchen.kitchen_order_id == payload["kitchen_order_id"],
                    Kitchen.is_deleted == False,
                )
            )
            result = db.execute(stmt)
            kitchen_order = result.scalar_one_or_none()

            if kitchen_order:
                kitchen_order.status = "cancelled"
                db.commit()
                print(
                    f"Kitchen order {kitchen_order.kitchen_order_id} for order {kitchen_order.order_id} cancelled."
                )
        except Exception as e:
            print(
                f"Error during kitchen compensation for {payload.get('kitchen_order_id')}: {e}"
            )
        finally:
            db.close()


async def arrange_delivery(payload: Dict):
    db = SessionLocal()
    try:
        delivery_id = str(uuid.uuid4())
        delivery = Delivery(
            delivery_id=delivery_id,
            order_id=payload["order_id"],
            address=payload["delivery_address"],
            status="pending",
        )
        db.add(delivery)
        db.commit()
        db.refresh(delivery)

        # Simulate delivery arrangement
        delivery.status = "assigned"
        delivery.driver_id = f"driver_{random.randint(1, 10)}"
        db.commit()
        payload["delivery_id"] = delivery_id
        print(
            f"Delivery {delivery_id} for order {payload['order_id']} assigned to {delivery.driver_id}."
        )
        return {"success": True}
    except Exception as e:
        db.rollback()
        print(
            f"Error during delivery arrangement for order {payload.get('order_id')}: {e}"
        )
        return {"success": False, "error": str(e)}
    finally:
        db.close()


# 設置路由
@app.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    stmt = select(User).where(
        and_(User.username == form_data.username, User.is_deleted == False)
    )
    result = db.execute(stmt)
    user = result.scalar_one_or_none()

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
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role,
    }


from fastapi import APIRouter


user_router = APIRouter(prefix="/orchestration/users", tags=["User"])


@user_router.post("", response_model=UserResponse)
async def create_user(user: UserCreate, db: Session = Depends(get_db)):
    # 檢查用戶名是否已存在
    stmt = select(User).where(User.username == user.username)
    result = db.execute(stmt)
    db_user = result.scalar_one_or_none()
    if db_user:
        raise HTTPException(status_code=400, detail="用戶名已被註冊")

    # 檢查電子郵件是否已存在
    stmt = select(User).where(User.email == user.email)
    result = db.execute(stmt)
    db_user = result.scalar_one_or_none()
    if db_user:
        raise HTTPException(status_code=400, detail="電子郵件已被註冊")

    # 如果是顧客，需要同時創建顧客記錄
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
            # 檢查提供的 customer_id 是否存在
            stmt = select(Customer).where(
                and_(
                    Customer.customer_id == user.customer_id,
                    Customer.is_deleted == False,
                )
            )
            result = db.execute(stmt)
            existing_customer = result.scalar_one_or_none()
            if not existing_customer:
                raise HTTPException(
                    status_code=404,
                    detail=f"顧客ID '{user.customer_id}' 不存在",
                )
            customer_id = user.customer_id

    # 創建用戶
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
    current_user: User = Depends(get_customer_user),  # 只有顧客可以創建訂單
):
    # 驗證顧客ID
    if current_user.customer_id != order.customer_id:
        raise HTTPException(status_code=403, detail="無法以其他顧客身份下單")

    # 計算總金額
    total_amount = sum(item["price"] * item["quantity"] for item in order.items)

    # 創建訂單
    order_id = str(uuid.uuid4())
    saga_id = str(uuid.uuid4())

    db_order = Order(
        order_id=order_id,
        customer_id=order.customer_id,
        items=json.dumps(order.items),
        total_amount=total_amount,
        saga_id=saga_id,
        status=OrderStatus.PENDING,  # Initial status
    )
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    # 新增訂單狀態歷程
    db.add(OrderStatusHistory(order_id=order_id, status=db_order.status))
    db.commit()

    # Initialize saga state in Redis
    redis_client.hset(f"saga:{saga_id}", "status", "pending_start")
    redis_client.hset(f"saga:{saga_id}", "executed_steps", json.dumps([]))
    redis_client.hset(
        f"saga:{saga_id}", "order_id", order_id
    )  # Store order_id for easy lookup

    # Define the saga steps
    orchestrator = SagaOrchestrator()
    orchestrator.add_step(SagaStep("payment", process_payment, compensate_payment))
    orchestrator.add_step(SagaStep("kitchen", prepare_kitchen, compensate_kitchen))
    orchestrator.add_step(SagaStep("delivery", arrange_delivery, compensate_delivery))

    # Initial payload for the saga
    payload = {
        "order_id": order_id,
        "customer_id": order.customer_id,
        "items": order.items,
        "total_amount": total_amount,
        "delivery_address": order.delivery_address,
        "payment_method": order.payment_method.value,  # Pass payment method
    }

    # Execute the saga steps. For manual payment, this will create the pending payment record.
    # The orchestrator doesn't "wait" for manual confirmation in this synchronous flow.
    # It just records that the payment step has been initiated.
    print(f"Starting orchestration for order {order_id} with saga {saga_id}.")
    result = await orchestrator.execute(saga_id, payload)

    # Update order status based on initial saga execution result
    if result["success"]:
        # If all steps were "initiated" successfully (payment pending, kitchen received, delivery assigned)
        # the order can be considered CONFIRMED or in PREPARING state, depending on definition.
        # For a manual payment, it makes sense to keep it PENDING until payment is *actually* confirmed.
        # However, the orchestrator 'succeeded' in initiating the process.
        # We'll set it to pending here and rely on the /confirm-payment endpoint to truly confirm.
        db_order.status = (
            OrderStatus.PENDING
        )  # Still pending until payment is confirmed
        print(
            f"Order {order_id} initiated successfully. Payment awaiting confirmation."
        )
    else:
        db_order.status = OrderStatus.CANCELLED
        print(
            f"Order {order_id} cancelled during initial orchestration: {result.get('error')}"
        )
    db.commit()

    return OrderResponse(
        order_id=order_id, status=db_order.status, total_amount=total_amount
    )


@app.post("/orchestration/payments/{payment_id}/confirm")
async def confirm_orchestration_payment(
    payment_id: str,
    confirmation: PaymentConfirmation,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_staff_user),  # 只有店員可以確認付款
):
    # SQLAlchemy 2.0 查詢
    stmt = select(Payment).where(
        and_(Payment.payment_id == payment_id, Payment.is_deleted == False)
    )
    result = db.execute(stmt)
    payment = result.scalar_one_or_none()

    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    if payment.status != PaymentStatus.PENDING:
        raise HTTPException(status_code=400, detail="Payment is not in pending status")

    # SQLAlchemy 2.0 查詢
    stmt = select(Order).where(
        and_(Order.order_id == payment.order_id, Order.is_deleted == False)
    )
    result = db.execute(stmt)
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Associated order not found")

    orchestrator = SagaOrchestrator()
    orchestrator.add_step(SagaStep("payment", process_payment, compensate_payment))
    orchestrator.add_step(SagaStep("kitchen", prepare_kitchen, compensate_kitchen))
    orchestrator.add_step(SagaStep("delivery", arrange_delivery, compensate_delivery))

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
        # 新增訂單狀態歷程
        db.add(
            OrderStatusHistory(order_id=order.order_id, status=OrderStatus.CONFIRMED)
        )
        db.commit()
        print(
            f"Orchestration Payment {payment_id} confirmed successfully. Resuming saga."
        )

        # Manually mark payment step as completed in redis (as it was awaiting confirmation)
        executed_steps_json = redis_client.hget(f"saga:{saga_id}", "executed_steps")
        executed_steps = json.loads(executed_steps_json) if executed_steps_json else []
        if (
            "payment" not in executed_steps
        ):  # Should already be there from initial execute, but good to ensure
            executed_steps.append("payment")
            redis_client.hset(
                f"saga:{saga_id}", "executed_steps", json.dumps(executed_steps)
            )

        # Update the order status since payment is confirmed
        order.status = OrderStatus.CONFIRMED  # Now the order can be truly confirmed
        db.commit()

        # Attempt to execute subsequent steps of the saga *from* the 'kitchen' step
        # This would typically be done by a dedicated "saga recovery/continuation" worker
        # For this example, we'll re-run the orchestrator but it needs to skip already executed steps.
        # The orchestrator's `execute` method has been updated to handle already executed steps.

        continuation_result = await orchestrator.execute(saga_id, payload)

        if continuation_result["success"]:
            order.status = OrderStatus.DELIVERED
            print(
                f"Orchestration saga for order {order.order_id} completed after manual payment confirmation."
            )
            # 新增訂單狀態歷程
            db.add(
                OrderStatusHistory(
                    order_id=order.order_id, status=OrderStatus.DELIVERED
                )
            )
            db.commit()
        else:
            order.status = OrderStatus.CANCELLED
            print(
                f"Orchestration saga for order {order.order_id} failed during subsequent steps after payment confirmation: {continuation_result.get('error')}"
            )
            db.add(
                OrderStatusHistory(
                    order_id=order.order_id, status=OrderStatus.CANCELLED
                )
            )
            db.commit()
    else:
        payment.status = PaymentStatus.FAILED
        db.commit()
        # 新增訂單狀態歷程
        db.add(
            OrderStatusHistory(order_id=order.order_id, status=OrderStatus.CANCELLED)
        )
        db.commit()

        print(
            f"Orchestration Payment {payment_id} marked as failed. Initiating saga compensation."
        )

        # Trigger compensation for the saga
        await orchestrator.compensate(saga_id, payload)

        order.status = OrderStatus.CANCELLED  # Order is cancelled if payment fails
        db.commit()

        return {
            "message": "Payment failed and saga compensation initiated.",
            "saga_status": redis_client.hget(f"saga:{saga_id}", "status").decode(
                "utf-8"
            ),
        }


@app.get("/orchestration/orders/{order_id}", response_model=OrderResponse)
def get_order_status_orchestration(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # 任何登錄用戶
):
    # SQLAlchemy 2.0 查詢
    stmt = select(Order).where(
        and_(Order.order_id == order_id, Order.is_deleted == False)
    )
    result = db.execute(stmt)
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # 顧客只能查看自己的訂單
    if (
        current_user.role == UserRole.CUSTOMER
        and current_user.customer_id != order.customer_id
    ):
        raise HTTPException(status_code=403, detail="無權查看此訂單")

    return OrderResponse(
        order_id=order.order_id,
        status=order.status,
        total_amount=order.total_amount,
    )


@app.get("/orchestration/orders", response_model=List[OrderResponse])
def list_orders(
    customer_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 權限檢查：顧客只能查看自己的訂單
    if current_user.role == UserRole.CUSTOMER:
        customer_id = current_user.customer_id

    # SQLAlchemy 2.0 查詢
    stmt = select(Order).where(Order.is_deleted == False)
    if customer_id:
        stmt = stmt.where(Order.customer_id == customer_id)
    result = db.execute(stmt)
    orders = result.scalars().all()

    return [
        OrderResponse(
            order_id=o.order_id,
            status=o.status,
            total_amount=o.total_amount,
        )
        for o in orders
    ]


@app.post("/orchestration/orders/{order_id}/cancel")
async def cancel_order(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # SQLAlchemy 2.0 查詢
    stmt = select(Order).where(
        and_(Order.order_id == order_id, Order.is_deleted == False)
    )
    result = db.execute(stmt)
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # 權限檢查：顧客只能取消自己的訂單
    if (
        current_user.role == UserRole.CUSTOMER
        and current_user.customer_id != order.customer_id
    ):
        raise HTTPException(status_code=403, detail="無權取消此訂單")

    if order.status in [OrderStatus.CANCELLED, OrderStatus.DELIVERED]:
        raise HTTPException(status_code=400, detail="Order cannot be cancelled")
    order.status = OrderStatus.CANCELLED
    db.commit()
    # 新增訂單狀態歷程
    db.add(OrderStatusHistory(order_id=order_id, status=OrderStatus.CANCELLED))
    db.commit()
    return {"message": f"Order {order_id} cancelled."}


kitchen_router = APIRouter(prefix="/orchestration/kitchen", tags=["Kitchen"])


@kitchen_router.get("/orders/{kitchen_order_id}")
def get_kitchen_order_status(
    kitchen_order_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_staff_user),  # 只有店員可以查看廚房訂單
):
    # SQLAlchemy 2.0 查詢
    stmt = select(Kitchen).where(
        and_(
            Kitchen.kitchen_order_id == kitchen_order_id,
            Kitchen.is_deleted == False,
        )
    )
    result = db.execute(stmt)
    kitchen_order = result.scalar_one_or_none()

    if not kitchen_order:
        raise HTTPException(status_code=404, detail="Kitchen order not found")
    return {
        "kitchen_order_id": kitchen_order.kitchen_order_id,
        "order_id": kitchen_order.order_id,
        "status": kitchen_order.status,
        "estimated_time": kitchen_order.estimated_time,
        "created_at": kitchen_order.created_at,
    }


app.include_router(kitchen_router)


from fastapi import APIRouter

delivery_router = APIRouter(prefix="/orchestration/delivery", tags=["Delivery"])


@delivery_router.get("/orders/{delivery_id}")
def get_delivery_status(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_staff_user),  # 只有店員可以查看配送狀態
):
    # SQLAlchemy 2.0 查詢
    stmt = select(Delivery).where(
        and_(Delivery.delivery_id == delivery_id, Delivery.is_deleted == False)
    )
    result = db.execute(stmt)
    delivery = result.scalar_one_or_none()

    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return {
        "delivery_id": delivery.delivery_id,
        "order_id": delivery.order_id,
        "status": delivery.status,
        "driver_id": delivery.driver_id,
        "created_at": delivery.created_at,
    }


app.include_router(delivery_router)


menu_router = APIRouter(prefix="/orchestration/menu", tags=["Menu"])


@menu_router.get("/items")
def get_menu_items(db: Session = Depends(get_db)):
    # 菜單可以公開訪問，無需權限
    stmt = select(MenuItem).where(MenuItem.is_deleted == False)
    result = db.execute(stmt)
    items = result.scalars().all()

    return [
        {
            "id": item.id,
            "name": item.name,
            "price": item.price,
            "description": item.description,
            "image_url": item.image_url,  # 回傳圖片路徑（相對URL）
        }
        for item in items
    ]


app.include_router(menu_router)


from fastapi import APIRouter

menu_admin_router = APIRouter(prefix="/orchestration/menu/admin", tags=["MenuAdmin"])


@menu_admin_router.post("/items", response_model=MenuItemResponse)
def create_menu_item(
    name: str = Form(...),
    price: float = Form(...),
    description: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_staff_user),  # 只有店員可以創建菜單項目
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
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@menu_admin_router.put("/items/{item_id}", response_model=MenuItemResponse)
def update_menu_item(
    item_id: int,
    name: str = Form(...),
    price: float = Form(...),
    description: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_staff_user),  # 只有店員可以更新菜單項目
):
    # SQLAlchemy 查詢
    stmt = select(MenuItem).where(
        and_(MenuItem.id == item_id, MenuItem.is_deleted == False)
    )
    result = db.execute(stmt)
    db_item = result.scalar_one_or_none()

    if not db_item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    try:
        if image:
            # 儲存新圖並覆寫 image_url（不做舊檔刪除以簡化）
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
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# 修改 get_menu_items 回傳 image_url（若已有此段就只是補 image_url 欄位）
@menu_router.get("/items")
def get_menu_items(db: Session = Depends(get_db)):
    # 菜單可以公開訪問，無需權限
    stmt = select(MenuItem).where(MenuItem.is_deleted == False)
    result = db.execute(stmt)
    items = result.scalars().all()

    return [
        {
            "id": item.id,
            "name": item.name,
            "price": item.price,
            "description": item.description,
            "image_url": item.image_url,  # 回傳圖片路徑（相對URL）
        }
        for item in items
    ]


app.include_router(menu_admin_router)


from fastapi import APIRouter

history_router = APIRouter(
    prefix="/orchestration/orders/history", tags=["OrderHistory"]
)


@history_router.get("/{order_id}", response_model=List[OrderStatusHistoryResponse])
def get_order_history(order_id: str, db: Session = Depends(get_db)):
    # SQLAlchemy 2.0 查詢
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
    result = db.execute(stmt)
    history = result.scalars().all()

    return history


app.include_router(history_router)


customer_router = APIRouter(prefix="/orchestration/customers", tags=["Customer"])


@customer_router.post("", response_model=CustomerResponse)
def create_customer(
    customer: CustomerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_staff_user),  # 只有店員可以直接創建顧客
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
    current_user: User = Depends(get_current_user),  # 任何已登入用戶
):
    # 權限檢查：普通顧客只能查看自己的資料
    if (
        current_user.role == UserRole.CUSTOMER
        and current_user.customer_id != customer_id
    ):
        raise HTTPException(status_code=403, detail="無權查看其他顧客資料")

    # SQLAlchemy 2.0 查詢
    stmt = select(Customer).where(
        and_(Customer.customer_id == customer_id, Customer.is_deleted == False)
    )
    result = db.execute(stmt)
    customer = result.scalar_one_or_none()

    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@customer_router.get("", response_model=List[CustomerResponse])
def list_customers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_staff_user),  # 只有店員可以列出所有顧客
):
    # SQLAlchemy 2.0 查詢
    stmt = select(Customer).where(Customer.is_deleted == False)
    result = db.execute(stmt)
    customers = result.scalars().all()

    return customers


app.include_router(customer_router)


# Create database tables and run migrations
Base.metadata.create_all(bind=engine)

# # Import and run migrations
# from db_migrations import run_migrations

# try:
#     run_migrations()
# except Exception as e:
#     print(f"Warning: Migration failed: {e}")


# Create initial users if not exist
def create_initial_users():
    db = SessionLocal()
    try:
        # 檢查是否已有管理員
        stmt = select(User).where(User.role == UserRole.ADMIN)
        result = db.execute(stmt)
        admin = result.scalar_one_or_none()

        if not admin:
            admin_user = User(
                username="admin",
                email="admin@example.com",
                hashed_password=get_password_hash("admin"),
                role=UserRole.ADMIN,
            )
            db.add(admin_user)

        # 檢查是否已有店員
        stmt = select(User).where(User.role == UserRole.STAFF)
        result = db.execute(stmt)
        staff = result.scalar_one_or_none()

        if not staff:
            staff_user = User(
                username="staff",
                email="staff@example.com",
                hashed_password=get_password_hash("staff"),
                role=UserRole.STAFF,
            )
            db.add(staff_user)

        # 檢查是否已有顧客
        stmt = select(User).where(User.role == UserRole.CUSTOMER)
        result = db.execute(stmt)
        customer = result.scalar_one_or_none()

        if not customer:
            # 創建顧客記錄
            customer_id = str(uuid.uuid4())
            db_customer = Customer(
                customer_id=customer_id, name="customer", email="customer@example.com"
            )
            db.add(db_customer)
            db.commit()

            # 創建顧客用戶
            customer_user = User(
                username="customer",
                email="customer@example.com",
                hashed_password=get_password_hash("customer"),
                role=UserRole.CUSTOMER,
                customer_id=customer_id,
            )
            db.add(customer_user)

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error creating initial users: {e}")
    finally:
        db.close()


# Use example
if __name__ == "__main__":
    # 初始化範例用戶
    create_initial_users()

    import uvicorn

    print("Saga Pattern 實現完成！")
    print("Orchestration-based: 集中式協調，統一控制流程")
    print("Starting Orchestration service on port 8002 (Order)")

    async def run_orchestration_services():
        config_orchestration = uvicorn.Config(
            app, host="0.0.0.0", port=8002, log_level="info"
        )
        server_orchestration = uvicorn.Server(config_orchestration)
        await server_orchestration.serve()

    async def main():
        try:
            print("\n--- Running Orchestration Service (Order on 8002) ---")
            asyncio.create_task(run_orchestration_services())

            while True:
                await asyncio.sleep(3600)
        except Exception as e:
            print(e.__traceback__.tb_lineno)
            print(e)

    asyncio.run(main())

    print(
        "5. For Orchestration Order Service: uvicorn your_script_name:orchestration_order_service.app --host 0.0.0.0 --port 8002"
    )

    print("\n--- Orchestration Saga ---")
    print("1. Create an order: POST http://localhost:8002/orchestration/orders")
    print(
        "   Body: {'customer_id': 'cust456', 'items': [{'name': 'Pizza', 'price': 15.0, 'quantity': 1}], 'delivery_address': '456 Oak Ave', 'payment_method': 'cash'}"
    )
    print(
        "   This will create a PENDING payment record in the DB and initiate the saga."
    )
    print(
        "2. Clerk confirms payment: POST http://localhost:8002/orchestration/payments/{payment_id}/confirm"
    )
    print("   Body: {'success': true}")
    print("   Or to fail: {'success': false}")
    print("   Replace {payment_id} with the actual payment_id from the DB.")
    print("   This will trigger the continuation or compensation of the saga.")
    print(
        "3. Check order status: GET http://localhost:8002/orchestration/orders/{order_id}"
    )
    print(
        "4. Check kitchen order status: GET http://localhost:8002/orchestration/kitchen/orders/{delivery_id}"
    )
    print(
        "5. Check delivery status: GET http://localhost:8002/orchestration/delivery/orders/{delivery_id}"
    )

    # For running from a single script (less ideal for multiple FastAPI apps but works for demo):
    # This requires more advanced async handling or using a process manager.
    # For now, stick to the `uvicorn` commands as recommended above.
    print(
        "2. Clerk confirms payment: POST http://localhost:8002/orchestration/payments/{payment_id}/confirm"
    )
    print("   Body: {'success': true}")
    print("   Or to fail: {'success': false}")
    print("   Replace {payment_id} with the actual payment_id from the DB.")
    print("   This will trigger the continuation or compensation of the saga.")
    print(
        "3. Check order status: GET http://localhost:8002/orchestration/orders/{order_id}"
    )
    print(
        "4. Check kitchen order status: GET http://localhost:8002/orchestration/kitchen/orders/{delivery_id}"
    )
    print(
        "5. Check delivery status: GET http://localhost:8002/orchestration/delivery/orders/{delivery_id}"
    )

    # For running from a single script (less ideal for multiple FastAPI apps but works for demo):
    # This requires more advanced async handling or using a process manager.
    # For now, stick to the `uvicorn` commands as recommended above.
    print("\n--- 認證指南 ---")
    print("1. 獲取令牌: POST http://localhost:8002/token")
    print("   表單數據: username=staff&password=staff")
    print("   或: username=customer&password=customer")
    print("   或: username=admin&password=admin")
    print("2. 使用令牌: 在請求標頭中添加 'Authorization: Bearer {token}'")
    print("3. 顧客只能查看和管理自己的訂單")
    print("4. 店員可以查看所有訂單並確認付款")
    print("5. 管理員可以執行所有操作")

    print("\n--- 顧客ID說明 ---")
    print("1. 顧客ID是識別餐廳顧客的唯一標識符")
    print("2. 顧客在註冊時系統會自動生成顧客ID")
    print("3. 有三種方式獲取顧客ID:")
    print("   a. 註冊新用戶時，系統自動生成")
    print(
        "   b. 從用戶個人資料中查詢: GET http://localhost:8002/orchestration/users/me"
    )
    print("   c. 餐廳工作人員可以通過顧客管理系統查詢")
    print("4. 顧客下訂單時，系統會自動使用其帳戶關聯的顧客ID")
    print("5. 顧客只能使用自己的顧客ID下單，系統會自動驗證")
    print("1. Create an order: POST http://localhost:8002/orchestration/orders")
    print(
        "   Body: {'customer_id': 'cust456', 'items': [{'name': 'Pizza', 'price': 15.0, 'quantity': 1}], 'delivery_address': '456 Oak Ave', 'payment_method': 'cash'}"
    )
    print(
        "   This will create a PENDING payment record in the DB and initiate the saga."
    )
    print(
        "2. Clerk confirms payment: POST http://localhost:8002/orchestration/payments/{payment_id}/confirm"
    )
    print("   Body: {'success': true}")
    print("   Or to fail: {'success': false}")
    print("   Replace {payment_id} with the actual payment_id from the DB.")
    print("   This will trigger the continuation or compensation of the saga.")
    print(
        "3. Check order status: GET http://localhost:8002/orchestration/orders/{order_id}"
    )
    print(
        "4. Check kitchen order status: GET http://localhost:8002/orchestration/kitchen/orders/{delivery_id}"
    )
    print(
        "5. Check delivery status: GET http://localhost:8002/orchestration/delivery/orders/{delivery_id}"
    )

    # For running from a single script (less ideal for multiple FastAPI apps but works for demo):
    # This requires more advanced async handling or using a process manager.
    # For now, stick to the `uvicorn` commands as recommended above.
    print(
        "2. Clerk confirms payment: POST http://localhost:8002/orchestration/payments/{payment_id}/confirm"
    )
    print("   Body: {'success': true}")
    print("   Or to fail: {'success': false}")
    print("   Replace {payment_id} with the actual payment_id from the DB.")
    print("   This will trigger the continuation or compensation of the saga.")
    print(
        "3. Check order status: GET http://localhost:8002/orchestration/orders/{order_id}"
    )
    print(
        "4. Check kitchen order status: GET http://localhost:8002/orchestration/kitchen/orders/{delivery_id}"
    )
    print(
        "5. Check delivery status: GET http://localhost:8002/orchestration/delivery/orders/{delivery_id}"
    )

    # For running from a single script (less ideal for multiple FastAPI apps but works for demo):
    # This requires more advanced async handling or using a process manager.
    # For now, stick to the `uvicorn` commands as recommended above.
    print("\n--- 認證指南 ---")
    print("1. 獲取令牌: POST http://localhost:8002/token")
    print("   表單數據: username=staff&password=staff")
    print("   或: username=customer&password=customer")
    print("   或: username=admin&password=admin")
    print("2. 使用令牌: 在請求標頭中添加 'Authorization: Bearer {token}'")
    print("3. 顧客只能查看和管理自己的訂單")
    print("4. 店員可以查看所有訂單並確認付款")
    print("5. 管理員可以執行所有操作")

    print("\n--- 顧客ID說明 ---")
    print("1. 顧客ID是識別餐廳顧客的唯一標識符")
    print("2. 顧客在註冊時系統會自動生成顧客ID")
    print("3. 有三種方式獲取顧客ID:")
    print("   a. 註冊新用戶時，系統自動生成")
    print(
        "   b. 從用戶個人資料中查詢: GET http://localhost:8002/orchestration/users/me"
    )
    print("   c. 餐廳工作人員可以通過顧客管理系統查詢")
    print("4. 顧客下訂單時，系統會自動使用其帳戶關聯的顧客ID")
    print("5. 顧客只能使用自己的顧客ID下單，系統會自動驗證")
