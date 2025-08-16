import streamlit as st
import httpx
import json
import time
from datetime import datetime
import threading
import logging

try:
    import websocket  # websocket-client
except Exception:
    websocket = None

# logging 設定（前端主要用於開發除錯）
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("front_main")

# 後端服務的基礎 URL
ORDER_SERVICE_URL = "http://localhost:8002"  # Orchestration 模式的 Order Service 端口

st.set_page_config(layout="wide", page_title="分布式訂單系統")

# 初始化session state
if "access_token" not in st.session_state:
    st.session_state.access_token = None
if "role" not in st.session_state:
    st.session_state.role = None
if "username" not in st.session_state:
    st.session_state.username = None
if "customer_id" not in st.session_state:
    st.session_state.customer_id = None

# 新增：rerun flag（避免在 callback 內直接呼叫 st.experimental_rerun）
if "_needs_rerun" not in st.session_state:
    st.session_state._needs_rerun = False

# 在 session state 儲存通知列表與啟動旗標
if "ws_notifications" not in st.session_state:
    st.session_state.ws_notifications = []
if "ws_thread_started" not in st.session_state:
    st.session_state.ws_thread_started = False


# 輔助函數：處理API請求
def make_api_request(method, endpoint, data=None, token=None, params=None, files=None):
    url = f"{ORDER_SERVICE_URL}{endpoint}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    logger.debug("API請求: %s %s", method, url)
    logger.debug("請求標頭: %s", headers)
    logger.debug("請求參數: %s", params)
    if data:
        logger.debug("請求數據: %s", data)

    try:
        # 使用 httpx 同步請求
        if files:
            response = httpx.request(
                method,
                url,
                headers=headers,
                data=data,
                params=params,
                files=files,
                timeout=10.0,
            )
        else:
            response = httpx.request(
                method, url, headers=headers, json=data, params=params, timeout=10.0
            )

        logger.debug("回應狀態碼: %s", response.status_code)
        if response.status_code != 200:
            logger.debug("回應內容: %s", response.text)

        if response.status_code == 401:
            st.error("認證失敗，請重新登入")
            st.session_state.access_token = None
            st.session_state.role = None
            st.session_state.username = None
            st.session_state.customer_id = None
            return None
        elif response.status_code == 422:
            logger.info("請求參數錯誤: %s", response.text)
            error_detail = "請求參數錯誤"
            try:
                error_data = response.json()
                if "detail" in error_data:
                    error_detail = error_data["detail"]
            except:
                pass
            st.error(f"請求參數錯誤: {error_detail}")
            return None

        return response
    except httpx.ConnectError:
        st.error("無法連接到後端服務，請確認服務已啟動")
        return None
    except Exception as e:
        logger.exception("發生錯誤於 make_api_request")
        st.error(f"發生錯誤: {e}")
        return None


