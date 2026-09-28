"""
Bot Discord: /freeaccsteam + Xác minh thành viên + THỐNG KÊ SERVER
-------------------------------------------------------------------
- /freeaccsteam  -> chọn game bằng menu thả xuống -> bot tạo kênh riêng gửi Tài khoản + Mật khẩu
- /setacc        -> (admin) đặt tài khoản/mật khẩu theo từng game
- Kênh ticket tự xóa sau 5 phút, mỗi user 1 lần / 24h (lưu file, không mất khi restart)
- /setupverify   -> (admin) đăng bảng nút "✅ Xác minh"
- /setupstats    -> (admin) TỰ TẠO mục "📊 THỐNG KÊ SERVER" gồm các kênh voice bị khóa:
                       ╔ Tổng thành viên / ╠ Bots / ╠ Đã xác minh / ╠ Acc đã phát / ╚ Ticket đang mở
                    Bot tự cập nhật số liệu mỗi 5 phút. Chạy lại /setupstats để tạo lại nếu lỡ xóa.

Cài đặt:  pip install -U discord.py
Chạy:     python bot.py
"""

import os
import json
import asyncio
import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

# ====================== CẤU HÌNH ======================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

# ID admin: điền ID USER hoặc ID ROLE, bot tự nhận diện cả 2.
ADMIN_IDS = {1548281829432365056, 987654321098765432}

# ID category chứa các kênh ticket (None nếu không cần)
TICKET_CATEGORY_ID = None

AUTO_DELETE_SECONDS = 5 * 60  # 5 phút

# Role gán sau khi bấm xác minh
VERIFY_ROLE_ID = 1548281835283292242

# Role tự gán cho người MỚI VÀO (None nếu không dùng)
UNVERIFIED_ROLE_ID = 1548621841495752785

GAME_LIST = [
    "Steam - How to Fish",
    "Steam - ARK Survival",
    "Steam - GTA V",
    "Steam - Red Dead 2",
    "Steam - Subnautica Below Zero",
]

# Kênh đăng đánh giá thật của khách (None nếu chưa dùng)
REVIEW_CHANNEL_ID = 1548281883580694579

# ---- THỐNG KÊ SERVER ----
STATS_CATEGORY_NAME = "📊 THỐNG KÊ SERVER"
# (khóa, mẫu tên kênh) - {} sẽ được thay bằng số. Muốn thêm/bớt dòng thì sửa ở đây.
STATS_DEFINITIONS = [
    ("total_members", "╔ Tổng thành viên: {}"),
    ("bots",          "╠ Bots: {}"),
    ("verified",      "╠ Đã xác minh: {}"),
    ("given",         "╠ Acc đã phát: {}"),
    ("active",        "╚ Ticket đang mở: {}"),
]
STATS_UPDATE_MINUTES = 5  # Discord giới hạn đổi tên kênh ~2 lần/10 phút, đừng để nhỏ hơn 5

DATA_FILE = "ticket_data.json"

# ====================== KHỞI TẠO ======================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
    else:
        loaded = {}
    loaded.setdefault("accounts", {})
    loaded.setdefault("last_ticket", {})
    loaded.setdefault("total_given", 0)
    loaded.setdefault("stats", {"guild_id": None, "channels": {}})
    return loaded


def save_data(d):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


data = load_data()

pending_reviews = {}   # {order_key: {"user_id":..., "game":...}}
active_tickets = 0     # số ticket đang mở (đếm trong bộ nhớ)


def get_account_for_game(game_name: str):
    return data["accounts"].get(game_name)


def get_last_ticket_time(user_id: int):
    ts = data["last_ticket"].get(str(user_id))
    return datetime.datetime.fromisoformat(ts) if ts else None


def set_last_ticket_time_now(user_id: int):
    data["last_ticket"][str(user_id)] = datetime.datetime.utcnow().isoformat()


