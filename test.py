
import os
from google import genai
GOOGLE_API_KEY = "AIzaSyASUZ5k9EcXHCzlRrbK5WRWaU472aGWgrw"

from google.genai import types
import asyncio

client = genai.Client(api_key=GOOGLE_API_KEY)

LIVE_MODEL = 'gemini-2.0-flash-live-001'  # @param ['gemini-2.0-flash-live-001', 'gemini-live-2.5-flash-preview', 'gemini-2.5-flash-preview-native-audio-dialog', 'gemini-2.5-flash-exp-native-audio-thinking-dialog'] {allow-input: true, isTemplate: true}
MODEL = 'gemini-2.5-flash'  # @param ['gemini-2.5-flash'] {allow-input: true, isTemplate: true}

import json
from urllib.robotparser import RobotFileParser
from urllib.parse import urlparse

from IPython.display import display, HTML, Markdown


def show_parts(r: types.GenerateContentResponse) -> None:
  """Helper for rendering a GenerateContentResponse object in IPython."""
  parts = r.candidates[0].content.parts
  if parts is None:
    finish_reason = r.candidates[0].finish_reason
    print(f'{finish_reason=}')
    return

  for part in parts:
    if part.text:
      display(Markdown(part.text))
    elif part.executable_code:
      display(Markdown(f'```python\n{part.executable_code.code}\n```'))
    else:
      print(json.dumps(part.model_dump(exclude_none=True), indent=2))

  grounding_metadata = r.candidates[0].grounding_metadata
  if grounding_metadata and grounding_metadata.search_entry_point:
    display(HTML(grounding_metadata.search_entry_point.rendered_content))


def can_crawl_url(url: str, user_agent: str = "*") -> bool:
    """Look up robots.txt for a URL and determine if crawling is permissable.

    Args:
        url: The full URL to check.
        user_agent: The user agent to check, defaults to any UA.

    Returns:
        True if the URL can be crawled, False otherwise.
    """
    try:
      parsed_url = urlparse(url)
      robots_url = f"{parsed_url.scheme}://{parsed_url.netloc}/robots.txt"
      rp = RobotFileParser(robots_url)
      rp.read()

      return rp.can_fetch(user_agent, url)

    except Exception as e:
      print(f"Error checking robots.txt: {e}")
      return False  # Be a good citizen: fail closed.


config = {
    'response_modalities': ['TEXT'],
    'tools': [
        {'google_search': {}},
    ],
}


async def stream_response(stream, *, tool=None):
  """Handle a live streamed response, printing out text and issue tool calls."""
  all_responses = []

  async for msg in stream.receive():
    all_responses.append(msg)

    if text := msg.text:
      # Print streamed text responses.
      print(text, end='')

    elif tool_call := msg.tool_call:
      # Handle tool calls.
      for fc in tool_call.function_calls:
        print(f'< Tool call', fc.model_dump(exclude_none=True))

        if tool:
          # Call the tool.
          assert fc.name == tool.__name__, "Unknown tool call encountered"
          tool_result = tool(**fc.args)

        else:
          # Return 'ok' as a way to mock tool calls.
          tool_result = 'ok'

        tool_response = types.LiveClientToolResponse(
            function_responses=[types.FunctionResponse(
                name=fc.name,
                id=fc.id,
                response={'result': tool_result},
            )]
        )

        await stream.send(input=tool_response)

  return all_responses


async def run():
  async with client.aio.live.connect(model=LIVE_MODEL, config=config) as stream:

    await stream.send(input="What is today's btc price in binance as of 4:32 pm 22nd sept", end_of_turn=True)
    await stream_response(stream)


# Fix: Use asyncio.run() to run the async function
if __name__ == "__main__":
    asyncio.run(run())