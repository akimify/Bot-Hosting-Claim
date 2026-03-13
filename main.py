import os
import asyncio
import re
from playwright.async_api import async_playwright

# ===== 硬编码配置（调试用）=====
DISCORD_EMAIL    = "pungwing@milan.us.kg"
DISCORD_PASSWORD = "AkiRa13218*#"
GEMINI_API_KEY   = "AIzaSyCqzxNLEzc-EqQeqszIseKOweSaq-tn6fc"
PROXY_URL        = "socks5://127.0.0.1:1080"  # gost 本地转发端口

LOGIN_URL = "https://bot-hosting.net/login"
EARN_URL  = "https://bot-hosting.net/panel/earn"

ESSENTIAL_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
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
    print(f"\n→ 访问登录页: {LOGIN_URL}")
    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    print("✓ 登录页加载完成")

    print("→ 点击 Discord 登录按钮...")
    await page.click('a[href="/login/discord"]', timeout=10000)
    print("✓ 已点击")

    print("→ 等待跳转到 Discord 登录页...")
    await page.wait_for_url("**/discord.com/login**", timeout=30000)
    print(f"✓ 已到达: {page.url}")

    await page.wait_for_timeout(2000)

    print("→ 填入邮箱...")
    await page.wait_for_selector('input[name="email"]', timeout=15000)
    await page.fill('input[name="email"]', DISCORD_EMAIL)

    print("→ 填入密码...")
    await page.fill('input[name="password"]', DISCORD_PASSWORD)

    print("→ 点击登录...")
    await page.click('button[type="submit"]', timeout=10000)

    print("→ 等待登录响应...")
    try:
        await page.wait_for_url("**/discord.com/oauth2/authorize**", timeout=20000)
        print("✓ 已到达 OAuth 授权页")
    except Exception:
        url = page.url
        if "discord.com/login" in url:
            try:
                err = await page.locator('[class*="errorMessage"]').inner_text()
                print(f"❌ Discord 登录错误: {err}")
            except Exception:
                print("❌ 登录超时，可能触发了 2FA 或验证码")
            await page.screenshot(path="discord_login_fail.png")
            return False

    await page.wait_for_timeout(2000)

    # 处理授权页（可能有"继续滚动"服务条款）
    print("→ 处理 OAuth 授权页...")
    for i in range(5):
        try:
            btn = await page.wait_for_selector('button.primary_a22cb0', timeout=8000)
            btn_text = (await btn.inner_text()).strip()
            print(f"  当前按钮: '{btn_text}'")

            if "滚动" in btn_text or "scroll" in btn_text.lower():
                print("  → 滚动条款到底部...")
                await page.evaluate("""
                    var s = document.querySelector('[class*="scroller"]')
                        || document.querySelector('[class*="scrollerBase"]')
                        || document.querySelector('[class*="content"]');
                    if (s) s.scrollTop = s.scrollHeight;
                    window.scrollTo(0, document.body.scrollHeight);
                """)
                await page.wait_for_timeout(1500)
                await btn.click()
                print("  ✓ 已点击（滚动后）")
                await page.wait_for_timeout(1500)

            elif "授权" in btn_text or "authorize" in btn_text.lower():
                await btn.click()
                print("✓ 已点击授权按钮")
                break

            else:
                is_disabled = await btn.is_disabled()
                if not is_disabled:
                    await btn.click()
                    print(f"  ✓ 已点击: '{btn_text}'")
                    await page.wait_for_timeout(1500)
                else:
                    print(f"  ⚠️  按钮 disabled: '{btn_text}'")
                    break

        except Exception as e:
            print(f"  ℹ️  授权按钮处理结束: {e}")
            break

    print("→ 等待跳回 bot-hosting...")
    await page.wait_for_url("**/bot-hosting.net/**", timeout=30000)
    print(f"✓ 已跳回: {page.url}")

    await page.wait_for_timeout(3000)
    token = await page.evaluate("localStorage.getItem('token')")
    if token:
        print(f"✓ 登录成功！token 前20位: {str(token)[:20]}...")
        return True
    else:
        print("⚠️  未找到 token")
        await page.screenshot(path="no_token.png")
        return False

