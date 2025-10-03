import os
from mistralai import Mistral
from dotenv import load_dotenv
import json
load_dotenv()
api_key = os.environ["MISTRAL_API_KEY"]
client = Mistral(api_key)

code_agent = client.beta.agents.create(
    model="mistral-medium-2505",
    name="Coding Agent",
    description="Agent used to execute code using the interpreter tool.",
    instructions="Use the code interpreter tool when you have to run code.",
    tools=[
                {"type": "web_search"},
                {"type": "code_interpreter"},
                {"type": "image_generation"}
            ],
    completion_args={
        "temperature": 0.3,
        "top_p": 0.95,
    }
)

response = client.beta.conversations.start(
    agent_id=code_agent.id,
    inputs="generate an image of a cat wearing a hat and holding a sign that says hello world",
)

print(json.dumps(response, indent=4, default=str))