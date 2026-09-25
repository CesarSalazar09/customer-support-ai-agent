"""
Customer Support AI Agent 
"""

# ── Imports ───────────────────────────────────────────────────────────────────
from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory import MemoryClient
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
from mcp.client.streamable_http import streamable_http_client
import argparse, json
import os, asyncio, boto3
from strands.hooks import (
    HookProvider, AfterInvocationEvent, HookRegistry, MessageAddedEvent,
)
import logging
import uuid
from typing import Dict
from bedrock_agentcore.tools.code_interpreter_client import code_session
from strands_tools.browser import AgentCoreBrowser

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("CSAI_Agent")

app = BedrockAgentCoreApp()

# Suppress interactive tool-consent prompts (required in headless deployments).
os.environ["BYPASS_TOOL_CONSENT"] = "true"

GATEWAY_URL = "https://customersupportgateway-99wned7nhi.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
KB_ID       = "PS6005HIIP"
REGION      = "us-east-1"
MEMORY_ID   = "CustomerSupportMemory-yLdCmG8UGj"

model_id = "global.amazon.nova-2-lite-v1:0"
model = BedrockModel(model_id=model_id)
memory_client = MemoryClient(region_name=REGION)
_bedrock_runtime = boto3.client('bedrock-agent-runtime', region_name=REGION)


# ── Funciones auxiliares para manejo robusto de mensajes ───────────────────────
def _get_text_content(msg) -> str | None:
    """Extrae texto plano independientemente de si el contenido es str o lista de bloques."""
    if not isinstance(msg, dict):
        return None
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list) and len(content) > 0:
        first = content[0]
        if isinstance(first, dict) and "text" in first:
            return first["text"]
    return None


def _set_text_content(msg, new_text: str):
    """Actualiza el texto en el formato adecuado según el tipo de mensaje."""
    content = msg.get("content")
    if isinstance(content, list) and len(content) > 0 and isinstance(content[0], dict) and "text" in content[0]:
        content[0]["text"] = new_text
    else:
        msg["content"] = new_text


# ── TODO 4 — Namespace Helper ─────────────────────────────────────────────────
def get_namespaces(mem_client: MemoryClient, memory_id: str) -> Dict:
    """Return a dict mapping strategy type → namespace template string."""
    namespaces = {}
    strategies = mem_client.get_memory_strategies(memory_id)
    for strategy in strategies:
        strat_type = strategy.get("strategyType") or strategy.get("type")
        if "namespaceTemplates" in strategy and strategy["namespaceTemplates"]:
            namespaces[strat_type] = strategy["namespaceTemplates"][0]
        elif "namespaces" in strategy and strategy["namespaces"]:
            namespaces[strat_type] = strategy["namespaces"][0]

    return namespaces


