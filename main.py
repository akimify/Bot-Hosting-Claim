import os
import asyncio
import re
from playwright.async_api import async_playwright

# ===== 配置区 =====
TARGET_URL  = "https://bot-hosting.net/login"
EARN_URL    = "https://bot-hosting.net/panel/earn"

DISCORD_EMAIL    = os.getenv("DISCORD_EMAIL")
DISCORD_PASSWORD = os.getenv("DISCORD_PASSWORD")
PROXY_URL        = os.getenv("PROXY")

ESSENTIAL_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "cache-control": "max-age=0",
    "dnt": "1"
}

# ===== 代理解析 =====
def parse_proxy(proxy_url):
    if not proxy_url:
        return None
    proxy_url = proxy_url.rstrip('/')
    try:
        if "://" not in proxy_url:
            proxy_url = "http://" + proxy_url
        protocol, rest = proxy_url.split("://", 1)
        if "@" in rest:
            auth, host_port = rest.split("@", 1)
            username, password = auth.split(":", 1)
        else:
            username = password = None
            host_port = rest
        proxy_config = {"server": f"{protocol}://{host_port}"}
        if username and password:
            proxy_config["username"] = username
            proxy_config["password"] = password
        return proxy_config
    except Exception as e:
        print(f"⚠️  代理解析失败: {e}")
        return None

