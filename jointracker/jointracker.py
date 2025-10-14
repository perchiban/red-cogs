import discord
from redbot.core import commands, Config
from datetime import datetime, timedelta
import pytz

class DailyJoinsTracker(commands.Cog):
    """Track daily member joins in a specific channel"""
    
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        
        # Ensure members intent is enabled
        if not self.bot.intents.members:
            print("[DailyJoinsTracker] WARNING: Members intent is not enabled!")
            print("[DailyJoinsTracker] To fix this, add to your bot's config or main file:")
            print("[DailyJoinsTracker] intents.members = True")
        self.config.register_guild(
            track_channel=None,
            join_count=0,
            last_joiner=None,
            last_join_message=0,
            message_template="{count} people joined today! Latest: {user}",
            timezone="UTC"
        )
    
    @commands.group()
    @commands.admin_or_permissions(manage_guild=True)
    async def jointracker(self, ctx):
        """Configure the daily joins tracker"""
        pass
    
    @jointracker.command()
    async def setchannel(self, ctx, channel: discord.TextChannel):
        """Set the channel where join counts will be posted"""
        await self.config.guild(ctx.guild).track_channel.set(channel.id)
        await ctx.send(f"✓ Join tracking channel set to {channel.mention}")
    
    @jointracker.command()
    async def settemplate(self, ctx, *, template: str):
        """
        Set custom message template for join count.
        
        Available placeholders:
        - {count}: Number of joins today
        - {user}: Mention of latest joiner
        - {user.name}: Latest joiner's name
        - {date}: Today's date
        
        Example: "{count} joins today! Welcome {user}! 🎉"
        """
        await self.config.guild(ctx.guild).message_template.set(template)
        await ctx.send(f"✓ Message template updated:\n`{template}`")
    
    @jointracker.command()
    async def settimezone(self, ctx, timezone: str):
        """
        Set timezone for daily reset (default: UTC).
        
        Common timezones: US/Eastern, US/Central, US/Mountain, US/Pacific,
        Europe/London, Europe/Paris, Asia/Tokyo, Australia/Sydney
        """
        try:
            pytz.timezone(timezone)
            await self.config.guild(ctx.guild).timezone.set(timezone)
            await ctx.send(f"✓ Timezone set to {timezone}")
        except pytz.exceptions.UnknownTimeZoneError:
            await ctx.send(f"❌ Unknown timezone: {timezone}")
    
    @jointracker.command()
    async def reset(self, ctx):
        """Manually reset the daily join counter"""
        await self.config.guild(ctx.guild).join_count.set(0)
        await self.config.guild(ctx.guild).last_joiner.set(None)
        await ctx.send("✓ Join counter reset")
    
    @jointracker.command()
    async def test(self, ctx):
        """Test the join tracker with a simulated join"""
        await self._update_join_message(ctx.guild, ctx.channel, ctx.author)
        await ctx.send("✓ Test message sent. Check the tracking channel!")
    
    @jointracker.command()
    async def status(self, ctx):
        """Show current join tracker status"""
        settings = await self.config.guild(ctx.guild).all()
        channel_id = settings["track_channel"]
        
        if not channel_id:
            await ctx.send("❌ No tracking channel set. Use `jointracker setchannel` first.")
            return
        
        channel = ctx.guild.get_channel(channel_id)
        template = settings["message_template"]
        timezone = settings["timezone"]
        count = settings["join_count"]
        
        embed = discord.Embed(title="Join Tracker Status", color=discord.Color.blue())
        embed.add_field(name="Channel", value=channel.mention if channel else "❌ Channel not found", inline=False)
        embed.add_field(name="Today's Joins", value=str(count), inline=False)
        embed.add_field(name="Message Template", value=f"`{template}`", inline=False)
        embed.add_field(name="Timezone", value=timezone, inline=False)
        await ctx.send(embed=embed)
    
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Track member joins"""
        guild = member.guild
        
        settings = await self.config.guild(guild).all()
        channel_id = settings["track_channel"]
        
        if not channel_id:
            return
        
        channel = guild.get_channel(channel_id)
        if not channel:
            return
        
        # Check if we need to reset (new day)
        tz = pytz.timezone(settings["timezone"])
        now = datetime.now(tz)
        
        # Try to get the last message to check its date
        await self._check_and_reset_if_needed(guild, channel, tz)
        
        # Increment counter and update joiner
        join_count = await self.config.guild(guild).join_count.get()
        join_count += 1
        await self.config.guild(guild).join_count.set(join_count)
        await self.config.guild(guild).last_joiner.set(member.id)
        
        # Update the message
        await self._update_join_message(guild, channel, member)
    
    async def _check_and_reset_if_needed(self, guild: discord.Guild, channel: discord.TextChannel, tz):
        """Check if we should reset the counter for a new day"""
        last_msg_id = await self.config.guild(guild).last_join_message()
        
        if not last_msg_id:
            return
        
        try:
            last_msg = await channel.fetch_message(last_msg_id)
            msg_date = last_msg.created_at.astimezone(tz).date()
            today = datetime.now(tz).date()
            
            if msg_date < today:
                # New day, reset counter
                await self.config.guild(guild).join_count.set(0)
                await self.config.guild(guild).last_joiner.set(None)
        except (discord.NotFound, discord.Forbidden):
            # Message was deleted or no permission
            pass
    
    async def _update_join_message(self, guild: discord.Guild, channel: discord.TextChannel, member: discord.Member):
        """Update or create the join count message"""
        settings = await self.config.guild(guild).all()
        template = settings["message_template"]
        count = settings["join_count"]
        
        # Format the message
        message_text = template.format(
            count=count,
            user=member.mention,
            **{"user.name": member.name, "date": datetime.now().strftime("%Y-%m-%d")}
        )
        
        last_msg_id = settings["last_join_message"]
        
        try:
            if last_msg_id:
                try:
                    last_msg = await channel.fetch_message(last_msg_id)
                    await last_msg.edit(content=message_text)
                    return
                except (discord.NotFound, discord.Forbidden):
                    pass
            
            # Create new message if old one doesn't exist
            new_msg = await channel.send(message_text)
            await self.config.guild(guild).last_join_message.set(new_msg.id)
        except discord.Forbidden:
            print(f"No permission to post in {channel} in {guild}")

async def setup(bot):
    await bot.add_cog(DailyJoinsTracker(bot))