# 登入頁面
def login_page():
    st.title("🛍️ 分布式訂單系統 - 用戶登入")

    with st.form("login_form"):
        username = st.text_input("用戶名", placeholder="請輸入用戶名")
        password = st.text_input("密碼", type="password", placeholder="請輸入密碼")
        submit_button = st.form_submit_button(label="登入")

        if submit_button:
            # 使用 httpx 直接呼叫 token endpoint (表單)
            token_resp = httpx.post(
                f"{ORDER_SERVICE_URL}/token",
                data={"username": username, "password": password},
                timeout=10.0,
            )
            if token_resp.status_code == 200:
                token_data = token_resp.json()
                st.session_state.access_token = token_data["access_token"]
                st.session_state.role = token_data["role"]
                st.session_state.username = username

                # 如果是顧客，獲取customer_id
                if token_data["role"] == "customer":
                    try:
                        user_response = httpx.get(
                            f"{ORDER_SERVICE_URL}/orchestration/users/me",
                            headers={
                                "Authorization": f"Bearer {st.session_state.access_token}"
                            },
                            timeout=10.0,
                        )
                        logger.debug("用戶資訊回應: %s", user_response.status_code)
                        logger.debug("用戶資訊內容: %s", user_response.text)

                        if user_response.status_code == 200:
                            user_data = user_response.json()
                            st.session_state.customer_id = user_data.get("customer_id")
                            logger.info("設置顧客ID: %s", st.session_state.customer_id)
                        else:
                            st.warning(
                                f"無法獲取用戶資料 (狀態碼: {user_response.status_code})"
                            )
                    except Exception as e:
                        logger.exception("獲取用戶資料時出錯")
                        st.warning(f"獲取用戶資料時出錯: {e}")

                st.success(f"登入成功！歡迎 {username}")
                st.rerun()
            else:
                logger.warning("登入失敗: %s", token_resp.text)
                st.error("登入失敗，請檢查用戶名和密碼")
                st.error(f"錯誤詳情: {token_resp.text}")

    with st.expander("沒有帳號？點擊註冊"):
        with st.form("register_form"):
            new_username = st.text_input(
                "用戶名", key="reg_username", placeholder="請設定用戶名"
            )
            new_email = st.text_input(
                "電子郵件", key="reg_email", placeholder="請輸入電子郵件"
            )
            new_password = st.text_input(
                "密碼", type="password", key="reg_password", placeholder="請設定密碼"
            )
            confirm_password = st.text_input(
                "確認密碼",
                type="password",
                key="confirm_password",
                placeholder="請再次輸入密碼",
            )
            register_button = st.form_submit_button(label="註冊")

            if register_button:
                if new_password != confirm_password:
                    st.error("兩次輸入的密碼不一致")
                else:
                    register_data = {
                        "username": new_username,
                        "email": new_email,
                        "password": new_password,
                        "role": "customer",  # 默認註冊為顧客
                    }

                    response = make_api_request(
                        "POST", "/orchestration/users", register_data
                    )
                    if response and response.status_code == 200:
                        st.success("註冊成功！請使用新帳號登入")
                    else:
                        error_msg = "註冊失敗"
                        if response:
                            try:
                                error_msg = response.json().get("detail", error_msg)
                            except:
                                pass
                        st.error(error_msg)


# 顯示菜單頁面
def menu_page():
    st.header("🍽️ 餐廳菜單")

    # 獲取菜單項
    response = make_api_request("GET", "/orchestration/menu/items")

    if response and response.status_code == 200:
        menu_items = response.json()

        if not menu_items:
            st.info("菜單暫無項目")
            if st.session_state.role in ["staff", "admin"]:
                st.warning("請添加菜單項目")
            return

        # 分列顯示菜單
        cols = st.columns(3)
        for i, item in enumerate(menu_items):
            with cols[i % 3]:
                # 顯示圖片（若有）
                if item.get("image_url"):
                    try:
                        st.image(
                            f"{ORDER_SERVICE_URL}{item['image_url']}",
                            use_container_width=True,
                        )
                    except:
                        pass

                with st.container():
                    st.subheader(item["name"])
                    st.write(f"價格: ${item['price']:.2f}")
                    if item.get("description"):
                        st.write(item["description"])

                    # 顧客可以選擇添加到訂單
                    if st.session_state.role == "customer":
                        quantity = st.number_input(
                            f"數量", min_value=1, value=1, key=f"qty_{item['id']}"
                        )
                        if st.button("加入訂單", key=f"add_{item['id']}"):
                            if "cart" not in st.session_state:
                                st.session_state.cart = []

                            found = False
                            for cart_item in st.session_state.cart:
                                if cart_item["id"] == item["id"]:
                                    cart_item["quantity"] += quantity
                                    found = True
                                    break

                            if not found:
                                st.session_state.cart.append(
                                    {
                                        "id": item["id"],
                                        "name": item["name"],
                                        "price": item["price"],
                                        "quantity": quantity,
                                    }
                                )

                            st.success(f"已將 {quantity} 份 {item['name']} 加入訂單")
                            st.rerun()
    else:
        st.error("無法獲取菜單")