# ===== Discord OAuth 登录 =====
async def discord_login(page):
    """
    完整的 Discord OAuth 登录流程：
    1. 访问 bot-hosting 登录页，点击 Discord 登录按钮
    2. 跳转到 Discord 登录页，填入邮箱密码
    3. 点击登录，等待跳回 OAuth 授权页
    4. 点击授权按钮
    5. 等待跳回 bot-hosting，拿到 JWT token
    返回: True (成功) / False (失败)
    """
    if not DISCORD_EMAIL or not DISCORD_PASSWORD:
        print("❌ 未设置 DISCORD_EMAIL 或 DISCORD_PASSWORD 环境变量")
        return False

    try:
        # 步骤 1: 访问登录页
        print(f"\n→ 访问登录页: {TARGET_URL}")
        await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
        print("✓ 登录页加载完成")

        # 步骤 2: 点击 Discord 登录按钮（<a href="/login/discord">）
        print("→ 点击 Discord 登录按钮...")
        await page.click('a[href="/login/discord"]', timeout=10000)
        print("✓ 已点击 Discord 登录按钮")

        # 步骤 3: 等待跳转到 Discord 登录页
        print("→ 等待跳转到 Discord 登录页...")
        await page.wait_for_url("**/discord.com/login**", timeout=30000)
        print(f"✓ 已到达 Discord 登录页: {page.url}")

        # 步骤 4: 填入邮箱
        print("→ 填入邮箱...")
        await page.wait_for_selector('input[name="email"]', timeout=15000)
        await page.fill('input[name="email"]', DISCORD_EMAIL)
        print("✓ 邮箱已填入")

        # 步骤 5: 填入密码
        print("→ 填入密码...")
        await page.wait_for_selector('input[name="password"]', timeout=10000)
        await page.fill('input[name="password"]', DISCORD_PASSWORD)
        print("✓ 密码已填入（已脱敏）")

        # 步骤 6: 点击登录按钮
        print("→ 点击登录按钮...")
        # 登录按钮是 button[type="submit"]
        await page.click('button[type="submit"]', timeout=10000)
        print("✓ 已点击登录按钮")

        # 步骤 7: 等待跳转（两种情况：直接跳授权页 or 需要处理 2FA）
        print("→ 等待 Discord 登录响应...")
        try:
            await page.wait_for_url("**/discord.com/oauth2/authorize**", timeout=20000)
            print("✓ 已到达 OAuth 授权页")
        except Exception:
            # 检查是否出现了 2FA 或错误提示
            current_url = page.url
            print(f"  当前页面: {current_url}")
            if "login" in current_url:
                # 检查是否有错误信息
                error_el = await page.query_selector('[class*="errorMessage"]')
                if error_el:
                    error_text = await error_el.inner_text()
                    print(f"❌ Discord 登录失败: {error_text}")
                else:
                    print("❌ Discord 登录超时，可能需要处理 2FA 或验证码")
                return False

        # 步骤 8: 点击授权按钮
        print("→ 等待授权按钮...")
        # 授权按钮：primary 类型的按钮，文字含"授权"或"Authorize"
        authorize_btn = None
        for selector in [
            'button.primary_a22cb0',
            'button[type="submit"]',
        ]:
            try:
                authorize_btn = await page.wait_for_selector(selector, timeout=8000)
                if authorize_btn and await authorize_btn.is_visible():
                    btn_text = await authorize_btn.inner_text()
                    print(f"  找到按钮: '{btn_text}' (selector: {selector})")
                    break
            except Exception:
                continue

        if not authorize_btn:
            # 可能已经授权过，直接跳回了
            print("  ℹ️  未找到授权按钮，可能已自动授权")
        else:
            await authorize_btn.click()
            print("✓ 已点击授权按钮")

        # 步骤 9: 等待跳回 bot-hosting
        print("→ 等待跳回 bot-hosting...")
        await page.wait_for_url("**/bot-hosting.net/**", timeout=30000)
        print(f"✓ 已跳回: {page.url}")

        # 步骤 10: 等待 token 写入 localStorage
        print("→ 等待 token 写入...")
        await page.wait_for_timeout(3000)

        token = await page.evaluate("localStorage.getItem('token')")
        if token:
            print(f"✓ 登录成功！token 已获取（前20位: {token[:20]}...）")
            return True
        else:
            print("⚠️  登录后未找到 token，请检查流程")
            return False

    except Exception as e:
        print(f"❌ Discord 登录失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

# ===== hCaptcha 处理 =====
async def solve_hcaptcha(page):
    try:
        from hcaptcha_challenger.agent import AgentV, AgentConfig
        from hcaptcha_challenger.models import CaptchaResponse

        CONFIGURED_MODEL = "gemini-2.5-flash-image"
        print(f"🛡️  使用模型: {CONFIGURED_MODEL}")

        agent_config = AgentConfig(model=CONFIGURED_MODEL)
        agent = AgentV(page=page, agent_config=agent_config)

        print("  → 点击 hcaptcha 复选框...")
        await agent.robotic_arm.click_checkbox()

        print("  → 等待挑战加载并解决...")
        await agent.wait_for_challenge()

        if agent.cr_list:
            print("  ✓ hCaptcha 验证成功！")
            return True
        else:
            print("  ℹ️  验证完成（无挑战响应）")
            return True

    except ImportError:
        print("⚠️  hcaptcha_challenger 未安装，跳过自动验证")
        return False
    except Exception as e:
        print(f"⚠️  hCaptcha 处理出错: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

# ===== 强制关闭所有弹窗 =====
async def force_close_all_modals(page):
    closed_any = False
    print("  → 清理残留弹窗...")
    try:
        ok_button = await page.wait_for_selector('button.swal-button.swal-button--confirm', timeout=2000)
        if ok_button and await ok_button.is_visible():
            await ok_button.click()
            closed_any = True
            await page.wait_for_timeout(2000)
    except Exception:
        pass

    try:
        for selector in ['div.modal-content span.close', 'span.close', '.modal-content .close']:
            close_button = await page.query_selector(selector)
            if close_button and await close_button.is_visible():
                await close_button.click()
                closed_any = True
                await page.wait_for_timeout(2000)
                break
    except Exception:
        pass

    return closed_any

# ===== 智能关闭弹窗（带进度解析）=====
async def close_all_modals(page):
    claimed, total = None, None
    try:
        print("  → 等待成功弹窗出现...")
        await page.wait_for_selector('.swal-modal', timeout=15000)
        await page.wait_for_timeout(1500)

        try:
            title = await page.locator('.swal-title').inner_text()
            text_content = await page.locator('.swal-text').inner_text()
            print(f"  弹窗内容: {title} | {text_content}")
            match = re.search(r'(\d+)\s*/\s*(\d+)', text_content)
            if match:
                claimed = int(match.group(1))
                total = int(match.group(2))
                print(f"  📊 进度: {claimed}/{total}")
        except Exception as e:
            print(f"  ⚠️  无法解析弹窗文本: {e}")

        ok_button = await page.wait_for_selector('button.swal-button.swal-button--confirm', timeout=5000)
        if ok_button:
            await ok_button.click()
            await page.wait_for_timeout(2000)

        try:
            await page.wait_for_selector('.swal-modal', state='hidden', timeout=10000)
        except Exception:
            pass

        # 关闭广告弹窗
        try:
            for selector in ['div.modal-content span.close', 'span.close', '.modal-content .close']:
                close_button = await page.query_selector(selector)
                if close_button and await close_button.is_visible():
                    await close_button.click()
                    await page.wait_for_timeout(2000)
                    break
        except Exception:
            pass

        await page.wait_for_timeout(2000)
        return claimed, total

    except Exception as e:
        print(f"  ⚠️  处理弹窗失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None, None

# ===== 检查按钮状态并处理 hCaptcha =====
async def check_button_and_solve_hcaptcha(page, max_retries=3):
    claim_button_selector = 'button.btn.green[type="submit"]'
    for retry in range(max_retries):
        try:
            print(f"  → 检查按钮状态 ({retry + 1}/{max_retries})...")
            claim_button = await page.wait_for_selector(claim_button_selector, timeout=10000)
            if not claim_button:
                return False

            is_disabled = await claim_button.is_disabled()
            button_text = await claim_button.inner_text()
            print(f"  按钮: {'disabled' if is_disabled else 'enabled'} | '{button_text}'")

            if not is_disabled:
                return True

            if "complete the captcha" in button_text.lower():
                print("  ⚠️  需要 hCaptcha 验证")
                success = await solve_hcaptcha(page)
                if success:
                    await page.wait_for_timeout(3000)
                    claim_button = await page.query_selector(claim_button_selector)
                    if claim_button and not await claim_button.is_disabled():
                        return True
            elif "you are on cooldown" in button_text.lower():
                print("  ⚠️  冷却中")
                return False
            else:
                return False

        except Exception as e:
            print(f"  ⚠️  检查按钮失败: {e}")
            return False

    return False

# ===== 点击领取按钮 =====
async def click_claim_coins(page, max_attempts=15):
    print(f"\n🎯 开始领取流程（最多 {max_attempts} 次）...")

    claim_button_selector = 'button.btn.green[type="submit"]'
    total_coins = 10
    claimed_so_far = 0
    task_completed = False

    for attempt in range(1, max_attempts + 1):
        if task_completed:
            break

        remaining_needed = total_coins - claimed_so_far
        print(f"\n{'='*50}")
        print(f"【尝试 {attempt}/{max_attempts} | 剩余: {max(0, remaining_needed)}】")
        print(f"{'='*50}")

        await force_close_all_modals(page)

        button_ready = await check_button_and_solve_hcaptcha(page, max_retries=3)

        if not button_ready:
            try:
                claim_button = await page.query_selector(claim_button_selector)
                if claim_button:
                    button_text = await claim_button.inner_text()
                    if "you are on cooldown" in button_text.lower():
                        print(f"  → 冷却中，等待 35 秒...")
                        await page.wait_for_timeout(35 * 1000)
                        continue
            except Exception:
                pass
            await page.wait_for_timeout(8000)
            continue

        claim_button = await page.wait_for_selector(claim_button_selector, timeout=15000)
        if not claim_button or await claim_button.is_disabled():
            await page.wait_for_timeout(8000)
            continue

        print("  → 点击领取按钮...")
        await claim_button.click()
        print("  ✓ 已点击")

        print("  → 等待弹窗（18秒）...")
        await page.wait_for_timeout(18 * 1000)

        claimed, total = await close_all_modals(page)

        if claimed is not None and total is not None:
            claimed_so_far = claimed
            total_coins = total
            print(f"  📊 进度: {claimed}/{total}")
            if claimed >= total:
                print(f"\n🎉 已完成全部目标！({claimed}/{total})")
                task_completed = True

        await page.wait_for_timeout(1 if task_completed else 10 * 1000)

    if task_completed or claimed_so_far >= total_coins:
        print(f"\n✅ 任务完成！最终进度: {claimed_so_far}/{total_coins}")
        return True
    else:
        print(f"\n⚠️  未达到目标（当前: {claimed_so_far}/{total_coins}）")
        return False

# ===== 主流程 =====
async def main():
    proxy_config = parse_proxy(PROXY_URL)
    if proxy_config:
        print(f"✓ 使用代理: {proxy_config['server']}")
    else:
        print("ℹ️  无代理")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
            proxy=proxy_config
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="zh-CN",
            timezone_id="Asia/Shanghai"
        )

        page = await context.new_page()

        async def intercept_route(route):
            if route.request.resource_type == "document":
                await route.continue_(headers=ESSENTIAL_HEADERS)
            else:
                await route.continue_()

        await page.route("**/*", intercept_route)

        # 步骤 1: Discord 登录
        print("\n→ 步骤 1: Discord 登录")
        login_success = await discord_login(page)
        if not login_success:
            print("❌ 登录失败，退出")
            await browser.close()
            return

        # 步骤 2: 跳转到 earn 页面
        print(f"\n→ 步骤 2: 跳转到 {EARN_URL}")
        await page.goto(EARN_URL, wait_until="domcontentloaded", timeout=60000)
        print("✓ 跳转完成")

        # 步骤 3: 初始按钮检查
        print("\n→ 步骤 3: 检查初始按钮状态")
        await check_button_and_solve_hcaptcha(page, max_retries=2)

        # 步骤 4: 开始领取
        print("\n→ 步骤 4: 开始自动领取")
        success = await click_claim_coins(page, max_attempts=15)

        if success:
            print("\n✅ 领取任务全部完成！")
        else:
            print("\n⚠️  领取任务未完成，请检查页面状态")

        print("\n→ 保持页面 30 秒...")
        await page.wait_for_timeout(30000)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
