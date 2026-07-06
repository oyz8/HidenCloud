#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
import requests
from datetime import datetime, timezone, timedelta
from seleniumbase import Driver
import signal
import subprocess

# ====================== 配置区域 ======================
HIDENCLOUD = os.getenv("HIDENCLOUD", "")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")
PROXY_SERVER = os.getenv("PROXY_SERVER", "")

if "-----" in HIDENCLOUD:
    HIDEN_EMAIL, HIDEN_PWD = HIDENCLOUD.split("-----", 1)
else:
    raise ValueError("❌ HIDENCLOUD 格式错误，应为 email-----password")

BASE_URL = "https://dash.hidencloud.com"
STATE_DIR = "browser_state"
SCREENSHOT_DIR = "screenshots"

os.makedirs(STATE_DIR, exist_ok=True)
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

USER_DATA_DIR = os.path.abspath(os.path.join(STATE_DIR, "selenium_profile"))


# ====================== 工具函数 ======================
def get_bj_time():
    """返回北京时间字符串"""
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')


def send_tg_notification(message, photo_path=None):
    """发送 Telegram 通知，可附带截图"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("[WARN] 未配置 TG 信息，跳过发送")
        return
    try:
        if photo_path and os.path.exists(photo_path):
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
            with open(photo_path, 'rb') as f:
                files = {'photo': f}
                data = {'chat_id': TG_CHAT_ID, 'caption': message, 'parse_mode': 'Markdown'}
                requests.post(url, files=files, data=data, timeout=30)
        else:
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
            payload = {"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "Markdown"}
            requests.post(url, json=payload, timeout=10)
        print("[INFO] 📡 TG 通知已发送")
    except Exception as e:
        print(f"[ERROR] TG 发送失败: {e}")


def take_screenshot(driver, name):
    """截图并返回文件路径"""
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime('%H%M%S')
    filename = f"{SCREENSHOT_DIR}/{timestamp}-{name}.png"
    try:
        driver.save_screenshot(filename)
        print(f"[INFO] 📸 截图 → {filename}")
    except Exception as e:
        print(f"[WARN] 截图失败: {e}")
        filename = None
    return filename


def wait_for_turnstile_token(driver, timeout=90):
    """等待 Cloudflare Turnstile token 生成"""
    print("[INFO] ⏳ 等待 Turnstile 验证通过...")
    start = time.time()
    while time.time() - start < timeout:
        token = driver.execute_script(
            'return document.querySelector("[name=cf-turnstile-response]")?.value'
        )
        if token and len(token) > 20:
            print("[INFO] ✅ Turnstile token 已生成")
            return True
        time.sleep(1)
    return False


def wait_for_url_contains(driver, keyword, timeout=45):
    """等待当前 URL 包含特定关键字"""
    start = time.time()
    while time.time() - start < timeout:
        if keyword in driver.current_url:
            return True
        time.sleep(0.5)
    return False


def check_login_error(driver):
    """检查页面是否有登录错误信息"""
    try:
        error_selectors = [
            ".text-red-500", ".alert-danger", "[role='alert']", ".error", ".invalid-feedback"
        ]
        for sel in error_selectors:
            elem = driver.find_element(sel, by="css selector")
            if elem and elem.is_displayed() and elem.text.strip():
                return elem.text.strip()
    except:
        pass
    return None


def mask_email(email):
    """邮箱脱敏显示"""
    if '@' in email:
        local, domain = email.split('@', 1)
        return f"{local[:3]}***@{domain}"
    return f"{email[:3]}***"


def parse_due_date(text):
    """将页面显示的日期字符串转换为 YYYY-MM-DD 格式"""
    if not text:
        return None
    # 格式: "28 Apr 2026"
    match = re.search(r'(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})', text)
    if match:
        day, month_str, year = match.groups()
        try:
            dt = datetime.strptime(f"{day} {month_str} {year}", "%d %b %Y")
            return dt.strftime("%Y-%m-%d")
        except:
            pass
    # 已经是标准格式
    if re.match(r'\d{4}-\d{2}-\d{2}', text):
        return text
    return None


def get_current_due_date(driver):
    """获取当前管理页面的到期时间，返回原始字符串和标准化日期"""
    due_selectors = [
        ("xpath", "//h6[contains(text(),'Due date')]/following-sibling::div"),
        ("xpath", "//h6[contains(text(),'Due Date')]/following-sibling::div"),
        ("xpath", "//*[contains(text(),'Due date')]/following-sibling::*"),
        ("xpath", "//*[contains(text(),'Expire')]/following-sibling::*"),
        ("xpath", "//*[contains(text(),'Expiry')]/following-sibling::*"),
        ("xpath", "//span[contains(@class,'due-date') or contains(@class,'expire')]"),
        ("xpath", "//div[contains(@class,'card-body')]//div[not(contains(@class,'card-header'))]"),
    ]
    
    for by, selector in due_selectors:
        try:
            due_elem = driver.find_element(by, selector)
            if due_elem and due_elem.text.strip():
                raw = due_elem.text.strip()
                print(f"[DEBUG] 找到到期日期元素: {raw[:50]}")
                std = parse_due_date(raw)
                return raw, std
        except Exception as e:
            print(f"[DEBUG] 选择器失败 {selector}: {str(e)[:50]}")
            continue
    
    # 如果找不到元素，尝试从页面文本中直接提取日期
    try:
        page_text = driver.find_element("tag name", "body").text
        date_patterns = [
            r'(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})',  # 28 Apr 2026
            r'(\d{4})-(\d{2})-(\d{2})',               # 2026-04-28
            r'(\d{2})/(\d{2})/(\d{4})',               # 04/28/2026
        ]
        for pattern in date_patterns:
            match = re.search(pattern, page_text)
            if match:
                raw = match.group(0)
                std = parse_due_date(raw)
                print(f"[DEBUG] 从页面文本提取日期: {raw}")
                return raw, std
    except:
        pass
    
    print("[WARN] 无法找到到期日期元素")
    return "N/A", None


# ====================== 主逻辑 ======================
def main():
    print("[INFO] " + "=" * 50)
    print("[INFO] HidenCloud 自动续期脚本 (SeleniumBase)")
    print("[INFO] " + "=" * 50)
    print(f"[INFO] 📂 状态目录: {USER_DATA_DIR}")
    print(f"[INFO] 📸 截图目录: {SCREENSHOT_DIR}")

    # ---------- 浏览器驱动配置 ----------
    driver_kwargs = {
        "headless": True,
        "uc": True,  # 使用 undetected-chromedriver 更好绕过 Cloudflare
        "window_size": "1920,1080",
    }
    
    if PROXY_SERVER:
        driver_kwargs["proxy"] = PROXY_SERVER
        print(f"[INFO] 🌐 使用代理: {PROXY_SERVER}")
    
    driver = Driver(**driver_kwargs)
    
    # 添加浏览器伪装
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    driver.execute_script("Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]})")
    driver.execute_script("Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en-US', 'en']})")
    print("[INFO] 🎭 已应用浏览器伪装")
    
    # 安全包装 driver.get，绕过 uc=True 的窗口关闭超时
    original_get = driver.get
    
    def safe_get(url, max_retries=3):
        for attempt in range(max_retries):
            try:
                original_get(url)
                return
            except Exception as e:
                error_msg = str(e).lower()
                if "close window" in error_msg or "failed to close window" in error_msg:
                    print(f"[WARN] 窗口关闭超时 (尝试 {attempt + 1}/{max_retries})，重试...")
                    try:
                        driver.execute_script("try { window.close(); } catch(e) {}")
                        if driver.window_handles:
                            driver.switch_to.window(driver.window_handles[0])
                    except:
                        pass
                    time.sleep(2)
                elif "timeout" in error_msg:
                    print(f"[WARN] 页面加载超时 (尝试 {attempt + 1}/{max_retries})，重试...")
                    time.sleep(3)
                else:
                    raise
        print("[WARN] 窗口关闭超时，继续执行...")
    
    driver.get = safe_get

    driver.set_page_load_timeout(90)
    driver.set_script_timeout(60)

    try:
        driver.get("about:blank")
    except Exception as e:
        print(f"[WARN] 访问 about:blank 失败（可忽略）: {e}")

    time.sleep(2)
    
    driver.set_page_load_timeout(60)
    driver.set_script_timeout(60)

    final_screenshot = None
    result_status = "❌ 续订失败"
    due_date_before_raw = "N/A"
    due_date_before_std = None
    due_date_after_raw = "N/A"
    due_date_after_std = None
    sid = None

    try:
        # ---------- 1. 访问主页 ----------
        print(f"[INFO] 🌐 访问主页: {BASE_URL}/dashboard")
        driver.get(f"{BASE_URL}/dashboard")
        time.sleep(5)
        take_screenshot(driver, "01-initial")
        
        print("[DEBUG] Dashboard URL:", driver.current_url)
        body_text = driver.execute_script("return document.body.innerText || '';")
        print(f"[DEBUG] Dashboard 页面内容长度: {len(body_text)} 字符")
        
        # ---------- 2. 登录判断 ----------
        needs_login = False
        
        if "/auth/login" in driver.current_url:
            print("[INFO] 🔒 检测到未登录（URL），开始登录流程")
            needs_login = True
        elif driver.is_element_visible("input#username"):
            print("[INFO] 🔒 检测到未登录（登录表单可见），开始登录流程")
            needs_login = True
        elif len(body_text) < 500:
            print(f"[WARN] 页面内容过少({len(body_text)} 字符)，强制重新登录")
            needs_login = True
        
        if needs_login:
            take_screenshot(driver, "02-login-page")
            
            # Cloudflare 验证处理 - 多次重试
            print("[INFO] 检查 Cloudflare 验证...")
            login_form_found = False
            
            for main_attempt in range(3):
                print(f"[INFO] ===== 主验证尝试 {main_attempt + 1}/3 =====")
                
                # 等待页面内容变化
                for cf_attempt in range(10):
                    try:
                        cf_turnstile = driver.is_element_present(".cf-turnstile")
                        cf_widget = driver.is_element_present(".cf-widget")
                        login_form = driver.is_element_visible("input#username")
                        
                        if login_form:
                            print("[INFO] ✅ 登录表单已出现")
                            login_form_found = True
                            break
                        
                        if cf_turnstile:
                            print(f"[INFO] 🔐 检测到 Turnstile ({cf_attempt + 1}/10)...")
                            try:
                                driver.uc_gui_click_cf(".cf-turnstile")
                            except:
                                driver.execute_script("""
                                    var turnstile = document.querySelector('.cf-turnstile iframe');
                                    if (turnstile) turnstile.click();
                                """)
                            time.sleep(3)
                        elif cf_widget:
                            print(f"[INFO] 🔐 检测到 CF Widget ({cf_attempt + 1}/10)...")
                            time.sleep(3)
                        else:
                            print(f"[INFO] ⏳ 等待验证完成... ({cf_attempt + 1}/10)")
                            time.sleep(2)
                            
                    except Exception as e:
                        print(f"[DEBUG] 验证检查异常: {e}")
                        time.sleep(2)
                
                if login_form_found:
                    break
                    
                # 如果没找到表单，尝试刷新
                print(f"[WARN] 主尝试 {main_attempt + 1} 失败，刷新页面...")
                driver.refresh()
                time.sleep(8)
                take_screenshot(driver, f"02-retry-{main_attempt + 1}")
            
            # 最终检查
            if not driver.is_element_visible("input#username"):
                print("[ERROR] 无法到达登录表单，请检查网络或手动验证")
                take_screenshot(driver, "ERROR-no-login-form")
                raise Exception("无法到达登录表单，可能是 Cloudflare 阻止了自动化访问")
            
            masked_email = mask_email(HIDEN_EMAIL)
            print(f"[INFO] ✍️ 填写邮箱: {masked_email}")
            
            # 使用更可靠的方式填写表单
            try:
                driver.type("input#username", HIDEN_EMAIL)
            except:
                print("[WARN] 使用备用方式填写邮箱...")
                driver.execute_script("document.querySelector('input#username').value = arguments[0];", HIDEN_EMAIL)
            
            try:
                driver.type("input#password", HIDEN_PWD)
            except:
                print("[WARN] 使用备用方式填写密码...")
                driver.execute_script("document.querySelector('input#password').value = arguments[0];", HIDEN_PWD)
            
            take_screenshot(driver, "04-credentials-filled")

            # Turnstile 处理 - 多次尝试
            print("[INFO] ⏳ 等待 Turnstile 加载...")
            time.sleep(8)
            
            turnstile_resolved = False
            for turnstile_attempt in range(5):
                if driver.is_element_present(".cf-turnstile"):
                    print(f"[INFO] 🖱️ 点击 Turnstile ({turnstile_attempt + 1}/5)...")
                    try:
                        driver.uc_gui_click_cf(".cf-turnstile")
                    except:
                        driver.click(".cf-turnstile")
                    take_screenshot(driver, f"05-turnstile-click-{turnstile_attempt + 1}")
                    time.sleep(8)
                    
                    # 检查 token 是否生成
                    token = driver.execute_script(
                        'return document.querySelector("[name=cf-turnstile-response]")?.value'
                    )
                    if token and len(token) > 20:
                        print("[INFO] ✅ Turnstile token 已生成")
                        turnstile_resolved = True
                        take_screenshot(driver, "06-token-ready")
                        break
                else:
                    # Turnstile 已经消失，说明验证通过
                    print("[INFO] ✅ Turnstile 已解决")
                    turnstile_resolved = True
                    break
            
            if not turnstile_resolved:
                print("[WARN] Turnstile 可能未完成，尝试继续...")
            
            print("[INFO] 🚀 提交登录表单")
            driver.click("button[type='submit']")
            take_screenshot(driver, "07-login-submitted")
            
            # 提交后继续等待 Turnstile
            for post_wait in range(10):
                time.sleep(3)
                
                # 检查是否已跳转
                if "/dashboard" in driver.current_url:
                    print(f"[INFO] ✅ 已跳转到 Dashboard ({post_wait + 1})")
                    break
                
                # 检查 Turnstile
                token = driver.execute_script(
                    'return document.querySelector("[name=cf-turnstile-response]")?.value'
                )
                if token and len(token) > 20:
                    print(f"[INFO] ✅ 提交后 Token 已生成 ({post_wait + 1})")
                    break
                    
                if post_wait < 9:
                    print(f"[INFO] ⏳ 等待登录响应... ({post_wait + 1}/10)")
            
            print("[INFO] ⏳ 等待登录跳转...")
            
            login_success = False
            for login_wait in range(15):
                time.sleep(2)
                if "/dashboard" in driver.current_url:
                    print(f"[INFO] ✅ 已跳转到 Dashboard ({login_wait + 1})")
                    login_success = True
                    break
                print(f"[DEBUG] 等待跳转... ({login_wait + 1}/15) 当前: {driver.current_url}")
            
            if not login_success:
                error_text = check_login_error(driver)
                if error_text:
                    print(f"[ERROR] 登录失败: {error_text}")
                    take_screenshot(driver, "ERROR-login-failed-message")
                else:
                    print("[WARN] 登录未成功，尝试直接访问 Dashboard...")
                    take_screenshot(driver, "ERROR-login-stuck")
                
                # 尝试直接访问 Dashboard（可能有缓存的登录状态）
                driver.get(f"{BASE_URL}/dashboard")
                time.sleep(5)
                
                if "/dashboard" in driver.current_url:
                    print("[INFO] ✅ 绕过登录访问 Dashboard 成功")
                    login_success = True
                elif "/auth/login" in driver.current_url:
                    print("[ERROR] 无法登录，请检查凭证或使用代理")
                    raise Exception("无法登录 Cloudflare 阻止了自动化访问")

            print("[INFO] ✅ 登录成功")
            take_screenshot(driver, "07-login-success")
            
            # ---------- 处理第二层 Cloudflare 安全验证 ----------
            print("[INFO] 🛡️ 检查第二层安全验证...")
            security_success = False
            
            for security_wait in range(40):
                time.sleep(3)
                current_url = driver.current_url
                
                # 检查是否遇到安全验证页面
                try:
                    body_text = driver.execute_script("return document.body.innerText || '';")
                    
                    if "Verifying" in body_text or "Analyzing connection" in body_text or "Protection Enabled" in body_text:
                        print(f"[INFO] ⏳ Cloudflare 安全验证中 ({security_wait + 1}/40)...")
                        
                        # 模拟用户行为：随机滚动和鼠标移动
                        if security_wait % 5 == 0:
                            driver.execute_script("window.scrollBy(0, Math.random() * 100);")
                            driver.execute_script("""
                                var event = new MouseEvent('mousemove', {
                                    clientX: Math.random() * window.innerWidth,
                                    clientY: Math.random() * window.innerHeight,
                                    bubbles: true
                                });
                                document.dispatchEvent(event);
                            """)
                        continue
                        
                    # 检查是否已到达 Dashboard 且内容正常
                    if "/dashboard" in current_url and len(body_text) > 500:
                        print(f"[INFO] ✅ 第二层验证完成，Dashboard 内容长度: {len(body_text)} 字符")
                        security_success = True
                        break
                        
                except Exception as e:
                    print(f"[DEBUG] 检查安全验证时出错: {e}")
                
                if security_wait < 39:
                    print(f"[DEBUG] 等待安全验证... ({security_wait + 1}/40)")
            
            if not security_success:
                print("[WARN] ⚠️ 第二层验证超时，尝试刷新页面...")
                driver.refresh()
                time.sleep(10)
                
                # 再次等待验证完成
                for retry_wait in range(20):
                    time.sleep(3)
                    try:
                        body_text = driver.execute_script("return document.body.innerText || '';")
                        if "/dashboard" in driver.current_url and len(body_text) > 500:
                            print(f"[INFO] ✅ 刷新后验证完成，内容长度: {len(body_text)} 字符")
                            security_success = True
                            break
                        print(f"[DEBUG] 刷新后等待... ({retry_wait + 1}/20)")
                    except:
                        continue
            
            take_screenshot(driver, "07b-security-check")
        else:
            print("[INFO] ✅ 已登录，跳过登录流程")
            take_screenshot(driver, "02-already-logged-in")
            
            # 确保 Dashboard 页面完全加载
            print("[DEBUG] 等待 Dashboard 完全加载...")
            for load_wait in range(5):
                time.sleep(2)
                try:
                    body_text = driver.execute_script("return document.body.innerText || '';")
                    print(f"[DEBUG] Dashboard 内容长度: {len(body_text)} 字符")
                    if len(body_text) > 200:
                        break
                except:
                    continue

        # ---------- 3. 提取服务器 ID ----------
        print("[INFO] 🔍 提取服务器 ID...")
        take_screenshot(driver, "08-dashboard")
        
        print("[INFO] ⏳ 等待页面加载完成...")
        
        # 等待页面完全加载
        for attempt in range(5):
            time.sleep(3)
            try:
                body_text = driver.execute_script("return document.body.innerText || '';")
                print(f"[DEBUG] 页面内容长度: {len(body_text)} 字符 ({attempt + 1}/5)")
                if len(body_text) > 500:
                    break
            except Exception as e:
                print(f"[WARN] 页面等待失败: {e}")
        
        # 如果页面内容仍然很短，尝试刷新
        body_text = driver.execute_script("return document.body.innerText || '';")
        if len(body_text) < 500:
            print(f"[WARN] 页面内容过短，尝试刷新...")
            driver.refresh()
            time.sleep(8)
            
            # 再次等待
            for attempt in range(3):
                time.sleep(3)
                body_text = driver.execute_script("return document.body.innerText || '';")
                print(f"[DEBUG] 刷新后页面内容长度: {len(body_text)} 字符 ({attempt + 1}/3)")
                if len(body_text) > 500:
                    break
        
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)

        sid = None
        server_text = None
        
        # 尝试从所有服务链接中提取（最可靠的方式）
        print("[DEBUG] 查找所有 /service/ 链接...")
        try:
            all_links = driver.find_elements("xpath", "//a[contains(@href, '/service/')]")
            print(f"[DEBUG] 找到 {len(all_links)} 个服务链接")
            for i, link in enumerate(all_links):
                try:
                    href = link.get_attribute("href") or ""
                    text = link.text.strip()
                    print(f"[DEBUG] 链接 {i}: href='{href}', text='{text[:50]}'")
                    match = re.search(r'/service/(\d+)', href)
                    if match:
                        potential_sid = match.group(1)
                        if len(potential_sid) >= 4:
                            sid = potential_sid
                            server_text = text
                            print(f"[INFO] ✅ 从链接提取到服务器 ID: {sid}")
                            break
                except:
                    continue
        except Exception as e:
            print(f"[DEBUG] 链接搜索失败: {e}")

        # 尝试从页面文本中提取
        if not sid:
            print("[DEBUG] 尝试从页面文本提取服务器 ID...")
            try:
                page_html = driver.page_source
                matches = re.findall(r'(?:Free\s+)?Server\s*#\s*(\d+)', page_html, re.IGNORECASE)
                if matches:
                    sid = matches[0]
                    print(f"[INFO] ✅ 从页面源码提取到服务器 ID: {sid}")
            except Exception as e:
                print(f"[DEBUG] 文本提取失败: {e}")

        # 尝试 JavaScript 获取所有可见文本
        if not sid:
            print("[DEBUG] 使用 JavaScript 提取页面文本...")
            try:
                js_result = driver.execute_script("""
                    var text = document.body.innerText || document.body.textContent || '';
                    return text;
                """)
                if js_result:
                    matches = re.findall(r'(?:Free\s+)?Server\s*#\s*(\d+)', js_result, re.IGNORECASE)
                    if matches:
                        sid = matches[0]
                        print(f"[INFO] ✅ 从 JS 提取到服务器 ID: {sid}")
            except Exception as e:
                print(f"[DEBUG] JS 提取失败: {e}")

        # 尝试遍历所有链接查找
        if not sid:
            print("[DEBUG] 遍历所有链接...")
            try:
                all_elements = driver.find_elements("xpath", "//a")
                print(f"[DEBUG] 找到 {len(all_elements)} 个链接")
                for elem in all_elements:
                    try:
                        text = elem.text.strip()
                        if 'Server' in text or 'server' in text:
                            href = elem.get_attribute("href") or ""
                            match = re.search(r'/service/(\d+)', href)
                            if match:
                                sid = match.group(1)
                                print(f"[INFO] ✅ 从遍历提取到服务器 ID: {sid}")
                                break
                    except:
                        continue
            except Exception as e:
                print(f"[DEBUG] 遍历失败: {e}")

        # 滚动页面多次尝试
        if not sid:
            print("[INFO] 滚动页面查找服务器...")
            for scroll_pos in [0, 300, 600, 1000, 1500, 2000]:
                driver.execute_script(f"window.scrollTo(0, {scroll_pos});")
                time.sleep(1)
                
                try:
                    links = driver.find_elements("xpath", "//a[contains(@href, '/service/')]")
                    for link in links:
                        href = link.get_attribute("href") or ""
                        match = re.search(r'/service/(\d+)', href)
                        if match and len(match.group(1)) >= 4:
                            sid = match.group(1)
                            print(f"[INFO] ✅ 滚动后提取到服务器 ID: {sid}")
                            break
                except:
                    continue
                if sid:
                    break

        # 如果还是找不到，尝试使用上次成功的 ID
        if not sid:
            print("[WARN] 无法自动检测服务器 ID，尝试使用默认 ID...")
            sid = "207262"
            print(f"[INFO] 使用默认服务器 ID: {sid}")

        if not sid:
            take_screenshot(driver, "ERROR-no-server-id")
            raise Exception("无法提取服务器 ID")

        manage_url = f"{BASE_URL}/service/{sid}/manage"
        print(f"[INFO] 🚀 访问管理页面: {BASE_URL}/service/***/manage")
        driver.get(manage_url)
        
        print("[INFO] ⏳ 等待管理页面加载完成...")
        for attempt in range(3):
            time.sleep(2)
            try:
                body_text = driver.execute_script("return document.body.innerText || '';")
                if len(body_text) > 50:
                    print(f"[DEBUG] 管理页面内容长度: {len(body_text)} 字符")
                    break
                print(f"[WARN] 管理页面内容过短，尝试 {attempt + 1}/3...")
            except Exception as e:
                print(f"[WARN] 管理页面等待失败: {e}")
        
        take_screenshot(driver, "09-manage-page")

        # ---------- 4. 获取续订前到期时间 ----------
        due_date_before_raw, due_date_before_std = get_current_due_date(driver)
        print(f"[INFO] 续订前到期时间: {due_date_before_raw}")

        # ---------- 5. 续期操作 ----------
        renew_executed = False
        restricted = False
        days_left = None
        threshold = None

        try:
            print("[INFO] 🔄 查找并点击 Renew 按钮...")

            # 定位 Renew 按钮
            renew_btn = None
            print("[DEBUG] 开始查找 Renew 按钮...")
            
            # 尝试所有按钮
            try:
                all_buttons = driver.find_elements("tag name", "button")
                print(f"[DEBUG] 页面共有 {len(all_buttons)} 个按钮")
                for i, btn in enumerate(all_buttons):
                    try:
                        btn_text = btn.text.strip()
                        btn_class = btn.get_attribute("class") or ""
                        btn_onclick = btn.get_attribute("onclick") or ""
                        print(f"[DEBUG] 按钮 {i}: text='{btn_text}', class='{btn_class[:30]}', onclick='{btn_onclick[:50]}'")
                        
                        if any(keyword in (btn_text + btn_class + btn_onclick).lower() 
                               for keyword in ['renew', 'recycle', 'extend', '续', '延长']):
                            if btn.is_displayed():
                                renew_btn = btn
                                print(f"[INFO] ✅ 通过文本匹配找到 Renew 按钮")
                                break
                    except:
                        continue
            except Exception as e:
                print(f"[DEBUG] 按钮搜索出错: {e}")
            
            if not renew_btn:
                selectors = [
                    ("css selector", "button[onclick*='showRenewAlert']"),
                    ("xpath", "//button[.//i[contains(@class, 'bx-recycle')]]"),
                    ("xpath", "//button[contains(text(),'Renew')]"),
                    ("xpath", "//button[contains(text(),'renew')]"),
                    ("xpath", "//button[contains(@class, 'renew')]"),
                    ("xpath", "//button[contains(@class, 'recycle')]"),
                    ("xpath", "//button[contains(@aria-label, 'Renew')]"),
                    ("xpath", "//*[contains(text(),'Renew')]"),
                ]
                for by, value in selectors:
                    try:
                        renew_btn = driver.find_element(by, value)
                        if renew_btn and renew_btn.is_displayed():
                            print(f"[INFO] ✅ 通过选择器找到 Renew 按钮: {value}")
                            break
                    except:
                        continue

            if not renew_btn:
                take_screenshot(driver, "ERROR-renew-button-not-found")
                raise Exception("页面上未找到 Renew 按钮")

            # 提取 onclick 属性
            onclick_val = renew_btn.get_attribute("onclick") or ""
            print(f"[INFO] Renew 按钮 onclick: {onclick_val}")

            param_match = re.search(
                r'showRenewAlert\((\d+),\s*(\d+),\s*(true|false)\)', onclick_val
            )
            if param_match:
                days_left = int(param_match.group(1))
                threshold = int(param_match.group(2))
                is_free = param_match.group(3) == "true"
                print(f"[INFO] 到期剩余: {days_left} 天, 续期阈值: ≤{threshold} 天, 免费服务: {is_free}")

            # 点击 Renew 按钮
            renew_btn.click()
            renew_executed = True
            print("[INFO] ✅ Renew 按钮已点击")
            time.sleep(3)
            take_screenshot(driver, "10-renew-clicked")

            time.sleep(1)

            # 检测限制弹窗
            restriction_h3 = driver.execute_script(
                "var el = document.querySelector('.fixed.inset-0 h3');"
                "return el ? el.textContent.trim() : '';"
            )
            if 'Renewal Restricted' in restriction_h3:
                restricted = True
                alert_text = driver.execute_script(
                    "var el = document.querySelector('.fixed.inset-0 p');"
                    "return el ? el.textContent.trim() : '';"
                )
                print(f"[INFO] ⚠️ 触发限制弹窗: {alert_text}")
                take_screenshot(driver, "11-renewal-restricted-popup")

                try:
                    ok_btn = driver.find_element("xpath", "//button[contains(text(),'OK')]")
                    ok_btn.click()
                    time.sleep(1)
                    print("[INFO] 已关闭限制弹窗")
                except:
                    pass
            else:
                # 正常续期流程
                print("[INFO] 📦 等待续期模态框...")
                modal_selector = f"div#renewService-{sid}"
                driver.wait_for_element_visible(modal_selector, timeout=10)
                take_screenshot(driver, "11-renew-modal-opened")

                print("[INFO] 📦 点击 Create Invoice...")
                submit_btn = driver.find_element(by="css selector", value=f"{modal_selector} button[type='submit']")
                submit_btn.click()
                time.sleep(3)
                take_screenshot(driver, "12-invoice-created")

                print("[INFO] 💳 等待支付页面...")
                time.sleep(5)
                take_screenshot(driver, "13-invoice-page")

                # 滚动到底部
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)
                take_screenshot(driver, "14-scrolled-to-bottom")

                print("[INFO] ✅ Pay 按钮已点击")
                pay_clicked = driver.execute_script("""
                    var btn = document.querySelector('button[type="submit"]');
                    if(btn && btn.innerText.includes('Pay')) {
                        btn.click();
                        return true;
                    }
                    return false;
                """)

                if pay_clicked:
                    print("[INFO] ⏳ 等待支付完成...")
                    time.sleep(5)
                    take_screenshot(driver, "15-pay-clicked")
                else:
                    print("[WARN] 未找到 Pay 按钮，可能免费服务自动完成")
                    take_screenshot(driver, "15-no-pay-button")

        except Exception as e:
            print(f"[ERROR] ❌ 续期过程出错: {e}")
            take_screenshot(driver, "ERROR-renew-process")
            raise e

        # ---------- 6. 获取续订后到期时间 ----------
        driver.get(manage_url)
        time.sleep(3)
        due_date_after_raw, due_date_after_std = get_current_due_date(driver)
        print(f"[INFO] 续订后到期时间: {due_date_after_raw}")
        final_screenshot = take_screenshot(driver, "16-final-due-date")

        if due_date_after_std:
            print(f"到期时间(标准): {due_date_after_std}")
        else:
            print(f"到期时间(标准): {due_date_after_raw}")

        # ---------- 7. 判断结果状态 ----------
        if restricted and not renew_executed:
            result_status = "ℹ️ 暂无可续期"
        elif restricted and renew_executed:
            result_status = "ℹ️ 暂无可续期"
        elif due_date_before_std and due_date_after_std:
            if due_date_after_std > due_date_before_std:
                result_status = "✅ 续订成功"
            else:
                result_status = "❌ 续订失败"
        elif renew_executed and not restricted:
            result_status = "⚠️ 续期已执行，请确认"
        else:
            result_status = "❌ 续订失败"

        # ---------- 8. 发送 TG 通知 ----------
        bj_time = get_bj_time()
        change_info = ""
        if due_date_before_raw != "N/A" and due_date_after_raw != "N/A":
            if due_date_before_raw == due_date_after_raw:
                change_info = due_date_after_raw
            else:
                change_info = f"{due_date_before_raw} → {due_date_after_raw}"
        else:
            change_info = due_date_after_raw

        extra_info = ""
        if restricted and days_left is not None and threshold is not None:
            extra_info = f"\n剩余: {days_left} 天 (需 ≤{threshold} 天可续)"

        tg_caption = (
            f"{result_status}\n\n"
            f"账号: `{HIDEN_EMAIL}`\n"
            f"服务器: `Free Server #{sid}`\n"
            f"到期: {change_info}{extra_info}\n"
            f"时间: {bj_time}\n\n"
            f"HidenCloud Auto Renew"
        )
        send_tg_notification(tg_caption, photo_path=final_screenshot)

        print(f"[INFO] 🎉 任务完成 — {result_status}")

    except Exception as e:
        print(f"[ERROR] ❌ 脚本执行失败: {e}")
        try:
            take_screenshot(driver, "CRITICAL-ERROR")
        except:
            pass
        send_tg_notification(f"❌ HidenCloud 续期失败\n错误: {str(e)[:100]}")
        raise
    finally:
        try:
            driver.quit()
        except Exception as quit_err:
            print(f"[WARN] 浏览器退出时出错（可忽略）: {quit_err}")
            try:
                import os
                import subprocess
                subprocess.run(['pkill', '-f', 'chrome'], stderr=subprocess.DEVNULL)
                subprocess.run(['pkill', '-f', 'chromedriver'], stderr=subprocess.DEVNULL)
            except:
                pass


if __name__ == "__main__":
    main()
