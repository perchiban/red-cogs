import discord
import asyncio
import random
import json
from datetime import datetime, timedelta
from redbot.core import commands, Config
from typing import Optional
from pathlib import Path
from redbot.core.data_manager import cog_data_path

class Lottery(commands.Cog):
    """A lottery system with referral integration and result logging."""
    
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567891, force_registration=True)
        default_guild = {
            "active_lotteries": {},
            "completed_lotteries": {},
            "log_channel": None,
            "referrals_per_entry": 5  # Default: 5 referrals = 1 extra entry
        }
        self.config.register_guild(**default_guild)
        
        # Create logs directory if it doesn't exist
        self.logs_dir = cog_data_path(self) / "lottery_logs"
        self.logs_dir.mkdir(exist_ok=True)
    
    @commands.group(name="lotteryconfig")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def lottery_config(self, ctx):
        """Configure lottery settings."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)
    
    @lottery_config.command(name="logchannel")
    async def set_log_channel(self, ctx, channel: discord.TextChannel):
        """Set the channel where lottery results will be logged."""
        await self.config.guild(ctx.guild).log_channel.set(channel.id)
        await ctx.send(f"✅ Lottery results will now be logged to {channel.mention}")
    
    @lottery_config.command(name="referralrate")
    async def set_referral_rate(self, ctx, count: int):
        """Set how many referrals equal one extra entry (default: 5)."""
        if count <= 0:
            await ctx.send("❌ Referral count must be a positive number.")
            return
        
        await self.config.guild(ctx.guild).referrals_per_entry.set(count)
        await ctx.send(f"✅ Set to {count} referrals per extra entry.")
    
    @lottery_config.command(name="view")
    async def view_config(self, ctx):
        """View current lottery configuration."""
        log_channel_id = await self.config.guild(ctx.guild).log_channel()
        referrals_per_entry = await self.config.guild(ctx.guild).referrals_per_entry()
        
        log_channel = ctx.guild.get_channel(log_channel_id) if log_channel_id else None
        
        embed = discord.Embed(
            title="⚙️ Lottery Configuration",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Log Channel",
            value=log_channel.mention if log_channel else "Not set",
            inline=False
        )
        embed.add_field(
            name="Referrals Per Entry",
            value=f"{referrals_per_entry} referrals = 1 extra entry",
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def lottery(
        self, 
        ctx, 
        channel: discord.TextChannel,
        duration: int,
        use_referrals: bool,
        name: str,
        emoji: str = "🎟️",
        *,
        description: str = "React to enter the lottery!"
    ):
        """
        Start a lottery that automatically draws a winner.
        
        Parameters:
        - channel: The channel where the lottery will be posted
        - duration: Duration in minutes until the winner is drawn
        - use_referrals: true/false - Enable referral bonus entries
        - name: Unique name for this lottery (used for reruns and logging)
        - emoji: The emoji to use for reactions (default: 🎟️)
        - description: Custom description for what the lottery is about
        
        Example:
        [p]lottery #general 60 true VIP_Giveaway 🎲 Win a VIP role!
        """
        
        if duration <= 0:
            await ctx.send("❌ Duration must be a positive number of minutes.")
            return
        
        # Check if name is already used
        completed = await self.config.guild(ctx.guild).completed_lotteries()
        active = await self.config.guild(ctx.guild).active_lotteries()
        
        if name in completed or name in active:
            await ctx.send(f"❌ A lottery with the name '{name}' already exists. Please choose a unique name.")
            return
        
        # Calculate end time
        end_time = discord.utils.utcnow() + timedelta(minutes=duration)
        end_timestamp = int(end_time.timestamp())
        start_timestamp = int(discord.utils.utcnow().timestamp())
        
        # Create initial embed
        embed = discord.Embed(
            title="🎰 Sorteo Abierto!",
            description=f"{description}\n\nReacciona con {emoji} abajo para participar!",
            color=0xF1C40F,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(
            name="📋 Como participo?",
            value=f"Simplemente reacciona con {emoji} a este mensaje",
            inline=False
        )
        
        if use_referrals:
            referrals_per_entry = await self.config.guild(ctx.guild).referrals_per_entry()
            embed.add_field(
                name="🎁 Oportunidades Extra",
                value=f"1 ticket extra otorgado por cada {referrals_per_entry} personas invitadas DESPUES del inicio de la loteria!",
                inline=False
            )
        
        embed.add_field(
            name="⏰ Finalizacion del sorteo",
            value=f"<t:{end_timestamp}:R> (<t:{end_timestamp}:F>)",
            inline=False
        )
        
        # Send the lottery message
        try:
            lottery_message = await channel.send(embed=embed)
            await lottery_message.add_reaction(emoji)
        except discord.Forbidden:
            await ctx.send(f"❌ I don't have permission to send messages in {channel.mention}")
            return
        except discord.HTTPException:
            await ctx.send("❌ Failed to create lottery. The emoji might be invalid.")
            return
        
        # Store lottery data
        lottery_data = {
            "message_id": lottery_message.id,
            "channel_id": channel.id,
            "emoji": emoji,
            "use_referrals": use_referrals,
            "start_time": start_timestamp,
            "end_time": end_timestamp,
            "starter_id": ctx.author.id,
            "name": name,
            "description": description
        }
        
        async with self.config.guild(ctx.guild).active_lotteries() as active_lotteries:
            active_lotteries[name] = lottery_data
        
        await ctx.send(f"✅ Lottery '{name}' created in {channel.mention}! Winner will be drawn in {duration} minutes.")
        
        # Schedule the winner drawing
        await self._schedule_draw(ctx.guild, name)
    
    async def _get_referral_cog(self):
        """Get the ReferralSystem cog if available."""
        return self.bot.get_cog("ReferralSystem")
    
    async def _calculate_entries(self, guild: discord.Guild, participants: list, start_time: int, use_referrals: bool):
        """Calculate entries for each participant based on referrals since start_time."""
        entries_map = {}  # {user_id: entry_count}
        
        if not use_referrals:
            # Everyone gets 1 entry
            for user in participants:
                entries_map[user.id] = 1
            return entries_map
        
        # Get referral cog
        referral_cog = await self._get_referral_cog()
        if not referral_cog:
            # Referrals requested but cog not available, give everyone 1 entry
            for user in participants:
                entries_map[user.id] = 1
            return entries_map
        
        # Get referral data
        referral_config = referral_cog.config.guild(guild)
        referrals_data = await referral_config.referrals()
        referrals_per_entry = await self.config.guild(guild).referrals_per_entry()
        
        for user in participants:
            # Base entry
            entries = 1
            
            # Count referrals made after lottery started
            referral_count = 0
            for invited_user_id, inviter_id in referrals_data.items():
                if inviter_id == user.id:
                    # Check if this user joined after lottery started
                    invited_member = guild.get_member(int(invited_user_id))
                    if invited_member and invited_member.joined_at:
                        join_timestamp = int(invited_member.joined_at.timestamp())
                        if join_timestamp >= start_time:
                            referral_count += 1
            
            # Calculate bonus entries
            bonus_entries = referral_count // referrals_per_entry
            entries += bonus_entries
            
            entries_map[user.id] = entries
        
        return entries_map
    
    async def _schedule_draw(self, guild: discord.Guild, lottery_name: str):
        """Schedule and execute the lottery drawing."""
        
        # Get lottery data
        active_lotteries = await self.config.guild(guild).active_lotteries()
        lottery_data = active_lotteries.get(lottery_name)
        
        if not lottery_data:
            return
        
        duration_seconds = lottery_data["end_time"] - lottery_data["start_time"]
        
        # Wait for the duration
        await asyncio.sleep(duration_seconds)
        
        # Execute the draw
        await self._execute_draw(guild, lottery_name, is_rerun=False)
    
    async def _execute_draw(self, guild: discord.Guild, lottery_name: str, is_rerun: bool = False):
        """Execute the lottery drawing."""
        
        # Get lottery data
        if is_rerun:
            completed_lotteries = await self.config.guild(guild).completed_lotteries()
            lottery_data = completed_lotteries.get(lottery_name)
            source = "completed"
        else:
            active_lotteries = await self.config.guild(guild).active_lotteries()
            lottery_data = active_lotteries.get(lottery_name)
            source = "active"
        
        if not lottery_data:
            return
        
        channel = guild.get_channel(lottery_data["channel_id"])
        if not channel:
            return
        
        try:
            # Fetch the message
            message = await channel.fetch_message(lottery_data["message_id"])
            
            # Find the target reaction
            target_reaction = None
            emoji = lottery_data["emoji"]
            for reaction in message.reactions:
                if str(reaction.emoji) == emoji:
                    target_reaction = reaction
                    break
            
            if not target_reaction:
                if not is_rerun:
                    embed = discord.Embed(
                        title="🎰 El sorteo ha finalizado!",
                        description="Ningun participante ha entrado al sorteo.",
                        color=0xE74C3C,
                        timestamp=discord.utils.utcnow()
                    )
                    embed.set_footer(text="Suerte para la proxima!")
                    await message.edit(embed=embed)
                    await self._move_to_completed(guild, lottery_name)
                return
            
            # Get users who reacted (excluding bots)
            participants = []
            async for user in target_reaction.users():
                if not user.bot:
                    participants.append(user)
            
            if not participants:
                if not is_rerun:
                    embed = discord.Embed(
                        title="🎰 El sorteo ha finalizado",
                        description="Ningun participante ha entrado al sorteo.",
                        color=0xE74C3C,
                        timestamp=discord.utils.utcnow()
                    )
                    embed.set_footer(text="Suerte para la proxima!")
                    await message.edit(embed=embed)
                    await self._move_to_completed(guild, lottery_name)
                return
            
            # Calculate entries based on referrals
            entries_map = await self._calculate_entries(
                guild, 
                participants, 
                lottery_data["start_time"], 
                lottery_data["use_referrals"]
            )
            
            # Create weighted pool
            weighted_participants = []
            for user in participants:
                entry_count = entries_map.get(user.id, 1)
                weighted_participants.extend([user] * entry_count)
            
            # Pick random winner
            winner = random.choice(weighted_participants)
            winner_entries = entries_map.get(winner.id, 1)
            
            # Store draw results
            draw_results = {
                "winner_id": winner.id,
                "winner_name": str(winner),
                "total_participants": len(participants),
                "total_entries": len(weighted_participants),
                "entries_breakdown": {str(user.id): entries_map[user.id] for user in participants},
                "draw_timestamp": int(discord.utils.utcnow().timestamp())
            }
            
            # Save to file (only if not rerun)
            if not is_rerun:
                await self._log_results(guild, lottery_name, lottery_data, draw_results)
                await self._move_to_completed(guild, lottery_name, draw_results)
            
            # Create winner announcement embed
            starter = guild.get_member(lottery_data["starter_id"])
            embed = discord.Embed(
                title="🎊 Ganador del sorteo!" + (" (RERUN)" if is_rerun else ""),
                description=f"**Felicidades a {winner.mention}!**\n\nGanaste el sorteo!",
                color=0x2ECC71 if not is_rerun else 0x3498DB,
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(
                name="📊 Total de participantes",
                value=str(len(participants)),
                inline=True
            )
            embed.add_field(
                name="🎟️ Total de tickets",
                value=str(len(weighted_participants)),
                inline=True
            )
            embed.add_field(
                name="🏆 Ganador",
                value=winner.mention,
                inline=True
            )
            embed.add_field(
                name="🎯 Tickets del ganador",
                value=str(winner_entries),
                inline=True
            )
            embed.set_thumbnail(url=winner.display_avatar.url)
            
            if starter:
                embed.set_footer(text=f"Empezado por {starter} | Gracias a todos los participantes!")
            
            # Edit or send message
            if is_rerun:
                await channel.send(f"🔄 **RERUN RESULTS for '{lottery_name}'**", embed=embed)
            else:
                await message.edit(embed=embed)
                await channel.send(f"🎉 {winner.mention} ha ganado el sorteo!")
            
        except discord.NotFound:
            pass
        except discord.Forbidden:
            pass
        except Exception as e:
            print(f"Error in lottery draw: {e}")
    
    async def _log_results(self, guild: discord.Guild, lottery_name: str, lottery_data: dict, draw_results: dict):
        """Log lottery results to file and channel."""
        
        # Create log entry
        log_entry = {
            "lottery_name": lottery_name,
            "lottery_data": lottery_data,
            "draw_results": draw_results,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Save to file
        log_file = self.logs_dir / f"{guild.id}_{lottery_name}.txt"
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(log_entry, f, indent=2, ensure_ascii=False)
        
        # Send to log channel if configured
        log_channel_id = await self.config.guild(guild).log_channel()
        if log_channel_id:
            log_channel = guild.get_channel(log_channel_id)
            if log_channel:
                try:
                    # Create detailed breakdown
                    breakdown_lines = []
                    for user_id, entries in draw_results["entries_breakdown"].items():
                        member = guild.get_member(int(user_id))
                        member_name = str(member) if member else f"Unknown ({user_id})"
                        breakdown_lines.append(f"{member_name}: {entries} {'entry' if entries == 1 else 'entries'}")
                    
                    breakdown_text = "\n".join(breakdown_lines[:50])  # Limit to 50 for embed size
                    if len(breakdown_lines) > 50:
                        breakdown_text += f"\n... and {len(breakdown_lines) - 50} more"
                    
                    embed = discord.Embed(
                        title=f"📋 Lottery Results: {lottery_name}",
                        color=discord.Color.green(),
                        timestamp=discord.utils.utcnow()
                    )
                    embed.add_field(
                        name="Winner",
                        value=f"<@{draw_results['winner_id']}> ({draw_results['winner_name']})",
                        inline=False
                    )
                    embed.add_field(
                        name="Statistics",
                        value=f"Participants: {draw_results['total_participants']}\nTotal Entries: {draw_results['total_entries']}",
                        inline=False
                    )
                    embed.add_field(
                        name="Entry Breakdown",
                        value=f"```\n{breakdown_text}\n```",
                        inline=False
                    )
                    
                    # Send file
                    await log_channel.send(embed=embed, file=discord.File(log_file))
                except Exception as e:
                    print(f"Failed to log to channel: {e}")
    
    async def _move_to_completed(self, guild: discord.Guild, lottery_name: str, draw_results: dict = None):
        """Move lottery from active to completed."""
        async with self.config.guild(guild).active_lotteries() as active:
            lottery_data = active.pop(lottery_name, None)
            
            if lottery_data and draw_results:
                lottery_data["draw_results"] = draw_results
                async with self.config.guild(guild).completed_lotteries() as completed:
                    completed[lottery_name] = lottery_data
    
    @commands.command(name="rerunlottery")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def rerun_lottery(self, ctx, lottery_name: str):
        """Rerun a completed lottery with the same participant data.
        
        This will randomly select a new winner from the same pool with the same entry weights.
        """
        completed_lotteries = await self.config.guild(ctx.guild).completed_lotteries()
        
        if lottery_name not in completed_lotteries:
            await ctx.send(f"❌ No completed lottery found with the name '{lottery_name}'.")
            return
        
        await ctx.send(f"🔄 Rerunning lottery '{lottery_name}'...")
        await self._execute_draw(ctx.guild, lottery_name, is_rerun=True)
    
    @commands.command(name="listlotteries")
    @commands.guild_only()
    async def list_lotteries(self, ctx):
        """List all active and completed lotteries."""
        active = await self.config.guild(ctx.guild).active_lotteries()
        completed = await self.config.guild(ctx.guild).completed_lotteries()
        
        embed = discord.Embed(
            title="🎰 Lottery List",
            color=discord.Color.blue()
        )
        
        if active:
            active_list = "\n".join([f"• `{name}`" for name in active.keys()])
            embed.add_field(name="Active Lotteries", value=active_list, inline=False)
        else:
            embed.add_field(name="Active Lotteries", value="None", inline=False)
        
        if completed:
            completed_list = "\n".join([f"• `{name}`" for name in list(completed.keys())[:25]])
            if len(completed) > 25:
                completed_list += f"\n... and {len(completed) - 25} more"
            embed.add_field(name="Completed Lotteries (Rerunnable)", value=completed_list, inline=False)
        else:
            embed.add_field(name="Completed Lotteries", value="None", inline=False)
        
        await ctx.send(embed=embed)
    
    @commands.command(name="lotteryinfo")
    @commands.guild_only()
    async def lottery_info(self, ctx, lottery_name: str):
        """Get detailed information about a specific lottery."""
        active = await self.config.guild(ctx.guild).active_lotteries()
        completed = await self.config.guild(ctx.guild).completed_lotteries()
        
        lottery_data = active.get(lottery_name) or completed.get(lottery_name)
        
        if not lottery_data:
            await ctx.send(f"❌ No lottery found with the name '{lottery_name}'.")
            return
        
        is_active = lottery_name in active
        
        embed = discord.Embed(
            title=f"🎰 Lottery Info: {lottery_name}",
            description=lottery_data.get("description", "No description"),
            color=discord.Color.gold() if is_active else discord.Color.blue()
        )
        
        embed.add_field(
            name="Status",
            value="🟢 Active" if is_active else "🔴 Completed",
            inline=True
        )
        embed.add_field(
            name="Referrals Enabled",
            value="✅ Yes" if lottery_data.get("use_referrals") else "❌ No",
            inline=True
        )
        
        starter = ctx.guild.get_member(lottery_data.get("starter_id"))
        if starter:
            embed.add_field(
                name="Started By",
                value=starter.mention,
                inline=True
            )
        
        if is_active:
            embed.add_field(
                name="Ends",
                value=f"<t:{lottery_data['end_time']}:R>",
                inline=False
            )
        elif "draw_results" in lottery_data:
            results = lottery_data["draw_results"]
            embed.add_field(
                name="Winner",
                value=f"<@{results['winner_id']}>",
                inline=True
            )
            embed.add_field(
                name="Participants",
                value=str(results["total_participants"]),
                inline=True
            )
            embed.add_field(
                name="Total Entries",
                value=str(results["total_entries"]),
                inline=True
            )
        
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Lottery(bot))
