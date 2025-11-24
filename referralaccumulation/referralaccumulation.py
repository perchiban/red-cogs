import discord
from redbot.core import commands, Config
from redbot.core.utils.chat_formatting import box, humanize_list
from typing import Optional
from datetime import datetime

class ReferralAccumulation(commands.Cog):
    """A referral system that tracks member invites and awards points."""
    
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        
        default_guild = {
            "invites": {},  # {user_id: invite_code}
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
        except discord.Forbidden:
            pass
    
    @commands.Cog.listener()
    async def on_ready(self):
        """Cache invites on bot ready."""
        for guild in self.bot.guilds:
            await self.cache_invites(guild)
    
    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        """Update cache when invite is created."""
        if invite.guild.id not in self.invite_cache:
            self.invite_cache[invite.guild.id] = {}
        self.invite_cache[invite.guild.id][invite.code] = invite.uses
    
    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        """Update cache when invite is deleted."""
        if invite.guild.id in self.invite_cache:
            self.invite_cache[invite.guild.id].pop(invite.code, None)
    
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
            # Check if this invite belongs to a tracked referral
            invites_data = await self.config.guild(guild).invites()
            inviter_id = None
            
            for user_id, invite_code in invites_data.items():
                if invite_code == used_invite.code:
                    inviter_id = int(user_id)
                    break
            
            if inviter_id:
                # Store referral
                async with self.config.guild(guild).referrals() as referrals:
                    referrals[str(member.id)] = inviter_id
                
                # Award point
                async with self.config.guild(guild).points() as points:
                    points[str(inviter_id)] = points.get(str(inviter_id), 0) + 1
    
    @commands.command(name="referral")
    @commands.guild_only()
    async def create_referral(self, ctx, max_uses: Optional[int] = 0, max_age: Optional[int] = 0):
        """Create a referral invite link.
        
        Parameters:
        - max_uses: Maximum number of uses (0 = unlimited)
        - max_age: Maximum age in seconds (0 = unlimited)
        
        Example: `[p]referral 10 86400` creates an invite with 10 uses valid for 24 hours.
        """
        # Delete previous invites
        invites_data = await self.config.guild(ctx.guild).invites()
        old_invite_code = invites_data.get(str(ctx.author.id))
        
        if old_invite_code:
            try:
                invites = await ctx.guild.invites()
                for invite in invites:
                    if invite.code == old_invite_code:
                        await invite.delete(reason="User creating new referral invite")
                        break
            except discord.Forbidden:
                pass
        
        # Create new invite
        try:
            invite = await ctx.channel.create_invite(
                max_uses=max_uses,
                max_age=max_age,
                unique=True,
                reason=f"Referral invite for {ctx.author}"
            )
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to create invites in this channel.")
            return
        
        # Store invite
        async with self.config.guild(ctx.guild).invites() as invites_data:
            invites_data[str(ctx.author.id)] = invite.code
        
        # Update cache
        await self.cache_invites(ctx.guild)
        
        # Send invite to user
        embed = discord.Embed(
            title="🔗 Your Referral Link",
            description=f"Share this link to invite people and earn points!\n\n{invite.url}",
            color=discord.Color.green()
        )
        
        details = []
        if max_uses > 0:
            details.append(f"**Max Uses:** {max_uses}")
        else:
            details.append("**Max Uses:** Unlimited")
            
        if max_age > 0:
            details.append(f"**Expires In:** {max_age // 3600}h {(max_age % 3600) // 60}m")
        else:
            details.append("**Expires In:** Never")
        
        embed.add_field(name="Settings", value="\n".join(details), inline=False)
        
        try:
            await ctx.author.send(embed=embed)
            await ctx.send("✅ Your referral link has been sent to your DMs!")
        except discord.Forbidden:
            await ctx.send(embed=embed)
    
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

def setup(bot):
    bot.add_cog(ReferralAccumulation(bot))
