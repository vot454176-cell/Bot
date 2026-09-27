"""
Bot Discord: /freeaccsteam + Xác minh thành viên
--------------------------------------------------
- User gõ lệnh /freeaccsteam -> bot hỏi "cần tài khoản game gì" qua MENU THẢ XUỐNG (GAME_LIST)
- Sau khi chọn game, bot tạo 1 KÊNH RIÊNG (chỉ user đó + admin thấy được)
- Trong kênh, bot gửi ngay nội dung: "NHẬN ACCSTEAM MIỄN PHÍ" kèm Tài khoản + Mật khẩu của đúng game đã chọn
- Tài khoản/Mật khẩu do CHỦ BOT tự đặt THEO TỪNG GAME (dùng lệnh /setacc), bot không tự sinh
- Kênh ticket TỰ XÓA sau 5 phút kể từ lúc tạo
- Mỗi user chỉ được tạo ticket 1 LẦN / 24H (lưu vào file để không mất khi restart bot)
- /setupverify (admin) đăng bảng có nút "✅ Xác minh" -> user bấm vào sẽ được gán role,
  đồng thời TỰ ĐỘNG XÓA role "chưa xác minh" cũ (nếu có cấu hình UNVERIFIED_ROLE_ID),
  mở khóa các kênh chat khác (phần ẩn kênh với @everyone cần tự cấu hình trong Server Settings)

Cài đặt:
    pip install -U discord.py

Chạy:
    python bot.py

Trước khi chạy, xem phần CẤU HÌNH bên dưới để điền TOKEN, ROLE ADMIN, ảnh, v.v.
"""

import os
import json
import asyncio
import datetime

import discord
from discord import app_commands
from discord.ext import commands

# ====================== CẤU HÌNH ======================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

# ID admin: có thể điền ID CỦA USER (tài khoản Discord) hoặc ID CỦA ROLE, bot tự nhận diện được cả 2.
# Muốn thêm nhiều admin thì thêm nhiều ID vào trong dấu {}, cách nhau bằng dấu phẩy.
ADMIN_IDS = {1548281829432365056, 987654321098765432}

# ID category để chứa các kênh ticket (để trống None nếu không cần category riêng)
TICKET_CATEGORY_ID = None  # vd: 123456789012345678

AUTO_DELETE_SECONDS = 5 * 60  # 5 phút

# ID role sẽ được gán cho user sau khi bấm nút xác minh (chuột phải role -> Copy ID)
VERIFY_ROLE_ID = 1548281835283292242    # <-- đổi thành ID role "Member đã xác minh" của bạn

# ID role tự động gán cho user MỚI VÀO server (vd "Chưa xác minh").
# Để None nếu không cần bước này (không tự gán role khi vào, không tự xóa role gì khi xác minh).
UNVERIFIED_ROLE_ID = 1548621841495752785  # <-- đổi thành ID role "Chưa xác minh", hoặc để None nếu không dùng

# Danh sách game cố định hiển thị trong menu thả xuống của /freeaccsteam.
# Thêm/bớt/sửa tên tuỳ ý, tối đa 25 dòng (giới hạn của Discord select menu).
GAME_LIST = [
    "Steam - How to Fish ",
    "Steam - ARK Survival",
    "Steam - GTA V",
    "Steam - NARAKA",
]

# ID kênh sẽ đăng đánh giá THẬT của khách sau khi họ tự bấm sao (để None nếu chưa dùng tính năng này)
REVIEW_CHANNEL_ID = 1548281883580694579  # <-- đổi thành ID kênh review của bạn

DATA_FILE = "ticket_data.json"  # lưu key hiện tại + lịch sử tạo ticket của user

# ====================== KHỞI TẠO ======================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
            loaded.setdefault("accounts", {})  # {"Tên game": {"account": ..., "password": ...}}
            return loaded
    return {"accounts": {}, "last_ticket": {}}


def get_account_for_game(game_name: str):
    return data["accounts"].get(game_name)  # None nếu admin chưa /setacc cho game này


# Lưu tạm các đơn đang chờ khách bấm đánh giá: {order_key: {"user_id": ..., "game": ...}}
# Chỉ cần tồn tại trong bộ nhớ vì vòng đời ticket rất ngắn (AUTO_DELETE_SECONDS).
pending_reviews = {}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


data = load_data()


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


@bot.event
async def on_member_join(member: discord.Member):
    """Tự động gán role 'Chưa xác minh' cho user mới vào server (nếu có cấu hình)."""
    if UNVERIFIED_ROLE_ID is None:
        return
    role = member.guild.get_role(UNVERIFIED_ROLE_ID)
    if role:
        try:
            await member.add_roles(role, reason="Tự động gán role chưa xác minh khi mới vào server")
        except discord.Forbidden:
            print("⚠️ Bot không có quyền gán UNVERIFIED_ROLE_ID cho thành viên mới. Kiểm tra vị trí role bot.")


# ---------- Nút bấm xác minh ----------
class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # timeout=None để nút không bao giờ hết hạn, kể cả khi bot restart

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

            # Nếu có cấu hình role "chưa xác minh", xóa role đó đi sau khi xác minh xong
            if UNVERIFY_ROLE := (guild.get_role(UNVERIFIED_ROLE_ID) if UNVERIFIED_ROLE_ID else None):
                if UNVERIFY_ROLE in interaction.user.roles:
                    await interaction.user.remove_roles(UNVERIFY_ROLE, reason="Đã xác minh xong")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Bot không có quyền gán/xóa role này. Báo admin kiểm tra: role bot phải nằm CAO HƠN role xác minh và role chưa-xác-minh trong danh sách Roles.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "✅ Xác minh thành công! Giờ bạn có thể xem các kênh khác trong server.", ephemeral=True
        )


