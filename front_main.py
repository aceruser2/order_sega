import streamlit as st
import requests
import json
import time
from datetime import datetime

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


# 輔助函數：處理API請求
def make_api_request(method, endpoint, data=None, token=None, params=None):
    url = f"{ORDER_SERVICE_URL}{endpoint}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # 調試信息
    print(f"API請求: {method} {url}")
    print(f"請求標頭: {headers}")
    print(f"請求參數: {params}")
    if data:
        print(f"請求數據: {data}")

    try:
        if method == "GET":
            response = requests.get(url, headers=headers, params=params)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=data)
        elif method == "PUT":
            response = requests.put(url, headers=headers, json=data)
        elif method == "DELETE":
            response = requests.delete(url, headers=headers)

        # 記錄回應
        print(f"回應狀態碼: {response.status_code}")
        if response.status_code != 200:
            print(f"回應內容: {response.text}")

        if response.status_code == 401:
            st.error("認證失敗，請重新登入")
            st.session_state.access_token = None
            st.session_state.role = None
            st.session_state.username = None
            st.session_state.customer_id = None
            return None
        elif response.status_code == 422:
            print(f"請求參數錯誤: {response.text}")
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
    except requests.exceptions.ConnectionError:
        st.error("無法連接到後端服務，請確認服務已啟動")
        return None
    except Exception as e:
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
            response = requests.post(
                f"{ORDER_SERVICE_URL}/token",
                data={"username": username, "password": password},
            )

            if response.status_code == 200:
                token_data = response.json()
                st.session_state.access_token = token_data["access_token"]
                st.session_state.role = token_data["role"]
                st.session_state.username = username

                # 如果是顧客，獲取customer_id
                if token_data["role"] == "customer":
                    try:
                        user_response = requests.get(
                            f"{ORDER_SERVICE_URL}/orchestration/users/me",
                            headers={
                                "Authorization": f"Bearer {st.session_state.access_token}"
                            },
                        )
                        print(f"用戶資訊回應: {user_response.status_code}")
                        print(f"用戶資訊內容: {user_response.text}")

                        if user_response.status_code == 200:
                            user_data = user_response.json()
                            st.session_state.customer_id = user_data.get("customer_id")
                            print(f"設置顧客ID: {st.session_state.customer_id}")
                        else:
                            st.warning(
                                f"無法獲取用戶資料 (狀態碼: {user_response.status_code})"
                            )
                    except Exception as e:
                        st.warning(f"獲取用戶資料時出錯: {e}")

                st.success(f"登入成功！歡迎 {username}")
                st.rerun()
            else:
                st.error("登入失敗，請檢查用戶名和密碼")
                st.error(f"錯誤詳情: {response.text}")

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
                            use_column_width=True,
                        )
                    except:
                        # 若圖片載入失敗，仍顯示文字內容
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

                            # 檢查項目是否已在購物車中
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
                            st.rerun()  # 使用新的 API
    else:
        st.error("無法獲取菜單")