# 顯示購物車
def cart_page():
    st.header("🛒 購物車")

    if "cart" not in st.session_state or not st.session_state.cart:
        st.info("購物車為空")
        return

    total = 0
    for i, item in enumerate(st.session_state.cart):
        col1, col2, col3, col4, col5 = st.columns([3, 2, 2, 1, 1])
        with col1:
            st.write(item["name"])
        with col2:
            st.write(f"${item['price']:.2f}")
        with col3:
            new_qty = st.number_input(
                "數量", min_value=1, value=item["quantity"], key=f"cart_{i}"
            )
            if new_qty != item["quantity"]:
                st.session_state.cart[i]["quantity"] = new_qty
                st.rerun()
        with col4:
            item_total = item["price"] * item["quantity"]
            st.write(f"${item_total:.2f}")
            total += item_total
        with col5:
            if st.button("移除", key=f"remove_{i}"):
                st.session_state.cart.pop(i)
                st.rerun()

    st.markdown("---")
    st.markdown(f"### 總金額: ${total:.2f}")

    with st.form("checkout_form"):
        order_type_label = st.selectbox(
            "訂單類型", ["內用", "外帶"], key="order_type_select"
        )
        if order_type_label == "內用":
            table_number = st.text_input("桌號", placeholder="請輸入桌號")
        else:
            table_number = None

        payment_method = "cash"
        checkout_button = st.form_submit_button("確認訂單")

        if checkout_button:
            if order_type_label == "內用" and (
                not table_number or table_number.strip() == ""
            ):
                st.error("內用訂單請填寫桌號")
            else:
                items = []
                for item in st.session_state.cart:
                    items.append(
                        {
                            "name": item["name"],
                            "price": item["price"],
                            "quantity": item["quantity"],
                        }
                    )

                order_data = {
                    "customer_id": st.session_state.customer_id,
                    "items": items,
                    "order_type": (
                        "dine_in" if order_type_label == "內用" else "takeaway"
                    ),
                    "table_number": table_number,
                    "payment_method": payment_method,
                }

                response = make_api_request(
                    "POST",
                    "/orchestration/orders",
                    order_data,
                    token=st.session_state.access_token,
                )

                if response and response.status_code == 200:
                    order_details = response.json()
                    st.success(f"訂單創建成功！訂單ID: {order_details['order_id']}")
                    st.json(order_details)
                    st.session_state.cart = []
                    time.sleep(2)
                    st.rerun()
                else:
                    error_msg = "訂單創建失敗"
                    if response:
                        try:
                            error_msg = response.json().get("detail", error_msg)
                        except:
                            pass
                    st.error(error_msg)


# 顯示訂單列表
def orders_page():
    st.header("📋 我的訂單")

    params = None
    if st.session_state.role == "customer" and st.session_state.customer_id:
        params = {"customer_id": st.session_state.customer_id}

    response = make_api_request(
        "GET",
        "/orchestration/orders",
        token=st.session_state.access_token,
        params=params,
    )

    if response and response.status_code == 200:
        orders = response.json()

        if not orders:
            st.info("暫無訂單記錄")
            return

        for order in orders:
            with st.container():
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.write(f"**訂單ID:** {order['order_id']}")
                with col2:
                    status_color = "blue"
                    if order["status"] == "delivered":
                        status_color = "green"
                    elif order["status"] == "cancelled":
                        status_color = "red"
                    st.markdown(f"**狀態:** :{status_color}[{order['status'].upper()}]")
                with col3:
                    st.write(f"**總金額:** ${order['total_amount']:.2f}")

                # 展開查看詳情按鈕
                with st.expander("查看詳情"):
                    order_detail_response = make_api_request(
                        "GET",
                        f"/orchestration/orders/{order['order_id']}",
                        token=st.session_state.access_token,
                    )

                    if (
                        order_detail_response
                        and order_detail_response.status_code == 200
                    ):
                        order_detail = order_detail_response.json()
                        st.json(order_detail)

                        # 獲取訂單歷史
                        history_response = make_api_request(
                            "GET",
                            f"/orchestration/orders/history/{order['order_id']}",
                            token=st.session_state.access_token,
                        )

                        if history_response and history_response.status_code == 200:
                            history = history_response.json()
                            st.subheader("訂單狀態歷史")
                            for status_change in history:
                                try:
                                    timestamp = datetime.fromisoformat(
                                        status_change["changed_at"].replace(
                                            "Z", "+00:00"
                                        )
                                    )
                                    formatted_time = timestamp.strftime(
                                        "%Y-%m-%d %H:%M:%S"
                                    )
                                except Exception:
                                    formatted_time = status_change.get("changed_at")
                                st.write(
                                    f"- {formatted_time}: {status_change['status'].upper()}"
                                )
                    else:
                        st.error("無法獲取訂單詳情")

                # 訂單操作按鈕
                if order["status"] not in ["delivered", "cancelled"]:
                    if st.button("取消訂單", key=f"cancel_{order['order_id']}"):
                        cancel_response = make_api_request(
                            "POST",
                            f"/orchestration/orders/{order['order_id']}/cancel",
                            token=st.session_state.access_token,
                        )

                        if cancel_response and cancel_response.status_code == 200:
                            st.success("訂單已取消")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error("訂單取消失敗")
    else:
        st.error("無法獲取訂單列表")


