import discord
from discord.ext import commands
import sqlite3
import os
import asyncio
import signal

TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
if not TOKEN:
    raise ValueError("Falta la variable de entorno DISCORD_BOT_TOKEN")

# IDs cargados desde variables de entorno
CANAL_PERMITIDO_ID = int(os.environ.get('CANAL_PERMITIDO_ID', '0'))
CANAL_STATUS_ID    = int(os.environ.get('CANAL_STATUS_ID', '0'))
CANAL_INFO_ID      = os.environ.get('CANAL_INFO_ID', '0')
ARCHIVO_DB = os.path.join(os.path.dirname(__file__), 'tickets.db')

# Configuración de roles de staff por servidor
# Servidor 1: rol identificado por nombre
# Servidor 2: rol identificado por ID
SERVER_CONFIG = {
    int(os.environ.get('CANAL_PERMITIDO_ID', '0')): {
        'rol_nombre': os.environ.get('ROL_STAFF_S1_NOMBRE', 'Director Junior'),
        'rol_id': None
    },
    int(os.environ.get('CANAL_S2_ID', '0')): {
        'rol_nombre': None,
        'rol_id': int(os.environ.get('ROL_STAFF_S2_ID', '0')) or None
    },
}

CANALES_PERMITIDOS = list(SERVER_CONFIG.keys())

def obtener_rol_staff(guild):
    for canal_id, config in SERVER_CONFIG.items():
        if guild.get_channel(canal_id):
            if config['rol_id']:
                return guild.get_role(config['rol_id'])
            elif config['rol_nombre']:
                return discord.utils.get(guild.roles, name=config['rol_nombre'])
    return None

def tiene_rol_staff(member, guild):
    rol = obtener_rol_staff(guild)
    return rol is not None and rol in member.roles

def iniciar_db():
    conexion = sqlite3.connect(ARCHIVO_DB)
    cursor = conexion.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS contador_tickets (id INTEGER PRIMARY KEY, numero INTEGER)''')
    cursor.execute('SELECT numero FROM contador_tickets WHERE id = 1')
    if cursor.fetchone() is None:
        cursor.execute('INSERT INTO contador_tickets (id, numero) VALUES (1, 0)')
    conexion.commit()
    conexion.close()
iniciar_db()

class TicketBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        loop = asyncio.get_event_loop()
        loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(self.apagado_silencioso()))

    async def apagado_silencioso(self):
        print("SIGTERM recibido, apagando silenciosamente...")
        try:
            canal_status = self.get_channel(CANAL_STATUS_ID)
            if canal_status:
                async for msg in canal_status.history(limit=20):
                    if msg.author == self.user and "online" in msg.content.lower():
                        try:
                            await msg.delete()
                        except discord.Forbidden:
                            pass
                await canal_status.send(
                    f"# EL BOT JUNIOR TICKET ESTA OFFLINE\n\n"
                    f"**Durante el tiempo que el bot este offline no puedes hacer tickets, "
                    f"tendrás que esperar hasta que vuelva a estar online 📋 **\n\n"
                    f"**De igual forma infórmate como es el procedimiento de tickets en **<#{CANAL_INFO_ID}>\n@everyone"
                )

            canal_ticket = self.get_channel(CANAL_PERMITIDO_ID)
            if canal_ticket:
                overwrites_everyone = canal_ticket.overwrites_for(canal_ticket.guild.default_role)
                overwrites_everyone.send_messages = False
                await canal_ticket.set_permissions(canal_ticket.guild.default_role, overwrite=overwrites_everyone)
        except Exception as e:
            print(f"Error durante apagado: {e}")
        finally:
            await self.close()

    async def on_ready(self):
        print(f'Logueado como {self.user}')
        canal_status = self.get_channel(CANAL_STATUS_ID)
        if canal_status:
            async for msg in canal_status.history(limit=20):
                if msg.author == self.user and "offline" in msg.content.lower():
                    try:
                        await msg.delete()
                    except discord.Forbidden:
                        pass
            await canal_status.send(
                f"# EL BOT JUNIOR TICKET ESTA ONLINE\n\n"
                f"**Ya puedes hacer tickets ✅ **\n\n"
                f"**Y si no sabes como hacerlos aun, ve al canal de** <#{CANAL_INFO_ID}>\n@everyone"
            )

        canal_ticket = self.get_channel(CANAL_PERMITIDO_ID)
        if canal_ticket:
            overwrites = canal_ticket.overwrites_for(canal_ticket.guild.default_role)
            overwrites.send_messages = None
            await canal_ticket.set_permissions(canal_ticket.guild.default_role, overwrite=overwrites)

bot = TicketBot()

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if message.channel.id == CANAL_PERMITIDO_ID:
        if not tiene_rol_staff(message.author, message.guild):
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            return
    await bot.process_commands(message)

def obtener_numero_ticket():
    conexion = sqlite3.connect(ARCHIVO_DB)
    cursor = conexion.cursor()
    cursor.execute('SELECT numero FROM contador_tickets WHERE id = 1')
    numero_actual = cursor.fetchone()[0]
    nuevo_numero = numero_actual + 1
    cursor.execute('UPDATE contador_tickets SET numero = ? WHERE id = 1', (nuevo_numero,))
    conexion.commit()
    conexion.close()
    return nuevo_numero

@bot.tree.command(name="ticket", description="Crea un canal de ticket")
async def ticket(interaction: discord.Interaction):
    if interaction.channel_id not in CANALES_PERMITIDOS:
        canal_correcto = None
        for canal_id in CANALES_PERMITIDOS:
            canal = interaction.guild.get_channel(canal_id)
            if canal:
                canal_correcto = canal
                break

        if canal_correcto:
            await interaction.response.send_message(
                f"No puedes usar este comando aquí. Dirígete a {canal_correcto.mention}.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "No puedes usar este comando aquí.",
                ephemeral=True
            )
        return

    numero = obtener_numero_ticket()
    nombre_canal = f"ticket-{numero}"
    categoria = interaction.channel.category
    guild = interaction.guild

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }

    rol_staff = obtener_rol_staff(guild)
    if rol_staff:
        overwrites[rol_staff] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    nuevo_canal = await guild.create_text_channel(
        name=nombre_canal,
        category=categoria,
        overwrites=overwrites
    )

    await interaction.response.send_message(f"Dirígete a {nuevo_canal.mention}", ephemeral=True)
    await nuevo_canal.send("Espera a que un staff te atienda. Gracias.")

@bot.tree.command(name="cerrarticket", description="Elimina el canal de ticket actual")
async def cerrarticket(interaction: discord.Interaction):
    if not tiene_rol_staff(interaction.user, interaction.guild):
        await interaction.response.send_message("No tienes permisos para cerrar este ticket.", ephemeral=True)
        return

    if interaction.channel.name.startswith("ticket-"):
        await interaction.response.send_message("Cerrando ticket...", ephemeral=True)
        await interaction.channel.delete()
    else:
        await interaction.response.send_message("Este comando solo funciona dentro de un ticket.", ephemeral=True)

bot.run(TOKEN)
