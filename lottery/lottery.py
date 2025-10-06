import discord
import asyncio
import random
from datetime import datetime, timedelta
from redbot.core import commands, Config
from typing import Optional

class Lottery(commands.Cog):
    """A lottery system that auto-draws winners after a specified time."""
    
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        default_guild = {
            "active_lotteries": {}
        }
        self.config.register_guild(**default_guild)
    
    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def lottery(
        self, 
        ctx, 
        channel: discord.TextChannel,
        duration: int,
        emoji: str = "🎟️",
        *,
        description: str = "React to enter the lottery!"
    ):
        """
        Start a lottery that automatically draws a winner.
        
        Parameters:
        - channel: The channel where the lottery will be posted
        - duration: Duration in minutes until the winner is drawn
        - emoji: The emoji to use for reactions (default: 🎟️)
        - description: Custom description for what the lottery is about
        
        Example:
        [p]lottery #general 60 🎲 Win a free role!
        """
        
        if duration <= 0:
            await ctx.send("Duration must be a positive number of minutes.")
            return
        
        # Calculate end time
        end_time = datetime.utcnow() + timedelta(minutes=duration)
        end_timestamp = int(end_time.timestamp())
        
        # Create initial embed
        embed = discord.Embed(
            title="🎰 Lottery Registration Open!",
            description=f"{description}\n\nReact with {emoji} below to enter!",
            color=0xF1C40F,
            timestamp=datetime.utcnow()
        )
        embed.add_field(
            name="📋 How to Enter",
            value=f"Simply react with {emoji} to this message",
            inline=False
        )
        embed.add_field(
            name="⏰ Drawing Time",
            value=f"<t:{end_timestamp}:R> (<t:{end_timestamp}:F>)",
            inline=False
        )
        embed.set_footer(text=f"Started by {ctx.author} | Good luck to all participants!")
        
        # Send the lottery message
        try:
            lottery_message = await channel.send(embed=embed)
            await lottery_message.add_reaction(emoji)
        except discord.Forbidden:
            await ctx.send(f"I don't have permission to send messages in {channel.mention}")
            return
        except discord.HTTPException:
            await ctx.send("Failed to create lottery. The emoji might be invalid.")
            return
        
        await ctx.send(f"✅ Lottery created in {channel.mention}! Winner will be drawn in {duration} minutes.")
        
        # Schedule the winner drawing
        await self._schedule_draw(lottery_message, emoji, duration, ctx.author)
    
    async def _schedule_draw(self, message: discord.Message, emoji: str, duration: int, starter: discord.Member):
        """Schedule and execute the lottery drawing."""
        
        # Wait for the duration
        await asyncio.sleep(duration * 60)
        
        try:
            # Refresh message to get latest reactions
            message = await message.channel.fetch_message(message.id)
            
            # Find the target reaction
            target_reaction = None
            for reaction in message.reactions:
                if str(reaction.emoji) == emoji:
                    target_reaction = reaction
                    break
            
            if not target_reaction:
                # No reactions found
                embed = discord.Embed(
                    title="🎰 Lottery Ended",
                    description="No participants entered the lottery.",
                    color=0xE74C3C,
                    timestamp=datetime.utcnow()
                )
                embed.set_footer(text="Better luck next time!")
                await message.edit(embed=embed)
                return
            
            # Get users who reacted (excluding bots)
            participants = []
            async for user in target_reaction.users():
                if not user.bot:
                    participants.append(user)
            
            if not participants:
                # No valid participants
                embed = discord.Embed(
                    title="🎰 Lottery Ended",
                    description="No valid participants entered the lottery.",
                    color=0xE74C3C,
                    timestamp=datetime.utcnow()
                )
                embed.set_footer(text="Better luck next time!")
                await message.edit(embed=embed)
                return
            
            # Pick random winner
            winner = random.choice(participants)
            
            # Create winner announcement embed
            embed = discord.Embed(
                title="🎊 Lottery Winner Announced!",
                description=f"**Congratulations to {winner.mention}!**\n\nYou have won the lottery!",
                color=0x2ECC71,
                timestamp=datetime.utcnow()
            )
            embed.add_field(
                name="📊 Total Participants",
                value=str(len(participants)),
                inline=True
            )
            embed.add_field(
                name="🏆 Winner",
                value=winner.mention,
                inline=True
            )
            embed.set_thumbnail(url=winner.display_avatar.url)
            embed.set_footer(text=f"Started by {starter} | Thank you to all participants!")
            
            # Edit the original message with winner
            await message.edit(embed=embed)
            
            # Optional: Mention the winner in a new message
            await message.channel.send(f"🎉 {winner.mention} has won the lottery!")
            
        except discord.NotFound:
            pass  # Message was deleted
        except discord.Forbidden:
            pass  # Lost permissions
        except Exception as e:
            print(f"Error in lottery draw: {e}")

def setup(bot):
    bot.add_cog(Lottery(bot))