# 店員支付確認頁面
def payment_confirmation_page():
    st.header("💳 支付確認")
    st.write("此功能僅供店員確認顧客支付。")

    response = make_api_request(
        "GET", "/orchestration/orders", token=st.session_state.access_token
    )

    if response and response.status_code == 200:
        orders = response.json()
        pending_orders = [order for order in orders if order["status"] == "pending"]

        if not pending_orders:
            st.info("暫無待確認支付的訂單")
            return

        st.subheader("待確認支付的訂單")

        for order in pending_orders:
            with st.container():
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**訂單ID:** {order['order_id']}")
                    st.write(f"**總金額:** ${order['total_amount']:.2f}")

                with col2:
                    payment_id = None
                    payment_resp = make_api_request(
                        "GET",
                        f"/orchestration/orders/{order['order_id']}/payment",
                        token=st.session_state.access_token,
                    )
                    if payment_resp and payment_resp.status_code == 200:
                        try:
                            payment_info = payment_resp.json()
                            payment_id = payment_info.get("payment_id")
                            st.write(f"系統 Payment ID: {payment_id}")
                        except:
                            payment_id = None

                    if not payment_id:
                        payment_id = st.text_input(
                            "輸入Payment ID", key=f"payment_{order['order_id']}"
                        )

                    if payment_id:
                        col_success, col_fail = st.columns(2)
                        with col_success:
                            if st.button(
                                "確認支付成功", key=f"confirm_{order['order_id']}"
                            ):
                                confirm_response = make_api_request(
                                    "POST",
                                    f"/orchestration/payments/{payment_id}/confirm",
                                    {"success": True},
                                    token=st.session_state.access_token,
                                )

                                if (
                                    confirm_response
                                    and confirm_response.status_code == 200
                                ):
                                    st.success("支付確認成功")
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error("支付確認失敗")

                        with col_fail:
                            if st.button(
                                "標記支付失敗", key=f"fail_{order['order_id']}"
                            ):
                                fail_response = make_api_request(
                                    "POST",
                                    f"/orchestration/payments/{payment_id}/confirm",
                                    {"success": False},
                                    token=st.session_state.access_token,
                                )

                                if fail_response and fail_response.status_code == 200:
                                    st.success("支付已標記為失敗")
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error("操作失敗")
    else:
        st.error("無法獲取訂單列表")


# 廚房訂單頁面（改為卡片 UI 且不在 callback 內直接 rerun）
def kitchen_orders_page():
    st.header("🍳 廚房訂單管理")
    st.write("列出近期廚房訂單。點選「標記完成」可將狀態由 preparing 變更為 ready。")

    resp = make_api_request(
        "GET", "/orchestration/kitchen/orders", token=st.session_state.access_token
    )
    if not resp or resp.status_code != 200:
        st.error("無法獲取廚房訂單列表")
        return

    orders = resp.json()
    if not orders:
        st.info("暫無廚房訂單")
        return

    # 更整齊的卡片式排列
    for k in orders:
        with st.container():
            left, right = st.columns([3, 1])
            with left:
                st.subheader(f"廚房訂單 {k.get('kitchen_order_id')}")
                st.write(f"關聯訂單: {k.get('order_id')}")
                status = k.get("status")
                if status == "preparing":
                    st.warning(f"狀態：{status.upper()} 🔧")
                elif status == "received":
                    st.info(f"狀態：{status.upper()}")
                elif status == "ready":
                    st.success(f"狀態：{status.upper()} ✅")
                else:
                    st.write(f"狀態：{status}")

                try:
                    items = json.loads(k.get("items") or "[]")
                    if items:
                        st.write("項目：")
                        for it in items:
                            st.write(
                                f"- {it.get('name')} x {it.get('quantity')} (${it.get('price')})"
                            )
                except Exception:
                    st.write("無法解析訂單項目")
            with right:
                st.write(f"建立時間：{k.get('created_at')}")
                # 只在 preparing 顯示標記完成按鈕
                if k.get("status") == "preparing":
                    if st.button(
                        "標記完成", key=f"complete_{k.get('kitchen_order_id')}"
                    ):
                        resp_complete = make_api_request(
                            "POST",
                            f"/orchestration/kitchen/orders/{k.get('kitchen_order_id')}/complete",
                            token=st.session_state.access_token,
                        )
                        if resp_complete and resp_complete.status_code == 200:
                            st.success("標記完成")
                            # 不直接呼叫 st.experimental_rerun()，改為設定 flag
                            st.session_state._needs_rerun = True
                        else:
                            st.error("標記完成失敗")