def is_admin(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator:
        return True
    if interaction.user.id in ADMIN_IDS:
        return True
    return any(r.id in ADMIN_IDS for r in interaction.user.roles)


def fmt_num(n: int) -> str:
    return f"{n:,}".replace(",", ".")  # 2494 -> 2.494


# ====================== THỐNG KÊ SERVER ======================
def compute_stats(guild: discord.Guild) -> dict:
    verify_role = guild.get_role(VERIFY_ROLE_ID)
    return {
        "total_members": guild.member_count or len(guild.members),
        "bots": sum(1 for m in guild.members if m.bot),
        "verified": len(verify_role.members) if verify_role else 0,
        "given": data["total_given"],
        "active": active_tickets,
    }


def stats_name(key: str, value: int) -> str:
    template = dict(STATS_DEFINITIONS)[key]
    return template.format(fmt_num(value))


@tasks.loop(minutes=STATS_UPDATE_MINUTES)
async def update_stats():
    info = data.get("stats", {})
    guild = bot.get_guild(info.get("guild_id")) if info.get("guild_id") else None
    if guild is None:
        return
    values = compute_stats(guild)
    for key, channel_id in info.get("channels", {}).items():
        channel = guild.get_channel(channel_id)
        if channel is None or key not in values:
            continue
        new_name = stats_name(key, values[key])
        if channel.name != new_name:
            try:
                await channel.edit(name=new_name, reason="Cập nhật thống kê server")
            except discord.HTTPException as e:
                print(f"⚠️ Không đổi được tên kênh thống kê '{key}': {e}")


@bot.tree.command(name="setupstats", description="(Admin) Tự tạo mục THỐNG KÊ SERVER (các kênh voice khóa)")
@app_commands.default_permissions(administrator=True)
async def setupstats(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Bạn không có quyền dùng lệnh này.", ephemeral=True)
        return
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("Lệnh này chỉ dùng được trong server.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    # Xóa kênh thống kê cũ (nếu có) để tạo lại sạch sẽ
    old = data.get("stats", {})
    for channel_id in old.get("channels", {}).values():
        ch = guild.get_channel(channel_id)
        if ch:
            try:
                await ch.delete(reason="Tạo lại kênh thống kê")
            except discord.HTTPException:
                pass

    # Mọi người thấy nhưng KHÔNG vào (Connect) được -> có icon ổ khóa như ảnh mẫu
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=False),
    }
    bot_member = guild.me
    if bot_member:
        overwrites[bot_member] = discord.PermissionOverwrite(
            view_channel=True, connect=True, manage_channels=True
        )

    try:
        category = discord.utils.get(guild.categories, name=STATS_CATEGORY_NAME)
        if category is None:
            category = await guild.create_category(STATS_CATEGORY_NAME, overwrites=overwrites, position=0)
        else:
            await category.edit(overwrites=overwrites)

        values = compute_stats(guild)
        channels = {}
        for key, _template in STATS_DEFINITIONS:
            ch = await guild.create_voice_channel(
                name=stats_name(key, values[key]),
                category=category,
                overwrites=overwrites,
                reason="Tạo kênh thống kê server",
            )
            channels[key] = ch.id
    except discord.Forbidden:
        await interaction.followup.send(
            "❌ Bot thiếu quyền **Manage Channels**. Cấp quyền cho role của bot rồi chạy lại /setupstats.",
            ephemeral=True,
        )
        return

    data["stats"] = {"guild_id": guild.id, "channels": channels}
    save_data(data)
    await interaction.followup.send(
        f"✅ Đã tạo mục **{STATS_CATEGORY_NAME}** với {len(channels)} kênh. Số liệu tự cập nhật mỗi {STATS_UPDATE_MINUTES} phút.",
        ephemeral=True,
    )


# ====================== SỰ KIỆN ======================
@bot.event
async def on_member_join(member: discord.Member):
    if UNVERIFIED_ROLE_ID is None:
        return
    role = member.guild.get_role(UNVERIFIED_ROLE_ID)
    if role:
        try:
            await member.add_roles(role, reason="Tự động gán role chưa xác minh khi mới vào server")
        except discord.Forbidden:
            print("⚠️ Bot không có quyền gán UNVERIFIED_ROLE_ID. Kiểm tra vị trí role của bot.")


class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ Xác minh", style=discord.ButtonStyle.success, custom_id="verify_button")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        role = guild.get_role(VERIFY_ROLE_ID)

        if role is None:
            await interaction.response.send_message(
                "⚠️ Bot chưa được cấu hình đúng role xác minh, báo admin kiểm tra lại VERIFY_ROLE_ID.",
                ephemeral=True,
            )
            return

        if role in interaction.user.roles:
            await interaction.response.send_message("Bạn đã xác minh rồi, không cần bấm lại nữa!", ephemeral=True)
            return

        try:
            await interaction.user.add_roles(role, reason="Tự xác minh qua nút bấm")
            unverified = guild.get_role(UNVERIFIED_ROLE_ID) if UNVERIFIED_ROLE_ID else None
            if unverified and unverified in interaction.user.roles:
                await interaction.user.remove_roles(unverified, reason="Đã xác minh xong")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Bot không có quyền gán/xóa role này. Role của bot phải nằm CAO HƠN role xác minh và role chưa-xác-minh.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "✅ Xác minh thành công! Giờ bạn có thể xem các kênh khác trong server.", ephemeral=True
        )