# ── TODO 5 — Memory Hook ──────────────────────────────────────────────────────
class MemoryHook(HookProvider):
    """Long-term memory hook for the customer support agent."""
    def __init__(
        self,
        actor_id: str,
        session_id: str,
        memory_client: MemoryClient,
        memory_id: str,
    ):
        self.actor_id = actor_id
        self.session_id = session_id
        self.memory_client = memory_client
        self.memory_id = memory_id
        self.namespaces = get_namespaces(memory_client, memory_id)

    def retrieve_customer_context(self, event: MessageAddedEvent):
        """Retrieve relevant memories and prepend them to the user message."""
        if not event.agent.messages:
            return

        last_msg = event.agent.messages[-1]
        if last_msg.get("role") != "user":
            return

        query = _get_text_content(last_msg)
        if not query:
            return

        memories_found = []

        for strategy_type, ns_template in self.namespaces.items():
            namespace = ns_template.replace("{actorId}", self.actor_id)
            try:
                response = self.memory_client.retrieve_memories(
                    memory_id=self.memory_id,
                    namespace=namespace,
                    query=query,
                    top_k=5
                )
                for mem in response:
                    # Soporta formato plano o anidado en content
                    text = mem.get("text")
                    if not text and isinstance(mem.get("content"), dict):
                        text = mem["content"].get("text")
                    elif not text and isinstance(mem.get("content"), str):
                        text = mem.get("content")

                    if text:
                        memories_found.append(f"[{strategy_type}] {text}")
            except Exception as e:
                logger.warning(f"Error recuperando memoria para {strategy_type}: {e}")

        if memories_found:
            context_str = "\n".join(memories_found)
            new_message_body = f"Customer Context:\n{context_str}\n\n{query}"
            _set_text_content(last_msg, new_message_body)

    def save_support_interaction(self, event: AfterInvocationEvent):
        """Save the completed turn to memory after the agent responds."""
        customer_query = None
        agent_response = None

        for msg in reversed(event.agent.messages):
            role = msg.get("role")
            text = _get_text_content(msg)

            if role == "assistant" and text and not agent_response:
                agent_response = text
            elif role == "user" and text and not customer_query:
                # Si el mensaje fue enriquecido con contexto, limpiamos la cabecera
                if "Customer Context:\n" in text and "\n\n" in text:
                    customer_query = text.split("\n\n", 1)[1]
                else:
                    customer_query = text

            if customer_query and agent_response:
                break

        if customer_query and agent_response:
            try:
                self.memory_client.create_event(
                    memory_id=self.memory_id,
                    actor_id=self.actor_id,
                    session_id=self.session_id,
                    messages=[
                        (customer_query, "USER"),
                        (agent_response, "ASSISTANT")
                    ]
                )
            except Exception as e:
                logger.warning(f"Error guardando evento en memoria: {e}")

    def register_hooks(self, registry: HookRegistry) -> None:  # type: ignore
        """Register both memory callbacks."""
        registry.add_callback(MessageAddedEvent, self.retrieve_customer_context)
        registry.add_callback(AfterInvocationEvent, self.save_support_interaction)


# ── TODO 6 — Knowledge Base Tool ─────────────────────────────────────────────
@tool
def search_knowledge_base(query: str) -> str:
    """
    Search the Amazon product catalog and support knowledge base.
    Use this for product specifications, return policies, warranty
    information, loyalty program details, and order status definitions.

    Args:
        query: The question or topic to search for

    Returns:
        Relevant information retrieved from the knowledge base
    """
    if not KB_ID:
        return "Knowledge base not configured."

    try:
        response = _bedrock_runtime.retrieve(
            knowledgeBaseId=KB_ID,
            retrievalQuery={"text": query}
        )
        results = response.get("retrievalResults", [])
        if not results:
            return "No relevant information found in the knowledge base."

        text_chunks = [
            res["content"]["text"]
            for res in results
            if "content" in res and "text" in res["content"]
        ]
        return "\n---\n".join(text_chunks)

    except Exception as e:
        logger.error(f"KB retrieval failed: {e}")
        return f"Error querying knowledge base: {str(e)}"