# 配送訂單頁面（改為列出近期配送單）
def delivery_page():
    st.header("🚚 配送訂單")
    st.write("顯示近期配送單（如無配送流程則此頁僅供檢視）。")

    resp = make_api_request(
        "GET", "/orchestration/delivery/orders", token=st.session_state.access_token
    )

    if not resp or resp.status_code != 200:
        st.error("無法獲取配送訂單列表")
        return

    deliveries = resp.json()
    if not deliveries:
        st.info("暫無配送單")
        return

    for d in deliveries:
        with st.container():
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"**配送ID:** {d.get('delivery_id')}")
                st.write(f"**關聯訂單ID:** {d.get('order_id')}")
                st.write(f"**地址:** {d.get('address')}")
                st.write(f"**狀態:** {d.get('status')}")
                st.write(f"**司機:** {d.get('driver_id') or '尚未分配'}")
            with col2:
                st.write(f"建立時間：{d.get('created_at')}")


# 菜單管理頁面 (店員和管理員)
def menu_admin_page():
    st.header("🍽️ 菜單管理")
    st.write(f"當前用戶: {st.session_state.username}, 角色: {st.session_state.role}")

    if st.session_state.role not in ["staff", "admin"]:
        st.error("您沒有權限訪問此頁面")
        return

    tab1, tab2, tab3 = st.tabs(["查看菜單", "新增菜單項", "編輯菜單"])

    with tab1:
        response = make_api_request("GET", "/orchestration/menu/items")
        if response and response.status_code == 200:
            menu_items = response.json()
            if not menu_items:
                st.info("菜單暫無項目")
            else:
                for item in menu_items:
                    with st.container():
                        col1, col2, col3 = st.columns([3, 2, 1])
                        with col1:
                            st.write(f"**{item['name']}**")
                            if item.get("description"):
                                st.write(item["description"])
                        with col2:
                            st.write(f"**價格:** ${item['price']:.2f}")
                        with col3:
                            if st.button("刪除", key=f"delete_{item['id']}"):
                                delete_response = make_api_request(
                                    "DELETE",
                                    f"/orchestration/menu/admin/items/{item['id']}",
                                    token=st.session_state.access_token,
                                )

                                if (
                                    delete_response
                                    and delete_response.status_code == 200
                                ):
                                    st.success("菜單項刪除成功")
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error("菜單項刪除失敗")
        else:
            st.error("無法獲取菜單")

    with tab2:
        st.subheader("新增菜單項")
        with st.form("add_menu_form"):
            new_name = st.text_input(
                "菜品名稱", key="new_item_name", placeholder="請輸入菜品名稱"
            )
            new_price = st.number_input(
                "價格", key="new_item_price", min_value=0.1, value=10.0, step=0.1
            )
            new_description = st.text_area(
                "描述", key="new_item_desc", placeholder="請輸入菜品描述"
            )
            new_image = st.file_uploader(
                "上傳圖片 (可選)", type=["png", "jpg", "jpeg"], key="new_item_image"
            )
            add_submitted = st.form_submit_button("新增菜單項")

            if add_submitted:
                if not new_name:
                    st.error("請輸入菜品名稱")
                else:
                    url = f"{ORDER_SERVICE_URL}/orchestration/menu/admin/items"
                    headers = {}
                    if st.session_state.access_token:
                        headers["Authorization"] = (
                            f"Bearer {st.session_state.access_token}"
                        )

                    data = {
                        "name": new_name,
                        "price": str(float(new_price)),
                        "description": new_description or "",
                    }

                    try:
                        if new_image is not None:
                            files = {
                                "image": (
                                    new_image.name,
                                    new_image.read(),
                                    new_image.type,
                                )
                            }
                            response = make_api_request(
                                "POST",
                                "/orchestration/menu/admin/items",
                                data=data,
                                token=st.session_state.access_token,
                                files=files,
                            )
                        else:
                            response = make_api_request(
                                "POST",
                                "/orchestration/menu/admin/items",
                                data=data,
                                token=st.session_state.access_token,
                            )
                    except Exception as e:
                        response = None
                    if response and response.status_code in (200, 201):
                        st.success("菜單項新增成功")
                        time.sleep(1)
                        st.rerun()
                    else:
                        try:
                            err = response.json()
                        except:
                            err = response.text
                        st.error(f"菜單項新增失敗: {response.status_code} {err}")

    with tab3:
        response = make_api_request("GET", "/orchestration/menu/items")
        if response and response.status_code == 200:
            menu_items = response.json()
        else:
            menu_items = []

        if not menu_items:
            st.info("暫無菜單項可編輯，請先新增菜單項")
            # 提供快速新增表單，避免使用者找不到新增按鈕時無法操作
            with st.form("quick_create_in_edit"):
                qc_name = st.text_input("菜品名稱 (建立用)", key="qc_name")
                qc_price = st.number_input(
                    "價格", key="qc_price", min_value=0.1, value=10.0
                )
                qc_desc = st.text_area("描述", key="qc_desc")
                qc_submit = st.form_submit_button("建立菜單項")
                if qc_submit:
                    if not qc_name:
                        st.error("請輸入菜品名稱")
                    else:
                        qc_data = {
                            "name": qc_name,
                            "price": float(qc_price),
                            "description": qc_desc or None,
                        }
                        qc_resp = make_api_request(
                            "POST",
                            "/orchestration/menu/admin/items",
                            qc_data,
                            token=st.session_state.access_token,
                        )
                        if qc_resp and qc_resp.status_code == 200:
                            st.success("已建立菜單項")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error("建立失敗")
            return

        item_names = [item["name"] for item in menu_items]
        selected_item_name = st.selectbox("選擇要編輯的菜品", item_names)
        selected_item = next(
            (item for item in menu_items if item["name"] == selected_item_name), None
        )

        if selected_item:
            if selected_item.get("image_url"):
                try:
                    st.image(
                        f"{ORDER_SERVICE_URL}{selected_item['image_url']}",
                        use_container_width=False,
                        width=200,
                    )
                except:
                    pass

            with st.form(f"edit_menu_item_{selected_item['id']}"):
                edit_name = st.text_input(
                    "菜品名稱",
                    value=selected_item["name"],
                    key=f"edit_name_{selected_item['id']}",
                )
                edit_price = st.number_input(
                    "價格",
                    min_value=0.1,
                    value=float(selected_item["price"]),
                    step=0.1,
                    key=f"edit_price_{selected_item['id']}",
                )
                edit_description = st.text_area(
                    "描述",
                    value=selected_item.get("description", ""),
                    key=f"edit_desc_{selected_item['id']}",
                )
                edit_image = st.file_uploader(
                    "上傳新圖片（可選）",
                    type=["png", "jpg", "jpeg"],
                    key=f"edit_img_{selected_item['id']}",
                )
                submit_button = st.form_submit_button("更新菜單項")

                if submit_button:
                    if not edit_name:
                        st.error("請輸入菜品名稱")
                    else:
                        url = f"{ORDER_SERVICE_URL}/orchestration/menu/admin/items/{selected_item['id']}"
                        headers = {}
                        if st.session_state.access_token:
                            headers["Authorization"] = (
                                f"Bearer {st.session_state.access_token}"
                            )

                        data = {
                            "name": edit_name,
                            "price": str(float(edit_price)),
                            "description": edit_description or "",
                        }

                        try:
                            if edit_image is not None:
                                files = {
                                    "image": (
                                        edit_image.name,
                                        edit_image.read(),
                                        edit_image.type,
                                    )
                                }
                                response = make_api_request(
                                    "PUT",
                                    f"/orchestration/menu/admin/items/{selected_item['id']}",
                                    data=data,
                                    token=st.session_state.access_token,
                                    files=files,
                                )
                            else:
                                response = make_api_request(
                                    "PUT",
                                    f"/orchestration/menu/admin/items/{selected_item['id']}",
                                    data=data,
                                    token=st.session_state.access_token,
                                )
                        except Exception:
                            response = None

                        if response and response.status_code in (200, 201):
                            st.success("菜單項更新成功")
                            time.sleep(1)
                            st.rerun()
                        else:
                            try:
                                err = response.json()
                            except:
                                err = response.text
                            st.error(f"菜單項更新失敗: {response.status_code} {err}")


