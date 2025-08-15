from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import logging

# 配置日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 資料庫配置
DATABASE_URL = "postgresql://user:password@localhost/restaurant_db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def ensure_soft_delete_columns():
    """確保所有表都有軟刪除欄位"""
    tables = [
        "orders",
        "payments",
        "kitchen_orders",
        "deliveries",
        "menu_items",
        "customers",
        "order_status_history",
        "users",
    ]

    with engine.connect() as conn:
        for table in tables:
            try:
                # 檢查 is_deleted 欄位是否存在
                check_sql = text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = :table AND column_name = 'is_deleted'"
                )
                result = conn.execute(check_sql, {"table": table}).first()

                if not result:
                    logger.info(f"Adding soft delete columns to {table}")
                    # 新增軟刪除欄位
                    conn.execute(
                        text(
                            f"""
                        ALTER TABLE {table} 
                        ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE,
                        ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE
                    """
                        )
                    )
                    conn.commit()
                    logger.info(f"Successfully added soft delete columns to {table}")
                else:
                    logger.info(f"Soft delete columns already exist in {table}")

            except Exception as e:
                logger.error(f"Error adding soft delete columns to {table}: {e}")


def run_migrations():
    """執行所有遷移"""
    logger.info("Starting database migrations...")

    try:
        # 1. 確保軟刪除欄位存在
        ensure_soft_delete_columns()

        # 在此處添加其他遷移步驟...

        logger.info("Migrations completed successfully")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise


if __name__ == "__main__":
    run_migrations()
