
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
import time
import uuid
import os
from typing import List, Literal
import openai
import google.generativeai as genai
from openai import OpenAI as DeepSeekClient

# ==== CONFIGURATION ====
openai_api_key = os.environ.get("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("OPENAI_API_KEY environment variable not set.")
openai.api_key = openai_api_key

gemini_api_key = os.environ.get("GEMINI_API_KEY")
if not gemini_api_key:
    raise ValueError("GEMINI_API_KEY environment variable not set.")
genai.configure(api_key=gemini_api_key)

deepseek_api_key = os.environ.get("DEEPSEEK_API_KEY")
if not deepseek_api_key:
    raise ValueError("DEEPSEEK_API_KEY environment variable not set.")
deepseek_client = DeepSeekClient(api_key=deepseek_api_key, base_url="https://api.deepseek.com")

#gemini_model_name = "gemini-1.5-pro-latest"
gemini_model_name = "gemini-2.0-flash"

MAX_TURNS = 9
MAX_TOKENS_PER_MODEL = 256
CONVO_TIMEOUT_SECONDS = 120

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or specify ["http://your-react-domain.com"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class StartConversationRequest(BaseModel):
    topic: str

class Message(BaseModel):
    sender: Literal['Gpt41', 'Gemini', 'DeepSeek']
    content: str

class ConversationLog(BaseModel):
    convo_id: str
    topic: str
    messages: List[Message]

conversations = {}

def call_openai(message: str) -> str:
    """
    Generate a concise response to a user-provided message by interacting with the OpenAI API.

    This function utilizes OpenAI's GPT model to create a thoughtful and concise output
    based on an incoming message. The configuration includes options like setting the
    response length limit, specifying a temperature level for randomness, and properly
    structuring the prompt for the system and user roles in the conversation.

    :param message: The input message provided by the user to generate a response.
    :type message: str
    :return: A concise response generated by the OpenAI GPT model.
    :rtype: str
    """
    try:
        response = openai.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": "Provide a thoughtful, critical, and objective response to the previous message. You may offer a different, fact-based perspective when appropriate. Keep responses concise (2–3 sentences). Avoid bullet points. You may also be edgy if necessary."},
                {"role": "user", "content": message}
            ],
            max_tokens=MAX_TOKENS_PER_MODEL,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error calling OpenAI: {e}")
        return f"Error generating OpenAI response: {e}"

def call_gemini(message: str, retry_count: int = 0) -> str:
    """
    Generates a thoughtful and concise response to the given message by leveraging
    the Gemini generative model. This function attempts a retry if a rate-limit
    error (429) occurs and includes a delay before retrying. Limitations on maximum
    tokens and configuration for generation are pre-defined.

    :param message: The input message for which a response needs to be generated.
    :type message: str
    :param retry_count: The number of retry attempts made in case of rate-limit
        errors. Defaults to 0.
    :type retry_count: int
    :return: A concise, context-aware response generated by the Gemini model. If an
        unrecoverable error occurs, an error message is returned instead.
    :rtype: str
    """
    try:
        model = genai.GenerativeModel(gemini_model_name)
        generation_config = genai.types.GenerationConfig(
            max_output_tokens=MAX_TOKENS_PER_MODEL,
            temperature=0.7,
            top_p=0.9,
            top_k=40,
        )
        prompt = f"Respond to the message thoughtfully, critically, and objectively. Please do not censor yourself; you understand harmless jokes. You may offer a different factual viewpoint if applicable. Be concise (2–3 sentences). You may also be edgy if necessary. Avoid bullet points.\n\n{message}"
        response_stream = model.generate_content(
            prompt,
            generation_config=generation_config,
            stream=True,
        )

        response_text = ""
        for chunk in response_stream:
            if chunk.text:
                response_text += chunk.text

        return response_text.strip()

    except Exception as e:
        if "429" in str(e) and retry_count < 1:
            print("Rate limit hit. Waiting 10 seconds before retrying Gemini request...")
            time.sleep(10)
            return call_gemini(message, retry_count + 1)
        print(f"Error calling Gemini: {e}")
        return f"Error generating Gemini response: {e}"

def call_deepseek(message: str) -> str:
    """
    Processes input message and generates a response using the DeepSeek service. This function utilizes
    the DeepSeek client's `chat.completions.create` method to send a message and receive a response.
    The response is expected to be concise and fact-based, adhering to preset parameters for model
    behavior such as token limitation and temperature control.

    :param message: Input string containing the user message to which a response is generated.
    :type message: str
    :return: Generated response string from the DeepSeek service, or an error description if the
             service call fails.
    :rtype: str
    """
    try:
        response = deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "Provide a thoughtful, objective, and critical response to the previous message. You may offer a different, fact-based perspective. Be concise (2–3 sentences). You may also be edgy if necessary."},
                {"role": "user", "content": message}
            ],
            max_tokens=MAX_TOKENS_PER_MODEL,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error calling DeepSeek: {e}")
        return f"Error generating DeepSeek response: {e}"