# 顯示購物車
def cart_page():
    st.header("🛒 購物車")

    if "cart" not in st.session_state or not st.session_state.cart:
        st.info("購物車為空")
        return

    # 顯示購物車內容
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
                st.rerun()  # 使用新的 API
        with col4:
            item_total = item["price"] * item["quantity"]
            st.write(f"${item_total:.2f}")
            total += item_total
        with col5:
            if st.button("移除", key=f"remove_{i}"):
                st.session_state.cart.pop(i)
                st.rerun()  # 使用新的 API

    st.markdown("---")
    st.markdown(f"### 總金額: ${total:.2f}")

    # 結帳表單
    with st.form("checkout_form"):
        delivery_address = st.text_input("配送地址", placeholder="請輸入送餐地址")
        payment_method = st.selectbox("付款方式", ["cash", "credit_card"])
        checkout_button = st.form_submit_button("確認訂單")

        if checkout_button:
            if not delivery_address:
                st.error("請填寫配送地址")
            else:
                # 轉換購物車內容為API需要的格式
                items = []
                for item in st.session_state.cart:
                    items.append(
                        {
                            "name": item["name"],
                            "price": item["price"],
                            "quantity": item["quantity"],
                        }
                    )

                # 創建訂單
                order_data = {
                    "customer_id": st.session_state.customer_id,
                    "items": items,
                    "delivery_address": delivery_address,
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

                    # 清空購物車
                    st.session_state.cart = []

                    # 刷新頁面
                    time.sleep(2)
                    st.rerun()  # 使用新的 API
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

    # 獲取訂單列表
    params = None  # 初始化為 None，而不是空字典
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

        # 顯示訂單列表
        for order in orders:
            with st.container(border=True):
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
                                timestamp = datetime.fromisoformat(
                                    status_change["changed_at"].replace("Z", "+00:00")
                                )
                                formatted_time = timestamp.strftime("%Y-%m-%d %H:%M:%S")
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
                            st.rerun()  # 使用新的 API
                        else:
                            st.error("訂單取消失敗")
    else:
        st.error("無法獲取訂單列表")


# 店員支付確認頁面
def payment_confirmation_page():
    st.header("💳 支付確認")
    st.write("此功能僅供店員確認顧客支付。")

    # 獲取訂單列表（pending 狀態）
    response = make_api_request(
        "GET", "/orchestration/orders", token=st.session_state.access_token
    )

    if response and response.status_code == 200:
        orders = response.json()

        # 過濾 pending 狀態的訂單
        pending_orders = [order for order in orders if order["status"] == "pending"]

        if not pending_orders:
            st.info("暫無待確認支付的訂單")
            return

        st.subheader("待確認支付的訂單")

        # 顯示待處理訂單
        for order in pending_orders:
            with st.container(border=True):
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**訂單ID:** {order['order_id']}")
                    st.write(f"**總金額:** ${order['total_amount']:.2f}")

                with col2:
                    # 獲取支付信息
                    payment_id_placeholder = st.empty()
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
                                    st.rerun()  # 使用新的 API
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
                                    st.rerun()  # 使用新的 API
                                else:
                                    st.error("操作失敗")
    else:
        st.error("無法獲取訂單列表")


# 廚房訂單頁面
def kitchen_orders_page():
    st.header("🍳 廚房訂單")

    # 顯示一個表單來查詢廚房訂單
    with st.form("kitchen_form"):
        kitchen_order_id = st.text_input("廚房訂單ID", placeholder="請輸入廚房訂單ID")
        submit_button = st.form_submit_button("查詢")

        if submit_button and kitchen_order_id:
            response = make_api_request(
                "GET",
                f"/orchestration/kitchen/orders/{kitchen_order_id}",
                token=st.session_state.access_token,
            )

            if response and response.status_code == 200:
                kitchen_order = response.json()
                st.success("廚房訂單查詢成功")

                st.subheader("廚房訂單詳情")
                st.write(f"**廚房訂單ID:** {kitchen_order['kitchen_order_id']}")
                st.write(f"**關聯訂單ID:** {kitchen_order['order_id']}")
                st.write(f"**狀態:** {kitchen_order['status']}")
                st.write(f"**預估時間:** {kitchen_order['estimated_time']} 分鐘")

                try:
                    items = json.loads(kitchen_order["items"])
                    st.subheader("訂單項目")
                    for item in items:
                        st.write(
                            f"- {item['name']} x {item['quantity']} (${item['price']:.2f} 每份)"
                        )
                except:
                    st.write("無法顯示訂單項目")
            else:
                st.error("廚房訂單查詢失敗")


# 配送訂單頁面
def delivery_page():
    st.header("🚚 配送訂單")

    # 顯示一個表單來查詢配送訂單
    with st.form("delivery_form"):
        delivery_id = st.text_input("配送ID", placeholder="請輸入配送ID")
        submit_button = st.form_submit_button("查詢")

        if submit_button and delivery_id:
            response = make_api_request(
                "GET",
                f"/orchestration/delivery/orders/{delivery_id}",
                token=st.session_state.access_token,
            )

            if response and response.status_code == 200:
                delivery_order = response.json()
                st.success("配送訂單查詢成功")

                st.subheader("配送訂單詳情")
                st.write(f"**配送ID:** {delivery_order['delivery_id']}")
                st.write(f"**關聯訂單ID:** {delivery_order['order_id']}")
                st.write(f"**狀態:** {delivery_order['status']}")
                st.write(f"**司機ID:** {delivery_order['driver_id'] or '尚未分配'}")
            else:
                st.error("配送訂單查詢失敗")


# 菜單管理頁面 (店員和管理員)
def menu_admin_page():
    st.header("🍽️ 菜單管理")

    # 顯示當前用戶角色與令牌
    st.write(f"當前用戶: {st.session_state.username}, 角色: {st.session_state.role}")

    if st.session_state.role not in ["staff", "admin"]:
        st.error("您沒有權限訪問此頁面")
        return

    tab1, tab2, tab3 = st.tabs(["查看菜單", "新增菜單項", "編輯菜單"])

    # 查看菜單
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

    # 新增菜單項（使用表單，確保按鈕穩定顯示）
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
                    # 使用 multipart/form-data 發送（file + form fields）
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

                    files = None
                    try:
                        if new_image is not None:
                            # new_image 是 Streamlit UploadedFile，讀取 bytes
                            files = {
                                "image": (
                                    new_image.name,
                                    new_image.read(),
                                    new_image.type,
                                )
                            }
                            response = requests.post(
                                url, data=data, files=files, headers=headers
                            )
                        else:
                            # 沒有檔案的情況仍以 form-data 發送（requests 會自動處理）
                            response = requests.post(url, data=data, headers=headers)

                        if response.status_code in (200, 201):
                            st.success("菜單項新增成功")
                            time.sleep(1)
                            st.rerun()
                        else:
                            try:
                                err = response.json()
                            except:
                                err = response.text
                            st.error(f"菜單項新增失敗: {response.status_code} {err}")
                    except Exception as e:
                        st.error(f"請求過程中出錯: {e}")

    # 編輯菜單（若無項目提供快速新增）
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
            # 顯示現有圖片
            if selected_item.get("image_url"):
                try:
                    st.image(
                        f"{ORDER_SERVICE_URL}{selected_item['image_url']}", width=200
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
                                response = requests.put(
                                    url, data=data, files=files, headers=headers
                                )
                            else:
                                response = requests.put(url, data=data, headers=headers)

                            if response.status_code in (200, 201):
                                st.success("菜單項更新成功")
                                time.sleep(1)
                                st.rerun()
                            else:
                                try:
                                    err = response.json()
                                except:
                                    err = response.text
                                st.error(
                                    f"菜單項更新失敗: {response.status_code} {err}"
                                )
                        except Exception as e:
                            st.error(f"更新過程中出錯: {e}")


# 顧客管理頁面 (只有店員和管理員)
def customer_management_page():
    st.header("👥 顧客管理")

    # 獲取顧客列表 - 修復權限問題
    response = make_api_request(
        "GET", "/orchestration/customers", token=st.session_state.access_token
    )

    if response and response.status_code == 200:
        customers = response.json()

        if not customers:
            st.info("暫無顧客資料")
            return

        # 顯示顧客列表
        for customer in customers:
            with st.container(border=True):
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


# 主界面
def main():
    # 側邊欄：登入狀態和導航
    with st.sidebar:
        st.title("🍽️ 餐廳訂單系統")

        if st.session_state.access_token:
            st.success(f"已登入: {st.session_state.username}")
            st.write(f"角色: {st.session_state.role}")
            if st.session_state.customer_id:
                st.write(f"顧客ID: {st.session_state.customer_id}")

            st.markdown("---")

            # 顯示導航選項 (根據用戶角色)
            pages = ["查看菜單"]

            if st.session_state.role == "customer":
                pages.extend(["購物車", "我的訂單"])

            # 確保管理員也能訪問菜單管理等功能
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

            # 給 radio 指定唯一 key，避免重複元件 ID 問題
            selected_page = st.radio("導航", pages, key="sidebar_nav")

            # 顯示用戶詳細信息 (便於調試)
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

    # 主內容區域
    if not st.session_state.access_token:
        login_page()
    else:
        # 根據選擇的頁面顯示不同內容
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


if __name__ == "__main__":
    # 開發時可以取消以下註釋來啟用調試頁面
    # debug_session()
    main()