@bot.event
async def on_ready():
    bot.add_view(VerifyView())  # đăng ký lại nút để nó vẫn hoạt động sau khi bot restart
    await bot.tree.sync()
    print(f"✅ Bot đã đăng nhập với tên: {bot.user}")


# ---------- Lệnh admin: đăng bảng xác minh vào kênh hiện tại ----------
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


# ---------- Lệnh admin: đổi tài khoản/mật khẩu cho 1 game cụ thể ----------
@app_commands.choices(
    game=[app_commands.Choice(name=g, value=g) for g in GAME_LIST]
)
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


# ---------- Lệnh admin: reset giới hạn 24h cho 1 user ----------
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


# ---------- Popup xin nhận xét sau khi khách đã chọn số sao ----------
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

        # Khoá các nút sao trên tin nhắn gốc, không cho bấm lại
        for child in self.rating_view.children:
            child.disabled = True
            if isinstance(child, discord.ui.Button) and child.custom_id == f"rate_{self.order_key}_{self.stars}":
                child.style = discord.ButtonStyle.success
        await interaction.response.edit_message(content="✅ Cảm ơn bạn đã đánh giá!", view=self.rating_view)


# ---------- 5 nút sao để khách tự đánh giá thật ----------
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


# ---------- Dropdown chọn game trước khi tạo ticket ----------
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
        # Chặn double-submit nếu user bấm chọn 2 lần liên tiếp
        for item in self.view.children:
            item.disabled = True
        await interaction.response.edit_message(content=f"✅ Đang tạo ticket cho **{chosen_game}**...", view=self.view)
        await create_freeacc_ticket(interaction, chosen_game, account_info)


class GameSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(GameSelect())


# ---------- Lệnh chính: tạo ticket nhận key ----------
@bot.tree.command(name="freeaccsteam", description="Tạo ticket riêng để nhận key miễn phí")
async def freeaccsteam(interaction: discord.Interaction):
    guild = interaction.guild
    user = interaction.user

    if guild is None:
        await interaction.response.send_message("Lệnh này chỉ dùng được trong server.", ephemeral=True)
        return

    # Kiểm tra giới hạn 1 lần / 24 giờ
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
    guild = interaction.guild
    user = interaction.user

    # Quyền: chỉ user này + admin role thấy được kênh
    everyone_role = guild.default_role
    if everyone_role is None:
        try:
            roles = await guild.fetch_roles()
            everyone_role = discord.utils.get(roles, id=guild.id)
        except discord.HTTPException:
            everyone_role = None

    overwrites = {}
    if everyone_role:
        overwrites[everyone_role] = discord.PermissionOverwrite(view_channel=False)
    overwrites[user] = discord.PermissionOverwrite(
        view_channel=True, send_messages=True, read_message_history=True
    )

    bot_member = guild.me or guild.get_member(bot.user.id)
    if bot_member is None:
        try:
            bot_member = await guild.fetch_member(bot.user.id)
        except discord.HTTPException:
            bot_member = None
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

    # An toàn: loại bỏ bất kỳ key nào lỡ bị None để không bao giờ crash ở bước tạo kênh
    removed_none = any(k is None for k in overwrites.keys())
    overwrites = {k: v for k, v in overwrites.items() if k is not None}
    if removed_none:
        print("⚠️ Cảnh báo: có 1 quyền (overwrite) bị None và đã được bỏ qua khi tạo kênh ticket.")

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
            "❌ Bot không có quyền tạo kênh. Vào server, cấp thêm quyền **Manage Channels** cho role của bot rồi thử lại.",
            ephemeral=True,
        )
        return

    # Đánh dấu user đã tạo ticket NGAY khi tạo kênh (chống spam bấm nhiều lần)
    set_last_ticket_time_now(user.id)
    save_data(data)

    # Gửi nội dung nhận acc
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

    # Mời khách tự bấm sao đánh giá thật (chỉ đúng người nhận acc mới bấm được)
    order_key = f"{user.id}_{int(datetime.datetime.utcnow().timestamp())}"
    pending_reviews[order_key] = {"user_id": user.id, "game": game_name}
    rating_view = RatingView(order_key, user.id, game_name)
    await ticket_channel.send(
        content=f"{user.mention} Bạn đánh giá lượt nhận acc này bao nhiêu sao?",
        view=rating_view,
    )

    # Lên lịch tự xóa kênh sau 5 phút
    async def auto_delete():
        await asyncio.sleep(AUTO_DELETE_SECONDS)
        pending_reviews.pop(order_key, None)  # hết hạn thì thôi, không ép khách đánh giá
        try:
            await ticket_channel.delete(reason="Tự động xóa ticket sau 5 phút")
        except discord.NotFound:
            pass

    bot.loop.create_task(auto_delete())


if __name__ == "__main__":
    if DISCORD_TOKEN == "DÁN_TOKEN_CỦA_BẠN_VÀO_ĐÂY":
        print("⚠️  Bạn chưa điền TOKEN. Mở file bot.py và dán token vào biến DISCORD_TOKEN.")
    else:
        bot.run(DISCORD_TOKEN)