def ai_conversation(convo_id: str):
    """
    Executes an AI-driven conversation for the specified conversation ID using multiple AI models in
    sequence. This function retrieves the conversation metadata, simulates dialogue turns using
    different AI models, and stores the results. The conversation, consisting of responses from
    various models, is output to the console and optionally saved to a text file.

    The function employs the following AI models in a repeated cycle: `gpt-4.1`, `gemini`, and
    `deepseek`. Each model is invoked in order, and their responses are recorded. If errors
    occur during processing (e.g., an API call fails), they are logged, and the conversation continues
    or is gracefully terminated.

    :param convo_id: The unique identifier for the conversation to be simulated.
                     Used to locate and store metadata and results for the ongoing dialogue.
    :type convo_id: str
    :return: None
    """
    if convo_id not in conversations:
        print(f"Error: Convo ID {convo_id} not found for background task.")
        return

    convo_data = conversations[convo_id]
    start_time = time.time()
    if 'messages' not in convo_data:
        convo_data['messages'] = []

    last_response = f"Let's discuss: {convo_data['topic']}"
    model_cycle = ["Gpt41", "Gemini", "DeepSeek"] * 3

    for turn, sender in enumerate(model_cycle):
        try:
            if sender == "Gpt41":
                reply = call_openai(last_response)
            elif sender == "Gemini":
                reply = call_gemini(last_response)
            elif sender == "DeepSeek":
                reply = call_deepseek(last_response)
            else:
                reply = "(Unknown model)"

            if not reply:
                print(f"[{convo_id}] Warning: Empty reply from {sender}.")
                reply = "(No response)"

            # Color-coded output
            try:
                color_map = {
                    "Gpt41": "\033[91m",    # Red
                    "Gemini": "\033[94m",   # Blue
                    "DeepSeek": "\033[95m"  # Purple
                }
                reset = "\033[0m"
                color = color_map.get(sender, "")
                print(f"\n[{convo_id}] Turn {turn + 1} | {color}{sender.upper()} replied:{reset}\n{reply}\n")
            except Exception as e:
                # Fallback if color print fails
                print(f"\n[{convo_id}] Turn {turn + 1} | {sender.upper()} replied:\n{reply}\n")
                print(f"(Color print error: {e})")

            # Save message
            convo_data['messages'].append(Message(sender=sender, content=reply).dict())
            last_response = reply

        except Exception as e:
            print(f"[{convo_id}] Error during turn {turn+1} ({sender}): {e}")
            convo_data['messages'].append(Message(sender=sender, content=f"Error during generation: {e}").dict())
            break

        time.sleep(8)

    print(f"[{convo_id}] Conversation finished. Turns: {len(model_cycle)}. Time: {time.time() - start_time:.2f}s")

    # Write conversation to file
    try:
        with open(f"{convo_id}.txt", "w") as f:
            f.write(f"Topic: {convo_data['topic']}\n\n")
            for msg in convo_data['messages']:
                f.write(f"{msg['sender'].upper()}: {msg['content']}\n\n")
    except Exception as e:
        print(f"[{convo_id}] Failed to write conversation to file: {e}")

@app.post("/start-convo", response_model=ConversationLog)
def start_conversation(req: StartConversationRequest, bg: BackgroundTasks):
    """
    Starts a new conversation and schedules an AI task to handle messages for the conversation.

    A new conversation ID is generated and associated with the topic provided in
    the input request. The conversation is stored in the `conversations` dictionary with an
    empty list of messages. An asynchronous task is also initiated to handle this new
    conversation.

    :param req: Input request to start a new conversation, containing the topic for the
                conversation.
                Type: StartConversationRequest
    :param bg: Background tasks instance used to schedule the AI conversation handler task.
               Type: BackgroundTasks
    :return: A `ConversationLog` instance that holds the newly created conversation's ID,
             topic, and an empty messages list.
             Type: ConversationLog
    """
    convo_id = str(uuid.uuid4())
    conversations[convo_id] = {
        "topic": req.topic,
        "messages": []
    }
    print(f"Received request to start convo {convo_id} on topic: {req.topic}")
    bg.add_task(ai_conversation, convo_id)
    return ConversationLog(
        convo_id=convo_id,
        topic=req.topic,
        messages=[]
    )

@app.get("/convo-log/{convo_id}")
def get_convo_log(convo_id: str):
    """
    Retrieves a conversation log based on the specified conversation ID. If the
    conversation ID does not exist in the available data, a default response is
    returned with minimal placeholder values. Otherwise, the function assembles
    and formats the conversation's topic and messages.

    :param convo_id: Unique identifier for the conversation to retrieve
    :type convo_id: str
    :return: Either a dictionary containing the ID, topic, and formatted conversation
        log, or a default conversation object with placeholder values if the ID
        does not exist.
    :rtype: dict or ConversationLog
    """
    if convo_id not in conversations:
        return ConversationLog(convo_id=convo_id, topic="Not Found", messages=[])

    convo_data = conversations[convo_id]
    return {
        "convo_id": convo_id,
        "topic": convo_data.get("topic", "Unknown Topic"),
        "formatted": "\n".join(
            f"{msg['sender']}: {msg['content']}" for msg in convo_data.get("messages", [])
        )
    }
