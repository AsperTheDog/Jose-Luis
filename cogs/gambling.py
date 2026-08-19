import random
import sqlite3
import discord
from discord import app_commands
from discord.ext import commands

DB_PATH = "bot_data.db"



class GamblingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot



async def setup(bot: commands.Bot):
    await bot.add_cog(GamblingCog(bot))