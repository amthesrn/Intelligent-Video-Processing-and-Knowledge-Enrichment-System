# # Youtube_mcp_client.py
# working version

import sys
import os
import json
import asyncio
import traceback
from typing import Optional, Dict, Any, List

from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_ext.tools.mcp import StdioServerParams, mcp_server_tools
from autogen_agentchat.agents import AssistantAgent, UserProxyAgent
from autogen_core.models import UserMessage
from autogen_agentchat.base import Handoff
from autogen_agentchat.conditions import HandoffTermination, TextMentionTermination
from autogen_agentchat.teams import RoundRobinGroupChat

from client_logger import setup_logger, log_event  # ✅ use shared logger module
# from client_logger import setup_logger



class RetryingMCPClient:
    def __init__(self, server_path: str, max_retries: int = 3, retry_delay: float = 2.0, logger: Optional[Any] = None):
        self.server_path = server_path
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.logger = logger or setup_logger()
        self.tools = None

    async def connect(self) -> List[Dict[str, Any]]:
        server_params = StdioServerParams(
            command="python",
            # args=[self.server_path],
            args=["-u", self.server_path],
            read_timeout_seconds=1500,
        )
        for attempt in range(1, self.max_retries + 1):
            try:
                self.logger.info(f"Connecting to MCP server (attempt {attempt}/{self.max_retries})...")
                self.tools = await mcp_server_tools(server_params)
                self.logger.info(f"✅ Retrieved {len(self.tools)} tools from MCP server.")
                return self.tools
            except Exception as e:
                self.logger.error(f"❌ Failed to connect to MCP server: {e}")
                if attempt < self.max_retries:
                    self.logger.info(f"Retrying in {self.retry_delay} seconds...")
                    await asyncio.sleep(self.retry_delay)
                else:
                    self.logger.error("Maximum retry attempts reached. Could not connect to server.")
                    raise

    def get_tools(self) -> List[Dict[str, Any]]:
        if not self.tools:
            raise RuntimeError("Not connected to MCP server. Call connect() first.")
        return self.tools


async def main() -> None:
    logger = setup_logger()
    logger.info("🚀 Starting YouTube MCP Client...")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    server_paths = [
        os.path.join(script_dir, "youtube_mcp_server.py"),
        "E:\\autogen_folder\\Youtube-Vision-MCP-main\\dist\\youtube_mcp_server.py"
    ]

    server_path = None
    for path in server_paths:
        if os.path.exists(path):
            server_path = path
            logger.info(f"Using server at: {server_path}")
            break

    if not server_path:
        logger.error("❌ Could not find the MCP server script. Please specify the correct path.")
        return

    try:
        mcp_client = RetryingMCPClient(server_path=server_path, logger=logger)
        tools = await mcp_client.connect()
    except Exception as e:
        logger.exception(f"❌ Failed to connect to MCP server: {e}")
        return

    logger.info("🤖 Initializing Gemini model client...")
    try:
        gemini_client = OpenAIChatCompletionClient(
            model="gemini-2.0-flash",
            api_key=os.getenv("GEMINI_API_KEY", "AIzaSyD_6BTDHBsxCNmm-izSnaZ979YrqHZXWGI")
        )
        logger.info("✅ Gemini client ready.")
    except Exception as e:
        logger.exception(f"❌ Failed to initialize Gemini client: {e}")
        return

    system_prompt = """
You are YoutubeVision, an AI assistant specialized in analyzing and extracting information from YouTube videos.
You can:
1. Download YouTube video content
2. Summarize videos
3. Extract key moments from videos
4. Answer questions about videos
When given a YouTube URL, you'll automatically use the appropriate tools to analyze it and provide insights.
Always verify the video ID was correctly extracted before processing.
If you encounter errors, try to diagnose the issue and suggest solutions.
"""

    logger.info("👥 Setting up agents...")
    try:
        user = UserProxyAgent(
            name="user",
            input_func=input
        )
        agent = AssistantAgent(
            name="YoutubeVision",
            system_message=system_prompt,
            model_client=gemini_client,
            tools=tools,
            handoffs=[Handoff(target="user", message="Transfer to user.")],
        )
        termination = HandoffTermination("user") | TextMentionTermination("TERMINATE")
        team = RoundRobinGroupChat([agent, user], termination_condition=termination)
    except Exception as e:
        logger.exception(f"❌ Failed to set up agents: {e}")
        return

    try:
        print("\n" + "=" * 50)
        print("🎬 YouTube Vision Assistant 🎬")
        print("=" * 50)
        print("Available commands:")
        print("1. Summarize a video: 'summarize https://youtube.com/watch?v=VIDEO_ID'")
        print("2. Extract key moments: 'moments https://youtube.com/watch?v=VIDEO_ID'")
        print("3. Download video: 'download https://youtube.com/watch?v=VIDEO_ID'")
        print("4. Ask about a video: 'ask https://youtube.com/watch?v=VIDEO_ID what is this video about?'")
        print("5. Or enter any question about a YouTube video URL")
        print("=" * 50 + "\n")
        task = input("Enter your request: ")
        logger.info(f"💬 Task: {task}")
    except KeyboardInterrupt:
        logger.info("Task input cancelled by user.")
        return
    except Exception as e:
        logger.exception(f"❌ Error getting task: {e}")
        return

    logger.info("💬 Beginning conversation stream...")
    try:
        async for event in team.run_stream(task=task):
            log_event(logger, event, print_to_console=True)
    except asyncio.TimeoutError:
        logger.error("❌ Conversation timed out.")
        print("\n⚠️ The operation timed out. This might happen with large videos or slow internet connections.")
    except KeyboardInterrupt:
        logger.info("Conversation interrupted by user.")
        print("\n👋 Goodbye!")
    except Exception as e:
        logger.exception(f"❌ Error during conversation: {e}")
        print(f"\n❌ An error occurred: {e}")
    else:
        logger.info("✅ Conversation ended successfully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        traceback.print_exc()