# ===== hCaptcha 处理 =====
async def solve_hcaptcha(page):
    try:
        from hcaptcha_challenger.agent import AgentV, AgentConfig
        from hcaptcha_challenger.models import CaptchaResponse

        os.environ["GEMINI_API_KEY"] = GEMINI_API_KEY

        CONFIGURED_MODEL = "gemini-2.5-flash-image"
        print(f"🛡️  使用模型: {CONFIGURED_MODEL}")

        agent_config = AgentConfig(model=CONFIGURED_MODEL)
        agent = AgentV(page=page, agent_config=agent_config)

        print("  → 点击 hcaptcha 复选框...")
        await agent.robotic_arm.click_checkbox()

        print("  → 等待挑战加载并自动解决...")
        await agent.wait_for_challenge()

        if agent.cr_list:
            cr: CaptchaResponse = agent.cr_list[-1]
            response_data = cr.model_dump(by_alias=True)
            print("  ✓ hCaptcha 验证成功！")
            print(f"    - success: {response_data.get('success', 'N/A')}")
            print(f"    - generated_pass_UUID: {str(response_data.get('generated_pass_UUID', 'N/A'))[:20]}...")
            return True
        else:
            print("  ℹ️  验证完成（无挑战响应）")
            return True

    except ImportError:
        print("⚠️  hcaptcha_challenger 未安装")
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
        print("  ✓ 弹窗已出现")
        await page.wait_for_timeout(1500)

        try:
            title = await page.locator('.swal-title').inner_text()
            text_content = await page.locator('.swal-text').inner_text()
            print(f"  弹窗内容: {title} | {text_content}")
            match = re.search(r'(\d+)\s*/\s*(\d+)', text_content)
            if match:
                claimed = int(match.group(1))
                total   = int(match.group(2))
                print(f"  📊 进度: {claimed}/{total}")
        except Exception as e:
            print(f"  ⚠️  无法解析弹窗文本: {e}")

        ok_button = await page.wait_for_selector('button.swal-button.swal-button--confirm', timeout=5000)
        if ok_button:
            await ok_button.click()
            print("  ✓ OK 已点击")
            await page.wait_for_timeout(2000)

        try:
            await page.wait_for_selector('.swal-modal', state='hidden', timeout=10000)
        except Exception:
            pass

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
        print(f"  ⚠️  弹窗处理失败: {type(e).__name__}: {e}")
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

            is_disabled  = await claim_button.is_disabled()
            button_text  = await claim_button.inner_text()
            print(f"  按钮: {'disabled' if is_disabled else 'enabled'} | '{button_text}'")

            if not is_disabled:
                print("  ✓ 按钮可用")
                return True

            if "complete the captcha" in button_text.lower():
                print("  ⚠️  需要 hCaptcha 验证")
                success = await solve_hcaptcha(page)
                if success:
                    await page.wait_for_timeout(3000)
                    claim_button = await page.query_selector(claim_button_selector)
                    if claim_button and not await claim_button.is_disabled():
                        print("  ✓ 按钮已可用")
                        return True
                    else:
                        print("  ℹ️  按钮仍为 disabled，继续重试...")
                else:
                    return False
            elif "you are on cooldown" in button_text.lower():
                print("  ⚠️  冷却中")
                return False
            else:
                return False

        except Exception as e:
            print(f"  ⚠️  检查按钮失败: {e}")
            return False

    print(f"  ⚠️  已达最大重试次数")
    return False

# ===== 点击领取按钮 =====
async def click_claim_coins(page, max_attempts=15):
    print(f"\n🎯 开始领取流程（最多 {max_attempts} 次）...")

    claim_button_selector = 'button.btn.green[type="submit"]'
    total_coins    = 10
    claimed_so_far = 0
    task_completed = False

    for attempt in range(1, max_attempts + 1):
        if task_completed:
            print(f"\n✅ 任务已完成（{claimed_so_far}/{total_coins}），退出")
            break

        print(f"\n{'='*50}")
        print(f"【尝试 {attempt}/{max_attempts} | 剩余: {max(0, total_coins - claimed_so_far)}】")
        print(f"{'='*50}")

        print("  → 清理残留弹窗...")
        await force_close_all_modals(page)

        print("  → 检查按钮状态...")
        button_ready = await check_button_and_solve_hcaptcha(page, max_retries=3)

        if not button_ready:
            try:
                claim_button = await page.query_selector(claim_button_selector)
                if claim_button:
                    button_text = await claim_button.inner_text()
                    if "you are on cooldown" in button_text.lower():
                        print("  → 冷却，等待 35 秒...")
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
            total_coins    = total
            remaining      = total - claimed
            print(f"  📊 进度: {claimed}/{total}（剩余 {remaining}）")
            if claimed >= total:
                print(f"\n🎉 已完成全部目标！({claimed}/{total})")
                task_completed = True
        else:
            print("  ⚠️  无法获取进度信息")

        await page.wait_for_timeout(1 * 1000 if task_completed else 10 * 1000)

    if task_completed or claimed_so_far >= total_coins:
        print(f"\n✅ 任务完成！最终进度: {claimed_so_far}/{total_coins}")
        return True
    else:
        print(f"\n⚠️  未达到目标（{claimed_so_far}/{total_coins}）")
        return False

# ===== 主流程 =====
async def main():
    proxy_config = parse_proxy(PROXY_URL)
    print(f"✓ 使用代理: {proxy_config['server'] if proxy_config else '无'}")

    # IP 出口检测
    import urllib.request
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"https": PROXY_URL, "http": PROXY_URL})
        )
        with opener.open("https://api.ipify.org", timeout=10) as resp:
            import re as _re
            ip_raw = resp.read().decode()
            ip_masked = _re.sub(r'(\d+\.\d+\.\d+\.)\d+', r'\1xx', ip_raw)
            print(f"🌐 出口 IP：{ip_masked}")
    except Exception as e:
        print(f"⚠️  IP 检测失败: {e}")

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
        if not await discord_login(page):
            print("❌ 登录失败，退出")
            await browser.close()
            return

        # 步骤 2: 跳转 earn 页
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
            print("\n⚠️  领取任务未完成")

        await page.screenshot(path="final_result.png")
        print("\n→ 保持页面 30 秒...")
        await page.wait_for_timeout(30000)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
