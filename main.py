"""
Bot Discord: /freeaccsteam + Xác minh thành viên
--------------------------------------------------
- User gõ lệnh /freeaccsteam -> bot tạo 1 KÊNH RIÊNG (chỉ user đó + admin thấy được)
- Trong kênh, bot gửi ngay nội dung: "NHẬN ACCSTEAM MIỄN PHÍ" kèm Tài khoản + Mật khẩu
- Tài khoản/Mật khẩu do CHỦ BOT tự đặt (dùng lệnh /setacc), bot không tự sinh
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

DATA_FILE = "ticket_data.json"  # lưu key hiện tại + lịch sử tạo ticket của user

# ====================== KHỞI TẠO ======================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"current_account": "CHƯA-CÓ-TÀI-KHOẢN", "current_password": "CHƯA-CÓ-MẬT-KHẨU", "last_ticket": {}}


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


# ---------- Lệnh admin: đổi tài khoản/mật khẩu hiện tại ----------
@bot.tree.command(name="setacc", description="(Admin) Đặt tài khoản + mật khẩu sẽ gửi cho user")
@app_commands.describe(account="Tài khoản muốn gửi cho user", password="Mật khẩu muốn gửi cho user")
@app_commands.default_permissions(administrator=True)
async def setacc(interaction: discord.Interaction, account: str, password: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Bạn không có quyền dùng lệnh này.", ephemeral=True)
        return
    data["current_account"] = account
    data["current_password"] = password
    save_data(data)
    await interaction.response.send_message(
        f"✅ Đã cập nhật:\nTài khoản: `{account}`\nMật khẩu: `{password}`", ephemeral=True
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

    await interaction.response.send_message("✅ Đang tạo ticket riêng cho bạn...", ephemeral=True)

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
            f"• **Tài khoản:** `{data['current_account']}`\n"
            f"• **Mật khẩu:** `{data['current_password']}`\n"
            f"• **Giới hạn:** 1 lượt / 24h\n\n"
            f"⚠️ Kênh này sẽ tự xóa sau **5 phút**."
        ),
        color=discord.Color.green(),
    )
    await ticket_channel.send(embed=info_embed)

    # Lên lịch tự xóa kênh sau 5 phút
    async def auto_delete():
        await asyncio.sleep(AUTO_DELETE_SECONDS)
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