# ── TODO 7 — Loyalty Discount Tool (Code Interpreter) ────────────────────────
@tool
def calculate_loyalty_discount(
    loyalty_points: int,
    tier: str,
    order_total: float,
    product_category: str = "standard",
) -> str:
    """
    Calculate the loyalty discount for a customer order using the
    AgentCore Code Interpreter. Runs exact arithmetic in a secure sandbox.

    Args:
        loyalty_points:   Customer's current points balance
        tier:             Customer tier — Silver, Gold, or Platinum
        order_total:      Order total in USD
        product_category: standard, device, or fresh

    Returns:
        Full discount breakdown and final price
    """
    code = f"""
import json
import math

earn_rates = {{"standard": 1, "device": 2, "fresh": 5}}
tier_rates = {{"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}}

loyalty_points = {loyalty_points}
tier = "{tier}"
order_total = {order_total}
product_category = "{product_category}"

max_points_value = order_total * 0.50
max_points = int(max_points_value * 100)
points_to_use = min(loyalty_points, max_points)
points_redeemed = math.floor(points_to_use / 500) * 500
points_discount = points_redeemed * 0.01

subtotal_after_points = order_total - points_discount

tier_discount_rate = tier_rates.get(tier, 0.0)
tier_discount = subtotal_after_points * tier_discount_rate
tier_discount_pct = int(tier_discount_rate * 100)

final_total = subtotal_after_points - tier_discount
total_savings = points_discount + tier_discount

earn_rate = earn_rates.get(product_category, 1)
points_earned = math.floor(final_total) * earn_rate

remaining_points = loyalty_points - points_redeemed + points_earned

result = {{
    "points_redeemed": points_redeemed,
    "tier_discount_pct": tier_discount_pct,
    "points_discount": round(points_discount, 2),
    "tier_discount": round(tier_discount, 2),
    "final_total": round(final_total, 2),
    "total_savings": round(total_savings, 2),
    "points_earned": points_earned,
    "remaining_points": remaining_points
}}

print(json.dumps(result))
"""

    try:
        with code_session(REGION) as session:
            response = session.invoke(
                "executeCode",
                {"code": code, "language": "python", "clearContext": True}
            )
            
            # Usando la estructura exacta de extracción de AgentCore
            for event in response["stream"]:
                return json.dumps(event["result"])

    except Exception as e:
        logger.warning(f"Code interpreter failed: {e}. Activando fallback.")
        tier_rates = {"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}
        tier_rate = tier_rates.get(tier, 0.0)
        tier_discount = order_total * tier_rate
        final_total = order_total - tier_discount

        fallback_result = {
            "points_redeemed": 0,
            "tier_discount_pct": int(tier_rate * 100),
            "tier_discount": round(tier_discount, 2),
            "final_total": round(final_total, 2),
            "remaining_points": loyalty_points,
            "fallback_active": True,
            "error": "El intérprete de código no estuvo disponible. Se aplicó únicamente el descuento por nivel."
        }
        return json.dumps(fallback_result)


# ── TODO 8 — Agent Entrypoint ─────────────────────────────────────────────────
@app.entrypoint
async def invoke(payload, context=None):
    """
    Main handler called by AgentCore for every incoming request.
    """
    try:
        user_input = payload.get("prompt")
        if not user_input:
            return "Error: Se requiere 'prompt' en el payload."

        actor_id = payload.get("customer_id", "anonymous_user")
        session_id = payload.get("session_id", str(uuid.uuid4()))

        memory_hook = MemoryHook(
            actor_id=actor_id,
            session_id=session_id,
            memory_client=memory_client,
            memory_id=MEMORY_ID
        )

        agent_core_browser = AgentCoreBrowser(region=REGION)

        agent_tools = [
            search_knowledge_base,
            calculate_loyalty_discount,
            agent_core_browser.browser
        ]

        mcp_client = MCPClient(
            lambda: streamable_http_client(url=GATEWAY_URL)
        )

        with mcp_client:
            gateway_tools = mcp_client.list_tools_sync()
            if gateway_tools:
                agent_tools.extend(gateway_tools)

            system_prompt = (
                "You are an intelligent customer support assistant for an e-commerce platform. "
                "Always respond in the same language as the customer's query (default to English). "
                "Be professional, accurate, and concise. "
                "You have access to a knowledge base for policies and specifications, a loyalty discount calculator, "
                "a browser tool for live web lookups, and tools to track orders and process refunds. "
                "Always call the appropriate tools when handling customer requests."
            )

            agent = Agent(
                model=model,
                tools=agent_tools,
                system_prompt=system_prompt,
                hooks=[memory_hook]
            )

            response = agent(user_input)

            # Retornar el texto del primer bloque de contenido
            if hasattr(response, "text") and response.text:
                return response.text
            if hasattr(response, "content"):
                c = response.content
                if isinstance(c, list) and c:
                    first = c[0]
                    if isinstance(first, dict) and "text" in first:
                        return first["text"]
                    if hasattr(first, "text"):
                        return first.text
                if isinstance(c, str):
                    return c
            return str(response)

    except Exception as e:
        logger.error(f"Invocation failed: {e}")
        return f"Ocurrió un error procesando tu solicitud: {str(e)}"

# ── CLI entry point (do not modify) ──────────────────────────────────────────
def main():
    """Run one invocation from the command line for local testing."""
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=str)
    args = parser.parse_args()
    response = asyncio.run(invoke(json.loads(args.payload)))
    print(response)


if __name__ == "__main__":
    app.run()
    # Uncomment the line below and comment app.run() for local CLI testing:
    # main()