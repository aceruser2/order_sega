# 分佈式訂單系統規格書

## 目錄
1. [系統概述](#1-系統概述)
2. [架構設計](#2-架構設計)
3. [技術堆疊](#3-技術堆疊)
4. [後端規格](#4-後端規格)
5. [前端規格](#5-前端規格)
6. [數據模型](#6-數據模型)
7. [安全性實現](#7-安全性實現)
8. [Saga 分佈式事務管理](#8-saga-分佈式事務管理)
9. [部署指南](#9-部署指南)
10. [測試案例](#10-測試案例)

## 1. 系統概述

本系統是一個基於微服務架構的餐廳訂單管理系統，使用 Saga 模式實現分佈式事務處理。系統包含訂單服務、支付服務、廚房服務和配送服務，以確保餐廳訂單流程的完整性和可靠性。

### 1.1 系統目標

- 提供可靠的餐廳訂單管理平台
- 實現微服務架構，各服務獨立部署、開發和擴展
- 利用 Saga 模式確保分佈式事務的一致性
- 支持多用戶角色：顧客、店員、管理員
- 提供友好的前端界面

### 1.2 核心功能

- 用戶認證與授權
- 菜單管理
- 訂單創建與處理
- 支付確認
- 廚房訂單追蹤
- 配送管理
- 訂單狀態追蹤

## 2. 架構設計

系統採用微服務架構，基於 FastAPI 後端和 Streamlit 前端。

### 2.1 系統架構圖

```
+-----------------+      +-------------------+
|                 |      |                   |
|  前端應用       +----->+  訂單服務         |
| (Streamlit)     |      | (Orchestration)   |
|                 |      |                   |
+-----------------+      +--------+----------+
                               |
                               |
                 +-------------v-------------+
                 |                           |
      +----------v------+   +---------------v+   +-------------+
      |                 |   |                |   |             |
      |  支付服務       |   |  廚房服務      |   |  配送服務   |
      |                 |   |                |   |             |
      +-----------------+   +----------------+   +-------------+
```

### 2.2 業務流程

1. 顧客瀏覽菜單
2. 顧客創建訂單
3. 系統創建訂單記錄並初始化 Saga
4. 生成支付記錄 (待確認)
5. 店員確認支付
6. 廚房開始準備餐點
7. 配送安排
8. 訂單完成

## 3. 技術堆疊

### 3.1 後端技術

- **Python**: 主要程序語言
- **FastAPI**: Web 框架
- **SQLAlchemy**: ORM 框架 (2.0 版本)
- **PostgreSQL**: 關係型數據庫
- **Redis**: 緩存和 Saga 狀態管理
- **JWT**: 認證機制
- **Pydantic**: 數據驗證
- **Uvicorn**: ASGI 服務器

### 3.2 前端技術

- **Python**: 程序語言
- **Streamlit**: 前端框架
- **Requests**: HTTP 請求處理

## 4. 後端規格

### 4.1 API 端點概覽

#### 4.1.1 認證與用戶管理

| 端點 | 方法 | 描述 | 權限 |
|------|------|------|------|
| `/token` | POST | 獲取訪問令牌 | 公開 |
| `/orchestration/users` | POST | 創建用戶 | 公開 |
| `/orchestration/users/me` | GET | 獲取當前用戶信息 | 已登入用戶 |

#### 4.1.2 菜單管理

| 端點 | 方法 | 描述 | 權限 |
|------|------|------|------|
| `/orchestration/menu/items` | GET | 獲取菜單項目 | 公開 |
| `/orchestration/menu/admin/items` | POST | 創建菜單項目 | 店員/管理員 |
| `/orchestration/menu/admin/items/{id}` | PUT | 更新菜單項目 | 店員/管理員 |
| `/orchestration/menu/admin/items/{id}` | DELETE | 刪除菜單項目 | 店員/管理員 |

#### 4.1.3 訂單管理

| 端點 | 方法 | 描述 | 權限 |
|------|------|------|------|
| `/orchestration/orders` | POST | 創建訂單 | 顧客 |
| `/orchestration/orders` | GET | 獲取訂單列表 | 所有登入用戶 |
| `/orchestration/orders/{id}` | GET | 獲取訂單詳情 | 所有登入用戶 |
| `/orchestration/orders/{id}/cancel` | POST | 取消訂單 | 所有登入用戶 |
| `/orchestration/orders/history/{id}` | GET | 獲取訂單狀態歷史 | 所有登入用戶 |

#### 4.1.4 支付管理

| 端點 | 方法 | 描述 | 權限 |
|------|------|------|------|
| `/orchestration/payments/{id}/confirm` | POST | 確認支付 | 店員/管理員 |

#### 4.1.5 廚房管理

| 端點 | 方法 | 描述 | 權限 |
|------|------|------|------|
| `/orchestration/kitchen/orders/{id}` | GET | 獲取廚房訂單 | 店員/管理員 |

#### 4.1.6 配送管理

| 端點 | 方法 | 描述 | 權限 |
|------|------|------|------|
| `/orchestration/delivery/orders/{id}` | GET | 獲取配送訂單 | 店員/管理員 |

#### 4.1.7 顧客管理

| 端點 | 方法 | 描述 | 權限 |
|------|------|------|------|
| `/orchestration/customers` | POST | 創建顧客 | 店員/管理員 |
| `/orchestration/customers` | GET | 獲取顧客列表 | 店員/管理員 |
| `/orchestration/customers/{id}` | GET | 獲取顧客詳情 | 所有登入用戶 |

### 4.2 權限控制

系統實現了三級權限模型：

1. **顧客**：只能訪問與自己相關的資源
   - 查看菜單
   - 創建訂單
   - 查看和取消自己的訂單

2. **店員**：可以執行餐廳操作
   - 所有顧客權限
   - 確認支付
   - 查看廚房訂單
   - 查看配送訂單
   - 管理菜單項目
   - 查看所有訂單

3. **管理員**：系統最高權限
   - 所有店員權限
   - 用戶管理
   - 系統配置

### 4.3 異常處理

系統實現了統一的異常處理機制：

- 4xx 錯誤：客戶端錯誤（如驗證失敗、權限不足）
- 5xx 錯誤：服務器錯誤

所有錯誤響應均提供詳細錯誤信息，幫助定位問題。

## 5. 前端規格

### 5.1 頁面結構

1. **登入頁面**：用戶認證和註冊
2. **菜單頁面**：顯示所有餐點
3. **購物車**：顯示所選商品和訂單確認
4. **訂單頁面**：顯示用戶訂單和狀態
5. **支付確認頁面**：店員確認顧客支付
6. **廚房管理頁面**：查看廚房訂單
7. **配送管理頁面**：查看配送狀態
8. **菜單管理頁面**：管理菜單項目
9. **顧客管理頁面**：管理顧客信息

### 5.2 用戶界面流程

```
登入/註冊 -> 瀏覽菜單 -> 將項目加入購物車 -> 結帳 -> 查看訂單狀態
```

店員額外流程：
```
登入 -> 確認支付 -> 查看廚房/配送訂單 -> 管理菜單項目
```

### 5.3 狀態管理

使用 Streamlit 的 `session_state` 管理用戶會話狀態：
- 認證令牌
- 用戶角色
- 購物車內容
- 當前選擇的頁面

## 6. 數據模型

### 6.1 關係型數據模型

系統包含以下主要數據表：

1. **User**: 用戶信息
   - id, username, email, hashed_password, role, customer_id, created_at

2. **Customer**: 顧客信息
   - id, customer_id, name, email, phone

3. **MenuItem**: 菜單項目
   - id, name, price, description

4. **Order**: 訂單
   - id, order_id, customer_id, items, total_amount, status, saga_id, created_at

5. **Payment**: 支付記錄
   - id, payment_id, order_id, amount, status, method, created_at

6. **Kitchen**: 廚房訂單
   - id, kitchen_order_id, order_id, items, status, estimated_time, created_at

7. **Delivery**: 配送記錄
   - id, delivery_id, order_id, address, status, driver_id, created_at

8. **OrderStatusHistory**: 訂單狀態歷史
   - id, order_id, status, changed_at

### 6.2 Saga 狀態模型

Redis 中存儲的 Saga 狀態：

```
saga:{saga_id} = {
    "status": "pending_start" | "executing" | "completed" | "compensating" | "compensated",
    "executed_steps": ["payment", "kitchen", "delivery"],
    "order_id": "order_id",
    "payload": { ... 事務數據 ... }
}
```

## 7. 安全性實現

### 7.1 認證機制

- 基於 JWT 的認證機制
- 令牌有效期：30分鐘
- 加密算法：HS256

### 7.2 密碼安全

- 密碼使用 bcrypt 進行哈希處理
- 不在數據庫中存儲明文密碼

### 7.3 權限控制

使用 FastAPI 的依賴項注入機制實現三層權限控制：
1. `get_current_user`: 驗證用戶身份
2. `get_staff_user`: 驗證店員權限
3. `get_customer_user`: 驗證顧客身份
4. `get_admin_user`: 驗證管理員權限

## 8. Saga 分佈式事務管理

### 8.1 Saga 模式概述

本系統採用 Orchestration（編排）模式的 Saga 實現，由中央協調器管理所有步驟的執行。

### 8.2 事務步驟

1. **訂單創建**：初始化訂單記錄
2. **支付處理**：創建支付記錄
3. **廚房處理**：創建廚房訂單
4. **配送安排**：安排配送

### 8.3 補償邏輯

每個步驟都有對應的補償操作：

1. **支付補償**：將支付狀態設置為已退款
2. **廚房補償**：取消廚房訂單
3. **配送補償**：取消配送安排

### 8.4 狀態持久化

使用 Redis 作為持久化層，存儲 Saga 執行狀態和已執行步驟，支持崩潰恢復和重試。

## 9. 部署指南

### 9.1 環境需求

- Python 3.8+
- PostgreSQL 12+
- Redis 6+

### 9.2 安裝依賴

```bash
pip install fastapi uvicorn sqlalchemy pydantic python-multipart python-jose[cryptography] passlib[bcrypt] psycopg2-binary redis pika streamlit
```

### 9.3 數據庫設置

1. 創建 PostgreSQL 數據庫：

```sql
CREATE DATABASE restaurant_db;
CREATE USER myuser WITH ENCRYPTED PASSWORD 'mypassword';
GRANT ALL PRIVILEGES ON DATABASE restaurant_db TO myuser;
```

2. 更新 DATABASE_URL：

```python
DATABASE_URL = "postgresql://myuser:mypassword@localhost/restaurant_db"
```

### 9.4 啟動後端

```bash
cd /home/acer/project/order_sega
alembic -c alembic.ini upgrade head
uvicorn backend_main:orchestration_order_service.app --host 0.0.0.0 --port 8002 --reload
```

### 9.5 啟動前端

```bash
cd /home/acer/project/order_sega
streamlit run front_main.py
```

## 10. 測試案例

### 10.1 單元測試

應包含以下單元測試：

1. **模型測試**：驗證各數據模型
2. **API 測試**：各 API 端點的功能測試
3. **權限測試**：驗證權限控制邏輯
4. **Saga 測試**：測試事務執行和補償

### 10.2 集成測試

測試各組件間的交互：

1. 訂單創建 -> 支付 -> 廚房 -> 配送
2. 不同角色權限驗證
3. 異常情況和補償機制

### 10.3 測試數據

系統自帶初始測試數據：

1. 默認用戶：
   - 管理員：username=admin, password=admin
   - 店員：username=staff, password=staff
   - 顧客：username=customer, password=customer

2. 示例菜單項目 (需手動添加)：
   - 披薩：$15
   - 漢堡：$10
   - 沙拉：$8

## 系統限制與未來擴展

### 當前限制

1. 無實時通知系統
2. 無支付網關集成
3. 有限的報表和分析功能
4. 無多語言支持

### 未來擴展

1. 實時訂單通知
2. 集成第三方支付
3. 高級報表和分析
4. 客戶忠誠度計劃
5. 移動應用程序
6. 多餐廳支持

---

文檔版本：1.0  
最後更新：2023-12-31

1. 菜單圖片上傳代測 v 
    The use_column_width parameter has been deprecated and will be removed in a future release. Please utilize the use_container_width parameter instead.
2. 顧客暫無信用卡結帳待修 v
3. 沒有外送,只有內用跟外帶 v 但保留頁面
4. 顧客訂單ui待優化
5. 把print移除,換logging
6. 把request改httpx模組
7. 模組化
8. 測試
9. 未來預計加入庫存限制