# 顧客管理頁面 (只有店員和管理員)
def customer_management_page():
    st.header("👥 顧客管理")

    response = make_api_request(
        "GET", "/orchestration/customers", token=st.session_state.access_token
    )

    if response and response.status_code == 200:
        customers = response.json()

        if not customers:
            st.info("暫無顧客資料")
            return

        for customer in customers:
            with st.container():
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.write(f"**姓名:** {customer['name']}")
                with col2:
                    st.write(f"**顧客ID:** {customer['customer_id']}")
                with col3:
                    st.write(f"**電子郵件:** {customer['email']}")
                if customer.get("phone"):
                    st.write(f"**電話:** {customer['phone']}")
    else:
        st.error("無法獲取顧客資料")


# WebSocket 客戶端相關
def _start_ws_client(token: str):
    """在背景 thread 啟動 websocket-client 並將通知 append 到 st.session_state.ws_notifications"""
    if websocket is None:
        logger.info("websocket-client not installed; 無法啟動 WS 客戶端")
        return

    def on_message(ws, message):
        try:
            data = json.loads(message)
            if "ws_notifications" not in st.session_state:
                st.session_state.ws_notifications = []
            st.session_state.ws_notifications.append(data)
        except Exception:
            logger.exception("WS on_message 處理失敗")

    def on_error(ws, error):
        logger.error("WS error: %s", error)

    def on_close(ws, close_status_code, close_msg):
        logger.info("WS closed: %s %s", close_status_code, close_msg)

    def on_open(ws):
        logger.info("WS connected")

    url = f"ws://localhost:8002/ws/notifications?token={token}"
    ws_app = websocket.WebSocketApp(
        url,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open,
    )
    ws_app.run_forever()