@bot.event
async def on_ready():
    bot.add_view(VerifyView())
    await bot.tree.sync()
    if not update_stats.is_running():
        update_stats.start()
    print(f"✅ Bot đã đăng nhập với tên: {bot.user}")


# ====================== LỆNH ADMIN ======================
@bot.tree.command(name="setupverify", description="(Admin) Đăng bảng xác minh có nút bấm vào kênh này")
@app_commands.default_permissions(administrator=True)
async def setupverify(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Bạn không có quyền dùng lệnh này.", ephemeral=True)
        return

    embed = discord.Embed(
        title="🔒 Xác minh thành viên",
        description=(
            "Chào mừng bạn đến với server!\n\n"
            "Bấm nút **✅ Xác minh** bên dưới để mở khóa toàn bộ kênh chat trong server."
        ),
        color=discord.Color.blurple(),
    )
    await interaction.channel.send(embed=embed, view=VerifyView())
    await interaction.response.send_message("✅ Đã đăng bảng xác minh.", ephemeral=True)


@app_commands.choices(game=[app_commands.Choice(name=g, value=g) for g in GAME_LIST])
@bot.tree.command(name="setacc", description="(Admin) Đặt tài khoản + mật khẩu sẽ gửi cho user theo từng game")
@app_commands.describe(
    game="Game muốn cập nhật tài khoản", account="Tài khoản muốn gửi cho user", password="Mật khẩu muốn gửi cho user"
)
@app_commands.default_permissions(administrator=True)
async def setacc(interaction: discord.Interaction, game: app_commands.Choice[str], account: str, password: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Bạn không có quyền dùng lệnh này.", ephemeral=True)
        return
    data["accounts"][game.value] = {"account": account, "password": password}
    save_data(data)
    await interaction.response.send_message(
        f"✅ Đã cập nhật tài khoản cho **{game.value}**:\nTài khoản: `{account}`\nMật khẩu: `{password}`",
        ephemeral=True,
    )


@bot.tree.command(name="resetfreeaccsteam", description="(Admin) Reset lại giới hạn 24h của 1 user cho lệnh /freeaccsteam")
@app_commands.describe(user="User cần reset giới hạn")
@app_commands.default_permissions(administrator=True)
async def resetfreeaccsteam(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Bạn không có quyền dùng lệnh này.", ephemeral=True)
        return

    existed = str(user.id) in data["last_ticket"]
    data["last_ticket"].pop(str(user.id), None)
    save_data(data)

    if existed:
        await interaction.response.send_message(
            f"✅ Đã reset giới hạn 24h cho {user.mention}. User này có thể dùng /freeaccsteam lại ngay.",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            f"ℹ️ {user.mention} chưa từng tạo ticket, không có gì để reset.", ephemeral=True
        )


# ====================== ĐÁNH GIÁ ======================
class ReviewCommentModal(discord.ui.Modal, title="Cảm ơn bạn đã đánh giá!"):
    comment = discord.ui.TextInput(
        label="Nhận xét của bạn (có thể để trống)",
        placeholder="Ví dụ: Nhận acc nhanh, chạy tốt!",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=300,
    )

    def __init__(self, order_key: str, stars: int, rating_view: "RatingView"):
        super().__init__()
        self.order_key = order_key
        self.stars = stars
        self.rating_view = rating_view

    async def on_submit(self, interaction: discord.Interaction):
        pending = pending_reviews.pop(self.order_key, None)
        if pending is None:
            await interaction.response.send_message("Đơn này đã được đánh giá rồi.", ephemeral=True)
            return

        if REVIEW_CHANNEL_ID:
            review_channel = interaction.guild.get_channel(REVIEW_CHANNEL_ID)
            if review_channel:
                comment_text = self.comment.value.strip() or "_Không có nhận xét_"
                embed = discord.Embed(
                    description=(
                        f"**Product:** {pending['game']}\n"
                        f"**Rate:** {self.stars}/5 {'⭐' * self.stars}\n"
                        f"**Comment:** {comment_text}\n"
                        f"**Buyer:** {interaction.user.mention}"
                    ),
                    color=discord.Color.gold(),
                )
                await review_channel.send(embed=embed)

        for child in self.rating_view.children:
            child.disabled = True
            if isinstance(child, discord.ui.Button) and child.custom_id == f"rate_{self.order_key}_{self.stars}":
                child.style = discord.ButtonStyle.success
        await interaction.response.edit_message(content="✅ Cảm ơn bạn đã đánh giá!", view=self.rating_view)


class RatingView(discord.ui.View):
    def __init__(self, order_key: str, owner_id: int, game: str):
        super().__init__(timeout=None)
        self.order_key = order_key
        self.owner_id = owner_id
        for n in range(1, 6):
            self.add_item(self._make_button(n))

    def _make_button(self, n: int):
        button = discord.ui.Button(
            label="⭐" * n, style=discord.ButtonStyle.secondary, custom_id=f"rate_{self.order_key}_{n}"
        )

        async def callback(interaction: discord.Interaction, stars=n):
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message("Chỉ khách hàng của đơn này mới đánh giá được.", ephemeral=True)
                return
            if self.order_key not in pending_reviews:
                await interaction.response.send_message("Đơn này đã được đánh giá rồi.", ephemeral=True)
                return
            await interaction.response.send_modal(ReviewCommentModal(self.order_key, stars, self))

        button.callback = callback
        return button


# ====================== /freeaccsteam ======================
class GameSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=g, value=g) for g in GAME_LIST]
        super().__init__(placeholder="Chọn game bạn cần tài khoản...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        chosen_game = self.values[0]
        account_info = get_account_for_game(chosen_game)
        if account_info is None:
            await interaction.response.send_message(
                f"⚠️ Hiện chưa có tài khoản nào được cấu hình cho **{chosen_game}**. Báo admin dùng `/setacc` để thêm.",
                ephemeral=True,
            )
            return
        for item in self.view.children:
            item.disabled = True
        await interaction.response.edit_message(content=f"✅ Đang tạo ticket cho **{chosen_game}**...", view=self.view)
        await create_freeacc_ticket(interaction, chosen_game, account_info)


class GameSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(GameSelect())


@bot.tree.command(name="freeaccsteam", description="Tạo ticket riêng để nhận acc Steam miễn phí")
async def freeaccsteam(interaction: discord.Interaction):
    guild = interaction.guild
    user = interaction.user

    if guild is None:
        await interaction.response.send_message("Lệnh này chỉ dùng được trong server.", ephemeral=True)
        return

    last_time = get_last_ticket_time(user.id)
    if last_time is not None:
        elapsed = datetime.datetime.utcnow() - last_time
        if elapsed < datetime.timedelta(hours=24):
            remaining = datetime.timedelta(hours=24) - elapsed
            hours, remainder = divmod(int(remaining.total_seconds()), 3600)
            minutes = remainder // 60
            await interaction.response.send_message(
                f"⏳ Bạn cần đợi thêm khoảng {hours} giờ {minutes} phút nữa mới được tạo ticket tiếp theo.",
                ephemeral=True,
            )
            return

    await interaction.response.send_message(
        "Bạn cần tài khoản của game nào? Chọn ở menu bên dưới:", view=GameSelectView(), ephemeral=True
    )


async def create_freeacc_ticket(interaction: discord.Interaction, game_name: str, account_info: dict):
    global active_tickets
    guild = interaction.guild
    user = interaction.user

    everyone_role = guild.default_role
    overwrites = {}
    if everyone_role:
        overwrites[everyone_role] = discord.PermissionOverwrite(view_channel=False)
    overwrites[user] = discord.PermissionOverwrite(
        view_channel=True, send_messages=True, read_message_history=True
    )

    bot_member = guild.me or guild.get_member(bot.user.id)
    if bot_member:
        overwrites[bot_member] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_channels=True
        )

    for admin_id in ADMIN_IDS:
        admin_role = guild.get_role(admin_id)
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
            continue
        admin_member = guild.get_member(admin_id)
        if admin_member:
            overwrites[admin_member] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

    overwrites = {k: v for k, v in overwrites.items() if k is not None}

    category = guild.get_channel(TICKET_CATEGORY_ID) if TICKET_CATEGORY_ID else None

    channel_name = f"freeacc-{user.name}".lower().replace(" ", "-")[:90]
    try:
        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            overwrites=overwrites,
            category=category if isinstance(category, discord.CategoryChannel) else None,
            reason=f"Ticket freeaccsteam cho {user}",
        )
    except discord.Forbidden:
        await interaction.followup.send(
            "❌ Bot không có quyền tạo kênh. Cấp thêm quyền **Manage Channels** cho role của bot rồi thử lại.",
            ephemeral=True,
        )
        return

    # Đánh dấu lượt + tăng bộ đếm thống kê
    set_last_ticket_time_now(user.id)
    data["total_given"] += 1
    save_data(data)
    active_tickets += 1

    info_embed = discord.Embed(
        title="🎁 NHẬN ACCSTEAM MIỄN PHÍ",
        description=(
            f"Chào mừng {user.mention} Bạn đang thực hiện nhận Acc miễn phí.\n\n"
            f"📌 **Thông tin:**\n"
            f"• **Game:** `{game_name}`\n"
            f"• **Tài khoản:** `{account_info['account']}`\n"
            f"• **Mật khẩu:** `{account_info['password']}`\n"
            f"• **Giới hạn:** 1 lượt / 24h\n\n"
            f"⚠️ Kênh này sẽ tự xóa sau **5 phút**."
        ),
        color=discord.Color.green(),
    )
    await ticket_channel.send(embed=info_embed)

    order_key = f"{user.id}_{int(datetime.datetime.utcnow().timestamp())}"
    pending_reviews[order_key] = {"user_id": user.id, "game": game_name}
    rating_view = RatingView(order_key, user.id, game_name)
    await ticket_channel.send(
        content=f"{user.mention} Bạn đánh giá lượt nhận acc này bao nhiêu sao?",
        view=rating_view,
    )

    async def auto_delete():
        global active_tickets
        await asyncio.sleep(AUTO_DELETE_SECONDS)
        pending_reviews.pop(order_key, None)
        try:
            await ticket_channel.delete(reason="Tự động xóa ticket sau 5 phút")
        except discord.NotFound:
            pass
        finally:
            active_tickets = max(0, active_tickets - 1)

    bot.loop.create_task(auto_delete())


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("⚠️  Bạn chưa điền TOKEN. Đặt biến môi trường DISCORD_TOKEN (hoặc dán token vào DISCORD_TOKEN trong bot.py).")
    else:
        bot.run(DISCORD_TOKEN)
