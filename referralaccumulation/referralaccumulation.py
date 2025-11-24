import discord
from redbot.core import commands, Config
from redbot.core.utils.chat_formatting import box, humanize_list
from typing import Optional
from datetime import datetime

class ReferralSystem(commands.Cog):
    """A referral system that tracks member invites and awards points."""
    
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        
        default_guild = {
            "invite_owners": {},  # {invite_code: user_id}
            "referrals": {},  # {invited_user_id: inviter_user_id}
            "points": {}  # {user_id: points}
        }
        
        self.config.register_guild(**default_guild)
        self.invite_cache = {}  # {guild_id: {invite_code: uses}}
    
    async def cache_invites(self, guild: discord.Guild):
        """Cache all current invites for a guild."""
        try:
            invites = await guild.invites()
            self.invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
            
            # Store invite owners for any new invites
            async with self.config.guild(guild).invite_owners() as owners:
                for inv in invites:
                    if inv.inviter and inv.code not in owners:
                        owners[inv.code] = inv.inviter.id
        except discord.Forbidden:
            pass
    
    @commands.Cog.listener()
    async def on_ready(self):
        """Cache invites on bot ready."""
        for guild in self.bot.guilds:
            await self.cache_invites(guild)
    
    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        """Automatically track invite owner when invite is created."""
        if invite.guild.id not in self.invite_cache:
            self.invite_cache[invite.guild.id] = {}
        self.invite_cache[invite.guild.id][invite.code] = invite.uses
        
        # Automatically store who created this invite
        if invite.inviter:
            async with self.config.guild(invite.guild).invite_owners() as owners:
                owners[invite.code] = invite.inviter.id
    
    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        """Update cache when invite is deleted."""
        if invite.guild.id in self.invite_cache:
            self.invite_cache[invite.guild.id].pop(invite.code, None)
        
        # Remove from stored owners
        async with self.config.guild(invite.guild).invite_owners() as owners:
            owners.pop(invite.code, None)
    
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Track which invite was used when a member joins."""
        if member.bot:
            return
        
        guild = member.guild
        
        try:
            new_invites = await guild.invites()
        except discord.Forbidden:
            return
        
        old_invites = self.invite_cache.get(guild.id, {})
        
        # Find which invite was used
        used_invite = None
        for invite in new_invites:
            old_uses = old_invites.get(invite.code, 0)
            if invite.uses > old_uses:
                used_invite = invite
                break
        
        # Update cache
        self.invite_cache[guild.id] = {inv.code: inv.uses for inv in new_invites}
        
        if used_invite:
            # Get the invite owner
            invite_owners = await self.config.guild(guild).invite_owners()
            inviter_id = invite_owners.get(used_invite.code)
            
            if inviter_id:
                # Store referral
                async with self.config.guild(guild).referrals() as referrals:
                    referrals[str(member.id)] = inviter_id
                
                # Award point
                async with self.config.guild(guild).points() as points:
                    points[str(inviter_id)] = points.get(str(inviter_id), 0) + 1
    
    @commands.command(name="myinvites")
    @commands.guild_only()
    async def my_invites(self, ctx):
        """View all your tracked invites."""
        invite_owners = await self.config.guild(ctx.guild).invite_owners()
        
        my_invites = [code for code, user_id in invite_owners.items() if user_id == ctx.author.id]
        
        if not my_invites:
            await ctx.send("📭 You don't have any active invites. Create one through Discord and it will be automatically tracked!")
            return
        
        try:
            invites = await ctx.guild.invites()
            invite_details = []
            
            for inv in invites:
                if inv.code in my_invites:
                    uses = inv.uses
                    max_uses = inv.max_uses if inv.max_uses else "∞"
                    expires = f"<t:{int(inv.expires_at.timestamp())}:R>" if inv.expires_at else "Never"
                    invite_details.append(f"`{inv.code}` - {uses}/{max_uses} uses - Expires: {expires}")
            
            embed = discord.Embed(
                title="📋 Your Tracked Invites",
                description="\n".join(invite_details) if invite_details else "No active invites found.",
                color=discord.Color.blue()
            )
            
            await ctx.send(embed=embed)
            
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to view invites in this server.")
    
    @commands.command(name="referrals")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def referral_leaderboard(self, ctx):
        """Display the referral leaderboard (Admin only)."""
        points_data = await self.config.guild(ctx.guild).points()
        
        if not points_data:
            await ctx.send("📊 No referrals tracked yet!")
            return
        
        # Sort by points descending
        sorted_referrers = sorted(points_data.items(), key=lambda x: x[1], reverse=True)
        
        embed = discord.Embed(
            title="🏆 Referral Leaderboard",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow()
        )
        
        leaderboard_text = []
        for idx, (user_id, points) in enumerate(sorted_referrers[:25], 1):
            user = ctx.guild.get_member(int(user_id))
            user_name = user.mention if user else f"Unknown User ({user_id})"
            
            medal = ""
            if idx == 1:
                medal = "🥇"
            elif idx == 2:
                medal = "🥈"
            elif idx == 3:
                medal = "🥉"
            
            leaderboard_text.append(f"{medal} **#{idx}** {user_name} - **{points}** referral{'s' if points != 1 else ''}")
        
        embed.description = "\n".join(leaderboard_text)
        embed.set_footer(text=f"Total tracked users: {len(sorted_referrers)}")
        
        await ctx.send(embed=embed)
    
    @commands.command(name="referred")
    @commands.guild_only()
    async def who_referred(self, ctx, member: Optional[discord.Member] = None):
        """Check who invited a member.
        
        If no member is specified, checks who invited you.
        """
        target = member or ctx.author
        
        referrals_data = await self.config.guild(ctx.guild).referrals()
        inviter_id = referrals_data.get(str(target.id))
        
        if not inviter_id:
            await ctx.send(f"❌ No referral data found for {target.display_name}.")
            return
        
        inviter = ctx.guild.get_member(inviter_id)
        inviter_name = inviter.mention if inviter else f"Unknown User (ID: {inviter_id})"
        
        embed = discord.Embed(
            title="👋 Referral Information",
            description=f"{target.mention} was invited by {inviter_name}",
            color=discord.Color.blue()
        )
        
        await ctx.send(embed=embed)
    
    @commands.command(name="myreferrals")
    @commands.guild_only()
    async def my_referrals(self, ctx, member: Optional[discord.Member] = None):
        """View who you invited, or check another user's invites."""
        target = member or ctx.author
        
        referrals_data = await self.config.guild(ctx.guild).referrals()
        points_data = await self.config.guild(ctx.guild).points()
        
        # Find all users invited by target
        invited_users = [
            user_id for user_id, inviter_id in referrals_data.items() 
            if inviter_id == target.id
        ]
        
        if not invited_users:
            await ctx.send(f"📭 {target.display_name} hasn't invited anyone yet.")
            return
        
        embed = discord.Embed(
            title=f"📋 {target.display_name}'s Referrals",
            color=discord.Color.purple()
        )
        
        total_points = points_data.get(str(target.id), 0)
        embed.description = f"**Total Referrals:** {total_points}"
        
        # List invited users
        invited_list = []
        for user_id in invited_users[:25]:  # Limit to 25
            user = ctx.guild.get_member(int(user_id))
            if user:
                invited_list.append(f"• {user.mention} ({user.name})")
            else:
                invited_list.append(f"• Unknown User (ID: {user_id})")
        
        if invited_list:
            embed.add_field(
                name="Invited Members",
                value="\n".join(invited_list),
                inline=False
            )
        
        if len(invited_users) > 25:
            embed.set_footer(text=f"Showing 25 of {len(invited_users)} invites")
        
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(ReferralSystem(bot))