# 主界面
def main():
    with st.sidebar:
        st.title("🍽️ 餐廳訂單系統")

        if st.session_state.access_token:
            st.success(f"已登入: {st.session_state.username}")
            st.write(f"角色: {st.session_state.role}")
            if st.session_state.customer_id:
                st.write(f"顧客ID: {st.session_state.customer_id}")

            st.markdown("---")

            pages = ["查看菜單"]

            if st.session_state.role == "customer":
                pages.extend(["購物車", "我的訂單"])

            if st.session_state.role in ["staff", "admin"]:
                pages.extend(
                    [
                        "訂單列表",
                        "支付確認",
                        "廚房訂單",
                        "配送管理",
                        "菜單管理",
                        "顧客管理",
                    ]
                )

            selected_page = st.radio("導航", pages, key="sidebar_nav")

            with st.expander("用戶詳細信息"):
                st.write(f"用戶名: {st.session_state.username}")
                st.write(f"角色: {st.session_state.role}")
                st.write(f"顧客ID: {st.session_state.customer_id}")
                token_short = (
                    st.session_state.access_token[:20] + "..."
                    if st.session_state.access_token
                    else None
                )
                st.write(f"Token: {token_short}")

            st.markdown("---")

            if st.button("登出"):
                st.session_state.access_token = None
                st.session_state.role = None
                st.session_state.username = None
                st.session_state.customer_id = None
                if "cart" in st.session_state:
                    del st.session_state.cart
                st.rerun()
        else:
            st.info("請先登入")
            selected_page = "登入"

    if not st.session_state.access_token:
        login_page()
    else:
        if selected_page == "查看菜單":
            menu_page()
        elif selected_page == "購物車":
            cart_page()
        elif selected_page == "我的訂單" or selected_page == "訂單列表":
            orders_page()
        elif selected_page == "支付確認":
            payment_confirmation_page()
        elif selected_page == "廚房訂單":
            kitchen_orders_page()
        elif selected_page == "配送管理":
            delivery_page()
        elif selected_page == "菜單管理":
            menu_admin_page()
        elif selected_page == "顧客管理":
            customer_management_page()

        # 在主流程末端（非 callback）統一處理 rerun
        if st.session_state.get("_needs_rerun", False):
            # 重置 flag 並在主流程呼叫 rerun（此處是在 streamlit 腳本的主線程）
            st.session_state._needs_rerun = False
            st.rerun()

        # 當店員登入且尚未啟動 WS thread 時啟動
        if st.session_state.access_token and st.session_state.role in [
            "staff",
            "admin",
        ]:
            if not st.session_state.ws_thread_started:
                try:
                    threading.Thread(
                        target=_start_ws_client,
                        args=(st.session_state.access_token,),
                        daemon=True,
                    ).start()
                    st.session_state.ws_thread_started = True
                except Exception as e:
                    st.warning(f"啟動 WS 客戶端失敗: {e}")


if __name__ == "__main__":
    main()
